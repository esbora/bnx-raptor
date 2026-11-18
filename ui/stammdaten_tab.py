"""Seiten „Mandanten“ und „Versicherungen“ (0.4.1).

Links die Liste mit Suche und „Neu“, rechts das Formular. Gespeichert wird automatisch beim Verlassen
eines Feldes – kein Speichern-Knopf. Versicherer-E-Mails sind das bestehende Versicherer-Adressbuch.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from core.extractor import is_valid_email

from . import theme


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
        self.suche.setPlaceholderText("Suchen …")
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


class MandantenTab(_StammSeite):
    FELDER = [("name", "Name / Firma *"), ("strasse", "Straße, Nr."), ("plz", "PLZ"), ("ort", "Ort"),
              ("telefon", "Telefon"), ("email", "E-Mail"), ("notiz", "Notiz")]
    NEU_TEXT = "Neuer Mandant"

    def _formular(self):
        art = QComboBox()
        art.addItem("Person", "person")
        art.addItem("Firma", "firma")
        art.currentIndexChanged.connect(lambda *_: self.speichern())
        self._feld("art", "Art", art)
        super()._formular()

    def _extra(self):
        self.rl.addSpacing(8)
        kopf = QHBoxLayout()
        kopf.addWidget(theme.ueberschrift("Akten / Mandate", "h3"), 1)
        self.b_akte = QPushButton(theme.icon("plus", "titel", 16), "  Neue Akte")
        self.b_akte.clicked.connect(self.neue_akte)
        kopf.addWidget(self.b_akte)
        self.rl.addLayout(kopf)
        self.akten = QListWidget()
        self.akten.setToolTip("Doppelklick öffnet die Akte")
        self.akten.itemDoubleClicked.connect(lambda it: self.akte_oeffnen(it.data(Qt.UserRole)))
        self.rl.addWidget(self.akten, 1)

    def _aktiv(self, an: bool):
        super()._aktiv(an)
        if hasattr(self, "b_akte"):
            self.b_akte.setEnabled(an)

    def laden(self):
        st = self.ctx.stammdaten
        wahl = self.aktuell
        self.liste.blockSignals(True)
        self.liste.clear()
        for m in st.mandanten(self.suche.text().strip()):
            it = QListWidgetItem(theme.icon("kanzlei" if m["art"] == "firma" else "start", "titel"),
                                 f"{m['name']}" + (f"  ·  {m['ort']}" if m["ort"] else "")
                                 + (f"  ·  {m['akten']} Akte(n)" if m["akten"] else ""))
            it.setData(Qt.UserRole, m["id"])
            self.liste.addItem(it)
            if m["id"] == wahl:
                self.liste.setCurrentItem(it)
        self.liste.blockSignals(False)
        self.anzeigen()

    def anzeigen(self):
        it = self.liste.currentItem()
        self.aktuell = it.data(Qt.UserRole) if it else None
        m = self.ctx.stammdaten.mandant(self.aktuell) if self.aktuell else None
        self._aktiv(m is not None)
        self.titel.setText(m["name"] if m else "Kein Mandant ausgewählt")
        self._setzen(m or {})
        self.l_status.setText("")
        self.akten.clear()
        if m:
            for a in self.ctx.stammdaten.akten_von_mandant(m["id"]):
                text = a["referenz"] + (f"  ·  Az. {a['aktenzeichen']}" if a.get("aktenzeichen") else "")
                li = QListWidgetItem(theme.icon("akten", "titel"), text)
                li.setData(Qt.UserRole, a["referenz"])
                self.akten.addItem(li)

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
        try:
            self.ctx.stammdaten.mandant_speichern(self.aktuell, **w)
        except ValueError as e:
            theme.status_setzen(self.l_status, "warn", str(e))
            return
        self.titel.setText(w["name"])
        it = self.liste.currentItem()
        if it:
            it.setText(w["name"] + (f"  ·  {w['ort']}" if w.get("ort") else ""))
        self._gespeichert()

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
        kopf.addWidget(self.b_mail)
        kopf.addWidget(self.b_mail_weg)
        self.rl.addLayout(kopf)
        self.mails = QListWidget()
        self.mails.setMaximumHeight(130)
        self.rl.addWidget(self.mails)
        self.rl.addWidget(theme.ueberschrift("Akten", "h3"))
        self.akten = QListWidget()
        self.akten.itemDoubleClicked.connect(lambda it: self.akte_oeffnen(it.data(Qt.UserRole)))
        self.rl.addWidget(self.akten, 1)

    def _aktiv(self, an: bool):
        super()._aktiv(an)
        for b in ("b_mail", "b_mail_weg"):
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
        self.titel.setText(v["name"] if v else "Keine Versicherung ausgewählt")
        self._setzen(v or {})
        self.l_status.setText("aus dem Versicherer-Adressbuch" if v and v["id"] is None else "")
        self.mails.clear()
        self.akten.clear()
        if v:
            for e in v["emails"]:
                self.mails.addItem(e)
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
        try:
            self.ctx.stammdaten.versicherung_speichern(vid, **w)
        except ValueError as e:
            theme.status_setzen(self.l_status, "warn", str(e))
            return
        self._eintrag().update(w)
        self.titel.setText(w["name"])
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
            QMessageBox.information(self, "E-Mail", str(e))
        self.laden()

    def mail_entfernen(self):
        it = self.mails.currentItem()
        vid = self._id_sicher()
        if it is None or vid is None:
            return
        self.ctx.stammdaten.email_entfernen(vid, it.text())
        self.laden()
