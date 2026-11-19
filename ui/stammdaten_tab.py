"""Seiten „Mandanten“ und „Versicherungen“ (0.4.1).

Links die Liste mit Suche und „Neu“, rechts das Formular. Gespeichert wird automatisch beim Verlassen
eines Feldes – kein Speichern-Knopf. Versicherer-E-Mails sind das bestehende Versicherer-Adressbuch.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core.extractor import is_valid_email
from core.fehlertexte import meldung
from core.protokoll import Konflikt, gleich, meta_text

# Fehler, bei denen die Eingabe im Formular bleibt und später erneut gespeichert wird
try:
    from core.netz import SitzungFehler, VerbindungFehler, WartungFehler
    OFFLINE = (VerbindungFehler, WartungFehler, SitzungFehler)
except ImportError:  # pragma: no cover
    OFFLINE = ()

from . import theme


def ordner_oeffnen(parent, ordner: list[tuple[str, str]], knopf, status_label, ctx=None):
    """Ein Ordner → sofort öffnen; mehrere → kurze Auswahl (neueste zuerst, „Alle öffnen“).
    Client im Mehrbenutzerbetrieb: lokale Kopien der Akten-Dokumente."""
    import os
    from PySide6.QtWidgets import QMenu
    if ctx is not None and not ctx.dateien.direkt:
        from .netz_ui import akte_lokal
        refs = list(dict.fromkeys(ref for _, ref in ordner))
        ordner = [(str(akte_lokal(ctx, ref)), ref) for ref in refs]
    if not ordner:
        theme.status_setzen(status_label, None, "Noch keine gespeicherten Dokumente in den Akten.")
        return
    if len(ordner) == 1:
        os.startfile(ordner[0][0])                         # type: ignore[attr-defined]
        return
    menu = QMenu(parent)
    for pfad, ref in ordner:
        menu.addAction(f"{pfad}   (Akte {ref})", lambda p=pfad: os.startfile(p))   # type: ignore[attr-defined]
    menu.addSeparator()
    menu.addAction(f"Alle {len(ordner)} Ordner öffnen", lambda: [os.startfile(p) for p, _ in ordner])
    menu.exec(knopf.mapToGlobal(knopf.rect().bottomLeft()))


class _VerlaufTabelle(QTableWidget):
    """„Änderungsverlauf“: Benutzer, Datum/Uhrzeit, Aktion und geänderte Felder."""

    def __init__(self):
        super().__init__(0, 3)
        self.setHorizontalHeaderLabels(["Wann", "Wer", "Was"])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.setAccessibleName("Änderungsverlauf")

    def fuellen(self, eintraege: list[dict]):
        self.setRowCount(len(eintraege))
        for r, e in enumerate(eintraege):
            wer = e["benutzer"] + (f" ({e['rolle_text']})" if e.get("rolle_text") and e["rolle_text"] not in
                                   e["benutzer"] else "")
            for c, text in enumerate((e["zeit_text"], wer, e["text"])):
                self.setItem(r, c, QTableWidgetItem(text))
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(1)


class _Notiz(QPlainTextEdit):
    """Mehrzeilige Notiz, die beim Verlassen speichert."""

    def __init__(self, beim_verlassen):
        super().__init__()
        self._fn = beim_verlassen
        self.setFixedHeight(80)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self._fn()


class _StammSeite(QWidget):
    FELDER: list[tuple[str, str]] = []
    NEU_TEXT = "Neu"
    SUCHE_TEXT = "Suchen …"

    def __init__(self, ctx, akte_oeffnen):
        super().__init__()
        self.ctx, self.akte_oeffnen = ctx, akte_oeffnen
        self.aktuell: int | None = None
        self._laedt = False
        split = QSplitter()
        links = theme.karte(QFrame(), schatten=False)
        ll = QVBoxLayout(links)
        ll.setContentsMargins(12, 12, 12, 12)
        oben = QHBoxLayout()
        self.suche = QLineEdit()
        self.suche.setPlaceholderText(self.SUCHE_TEXT)
        self.suche.setToolTip(getattr(self, "SUCHE_TIPP", ""))
        self.suche.textChanged.connect(self.laden)
        oben.addWidget(self.suche, 1)
        b_neu = QPushButton(theme.icon("plus", "primaer_text", 16), f"  {self.NEU_TEXT}")
        theme.rolle(b_neu, "primaer")
        b_neu.clicked.connect(self.neu)
        oben.addWidget(b_neu)
        ll.addLayout(oben)
        self.liste = QListWidget()
        self.liste.currentItemChanged.connect(lambda *_: self.anzeigen())
        ll.addWidget(self.liste, 1)
        split.addWidget(links)
        rechts = theme.karte(QFrame(), schatten=False)
        self.rl = QVBoxLayout(rechts)
        self.rl.setContentsMargins(18, 14, 18, 14)
        self.titel = theme.ueberschrift("–", "h2")
        self.rl.addWidget(self.titel)
        self.l_meta = theme.rolle(QLabel(""), "gedimmt")
        self.l_meta.setAccessibleName("Erstellt und geändert")
        self.rl.addWidget(self.l_meta)
        self._basis: dict = {}
        self._offen = False
        self._nur_liste = False
        self.form = QFormLayout()
        self.felder: dict[str, QWidget] = {}
        self._formular()
        self.rl.addLayout(self.form)
        self.l_status = theme.rolle(QLabel(""), "gedimmt")
        self.rl.addWidget(self.l_status)
        self._extra()
        split.addWidget(rechts)
        split.setSizes([330, 700])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split, 1)
        self._aktiv(False)

    def _feld(self, key: str, label: str, w: QWidget | None = None):
        if w is None:
            w = QLineEdit()
            w.editingFinished.connect(self.speichern)
        self.felder[key] = w
        w.setAccessibleName(label.rstrip(" *"))
        self.form.addRow(label + ":", w)

    def _formular(self):
        for key, label in self.FELDER:
            if key == "notiz":
                self._feld(key, label, _Notiz(self.speichern))
            else:
                self._feld(key, label)

    def _extra(self):
        pass

    def _aktiv(self, an: bool):
        for w in self.felder.values():
            w.setEnabled(an)

    def _werte(self) -> dict:
        out = {}
        for k, w in self.felder.items():
            if isinstance(w, QLineEdit):
                out[k] = w.text()
            elif isinstance(w, QPlainTextEdit):
                out[k] = w.toPlainText()
            elif isinstance(w, QComboBox):
                out[k] = w.currentData()
        return out

    def _setzen(self, daten: dict):
        self._laedt = True
        for k, w in self.felder.items():
            v = daten.get(k) or ""
            if isinstance(w, QLineEdit):
                w.setText(str(v))
            elif isinstance(w, QPlainTextEdit):
                w.setPlainText(str(v))
            elif isinstance(w, QComboBox):
                i = w.findData(v)
                w.setCurrentIndex(max(i, 0))
        self._laedt = False

    def _gespeichert(self):
        theme.status_setzen(self.l_status, "ok", "Gespeichert")

    # --- Mehrbenutzer: nur Geändertes speichern, Konflikte zeigen, Eingaben nie verlieren -------
    def _ungespeichert(self) -> dict:
        return {k: v for k, v in self._werte().items() if not gleich(self._basis.get(k), v)}

    def _feld_setzen(self, k: str, v):
        w = self.felder.get(k)
        self._laedt = True
        if isinstance(w, QLineEdit):
            w.setText(str(v or ""))
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText(str(v or ""))
        elif isinstance(w, QComboBox):
            w.setCurrentIndex(max(w.findData(v), 0))
        self._laedt = False

    def _sicher_speichern(self, fn, _intern: bool = False) -> bool:
        """fn(geaendert, basis). True = gespeichert (oder nichts zu tun). Nie verschachtelt: Während ein
        Vergleichsfenster offen ist, lösen weitere Feldwechsel kein zweites Speichern aus."""
        if getattr(self, "_im_speichern", False) and not _intern:
            return False
        self._im_speichern = True
        try:
            return self._sicher_speichern_innen(fn)
        finally:
            if not _intern:
                self._im_speichern = False

    def _sicher_speichern_innen(self, fn) -> bool:
        geaendert = self._ungespeichert()
        if not geaendert:
            self._offen = False
            return True
        basis = {k: self._basis.get(k) for k in geaendert}
        try:
            fn(geaendert, basis)
        except Konflikt as k:
            return self._konflikt(k, geaendert, fn)
        except OFFLINE as e:
            self._offen = True
            text = str(e) if not isinstance(e, OFFLINE[0]) else "keine Verbindung zum Server."
            theme.status_setzen(self.l_status, "fehler", f"NICHT gespeichert – {text} Ihre Eingabe bleibt im "
                                                         "Formular und wird nach dem Wiederverbinden gespeichert.")
            self.l_status.setToolTip(str(e))
            return False
        except ValueError as e:
            theme.status_setzen(self.l_status, "warn", meldung(e))
            return False
        except Exception as e:  # noqa: BLE001
            from .netz_ui import ausnahme_behandeln
            if ausnahme_behandeln(self, e):
                theme.status_setzen(self.l_status, "warn", "Nicht gespeichert.")
                return False
            raise
        self._basis.update(geaendert)
        self._offen = False
        return True

    def _konflikt(self, k: Konflikt, geaendert: dict, fn) -> bool:
        from .netz_ui import KonfliktDialog
        dlg = KonfliktDialog(self, k, geaendert)
        dlg.exec()
        if dlg.ergebnis == "meine":
            for f in geaendert:                      # bewusst überschreiben: Basis = aktueller Stand
                self._basis[f] = k.aktuell.get(f)
            return self._sicher_speichern(fn, _intern=True)
        if dlg.ergebnis == "aktuell":
            for f in k.felder:
                self._feld_setzen(f, k.aktuell.get(f))
                self._basis[f] = k.aktuell.get(f)
            return self._sicher_speichern(fn, _intern=True)
        self._offen = False
        theme.status_setzen(self.l_status, "warn", "Nicht gespeichert – gleichzeitige Änderung offen. Ihre Eingabe "
                                                   "steht weiter im Formular.")
        return False

    def von_aussen_aktualisieren(self):
        """Andere Benutzer haben etwas geändert: Liste neu laden. Das Formular nur, wenn darin nichts
        Ungespeichertes steht (sonst bleibt Ihre Eingabe unangetastet)."""
        if self._offen:
            self.speichern()
        self._nur_liste = bool(self._ungespeichert()) or self._offen
        try:
            self.laden()
        finally:
            self._nur_liste = False


class MandantenTab(_StammSeite):
    FELDER = [("name", "Name / Firma *"), ("strasse", "Straße, Nr."), ("plz", "PLZ"), ("ort", "Ort"),
              ("telefon", "Telefon"), ("email", "E-Mail"), ("notiz", "Notiz")]
    NEU_TEXT = "Neuer Mandant"
    SUCHE_TEXT = "Suchen …"
    SUCHE_TIPP = "Sucht nach Name, Mandats-Nr. (M01), Aktenzeichen, Versicherungsnummer oder Schaden-Nr."
    AKTEN_SPALTEN = [("aktenzeichen", "Aktenzeichen"), ("versicherungsnummer", "Versicherungsnummer"),
                     ("schaden_nr", "Schaden-Nr."), ("versicherung", "Versicherung")]

    def _formular(self):
        self.l_nummer = QLabel("–")
        self.l_nummer.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.l_nummer.setStyleSheet("font-weight: 700;")
        self.l_nummer.setAccessibleName("Mandats-Nr.")
        self.l_nummer.setToolTip("Wird automatisch vergeben und bleibt immer gleich")
        self.form.addRow("Mandats-Nr.:", self.l_nummer)
        art = QComboBox()
        art.addItem("Person", "person")
        art.addItem("Firma", "firma")
        art.currentIndexChanged.connect(lambda *_: self.speichern())
        self._feld("art", "Art", art)
        self.akte_felder: dict[str, QLineEdit] = {}
        self.form.setVerticalSpacing(6)

        def eingabe(key: str, text: str, akte: bool = False) -> QLineEdit:
            w = QLineEdit()
            w.setAccessibleName(text)
            if akte:
                w.setToolTip("Gehört zur markierten Akte unten. Hat der Mandant noch keine Akte, "
                             "wird sie beim Eintragen automatisch angelegt.")
                w.editingFinished.connect(lambda f=key: self._akte_feld_gesetzt(f))
                self.akte_felder[key] = w
            else:
                w.editingFinished.connect(self.speichern)
                self.felder[key] = w
            return w

        def zeile(links: QLineEdit, label2: str, rechts: QLineEdit, links_breite: int | None = None):
            h = QHBoxLayout()
            h.setSpacing(8)
            if links_breite:
                links.setFixedWidth(links_breite)
            h.addWidget(links, 0 if links_breite else 1)
            if label2:
                h.addWidget(QLabel(label2))
            h.addWidget(rechts, 1)
            return h

        self._feld("name", "Name / Firma *")
        self._feld("strasse", "Straße, Nr.")
        self.form.addRow("PLZ, Ort:", zeile(eingabe("plz", "PLZ"), "", eingabe("ort", "Ort"), 90))
        self.form.addRow("Telefon:", zeile(eingabe("telefon", "Telefon"), "E-Mail:", eingabe("email", "E-Mail")))
        self.form.addRow("Aktenzeichen:", eingabe("aktenzeichen", "Aktenzeichen", akte=True))
        self.form.addRow("Versicherungsnr.:", zeile(eingabe("versicherungsnummer", "Versicherungsnummer", akte=True),
                                                     "Schaden-Nr.:", eingabe("schaden_nr", "Schaden-Nr.", akte=True)))
        notiz = _Notiz(self.speichern)
        notiz.setFixedHeight(50)
        self._feld("notiz", "Notiz", notiz)

    def _extra(self):
        # Mandant löschen: Rechtsklick auf den Mandanten oder Entf-Taste
        from PySide6.QtGui import QKeySequence, QShortcut
        self.liste.setContextMenuPolicy(Qt.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._kontextmenue)
        self.liste.setToolTip("Rechtsklick: Mandant löschen")
        entf = QShortcut(QKeySequence.Delete, self.liste)
        entf.setContext(Qt.WidgetShortcut)
        entf.activated.connect(self.loeschen)
        self.rl.addSpacing(8)
        kopf = QHBoxLayout()
        kopf.addWidget(theme.ueberschrift("Akten / Mandate", "h3"), 1)
        self.b_akte = QPushButton(theme.icon("plus", "titel", 16), "  Neue Akte")
        self.b_akte.clicked.connect(self.neue_akte)
        self.b_ordner = QPushButton(theme.icon("ordner", "titel", 16), "  Dokumentenordner öffnen")
        self.b_ordner.setToolTip("Öffnet den Ordner mit den bisherigen Dokumenten dieses Mandanten (aus den Akten)")
        self.b_ordner.clicked.connect(lambda: ordner_oeffnen(self, self.ctx.stammdaten.dokumentordner(
            mandant_id=self.aktuell), self.b_ordner, self.l_status, self.ctx))
        kopf.addWidget(self.b_ordner)
        kopf.addWidget(self.b_akte)
        self.rl.addLayout(kopf)
        self.akten = QTableWidget(0, len(self.AKTEN_SPALTEN))
        self.akten.setHorizontalHeaderLabels([t for _, t in self.AKTEN_SPALTEN])
        self.akten.verticalHeader().setVisible(False)
        self.akten.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.akten.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.akten.setSelectionMode(QAbstractItemView.SingleSelection)
        self.akten.setEditTriggers(QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        self.akten.setAccessibleName("Akten / Mandate")
        self.akten.setToolTip("Doppelklick öffnet die Akte · markiertes Feld anklicken oder F2: direkt ändern")
        self.akten.itemDoubleClicked.connect(
            lambda it: self.akte_oeffnen(self.akten.item(it.row(), 0).data(Qt.UserRole)))
        self.akten.itemChanged.connect(self._akte_feld_geaendert)
        self.akten.itemSelectionChanged.connect(self._akte_felder_fuellen)
        self.akten.setMinimumHeight(90)
        from PySide6.QtWidgets import QTabWidget
        self.unten = QTabWidget()
        self.unten.addTab(self.akten, "Akten / Mandate")
        self.verlauf_tab = _VerlaufTabelle()
        self.unten.addTab(self.verlauf_tab, "Änderungsverlauf")
        self.rl.addWidget(self.unten, 1)

    def _aktiv(self, an: bool):
        super()._aktiv(an)
        for w in getattr(self, "akte_felder", {}).values():
            w.setEnabled(an)
        for b in ("b_akte", "b_ordner"):
            if hasattr(self, b):
                getattr(self, b).setEnabled(an)

    def laden(self):
        st = self.ctx.stammdaten
        wahl = self.aktuell
        self.liste.blockSignals(True)
        self.liste.clear()
        for m in st.mandanten(self.suche.text().strip()):
            it = QListWidgetItem(theme.icon("kanzlei" if m["art"] == "firma" else "start", "titel"),
                                 self._listentext(m, m["akten"]))
            it.setData(Qt.UserRole, m["id"])
            self.liste.addItem(it)
            if m["id"] == wahl:
                self.liste.setCurrentItem(it)
        self.liste.blockSignals(False)
        self.anzeigen()

    def anzeigen(self):
        if self._nur_liste:
            return
        it = self.liste.currentItem()
        neu_gewaehlt = (it.data(Qt.UserRole) if it else None) != self.aktuell
        self.aktuell = it.data(Qt.UserRole) if it else None
        m = self.ctx.stammdaten.mandant(self.aktuell) if self.aktuell else None
        self._aktiv(m is not None)
        self.titel.setText(m["name"] if m else "Kein Mandant ausgewählt")
        self.l_nummer.setText((m.get("nummer") or "–") if m else "–")
        self._basis = dict(m or {})
        self._setzen(m or {})
        self.l_meta.setText(meta_text(m))
        if neu_gewaehlt:
            self.l_status.setText("")
        self._akte_wahl = None if neu_gewaehlt else self._akte_ref()
        self._akten_tabelle(m)
        self.verlauf_tab.fuellen(self.ctx.aenderungsverlauf("mandant", m["id"]) if m else [])

    def _akten_tabelle(self, m):
        self.akten.blockSignals(True)
        self.akten.setRowCount(0)
        if m:
            akten = self.ctx.stammdaten.akten_von_mandant(m["id"])
            self.akten.setRowCount(len(akten))
            for r, a in enumerate(akten):
                for c, (feld, _) in enumerate(self.AKTEN_SPALTEN):
                    it = QTableWidgetItem(str(a.get(feld) or ""))
                    it.setData(Qt.UserRole, a["referenz"])
                    it.setData(Qt.UserRole + 1, str(a.get(feld) or ""))      # Basis für Konfliktprüfung
                    it.setToolTip(f"Akte {a['referenz']}")
                    if feld == "versicherung":                  # Versicherung wird in der Akte gewählt
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if c == 0:
                        it.setIcon(theme.icon("akten", "titel"))
                    self.akten.setItem(r, c, it)
        self.akten.blockSignals(False)
        self._akte_markieren(getattr(self, "_akte_wahl", None))

    @staticmethod
    def _listentext(m: dict, akten: int = 0) -> str:
        return ((f"{m['nummer']}  ·  " if m.get("nummer") else "") + (m.get("name") or "")
                + (f"  ·  {m['ort']}" if m.get("ort") else "") + (f"  ·  {akten} Akte(n)" if akten else ""))

    def _akte_feld_geaendert(self, it):
        feld = self.AKTEN_SPALTEN[it.column()][0]
        if feld == "versicherung":
            return
        if not self._akte_sicher(it.data(Qt.UserRole), feld, it.text().strip(), it.data(Qt.UserRole + 1)):
            return
        self.akten.blockSignals(True)
        it.setData(Qt.UserRole + 1, it.text().strip())
        self.akten.blockSignals(False)
        self._akte_felder_fuellen()
        self._gespeichert()

    def _akte_sicher(self, ref: str, feld: str, wert: str, basis, _intern: bool = False) -> bool:
        """Ein Akten-Feld speichern – mit Konfliktprüfung und ohne Datenverlust bei fehlender Verbindung."""
        if getattr(self, "_im_speichern", False) and not _intern:
            return False
        self._im_speichern = True
        try:
            return self._akte_sicher_innen(ref, feld, wert, basis)
        finally:
            if not _intern:
                self._im_speichern = False

    def _akte_sicher_innen(self, ref: str, feld: str, wert: str, basis) -> bool:
        st = self.ctx.stammdaten
        try:
            st.akte_setzen(ref, _basis={feld: basis}, **{feld: wert})
            return True
        except Konflikt as k:
            from .netz_ui import KonfliktDialog
            dlg = KonfliktDialog(self, k, {feld: wert})
            dlg.exec()
            if dlg.ergebnis == "meine":
                return self._akte_sicher(ref, feld, wert, k.aktuell.get(feld), _intern=True)
            if dlg.ergebnis == "aktuell":
                self.anzeigen_akten()
                return False
            theme.status_setzen(self.l_status, "warn", "Nicht gespeichert – gleichzeitige Änderung offen.")
            return False
        except OFFLINE as e:
            theme.status_setzen(self.l_status, "fehler", "NICHT gespeichert – keine Verbindung zum Server. Ihre "
                                                         f"Eingabe bleibt stehen. ({type(e).__name__})")
            return False

    # --- Akten-Felder im Formular ------------------------------------------------
    def _akte_ref(self) -> str | None:
        r = self.akten.currentRow()
        it = self.akten.item(r, 0) if r >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def _akte_markieren(self, ref: str | None):
        """Gewünschte Akte markieren (sonst die neueste) und ihre Werte in die Felder übernehmen."""
        zeile = 0
        for r in range(self.akten.rowCount()):
            if self.akten.item(r, 0).data(Qt.UserRole) == ref:
                zeile = r
        if self.akten.rowCount():
            self.akten.selectRow(zeile)
            self.akten.setCurrentCell(zeile, 0)
        self._akte_felder_fuellen()

    def _akte_felder_fuellen(self):
        ref = self._akte_ref()
        a = self.ctx.stammdaten.akte(ref) if ref else None
        self._akte_basis = dict(a or {})
        for feld, w in self.akte_felder.items():
            if w.hasFocus() and w.isModified() and not gleich(w.text(), self._akte_basis.get(feld)):
                continue                                    # gerade getippte Eingabe nicht überschreiben
            w.setText(str((a or {}).get(feld) or ""))
            w.setModified(False)

    def _akte_feld_gesetzt(self, feld: str):
        if self._laedt or not self.aktuell:
            return
        st = self.ctx.stammdaten
        wert = self.akte_felder[feld].text().strip()
        ref = self._akte_ref()
        if ref:
            basis = getattr(self, "_akte_basis", {}).get(feld)
            if gleich(basis, wert):
                return                                      # nichts geändert
            if not self._akte_sicher(ref, feld, wert, basis):
                return
        else:
            if not wert:
                return
            # Noch keine Akte: aus den eingetragenen Nummern automatisch anlegen
            werte = {f: w.text().strip() for f, w in self.akte_felder.items() if w.text().strip()}
            m = st.mandant(self.aktuell) or {}
            ref = werte.get("aktenzeichen") or werte.get("versicherungsnummer") or werte.get("schaden_nr")
            if st.akte(ref) and st.akte(ref).get("mandant_id") not in (None, self.aktuell):
                ref = f"{ref} ({m.get('nummer') or self.aktuell})"   # Nummer gehört schon zu anderem Mandanten
            st.akte_anlegen(ref, mandant_id=self.aktuell, mandant_name=m.get("name", ""),
                            mandant_email=m.get("email", ""), **werte)
        self._akte_wahl = ref
        self.anzeigen_akten()
        self._gespeichert()

    def anzeigen_akten(self):
        """Nur die Akten-Tabelle neu füllen (Formular und Fokus bleiben)."""
        m = self.ctx.stammdaten.mandant(self.aktuell) if self.aktuell else None
        fokus = QApplication.focusWidget()
        self._akten_tabelle(m)
        if fokus is not None:
            fokus.setFocus()
        it = self.liste.currentItem()
        if it and m:
            it.setText(self._listentext(m, self.akten.rowCount()))

    def neu(self):
        name, ok = QInputDialog.getText(self, "Neuer Mandant", "Name oder Firmenname:")
        if not ok or not name.strip():
            return
        self.aktuell = self.ctx.stammdaten.mandant_speichern(None, name=name.strip(), art="person")
        self.suche.clear()
        self.laden()
        self.felder["strasse"].setFocus()

    def speichern(self):
        if self._laedt or not self.aktuell:
            return
        w = self._werte()
        if w.get("email") and not is_valid_email(w["email"].strip()):
            theme.status_setzen(self.l_status, "warn", f"„{w['email']}“ ist keine gültige E-Mail-Adresse – "
                                                       "nicht gespeichert.")
            return
        mid = self.aktuell
        if not self._ungespeichert():
            return
        if not self._sicher_speichern(lambda g, b: self.ctx.stammdaten.mandant_speichern(mid, _basis=b, **g)):
            return
        st = self.ctx.stammdaten
        m = st.mandant(mid) or {}
        self.titel.setText(m.get("name", w["name"]))
        self.l_meta.setText(meta_text(m))
        self.verlauf_tab.fuellen(self.ctx.aenderungsverlauf("mandant", mid))
        it = self.liste.currentItem()
        if it:
            it.setText(self._listentext(m, len(st.akten_von_mandant(mid))))
        self._gespeichert()

    def _kontextmenue(self, pos):
        from PySide6.QtWidgets import QMenu
        it = self.liste.itemAt(pos)
        if it is None:
            return
        self.liste.setCurrentItem(it)
        menu = QMenu(self)
        menu.addAction(theme.icon("loeschen", "fehler", 16), "Mandant löschen …", self.loeschen)
        menu.exec(self.liste.viewport().mapToGlobal(pos))

    def loeschen(self):
        """Mandant nach Rückfrage löschen. Akten, Verlauf und Dokumente bleiben erhalten (nur ohne Mandant);
        die Mandats-Nr. wird nie neu vergeben."""
        st = self.ctx.stammdaten
        m = st.mandant(self.aktuell) if self.aktuell else None
        if not m:
            return
        n = len(st.akten_von_mandant(m["id"]))
        name = (f"{m['nummer']} · " if m.get("nummer") else "") + m["name"]
        text = f"Mandant „{name}“ wirklich löschen?"
        info = ("Die Akte und ihre Dokumente bleiben erhalten – sie ist danach keinem Mandanten zugeordnet."
                if n == 1 else
                f"Die {n} Akten und ihre Dokumente bleiben erhalten – sie sind danach keinem Mandanten zugeordnet."
                if n else "Dieser Mandant hat keine Akten.")
        box = QMessageBox(QMessageBox.Warning, "Mandant löschen", text, parent=self)
        box.setInformativeText(info + "\nDie Mandats-Nr. wird nicht neu vergeben.")
        ja = box.addButton("Löschen", QMessageBox.DestructiveRole)
        nein = box.addButton("Abbrechen", QMessageBox.RejectRole)
        box.setDefaultButton(nein)
        box.setEscapeButton(nein)
        box.exec()
        if box.clickedButton() is not ja:
            return
        zeile = self.liste.currentRow()
        st.mandant_loeschen(m["id"])
        self.aktuell = None
        self.laden()
        if self.liste.count():
            self.liste.setCurrentRow(min(zeile, self.liste.count() - 1))
        theme.status_setzen(self.l_status, "ok", f"„{name}“ gelöscht")

    def neue_akte(self):
        if not self.aktuell:
            return
        ref, ok = QInputDialog.getText(self, "Neue Akte", "Aktenzeichen oder Versicherungs-/Schaden-Nr.:")
        if not ok or not ref.strip():
            return
        m = self.ctx.stammdaten.mandant(self.aktuell)
        self.ctx.stammdaten.akte_anlegen(ref.strip(), mandant_id=self.aktuell, mandant_name=m["name"],
                                         mandant_email=m["email"])
        self.anzeigen()
        self.akte_oeffnen(ref.strip())


class VersicherungenTab(_StammSeite):
    FELDER = [("name", "Name *"), ("strasse", "Straße, Nr."), ("plz", "PLZ"), ("ort", "Ort"),
              ("telefon", "Telefon"), ("notiz", "Notiz")]
    NEU_TEXT = "Neue Versicherung"

    def _extra(self):
        self.rl.addSpacing(8)
        kopf = QHBoxLayout()
        kopf.addWidget(theme.ueberschrift("E-Mail-Adressen", "h3"), 1)
        self.b_mail = QPushButton(theme.icon("plus", "titel", 16), "  Adresse hinzufügen")
        self.b_mail.clicked.connect(self.mail_hinzufuegen)
        self.b_mail_weg = QPushButton("Entfernen")
        self.b_mail_weg.clicked.connect(self.mail_entfernen)
        self.b_standard = QPushButton("★ Als Standard")
        self.b_standard.setToolTip("Diese Adresse wird in Akten automatisch eingetragen, wenn es mehrere gibt")
        self.b_standard.clicked.connect(self.mail_standard)
        kopf.addWidget(self.b_mail)
        kopf.addWidget(self.b_standard)
        kopf.addWidget(self.b_mail_weg)
        self.rl.addLayout(kopf)
        self.mails = QListWidget()
        self.mails.setMaximumHeight(130)
        self.rl.addWidget(self.mails)
        akopf = QHBoxLayout()
        akopf.addWidget(theme.ueberschrift("Akten", "h3"), 1)
        self.b_ordner = QPushButton(theme.icon("ordner", "titel", 16), "  Dokumentenordner öffnen")
        self.b_ordner.setToolTip("Öffnet den Ordner mit den bisherigen Dokumenten zu dieser Versicherung (aus den Akten)")
        self.b_ordner.clicked.connect(lambda: ordner_oeffnen(self, self.ctx.stammdaten.dokumentordner(
            versicherung_id=self.aktuell), self.b_ordner, self.l_status, self.ctx) if self.aktuell else
            theme.status_setzen(self.l_status, None, "Zu dieser Versicherung gibt es noch keine Akten."))
        akopf.addWidget(self.b_ordner)
        self.rl.addLayout(akopf)
        self.akten = QListWidget()
        self.akten.itemDoubleClicked.connect(lambda it: self.akte_oeffnen(it.data(Qt.UserRole)))
        self.rl.addWidget(self.akten, 1)

    def _aktiv(self, an: bool):
        super()._aktiv(an)
        for b in ("b_mail", "b_mail_weg", "b_standard", "b_ordner"):
            if hasattr(self, b):
                getattr(self, b).setEnabled(an)

    def laden(self):
        wahl = self.aktuell
        self.liste.blockSignals(True)
        self.liste.clear()
        self._eintraege = self.ctx.stammdaten.versicherungen(self.suche.text().strip())
        for i, v in enumerate(self._eintraege):
            it = QListWidgetItem(theme.icon("adressbuch", "titel"), v["name"] + (
                f"  ·  {len(v['emails'])} E-Mail" if v["emails"] else ""))
            it.setData(Qt.UserRole, i)
            self.liste.addItem(it)
            if v["id"] is not None and v["id"] == wahl:
                self.liste.setCurrentItem(it)
        self.liste.blockSignals(False)
        self.anzeigen()

    def _eintrag(self) -> dict | None:
        it = self.liste.currentItem()
        return self._eintraege[it.data(Qt.UserRole)] if it else None

    def _id_sicher(self) -> int | None:
        """Adressbuch-Eintrag ohne eigenen Datensatz → beim ersten Bearbeiten anlegen (gleicher Name)."""
        v = self._eintrag()
        if v is None:
            return None
        if v["id"] is None:
            v["id"] = self.ctx.stammdaten.versicherung_speichern(None, name=v["name"])
        self.aktuell = v["id"]
        return v["id"]

    def anzeigen(self):
        v = self._eintrag()
        self.aktuell = v["id"] if v else None
        self._aktiv(v is not None)
        if self._nur_liste:
            return
        self.titel.setText(v["name"] if v else "Keine Versicherung ausgewählt")
        self._basis = dict(v or {})
        self._setzen(v or {})
        self.l_meta.setText(meta_text(v) if v and v.get("id") is not None else "")
        self.l_status.setText("aus dem Versicherer-Adressbuch" if v and v["id"] is None else "")
        self.mails.clear()
        self.akten.clear()
        if v:
            std = (v.get("standard_email") or "").lower()
            for e in v["emails"]:
                it = QListWidgetItem(f"★ {meldung(e)}  (Standard)" if e.lower() == std else e)
                it.setData(Qt.UserRole, e)
                self.mails.addItem(it)
            if v["id"] is not None:
                for a in self.ctx.stammdaten.akten_von_versicherung(v["id"]):
                    li = QListWidgetItem(theme.icon("akten", "titel"), a["referenz"])
                    li.setData(Qt.UserRole, a["referenz"])
                    self.akten.addItem(li)

    def neu(self):
        name, ok = QInputDialog.getText(self, "Neue Versicherung", "Name der Versicherung:")
        if not ok or not name.strip():
            return
        self.aktuell = self.ctx.stammdaten.versicherung_speichern(None, name=name.strip())
        self.suche.clear()
        self.laden()
        self.felder["strasse"].setFocus()

    def speichern(self):
        if self._laedt or self._eintrag() is None:
            return
        vid = self._id_sicher()
        w = self._werte()
        if not self._ungespeichert():
            return
        if not self._sicher_speichern(lambda g, b: self.ctx.stammdaten.versicherung_speichern(vid, _basis=b, **g)):
            return
        self._eintrag().update(w)
        self.titel.setText(w["name"])
        self.l_meta.setText(meta_text(self.ctx.stammdaten.versicherung(vid)))
        self._gespeichert()

    def mail_hinzufuegen(self):
        vid = self._id_sicher()
        if vid is None:
            return
        mail, ok = QInputDialog.getText(self, "E-Mail-Adresse", "E-Mail-Adresse der Versicherung:")
        mail = mail.strip()
        if not ok or not mail:
            return
        if not is_valid_email(mail):
            QMessageBox.warning(self, "Ungültig", f"„{mail}“ ist keine gültige E-Mail-Adresse.")
            return
        try:
            self.ctx.stammdaten.email_hinzufuegen(vid, mail)
        except ValueError as e:
            QMessageBox.information(self, "E-Mail", meldung(e))
        self.laden()

    def mail_entfernen(self):
        it = self.mails.currentItem()
        vid = self._id_sicher()
        if it is None or vid is None:
            return
        self.ctx.stammdaten.email_entfernen(vid, it.data(Qt.UserRole) or it.text())
        self.laden()

    def mail_standard(self):
        it = self.mails.currentItem()
        vid = self._id_sicher()
        if it is None or vid is None:
            return
        self.ctx.stammdaten.standard_email_setzen(vid, it.data(Qt.UserRole) or it.text())
        self.laden()
