"""Büro bilgileri penceresi (Einstellungen → Kanzleidaten)."""
from __future__ import annotations

from dataclasses import fields as dc_fields
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTextBrowser,
    QVBoxLayout, QWidget,
)

from core.kanzlei import Kanzlei, KanzleiStore, pruefen, signatur_html

# (alan, etiket) – gruplar halinde
GRUPPEN = [
    ("Kanzlei", [("name", "Name der Kanzlei *"), ("anwaelte", "Anwälte (je Zeile einer)"),
                 ("berufsbezeichnung", "Berufsbezeichnung"), ("kammer", "Zuständige Kammer")]),
    ("Anschrift und Kontakt", [("strasse", "Straße, Nr."), ("plz", "PLZ"), ("ort", "Ort"),
                               ("telefon", "Telefon"), ("fax", "Fax"), ("email", "E-Mail"),
                               ("website", "Website")]),
    ("Steuer", [("steuernummer", "Steuernummer"), ("ust_id", "USt-IdNr.")]),
    ("Bankverbindung", [("bank", "Bank"), ("iban", "IBAN"), ("bic", "BIC")]),
]


class KanzleiDialog(QDialog):
    def __init__(self, parent, store: KanzleiStore, erster_start: bool = False):
        super().__init__(parent)
        self.store = store
        self.daten = store.laden()
        self.neues_logo: Path | None = None
        self.setWindowTitle("Kanzleidaten")
        self.setMinimumWidth(820)

        self.edits: dict[str, QLineEdit | QPlainTextEdit] = {}
        links = QVBoxLayout()
        if erster_start:
            hinweis = QLabel("Willkommen! Bitte zuerst die Daten der Kanzlei eintragen. "
                             "Sie werden für Signatur, Briefkopf und Dateinamen verwendet.")
            hinweis.setWordWrap(True)
            links.addWidget(hinweis)

        for titel, felder in GRUPPEN:
            box = QGroupBox(titel)
            form = QFormLayout(box)
            for key, label in felder:
                wert = getattr(self.daten, key)
                if key == "anwaelte":
                    ed = QPlainTextEdit(wert)
                    ed.setFixedHeight(64)
                    ed.textChanged.connect(self.vorschau_aktualisieren)
                else:
                    ed = QLineEdit(wert)
                    ed.textChanged.connect(self.vorschau_aktualisieren)
                self.edits[key] = ed
                form.addRow(label + ":", ed)
            links.addWidget(box)

        # Sağ taraf: logo + imza önizlemesi
        rechts = QVBoxLayout()
        logo_box = QGroupBox("Logo")
        lb = QVBoxLayout(logo_box)
        self.logo_label = QLabel("Kein Logo")
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setMinimumHeight(90)
        lb.addWidget(self.logo_label)
        row = QHBoxLayout()
        b_logo = QPushButton("Logo wählen…")
        b_logo.clicked.connect(self.logo_waehlen)
        b_weg = QPushButton("Entfernen")
        b_weg.clicked.connect(self.logo_entfernen)
        row.addWidget(b_logo)
        row.addWidget(b_weg)
        lb.addLayout(row)
        rechts.addWidget(logo_box)

        vb = QGroupBox("Vorschau E-Mail-Signatur")
        vl = QVBoxLayout(vb)
        self.vorschau = QTextBrowser()
        vl.addWidget(self.vorschau)
        rechts.addWidget(vb, 1)

        haupt = QHBoxLayout()
        lw, rw = QWidget(), QWidget()
        lw.setLayout(links)
        rw.setLayout(rechts)
        haupt.addWidget(lw, 3)
        haupt.addWidget(rw, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Speichern")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.speichern)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(haupt)
        lay.addWidget(buttons)

        self.logo_anzeigen(store.logo_pfad(self.daten))
        self.vorschau_aktualisieren()

    def formular_lesen(self) -> Kanzlei:
        werte = {}
        for f in dc_fields(Kanzlei):
            ed = self.edits.get(f.name)
            if ed is None:
                werte[f.name] = getattr(self.daten, f.name)
            elif isinstance(ed, QPlainTextEdit):
                werte[f.name] = ed.toPlainText().strip()
            else:
                werte[f.name] = ed.text().strip()
        return Kanzlei(**werte)

    def logo_anzeigen(self, pfad: Path | None):
        if pfad and pfad.exists():
            pm = QPixmap(str(pfad))
            self.logo_label.setPixmap(pm.scaled(240, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.logo_label.setPixmap(QPixmap())
            self.logo_label.setText("Kein Logo")

    def logo_waehlen(self):
        name, _ = QFileDialog.getOpenFileName(self, "Logo wählen", "", "Bilder (*.png *.jpg *.jpeg)")
        if name:
            self.neues_logo = Path(name)
            self.logo_anzeigen(self.neues_logo)

    def logo_entfernen(self):
        self.neues_logo = None
        self.daten.logo = ""
        self.logo_anzeigen(None)

    def vorschau_aktualisieren(self):
        k = self.formular_lesen()
        # Önizlemede logo yer tutucusu yerine dosya yolu
        html = signatur_html(k, "LOGO" if (self.neues_logo or k.logo) else None)
        logo = self.neues_logo or self.store.logo_pfad(k)
        if logo:
            html = html.replace("cid:LOGO", Path(logo).as_uri())
        self.vorschau.setHtml(html)

    def speichern(self):
        k = self.formular_lesen()
        fehler = pruefen(k)
        if fehler:
            QMessageBox.warning(self, "Bitte prüfen", "\n".join(fehler))
            return
        if self.neues_logo:
            k.logo = self.store.logo_uebernehmen(self.neues_logo)
        self.store.speichern(k)
        self.accept()
