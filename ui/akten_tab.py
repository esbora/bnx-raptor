"""'Akten' sekmesi: dosya listesi, dosya geçmişi, cevap içe aktarma, e-posta taslağı."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.eingang import eml_lesen, finde_referenz
from core.eingang_service import eml_ablegen, protokollieren, zielordner
from core.entwurf import entwurf_erstellen
from core.extractor import is_valid_email
from core.journal import ARTEN
from core.mail_service import MailDraft


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

        # --- Üst çubuk ---
        oben = QHBoxLayout()
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Suchen: Versicherungsnummer, Mandant, E-Mail …")
        self.suche.textChanged.connect(self.laden)
        b_import = QPushButton("Antworten aus Outlook abrufen")
        b_import.clicked.connect(self.outlook_import)
        b_datei = QPushButton("E-Mail-Datei importieren…")
        b_datei.clicked.connect(self.datei_import_waehlen)
        oben.addWidget(self.suche, 1)
        oben.addWidget(b_import)
        oben.addWidget(b_datei)

        # --- Sol: dosya listesi ---
        self.liste = QTableWidget(0, 5)
        self.liste.setHorizontalHeaderLabels(
            ["Versicherungsnummer", "Mandant", "Versicherung", "Letzte Aktivität", "Einträge"])
        self.liste.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.liste.setSelectionMode(QAbstractItemView.SingleSelection)
        self.liste.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.liste.itemSelectionChanged.connect(self.akte_anzeigen)

        # --- Sağ: dosya ayrıntıları ---
        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        self.titel = QLabel("Keine Akte ausgewählt")
        self.titel.setStyleSheet("font-size: 14pt; font-weight: bold;")
        rl.addWidget(self.titel)

        stamm = QGroupBox("Akte")
        fl = QFormLayout(stamm)
        self.f_mandant_name = QLineEdit()
        self.f_mandant_email = QLineEdit()
        self.f_versicherer = QLineEdit()
        self.f_notiz = QLineEdit()
        fl.addRow("Mandant:", self.f_mandant_name)
        fl.addRow("E-Mail Mandant:", self.f_mandant_email)
        fl.addRow("E-Mail Versicherung:", self.f_versicherer)
        fl.addRow("Notiz:", self.f_notiz)
        b_speichern = QPushButton("Akte speichern")
        b_speichern.clicked.connect(self.akte_speichern)
        fl.addRow("", b_speichern)
        rl.addWidget(stamm)

        rl.addWidget(QLabel("Verlauf (Doppelklick öffnet die Datei, mehrere markieren für E-Mail):"))
        self.verlauf = QTableWidget(0, 5)
        self.verlauf.setHorizontalHeaderLabels(["Zeit", "Art", "An / Von", "Beschreibung", "Datei"])
        self.verlauf.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verlauf.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.verlauf.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verlauf.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.verlauf.cellDoubleClicked.connect(
            lambda r, _c: oeffnen(self.verlauf.item(r, 0).data(Qt.UserRole)))
        rl.addWidget(self.verlauf, 1)

        knoepfe = QHBoxLayout()
        b_ordner = QPushButton("Ordner öffnen")
        b_ordner.clicked.connect(self.ordner_oeffnen)
        b_mandant = QPushButton("E-Mail an Mandant…")
        b_mandant.clicked.connect(lambda: self.mail_mit_auswahl("mandant"))
        b_vers = QPushButton("E-Mail an Versicherung…")
        b_vers.clicked.connect(lambda: self.mail_mit_auswahl("versicherung"))
        knoepfe.addWidget(b_ordner)
        knoepfe.addStretch(1)
        knoepfe.addWidget(b_mandant)
        knoepfe.addWidget(b_vers)
        rl.addLayout(knoepfe)

        split = QSplitter()
        split.addWidget(self.liste)
        split.addWidget(rechts)
        split.setSizes([380, 620])

        lay = QVBoxLayout(self)
        lay.addLayout(oben)
        lay.addWidget(split, 1)
        hinweis = QLabel("Tipp: E-Mails (.eml / .msg) aus Outlook direkt hierher ziehen.")
        hinweis.setStyleSheet("color: #666;")
        lay.addWidget(hinweis)
        self.laden()

    # --- Liste -------------------------------------------------------------
    def laden(self):
        akten = self.ctx.journal.akten(self.suche.text().strip())
        self.liste.setRowCount(len(akten))
        for r, a in enumerate(akten):
            self.liste.setItem(r, 0, _item(a["referenz"], a["referenz"]))
            self.liste.setItem(r, 1, _item(a["mandant_name"] or a["mandant_email"]))
            self.liste.setItem(r, 2, _item(a["versicherer_email"]))
            self.liste.setItem(r, 3, _item(a["letzte"]))
            eing = f" ({a['eingaenge']} Antw.)" if a["eingaenge"] else ""
            self.liste.setItem(r, 4, _item(f"{a['anzahl']}{eing}"))
        self.liste.resizeColumnsToContents()

    def aktuelle_referenz(self) -> str:
        r = self.liste.currentRow()
        return self.liste.item(r, 0).data(Qt.UserRole) if r >= 0 and self.liste.item(r, 0) else ""

    def akte_anzeigen(self):
        ref = self.aktuelle_referenz()
        akte = self.ctx.journal.akte(ref) if ref else None
        if not akte:
            return
        self.titel.setText(f"Akte {ref}")
        self.f_mandant_name.setText(akte["mandant_name"])
        self.f_mandant_email.setText(akte["mandant_email"])
        self.f_versicherer.setText(akte["versicherer_email"])
        self.f_notiz.setText(akte["notiz"])
        rows = self.ctx.journal.verlauf(ref)
        self.verlauf.setRowCount(len(rows))
        for r, v in enumerate(rows):
            datei = v["ergebnis"] or v["dokument"]
            self.verlauf.setItem(r, 0, _item(v["zeit"], datei))
            self.verlauf.setItem(r, 1, _item(ARTEN.get(v["art"], v["art"])))
            self.verlauf.setItem(r, 2, _item(v["empfaenger"]))
            self.verlauf.setItem(r, 3, _item((v["meldung"] or "").splitlines()[0] if v["meldung"] else ""))
            self.verlauf.setItem(r, 4, _item(Path(datei).name if datei else ""))
        self.verlauf.resizeColumnsToContents()
        self.verlauf.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

    def akte_speichern(self):
        ref = self.aktuelle_referenz()
        if not ref:
            return
        email = self.f_mandant_email.text().strip()
        if email and not is_valid_email(email):
            QMessageBox.warning(self, "Ungültig", "E-Mail des Mandanten ist ungültig.")
            return
        # Burada boş değer de bilinçli olarak kaydedilir
        con = self.ctx.journal.con
        con.execute("UPDATE akten SET mandant_name=?, mandant_email=?, versicherer_email=?, notiz=?"
                    " WHERE referenz=?", (self.f_mandant_name.text().strip(), email,
                                         self.f_versicherer.text().strip(),
                                         self.f_notiz.text().strip(), ref))
        con.commit()
        self.laden()

    def ordner_oeffnen(self):
        akte = self.ctx.journal.akte(self.aktuelle_referenz())
        if akte and akte["ordner"]:
            oeffnen(akte["ordner"])

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
                to=empf.strip(), subject=betreff.format(nummer=ref), html_body=text,
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
        from core.outlook_eingang import OutlookPosteingang
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
