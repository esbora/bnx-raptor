"""Versicherer-Adressbuch penceresi: kayıtları görme, düzenleme, ekleme, silme."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.adressbuch import Adressbuch
from core.extractor import is_valid_email

SPALTEN = ["Versicherer", "E-Mail", "Zuletzt verwendet", "Anzahl"]


class AdressbuchDialog(QDialog):
    def __init__(self, parent, buch: Adressbuch):
        super().__init__(parent)
        self.buch = buch
        self.setWindowTitle("Versicherer-Adressbuch")
        self.resize(820, 460)

        info = QLabel(
            "Einträge entstehen automatisch, wenn Sie einen Entwurf mit Versicherer und "
            "E-Mail-Adresse bestätigen. Name und E-Mail können hier per Doppelklick korrigiert werden.")
        info.setWordWrap(True)

        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Suchen …")
        self.suche.textChanged.connect(self._filtern)

        self.table = QTableWidget(0, len(SPALTEN))
        self.table.setHorizontalHeaderLabels(SPALTEN)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemChanged.connect(self._geaendert)

        b_neu = QPushButton("Neuer Eintrag")
        b_neu.clicked.connect(self._neu)
        b_del = QPushButton("Löschen")
        b_del.clicked.connect(self._loeschen)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Close)
        knoepfe.button(QDialogButtonBox.Close).setText("Schließen")
        knoepfe.rejected.connect(self.accept)

        row = QHBoxLayout()
        row.addWidget(b_neu)
        row.addWidget(b_del)
        row.addStretch(1)
        row.addWidget(knoepfe)

        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.suche)
        lay.addWidget(self.table, 1)
        lay.addLayout(row)
        self.laden()

    def laden(self):
        self.table.blockSignals(True)
        eintraege = self.buch.alle()
        self.table.setRowCount(len(eintraege))
        for r, e in enumerate(eintraege):
            werte = [e["name"], e["email"], e["zuletzt"] or "", str(e["anzahl"] or 0)]
            for c, text in enumerate(werte):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, e["id"])
                item.setData(Qt.UserRole + 1, text)        # eski değer (geri almak için)
                if c >= 2:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)
        self._filtern(self.suche.text())

    def _filtern(self, text: str):
        t = text.lower().strip()
        for r in range(self.table.rowCount()):
            zeile = " ".join(self.table.item(r, c).text().lower() for c in (0, 1))
            self.table.setRowHidden(r, bool(t) and t not in zeile)

    def _geaendert(self, item: QTableWidgetItem):
        r = item.row()
        eid = item.data(Qt.UserRole)
        name, email = self.table.item(r, 0).text().strip(), self.table.item(r, 1).text().strip()
        fehler = ""
        if not name:
            fehler = "Der Name des Versicherers darf nicht leer sein."
        elif not is_valid_email(email):
            fehler = f"„{email}“ ist keine gültige E-Mail-Adresse."
        else:
            try:
                self.buch.aendern(eid, name, email)
            except ValueError as e:
                fehler = str(e)
        if fehler:
            QMessageBox.warning(self, "Nicht gespeichert", fehler)
            self.table.blockSignals(True)
            item.setText(item.data(Qt.UserRole + 1))     # eski değere dön
            self.table.blockSignals(False)
            return
        item.setData(Qt.UserRole + 1, item.text())

    def _neu(self):
        dlg = _NeuDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self.buch.hinzufuegen(*dlg.werte())
        except ValueError as e:
            QMessageBox.warning(self, "Nicht gespeichert", str(e))
        self.laden()

    def _loeschen(self):
        zeilen = sorted({i.row() for i in self.table.selectedItems()})
        if not zeilen:
            QMessageBox.information(self, "Löschen", "Bitte zuerst einen Eintrag auswählen.")
            return
        namen = "\n".join(f"{self.table.item(r, 0).text()} – {self.table.item(r, 1).text()}"
                          for r in zeilen)
        if QMessageBox.question(self, "Löschen", f"Diese Einträge löschen?\n\n{namen}") \
                != QMessageBox.Yes:
            return
        for r in zeilen:
            self.buch.loeschen(self.table.item(r, 0).data(Qt.UserRole))
        self.laden()


class _NeuDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Neuer Eintrag")
        self.name = QLineEdit()
        self.email = QLineEdit()
        lay = QVBoxLayout(self)
        for label, feld in (("Versicherer:", self.name), ("E-Mail:", self.email)):
            lay.addWidget(QLabel(label))
            lay.addWidget(feld)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        knoepfe.button(QDialogButtonBox.Ok).setText("Speichern")
        knoepfe.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        knoepfe.accepted.connect(self._check)
        knoepfe.rejected.connect(self.reject)
        lay.addWidget(knoepfe)

    def _check(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Fehlt", "Bitte den Namen des Versicherers eintragen.")
        elif not is_valid_email(self.email.text()):
            QMessageBox.warning(self, "Ungültig", "Bitte eine gültige E-Mail-Adresse eintragen.")
        else:
            self.accept()

    def werte(self) -> tuple[str, str]:
        return self.name.text().strip(), self.email.text().strip()
