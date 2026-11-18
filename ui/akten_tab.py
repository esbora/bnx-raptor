"""'Akten' sayfası: dosya listesi, Akte bilgileri (otomatik kaydedilir), Verlauf + önizleme, belge ekleme.

0.4.1: Aktenzeichen, Mandant, Versicherung, Versicherungsnummer ve Schaden-Nr. ayrı alanlar; „Dateien aus
Ordner hinzufügen…“ belgeleri açık Akte'ye ekler (hemen Verlauf'ta görünür); Verlauf'ta çift tıklama
belgeyi düzenlemek için açar (Word → Word düzenleme, PDF → PDF-Editor) ve aynı satırı + önizlemeyi günceller.
„Dokumente ohne Akte“: Akte seçilmeden işlenmiş belgeler sonradan bir Akte'ye bağlanır.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.eingang import eml_lesen, finde_referenz
from core.eingang_service import eml_ablegen, protokollieren, zielordner
from core.entwurf import entwurf_erstellen
from core.extractor import betreff as betreff_bilden
from core.extractor import is_valid_email
from core.journal import ARTEN
from core.mail_service import MailDraft

from . import theme

OHNE_AKTE = "\x00ohne"                       # interner Schlüssel der Zeile „Dokumente ohne Akte“
BEARBEITBAR = {".pdf", ".docx", ".doc", ".docm", ".rtf"}


def _item(text, daten=None) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text or ""))
    if daten is not None:
        it.setData(Qt.UserRole, daten)
    return it


def oeffnen(pfad: str):
    if pfad and Path(pfad).exists() and hasattr(os, "startfile"):
        os.startfile(pfad)  # type: ignore[attr-defined]


class ImportDialog(QDialog):
    """Outlook'ta bulunan cevapları onay kutularıyla listeler."""

    def __init__(self, parent, kandidaten):
        super().__init__(parent)
        self.setWindowTitle("Antworten aus Outlook übernehmen")
        self.resize(820, 400)
        self.kandidaten = kandidaten
        self.tab = QTableWidget(len(kandidaten), 5)
        self.tab.setHorizontalHeaderLabels(["", "Datum", "Absender", "Betreff", "Akte"])
        for r, k in enumerate(kandidaten):
            cb = QTableWidgetItem()
            cb.setCheckState(Qt.Checked)
            self.tab.setItem(r, 0, cb)
            self.tab.setItem(r, 1, _item(k.datum.strftime("%d.%m.%Y %H:%M") if k.datum else ""))
            self.tab.setItem(r, 2, _item(k.absender))
            self.tab.setItem(r, 3, _item(k.betreff + (f"  📎{k.anhaenge}" if k.anhaenge else "")))
            self.tab.setItem(r, 4, _item(k.referenz))
        self.tab.resizeColumnsToContents()
        self.tab.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Ausgewählte in Akten ablegen")
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"{len(kandidaten)} neue E-Mail(s) mit bekannter Versicherungsnummer gefunden:"))
        lay.addWidget(self.tab)
        lay.addWidget(bb)

    def ausgewaehlt(self):
        return [k for r, k in enumerate(self.kandidaten)
                if self.tab.item(r, 0).checkState() == Qt.Checked]


class AktenTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setAcceptDrops(True)
        self._laedt = False

        # --- Üst çubuk ---
        oben = QHBoxLayout()
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Suchen: Versicherungsnummer, Aktenzeichen, Mandant, E-Mail …")
        self.suche.textChanged.connect(self.laden)
        b_neu = QPushButton(theme.icon("plus", "primaer_text", 16), "  Neue Akte")
        theme.rolle(b_neu, "primaer")
        b_neu.clicked.connect(self.neue_akte)
        b_import = QPushButton("Antworten aus Outlook abrufen")
        b_import.clicked.connect(self.outlook_import)
        b_datei = QPushButton("E-Mail-Datei importieren…")
        b_datei.clicked.connect(self.datei_import_waehlen)
        oben.addWidget(self.suche, 1)
        oben.addWidget(b_neu)
        oben.addWidget(b_import)
        oben.addWidget(b_datei)

        # --- Sol: dosya listesi ---
        self.liste = QTableWidget(0, 5)
        self.liste.setHorizontalHeaderLabels(
            ["Akte / Nummer", "Mandant", "Versicherung", "Letzte Aktivität", "Einträge"])
        self.liste.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.liste.setSelectionMode(QAbstractItemView.SingleSelection)
        self.liste.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.liste.verticalHeader().hide()
        self.liste.itemSelectionChanged.connect(self.akte_anzeigen)

        # --- Sağ: dosya ayrıntıları ---
        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(8, 0, 0, 0)
        self.titel = theme.ueberschrift("Keine Akte ausgewählt", "h2")
        rl.addWidget(self.titel)
        self.stamm = theme.karte(QFrame(), schatten=False)
        fl = QGridLayout(self.stamm)                 # zweispaltig: mehr Platz für den Verlauf
        fl.setContentsMargins(14, 8, 14, 8)
        fl.setHorizontalSpacing(10)
        fl.setVerticalSpacing(6)
        self.f_aktenzeichen = QLineEdit()
        self.f_mandant = QComboBox()
        self.f_versicherung = QComboBox()
        self.f_vnr = QLineEdit()
        self.f_snr = QLineEdit()
        self.f_mandant_email = QLineEdit()
        self.f_versicherer = QLineEdit()
        self.f_notiz = QLineEdit()
        for w, n in ((self.f_aktenzeichen, "Aktenzeichen"), (self.f_mandant, "Mandant"), (self.f_versicherung,
                     "Versicherung"), (self.f_vnr, "Versicherungsnummer"), (self.f_snr, "Schaden-Nr."),
                     (self.f_mandant_email, "E-Mail Mandant"), (self.f_versicherer, "E-Mail Versicherung"),
                     (self.f_notiz, "Notiz")):
            w.setAccessibleName(n)
        for r, (l1, w1, l2, w2) in enumerate((("Aktenzeichen:", self.f_aktenzeichen, "Notiz:", self.f_notiz),
                                              ("Mandant:", self.f_mandant, "Versicherung:", self.f_versicherung),
                                              ("Versicherungsnr.:", self.f_vnr, "Schaden-Nr.:", self.f_snr),
                                              ("E-Mail Mandant:", self.f_mandant_email, "E-Mail Versicherung:",
                                               self.f_versicherer))):
            fl.addWidget(QLabel(l1), r, 0)
            fl.addWidget(w1, r, 1)
            fl.addWidget(QLabel(l2), r, 2)
            fl.addWidget(w2, r, 3)
        fl.setColumnStretch(1, 1)
        fl.setColumnStretch(3, 1)
        self.l_gespeichert = theme.rolle(QLabel(""), "gedimmt")
        fl.addWidget(self.l_gespeichert, 4, 0, 1, 4)
        for w in (self.f_aktenzeichen, self.f_vnr, self.f_snr, self.f_mandant_email, self.f_versicherer, self.f_notiz):
            w.editingFinished.connect(self.akte_speichern)
        self.f_mandant.currentIndexChanged.connect(lambda *_: self.akte_speichern())
        self.f_versicherung.currentIndexChanged.connect(lambda *_: self.akte_speichern())
        rl.addWidget(self.stamm)

        self.l_verlauf = QLabel("Verlauf – Doppelklick öffnet die Datei zum Bearbeiten; mehrere markieren für E-Mail:")
        rl.addWidget(self.l_verlauf)
        vsplit = QSplitter()
        self.verlauf = QTableWidget(0, 5)
        self.verlauf.setAccessibleName("Verlauf")
        self.verlauf.setMinimumHeight(170)
        self.verlauf.setHorizontalHeaderLabels(["Zeit", "Art", "An / Von", "Beschreibung", "Datei"])
        self.verlauf.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verlauf.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.verlauf.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verlauf.verticalHeader().hide()
        self.verlauf.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.verlauf.cellDoubleClicked.connect(lambda r, _c: self.bearbeiten(r))
        self.verlauf.currentCellChanged.connect(lambda r, *_: self.vorschau_zeigen(r))
        vsplit.addWidget(self.verlauf)
        self.vorschau = QLabel("Vorschau")
        self.vorschau.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.vorschau.setWordWrap(True)
        self.vorschau.setMinimumWidth(200)
        vsc = QScrollArea()
        vsc.setWidget(self.vorschau)
        vsc.setWidgetResizable(True)
        vsplit.addWidget(vsc)
        vsplit.setSizes([640, 260])
        rl.addWidget(vsplit, 1)

        knoepfe = QHBoxLayout()
        self.b_ordner = QPushButton(theme.icon("ordner", "titel", 16), "  Aktenordner öffnen")
        self.b_ordner.setToolTip("Zeigt den Ordner der Akte im Windows-Explorer")
        self.b_ordner.clicked.connect(self.ordner_oeffnen)
        self.b_hinzu = QPushButton(theme.icon("plus", "titel", 16), "  Dateien aus Ordner hinzufügen…")
        self.b_hinzu.setToolTip("Dateien auswählen – sie werden dieser Akte hinzugefügt und erscheinen im Verlauf")
        self.b_hinzu.clicked.connect(self.dateien_hinzufuegen)
        self.b_zuordnen = QPushButton("Akte zuordnen…")
        self.b_zuordnen.setToolTip("Markierte Dokumente einer Akte zuordnen")
        self.b_zuordnen.clicked.connect(self.akte_zuordnen)
        self.b_mandant = QPushButton("E-Mail an Mandant…")
        self.b_mandant.clicked.connect(lambda: self.mail_mit_auswahl("mandant"))
        self.b_vers = QPushButton("E-Mail an Versicherung…")
        self.b_vers.clicked.connect(lambda: self.mail_mit_auswahl("versicherung"))
        knoepfe.addWidget(self.b_ordner)
        knoepfe.addWidget(self.b_hinzu)
        knoepfe.addWidget(self.b_zuordnen)
        knoepfe.addStretch(1)
        rl.addLayout(knoepfe)
        mails = QHBoxLayout()                    # zweite Zeile: passt auch bei 1180 px Fensterbreite
        mails.addStretch(1)
        mails.addWidget(self.b_mandant)
        mails.addWidget(self.b_vers)
        rl.addLayout(mails)

        split = QSplitter()
        split.addWidget(self.liste)
        split.addWidget(rechts)
        self.liste.setMinimumWidth(240)
        split.setSizes([330, 800])

        lay = QVBoxLayout(self)
        lay.addLayout(oben)
        lay.addWidget(split, 1)
        hinweis = theme.rolle(QLabel("Tipp: E-Mails (.eml / .msg) aus Outlook direkt hierher ziehen."), "gedimmt")
        lay.addWidget(hinweis)
        self.laden()

    # --- Liste -------------------------------------------------------------
    def laden(self):
        akten = self.ctx.journal.akten(self.suche.text().strip())
        ohne = self.ctx.archiv.liste(ohne_akte=True)
        wahl = self.aktuelle_referenz()
        self.liste.blockSignals(True)
        self.liste.setRowCount(len(akten) + 1)
        self.liste.setItem(0, 0, _item("📄 Dokumente ohne Akte", OHNE_AKTE))
        for c in range(1, 5):
            self.liste.setItem(0, c, _item(""))
        self.liste.setItem(0, 4, _item(str(len(ohne))))
        st = self.ctx.stammdaten
        mand = {m["id"]: m["name"] for m in st.mandanten()}
        for r, a in enumerate(akten, 1):
            voll = st.akte(a["referenz"]) or {}
            self.liste.setItem(r, 0, _item(a["referenz"] + (f"  ·  {voll.get('aktenzeichen')}"
                                                             if voll.get("aktenzeichen") else ""), a["referenz"]))
            self.liste.setItem(r, 1, _item(mand.get(voll.get("mandant_id")) or a["mandant_name"] or a["mandant_email"]))
            self.liste.setItem(r, 2, _item(a["versicherer_email"]))
            self.liste.setItem(r, 3, _item(a["letzte"]))
            eing = f" ({a['eingaenge']} Antw.)" if a["eingaenge"] else ""
            self.liste.setItem(r, 4, _item(f"{a['anzahl']}{eing}"))
            if a["referenz"] == wahl:
                self.liste.selectRow(r)
        if wahl == OHNE_AKTE:
            self.liste.selectRow(0)
        self.liste.blockSignals(False)
        self.liste.resizeColumnsToContents()
        self.akte_anzeigen()

    def akte_waehlen(self, referenz: str):
        self.suche.clear()
        self.laden()
        for r in range(self.liste.rowCount()):
            if self.liste.item(r, 0).data(Qt.UserRole) == referenz:
                self.liste.selectRow(r)
                return

    def aktuelle_referenz(self) -> str:
        r = self.liste.currentRow()
        return self.liste.item(r, 0).data(Qt.UserRole) if r >= 0 and self.liste.item(r, 0) else ""

    def _combos_fuellen(self, akte: dict):
        st = self.ctx.stammdaten
        self.f_mandant.clear()
        self.f_mandant.addItem("— kein Mandant —", None)
        for m in st.mandanten():
            self.f_mandant.addItem(m["name"], m["id"])
        self.f_mandant.setCurrentIndex(max(self.f_mandant.findData(akte.get("mandant_id")), 0))
        self.f_versicherung.clear()
        self.f_versicherung.addItem("— keine Versicherung —", None)
        for v in st.versicherungen():
            self.f_versicherung.addItem(v["name"], v["id"] if v["id"] is not None else "buch:" + v["name"])
        self.f_versicherung.setCurrentIndex(max(self.f_versicherung.findData(akte.get("versicherung_id")), 0))

    def akte_anzeigen(self):
        ref = self.aktuelle_referenz()
        ohne = ref == OHNE_AKTE
        self.stamm.setVisible(not ohne)
        for b in (self.b_ordner, self.b_hinzu, self.b_mandant, self.b_vers):
            b.setVisible(not ohne)
        self.b_zuordnen.setVisible(ohne)
        if ohne:
            self.titel.setText("Dokumente ohne Akte")
            self.l_verlauf.setText("Bearbeitete Dokumente ohne Akte – markieren und „Akte zuordnen…“; "
                                   "Doppelklick öffnet zum Bearbeiten:")
            self._verlauf_dokumente(self.ctx.archiv.liste(ohne_akte=True))
            return
        akte = self.ctx.stammdaten.akte(ref) if ref else None
        if not akte:
            return
        self.l_verlauf.setText("Verlauf – Doppelklick öffnet die Datei zum Bearbeiten; mehrere markieren für E-Mail:")
        self._laedt = True
        self.titel.setText(f"Akte {ref}")
        self.f_aktenzeichen.setText(akte.get("aktenzeichen") or "")
        self._combos_fuellen(akte)
        self.f_vnr.setText(akte.get("versicherungsnummer") or "")
        self.f_snr.setText(akte.get("schaden_nr") or "")
        self.f_mandant_email.setText(akte["mandant_email"])
        self.f_versicherer.setText(akte["versicherer_email"])
        self.f_notiz.setText(akte["notiz"])
        self.l_gespeichert.setText("Änderungen werden automatisch gespeichert.")
        self._laedt = False
        rows = self.ctx.journal.verlauf(ref)
        self.verlauf.setRowCount(len(rows))
        for r, v in enumerate(rows):
            datei = v["ergebnis"] or v["dokument"]
            self.verlauf.setItem(r, 0, _item(v["zeit"], datei))
            self.verlauf.item(r, 0).setData(Qt.UserRole + 1, v["id"])
            self.verlauf.setItem(r, 1, _item(ARTEN.get(v["art"], v["art"])))
            self.verlauf.setItem(r, 2, _item(v["empfaenger"]))
            text = (v["meldung"] or "").splitlines()[0] if v["meldung"] else ""
            if v["bearbeitet"]:
                text = f"✎ bearbeitet {v['bearbeitet']}" + (f" · {text}" if text else "")
            self.verlauf.setItem(r, 3, _item(text))
            self.verlauf.setItem(r, 4, _item(Path(datei).name if datei else ""))
        self.verlauf.resizeColumnsToContents()
        self.verlauf.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.vorschau_zeigen(self.verlauf.currentRow())

    def _verlauf_dokumente(self, doks: list[dict]):
        self.verlauf.setRowCount(len(doks))
        for r, d in enumerate(doks):
            self.verlauf.setItem(r, 0, _item(d["bearbeitet"] or d["hinzugefuegt"], d["pfad"]))
            self.verlauf.item(r, 0).setData(Qt.UserRole + 2, d["id"])
            self.verlauf.setItem(r, 1, _item(d["typ"]))
            self.verlauf.setItem(r, 2, _item(""))
            herkunft = f" ← {d['quelle_name']}" if d.get("quelle_name") else ""
            self.verlauf.setItem(r, 3, _item(f"{d['rolle']}{herkunft}" + (f" · {d['notiz']}" if d["notiz"] else "")))
            self.verlauf.setItem(r, 4, _item(d["name"]))
        self.verlauf.resizeColumnsToContents()
        self.verlauf.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.vorschau_zeigen(self.verlauf.currentRow())

    def vorschau_zeigen(self, r: int):
        pfad = self.verlauf.item(r, 0).data(Qt.UserRole) if r >= 0 and self.verlauf.item(r, 0) else ""
        self.vorschau.clear()
        if not pfad or not Path(pfad).exists():
            self.vorschau.setText("Keine Vorschau" if pfad else "Eintrag wählen")
            return
        p = Path(pfad)
        try:
            if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"):
                from core import pdf_engine as pe
                from .pdf_ui import qpixmap
                doc = pe.oeffnen(p)
                self.vorschau.setPixmap(qpixmap(pe.seitenbild(doc[0], 240)))
                doc.close()
            elif p.suffix.lower() == ".docx":
                from core.docx_schreiben import docx_text
                self.vorschau.setText(f"<b>{p.name}</b><br><br>" + docx_text(p, 1200).replace("\n", "<br>"))
            else:
                self.vorschau.setText(p.name)
        except Exception as e:  # noqa: BLE001
            self.vorschau.setText(f"Keine Vorschau: {e}")

    def akte_speichern(self):
        if self._laedt:
            return
        ref = self.aktuelle_referenz()
        if not ref or ref == OHNE_AKTE:
            return
        email = self.f_mandant_email.text().strip()
        if email and not is_valid_email(email):
            theme.status_setzen(self.l_gespeichert, "warn", "E-Mail des Mandanten ist ungültig – nicht gespeichert.")
            return
        st = self.ctx.stammdaten
        mid = self.f_mandant.currentData()
        vid = self.f_versicherung.currentData()
        if isinstance(vid, str) and vid.startswith("buch:"):       # Adressbuch-Versicherung → Datensatz anlegen
            vid = st.versicherung_speichern(None, name=vid[5:])
        werte = dict(aktenzeichen=self.f_aktenzeichen.text().strip(), mandant_id=mid, versicherung_id=vid,
                     versicherungsnummer=self.f_vnr.text().strip(), schaden_nr=self.f_snr.text().strip(),
                     mandant_email=email, versicherer_email=self.f_versicherer.text().strip(),
                     notiz=self.f_notiz.text().strip())
        if mid:
            m = st.mandant(mid)
            werte["mandant_name"] = m["name"]
            if not email and m["email"]:
                werte["mandant_email"] = m["email"]
                self.f_mandant_email.setText(m["email"])
        if vid and not werte["versicherer_email"]:
            v = st.versicherung(vid)
            if v and v["emails"]:
                werte["versicherer_email"] = v["emails"][0]
                self.f_versicherer.setText(v["emails"][0])
        st.akte_setzen(ref, **werte)
        theme.status_setzen(self.l_gespeichert, "ok", "Gespeichert")

    def neue_akte(self):
        ref, ok = QInputDialog.getText(self, "Neue Akte", "Aktenzeichen oder Versicherungs-/Schaden-Nr.:")
        if not ok or not ref.strip():
            return
        self.ctx.stammdaten.akte_anlegen(ref.strip())
        self.akte_waehlen(ref.strip())
        self.f_aktenzeichen.setFocus()

    def ordner_oeffnen(self):
        akte = self.ctx.journal.akte(self.aktuelle_referenz())
        if akte and akte["ordner"]:
            oeffnen(akte["ordner"])
        elif akte:
            QMessageBox.information(self, "Aktenordner", "Für diese Akte ist noch kein Ordner hinterlegt. Er wird "
                                    "beim ersten „Dateien aus Ordner hinzufügen…“ übernommen.")

    # --- Dokumente ---------------------------------------------------------
    def dateien_hinzufuegen(self):
        ref = self.aktuelle_referenz()
        akte = self.ctx.journal.akte(ref) if ref and ref != OHNE_AKTE else None
        if not akte:
            return
        start = akte["ordner"] or ""
        namen, _ = QFileDialog.getOpenFileNames(self, f"Dateien zur Akte {ref} hinzufügen", start,
                                                "Dokumente (*.pdf *.docx *.doc *.jpg *.jpeg *.png *.tif *.tiff "
                                                "*.eml *.msg *.xlsx *.txt);;Alle Dateien (*)")
        if not namen:
            return
        if not akte["ordner"]:
            self.ctx.journal.akte_speichern(ref, ordner=str(Path(namen[0]).parent))
        neu = 0
        for n in namen:
            p = Path(n)
            if self.ctx.archiv.id_von(p) is not None and any(
                    d["pfad"].lower() == str(p).lower() for d in self.ctx.archiv.liste(akte=ref)):
                continue                                           # schon in dieser Akte
            self.ctx.archiv.erfassen(p, akte=ref)
            self.ctx.journal.add("akte", str(p), "", "", ref, meldung="aus Ordner hinzugefügt", art="dokument")
            neu += 1
        self.laden()
        theme.status_setzen(self.l_gespeichert, "ok", f"{neu} Datei(en) hinzugefügt – siehe Verlauf.")

    def akte_zuordnen(self):
        zeilen = sorted({i.row() for i in self.verlauf.selectedIndexes()})
        ids = [self.verlauf.item(r, 0).data(Qt.UserRole + 2) for r in zeilen]
        ids = [i for i in ids if i]
        if not ids:
            QMessageBox.information(self, "Akte zuordnen", "Bitte zuerst Dokumente markieren.")
            return
        refs = sorted(self.ctx.journal.referenzen())
        if not refs:
            QMessageBox.information(self, "Akte zuordnen", "Es gibt noch keine Akte – bitte „Neue Akte“ anlegen.")
            return
        ref, ok = QInputDialog.getItem(self, "Akte zuordnen", f"{len(ids)} Dokument(e) zuordnen zu:", refs, 0, False)
        if not ok:
            return
        for i in ids:
            d = self.ctx.archiv.dokument(i)
            self.ctx.archiv.zuordnen(i, ref)
            self.ctx.journal.add("akte", d["pfad"], "", "", ref, meldung="Dokument zugeordnet", art="dokument")
        self.laden()

    def bearbeiten(self, r: int):
        """Doppelklick: Word → Word-Bearbeitung, PDF → PDF-Editor (Speichern = gleiche Datei);
        danach werden derselbe Verlauf-Eintrag, das Archiv und die Vorschau aktualisiert."""
        it = self.verlauf.item(r, 0)
        pfad = it.data(Qt.UserRole) if it else ""
        if not pfad or not Path(pfad).exists():
            QMessageBox.information(self, "Datei", "Die Datei ist nicht (mehr) vorhanden.")
            return
        p = Path(pfad)
        if p.suffix.lower() not in BEARBEITBAR:
            oeffnen(pfad)
            return
        from .main_window import im_hintergrund
        gespeichert = False
        if p.suffix.lower() == ".pdf":
            from core import pdf_engine as pe
            from .pdf_editor import PdfEditor
            ed = PdfEditor(self, p, sprachen=tuple(self.ctx.cfg.get("ocr_sprachen", pe.SPRACHEN)))
            ed.exec()
            gespeichert = ed.gespeichert is not None
            if ed.gespeichert and ed.gespeichert != p:            # „Speichern unter…“ → neue Datei auch ins Archiv
                self.ctx.archiv.erfassen(ed.gespeichert, akte=self._akte_fuer_archiv(), rolle="bearbeitet", quelle=p)
        else:
            from .dokument_editor import WordDialog
            quelle_id = (self.ctx.archiv.dokument(self.ctx.archiv.id_von(p)) or {}).get("quelle_id") \
                if self.ctx.archiv.id_von(p) else None
            original = Path(self.ctx.archiv.dokument(quelle_id)["pfad"]) if quelle_id else None
            dlg = WordDialog(self, p, lambda fn, frist: im_hintergrund(fn, frist),
                             float(self.ctx.cfg.get("word_zeitlimit_sekunden", 90)), original)
            dlg.exec()
            gespeichert = dlg.ed.basis != "" and dlg.result() == QDialog.Accepted
        if gespeichert:
            self.ctx.archiv.erfassen(p, akte=self._akte_fuer_archiv())
            self.ctx.archiv.bearbeitet(p)
            vid = it.data(Qt.UserRole + 1)
            if vid:
                self.ctx.journal.bearbeitet_setzen(vid)
            self.akte_anzeigen()
            self.verlauf.selectRow(r)
            self.vorschau_zeigen(r)

    def _akte_fuer_archiv(self) -> str:
        ref = self.aktuelle_referenz()
        return "" if ref == OHNE_AKTE else ref

    # --- E-posta taslağı ---------------------------------------------------
    def mail_mit_auswahl(self, an: str):
        ref = self.aktuelle_referenz()
        akte = self.ctx.journal.akte(ref) if ref else None
        if not akte:
            QMessageBox.information(self, "Akte", "Bitte zuerst eine Akte auswählen.")
            return
        dateien = []
        for r in sorted({i.row() for i in self.verlauf.selectedIndexes()}):
            p = self.verlauf.item(r, 0).data(Qt.UserRole)
            if p and Path(p).exists() and Path(p).suffix.lower() in (".pdf", ".msg", ".eml", ".docx",
                                                                     ".jpg", ".png", ".xlsx"):
                dateien.append(Path(p))
        cfg = self.ctx.cfg
        if an == "mandant":
            vorschlag, betreff, text, art = (akte["mandant_email"], cfg["mandant_betreff_vorlage"],
                                             cfg["mandant_info_text_html"], "mandant")
        else:
            vorschlag, betreff, text, art = (akte["versicherer_email"], cfg["betreff_vorlage"],
                                             cfg["mail_text_html"], "entwurf")
        empf, ok = QInputDialog.getText(self, "Empfänger",
                                        f"E-Mail-Adresse ({len(dateien)} Anlage(n)):", text=vorschlag)
        if not ok or not empf.strip():
            return
        if not is_valid_email(empf):
            QMessageBox.warning(self, "Ungültig", f"„{empf}“ ist keine gültige E-Mail-Adresse.")
            return
        try:
            msg = entwurf_erstellen(self.ctx, MailDraft(
                to=empf.strip(), subject=betreff_bilden(betreff, ref, akte.get("nummer_art", "")), html_body=text,
                attachments=dateien), Path(akte["ordner"]) if akte["ordner"] else Path.home())
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Fehler", str(e))
            return
        if an == "mandant" and not akte["mandant_email"]:
            self.ctx.journal.akte_speichern(ref, mandant_email=empf.strip())
        self.ctx.journal.add("akte", "", str(dateien[0]) if dateien else "", empf.strip(), ref,
                             meldung=f"{msg} – Anlagen: " + ", ".join(d.name for d in dateien),
                             art=art)
        self.laden()

    # --- Gelen cevaplar ----------------------------------------------------
    def _ordner_fuer(self, ref: str) -> Path | None:
        ordner = zielordner(self.ctx, ref)
        if ordner:
            return ordner
        wahl = QFileDialog.getExistingDirectory(self, f"Aktenordner für {ref} wählen")
        if not wahl:
            return None
        self.ctx.journal.akte_speichern(ref, ordner=wahl)
        return zielordner(self.ctx, ref)

    def _referenz_fragen(self, betreff: str) -> str:
        refs = sorted(self.ctx.journal.referenzen())
        if not refs:
            return ""
        ref, ok = QInputDialog.getItem(self, "Akte zuordnen",
                                       f"Keine Versicherungsnummer erkannt:\n„{betreff}“\n\nAkte wählen:",
                                       refs, 0, False)
        return ref if ok else ""

    def outlook_import(self):
        from core.entwurf import mail_modus
        from core.outlook_eingang import OutlookPosteingang
        if mail_modus(self.ctx.cfg) == "eml":
            QMessageBox.information(
                self, "Outlook",
                "Das neue Outlook erlaubt keinen automatischen Abruf.\n\n"
                "So geht es trotzdem: Antwort-E-Mail in Outlook markieren und mit der Maus "
                "in diesen Reiter ziehen – oder über „Datei → Speichern unter“ als .eml/.msg "
                "speichern und mit „E-Mail-Datei importieren…“ übernehmen.")
            return
        try:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                post = OutlookPosteingang()
                kand = post.suchen(self.ctx.journal.referenzen(),
                                   int(self.ctx.cfg.get("eingang_tage", 30)),
                                   self.ctx.journal.bereits_importiert)
            finally:
                QGuiApplication.restoreOverrideCursor()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Outlook", str(e))
            return
        if not kand:
            QMessageBox.information(self, "Outlook", "Keine neuen Antworten gefunden.")
            return
        dlg = ImportDialog(self, kand)
        if dlg.exec() != QDialog.Accepted:
            return
        n = 0
        for k in dlg.ausgewaehlt():
            ordner = self._ordner_fuer(k.referenz)
            if not ordner:
                continue
            try:
                dateien = post.ablegen(k, ordner)
                protokollieren(self.ctx, k.referenz, k.absender, k.betreff, dateien, k.quelle_id)
                n += 1
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "Fehler", f"{k.betreff}:\n{e}")
        QMessageBox.information(self, "Fertig", f"{n} Antwort(en) in den Akten abgelegt.")
        self.laden()

    def datei_import_waehlen(self):
        namen, _ = QFileDialog.getOpenFileNames(self, "E-Mails wählen", "", "E-Mail (*.eml *.msg)")
        self.dateien_importieren([Path(n) for n in namen])

    def dateien_importieren(self, pfade: list[Path]):
        n = 0
        for p in pfade:
            try:
                if p.suffix.lower() == ".eml":
                    roh = p.read_bytes()
                    mail = eml_lesen(roh)
                    if self.ctx.journal.bereits_importiert(mail.quelle_id):
                        continue
                    ref = finde_referenz(f"{mail.betreff}\n{mail.text}", self.ctx.journal.referenzen()) \
                        or self._referenz_fragen(mail.betreff)
                    ordner = self._ordner_fuer(ref) if ref else None
                    if ordner:
                        eml_ablegen(self.ctx, mail, roh, ref, ordner)
                        n += 1
                elif p.suffix.lower() == ".msg":
                    from core.outlook_eingang import OutlookPosteingang
                    post = OutlookPosteingang()
                    item = post.msg_lesen(p)
                    k = post.kandidat_aus_item(item, self.ctx.journal.referenzen())
                    if self.ctx.journal.bereits_importiert(k.quelle_id):
                        continue
                    k.referenz = k.referenz or self._referenz_fragen(k.betreff)
                    ordner = self._ordner_fuer(k.referenz) if k.referenz else None
                    if ordner:
                        dateien = post.ablegen(k, ordner, item=item)
                        protokollieren(self.ctx, k.referenz, k.absender, k.betreff, dateien, k.quelle_id)
                        n += 1
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "Fehler", f"{p.name}:\n{e}")
        if pfade:
            QMessageBox.information(self, "Import", f"{n} E-Mail(s) in den Akten abgelegt.")
        self.laden()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.dateien_importieren([Path(u.toLocalFile()) for u in e.mimeData().urls()
                                  if u.toLocalFile().lower().endswith((".eml", ".msg"))])
