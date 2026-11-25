"""„Posteingang“ (0.5): gemeinsamer Kanzlei-Eingang mit Akte-Vorschlag, Aufgaben und Schnellaktionen.

Sekretariat: E-Mails aus Outlook (markierte), .eml/.msg und Dateien übernehmen, Akte bestätigen, vorbereiten.
Rechtsanwalt: entscheidet über die Schnellaktionen (Zur Kenntnis, Antwort vorbereiten, Unterlagen anfordern, Rückruf,
Frist prüfen) und verteilt Aufgaben. Alle Regeln (Rechte, Doppelte, Konflikte) liegen im Kern (core/posteingang.py).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core import posteingang as pk
from core import posteingang_service as ps
from core.benutzer import Berechtigung
from core.fehlertexte import meldung
from core.protokoll import Konflikt

from . import theme

try:
    from core.netz import SitzungFehler, VerbindungFehler, WartungFehler
    OFFLINE = (VerbindungFehler, WartungFehler, SitzungFehler)
except ImportError:  # pragma: no cover
    OFFLINE = ()

ANSICHTEN = [("Offene Eingänge", "e:offen"), ("Nicht zugeordnet", "e:nicht_zugeordnet"), ("Neu", "e:neu"),
             ("In Bearbeitung", "e:in_bearbeitung"), ("Erledigt", "e:erledigt"), ("Alle Eingänge", "e:alle"),
             ("Meine Aufgaben", "a:meine"), ("Überfällige Aufgaben", "a:ueberfaellig"),
             ("Alle offenen Aufgaben", "a:offen"), ("Erledigte Aufgaben", "a:erledigt")]
QUELLEN = {"outlook": "Outlook", "eml": "E-Mail-Datei", "msg": "Outlook-Datei", "datei": "Datei"}


def _item(text, daten=None) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text or ""))
    if daten is not None:
        it.setData(Qt.UserRole, daten)
    return it


def _de(zeit: str) -> str:
    from core.protokoll import _de as de
    return de(zeit) if zeit and len(zeit) > 10 else _tag(zeit)


def _tag(iso: str) -> str:
    try:
        j, m, t = (iso or "")[:10].split("-")
        return f"{t}.{m}.{j}"
    except ValueError:
        return iso or ""


def fehler_zeigen(parent, e: BaseException, titel: str = "BnX-Raptor") -> None:
    if isinstance(e, OFFLINE):
        QMessageBox.warning(parent, "Nicht gespeichert", str(e))
    elif isinstance(e, Berechtigung):
        QMessageBox.information(parent, "Keine Berechtigung", str(e))
    elif isinstance(e, Konflikt):
        QMessageBox.warning(parent, "Gleichzeitige Änderung", str(e))
    elif isinstance(e, ValueError):
        QMessageBox.warning(parent, titel, str(e))
    else:
        QMessageBox.critical(parent, titel, meldung(e))


class AufgabeDialog(QDialog):
    """Schnellaktion → Aufgabe: Verantwortlich, Beschreibung, Priorität, optional fällig am."""

    def __init__(self, parent, art: str, personen: list[dict], ich: str, darf_verteilen: bool,
                 vorschlag_verantwortlich: str = "", titel_zusatz: str = ""):
        super().__init__(parent)
        titel, text = pk.AKTIONEN[art]
        self.setWindowTitle(f"{titel} – Aufgabe anlegen")
        self.resize(520, 320)
        lay = QVBoxLayout(self)
        lay.addWidget(theme.ueberschrift(titel + (f" · {titel_zusatz}" if titel_zusatz else ""), "h3"))
        if art == "frist":
            h = theme.rolle(QLabel("Prüfauftrag: BnX-Raptor berechnet keine Frist und trägt keine Frist ein. Bitte "
                                   "selbst prüfen und im Fristenkalender eintragen."), "gedimmt")
            h.setWordWrap(True)
            lay.addWidget(h)
        form = QFormLayout()
        self.verantwortlich = QComboBox()
        for p in personen:
            self.verantwortlich.addItem(f"{p['anzeige']} ({_rolle(p.get('rolle'))})", p["name"])
        wahl = vorschlag_verantwortlich if darf_verteilen else ich
        i = self.verantwortlich.findData(wahl)
        if i < 0:
            i = self.verantwortlich.findData(ich)
        self.verantwortlich.setCurrentIndex(max(i, 0))
        self.verantwortlich.setEnabled(darf_verteilen)
        if not darf_verteilen:
            self.verantwortlich.setToolTip("Aufgaben für andere vergibt die Rechtsanwältin / der Rechtsanwalt.")
        self.beschreibung = QPlainTextEdit(text)
        self.beschreibung.setFixedHeight(90)
        self.prioritaet = QComboBox()
        for k, v in pk.PRIORITAETEN.items():
            self.prioritaet.addItem(v, k)
        self.prioritaet.setCurrentIndex(1)
        self.faellig = QLineEdit()
        self.faellig.setPlaceholderText("optional, TT.MM.JJJJ")
        form.addRow("Verantwortlich:", self.verantwortlich)
        form.addRow("Beschreibung:", self.beschreibung)
        form.addRow("Priorität:", self.prioritaet)
        form.addRow("Zu erledigen bis:", self.faellig)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Aufgabe anlegen")
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def _rolle(r: str | None) -> str:
    from core.benutzer import ROLLEN
    return ROLLEN.get(r or "", r or "")


class PosteingangTab(QWidget):
    """Seite „Posteingang“."""
    geaendert = Signal()

    def __init__(self, ctx, akte_oeffnen, nachricht_senden=None):
        super().__init__()
        self.ctx = ctx
        self.akte_oeffnen = akte_oeffnen
        self.nachricht_senden = nachricht_senden        # fn(empfaenger, text, akte, aufgabe_id) – Mehrbenutzer
        self.pe = ctx.posteingang
        self.setAcceptDrops(True)
        self._ausstehend: list[ps.Stueck] = []          # nach Verbindungsabbruch (gleiche Kennung)
        self._eingang: dict | None = None
        self._aufgabe: dict | None = None
        self._laedt = False
        self._personen: list[dict] = []

        oben = QHBoxLayout()
        self.b_outlook = QPushButton(theme.icon("mail", "primaer_text", 16), "  Aus Outlook übernehmen")
        theme.rolle(self.b_outlook, "primaer")
        self.b_outlook.setToolTip("Die im klassischen Outlook markierten E-Mails übernehmen (nur Kopien – im Postfach "
                                  "wird nichts verändert)")
        self.b_outlook.clicked.connect(self.outlook_uebernehmen)
        self.b_dateien = QPushButton(theme.icon("plus", "titel", 16), "  Dateien / E-Mails hinzufügen…")
        self.b_dateien.clicked.connect(self.dateien_waehlen)
        self.b_erneut = QPushButton("Erneut übertragen")
        self.b_erneut.setVisible(False)
        self.b_erneut.clicked.connect(self.ausstehende_ablegen)
        oben.addWidget(self.b_outlook)
        oben.addWidget(self.b_dateien)
        oben.addWidget(self.b_erneut)
        oben.addStretch(1)
        filter_ = QHBoxLayout()
        self.ansicht = QComboBox()
        for t, k in ANSICHTEN:
            self.ansicht.addItem(t, k)
        self.ansicht.setAccessibleName("Ansicht")
        self.ansicht.currentIndexChanged.connect(lambda *_: self.laden())
        self.wer = QComboBox()
        self.wer.setAccessibleName("Verantwortlich (Filter)")
        self.wer.currentIndexChanged.connect(lambda *_: self.laden())
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Suchen: Akte, Betreff, Absender …")
        self.suche.textChanged.connect(lambda *_: self.laden())
        filter_.addWidget(QLabel("Ansicht:"))
        filter_.addWidget(self.ansicht)
        filter_.addWidget(QLabel("Verantwortlich:"))
        filter_.addWidget(self.wer)
        filter_.addWidget(self.suche, 1)

        self.liste = QTableWidget(0, 7)
        self.liste.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.liste.setSelectionMode(QAbstractItemView.SingleSelection)
        self.liste.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.liste.verticalHeader().hide()
        self.liste.setAccessibleName("Posteingang")
        self.liste.itemSelectionChanged.connect(self.auswahl_zeigen)

        self.stapel = QStackedWidget()
        self.leer = theme.rolle(QLabel("Links einen Eingang oder eine Aufgabe auswählen – oder E-Mails/Dateien "
                                       "hierher ziehen."), "gedimmt")
        self.leer.setAlignment(Qt.AlignCenter)
        self.leer.setWordWrap(True)
        self.stapel.addWidget(self.leer)
        self.stapel.addWidget(self._eingang_panel())
        self.stapel.addWidget(self._aufgabe_panel())
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setWidget(self.stapel)

        split = QSplitter()
        split.addWidget(self.liste)
        split.addWidget(sc)
        split.setSizes([470, 730])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(oben)
        lay.addLayout(filter_)
        lay.addWidget(split, 1)
        self.status = theme.rolle(QLabel("Tipp: E-Mails (.eml/.msg), PDFs, Word-Dateien und Scans hierher ziehen."),
                                  "gedimmt")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

    # ------------------------------------------------------------------ Panels
    def _eingang_panel(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 0, 4, 0)
        self.e_titel = theme.ueberschrift("", "h2")
        self.e_meta = theme.rolle(QLabel(""), "gedimmt")
        self.e_meta.setWordWrap(True)
        self.e_meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.addWidget(self.e_titel)
        l.addWidget(self.e_meta)
        # Akte
        karte = theme.karte(QFrame(), schatten=False)
        kl = QVBoxLayout(karte)
        kl.setContentsMargins(12, 8, 12, 8)
        kopf = QHBoxLayout()
        kopf.addWidget(theme.ueberschrift("Akte", "h3"))
        self.e_akte = QLabel("")
        self.e_akte.setWordWrap(True)
        kopf.addWidget(self.e_akte, 1)
        self.b_akte_oeffnen = QPushButton("Akte öffnen")
        theme.rolle(self.b_akte_oeffnen, "link")
        self.b_akte_oeffnen.clicked.connect(lambda: self._eingang and self._eingang["akte"] and
                                            self.akte_oeffnen(self._eingang["akte"]))
        kopf.addWidget(self.b_akte_oeffnen)
        kl.addLayout(kopf)
        self.e_vorschlag_text = theme.rolle(QLabel(""), "gedimmt")
        self.e_vorschlag_text.setWordWrap(True)
        kl.addWidget(self.e_vorschlag_text)
        self.e_vorschlaege = QListWidget()
        self.e_vorschlaege.setAccessibleName("Akte-Vorschläge")
        self.e_vorschlaege.setMaximumHeight(110)
        self.e_vorschlaege.setWordWrap(True)
        kl.addWidget(self.e_vorschlaege)
        zk = QHBoxLayout()
        self.b_bestaetigen = QPushButton("Ausgewählte Akte bestätigen")
        theme.rolle(self.b_bestaetigen, "primaer")
        self.b_bestaetigen.clicked.connect(self.vorschlag_bestaetigen)
        self.b_andere = QPushButton("Andere Akte wählen…")
        self.b_andere.clicked.connect(self.andere_akte)
        self.b_ocr = QPushButton("Texterkennung für den Vorschlag")
        self.b_ocr.setToolTip("Gescannte PDF-Seiten auf diesem Rechner lesen (OCR) und den Vorschlag neu berechnen")
        self.b_ocr.clicked.connect(self.ocr_fuer_vorschlag)
        zk.addWidget(self.b_bestaetigen)
        zk.addWidget(self.b_andere)
        zk.addWidget(self.b_ocr)
        zk.addStretch(1)
        kl.addLayout(zk)
        l.addWidget(karte)
        # Angaben
        g = QGridLayout()
        self.f_belegart = QComboBox()
        self.f_belegart.setEditable(True)
        self.f_belegart.addItems([""] + pk.BELEGARTEN)
        self.f_datum = QLineEdit()
        self.f_datum.setPlaceholderText("TT.MM.JJJJ")
        self.f_verantwortlich = QComboBox()
        self.f_status = QComboBox()
        for k, v in pk.STATUS.items():
            self.f_status.addItem(v, k)
        self.f_schritt = QLineEdit()
        self.f_schritt.setPlaceholderText("z. B. „Mandant informieren“")
        self.l_belegart_hint = theme.rolle(QLabel(""), "gedimmt")
        for w_, n in ((self.f_belegart, "Belegart"), (self.f_datum, "Dokumentdatum"),
                      (self.f_verantwortlich, "Verantwortlich"), (self.f_status, "Status"),
                      (self.f_schritt, "Nächster Schritt")):
            w_.setAccessibleName(n)
        g.addWidget(QLabel("Belegart:"), 0, 0)
        g.addWidget(self.f_belegart, 0, 1)
        g.addWidget(QLabel("Dokumentdatum:"), 0, 2)
        g.addWidget(self.f_datum, 0, 3)
        g.addWidget(self.l_belegart_hint, 1, 1, 1, 3)
        g.addWidget(QLabel("Verantwortlich:"), 2, 0)
        g.addWidget(self.f_verantwortlich, 2, 1)
        g.addWidget(QLabel("Status:"), 2, 2)
        g.addWidget(self.f_status, 2, 3)
        g.addWidget(QLabel("Nächster Schritt:"), 3, 0)
        g.addWidget(self.f_schritt, 3, 1, 1, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        l.addLayout(g)
        self.f_belegart.lineEdit().editingFinished.connect(lambda: self._feld_speichern("belegart",
                                                                                         self.f_belegart.currentText()))
        self.f_belegart.activated.connect(lambda *_: self._feld_speichern("belegart", self.f_belegart.currentText()))
        self.f_datum.editingFinished.connect(lambda: self._feld_speichern("dokument_datum", self.f_datum.text()))
        self.f_verantwortlich.activated.connect(
            lambda *_: self._feld_speichern("verantwortlich", self.f_verantwortlich.currentData() or ""))
        self.f_status.activated.connect(lambda *_: self._feld_speichern("status", self.f_status.currentData()))
        self.f_schritt.editingFinished.connect(lambda: self._feld_speichern("naechster_schritt", self.f_schritt.text()))
        self.l_gespeichert = theme.rolle(QLabel(""), "gedimmt")
        l.addWidget(self.l_gespeichert)
        # Dateien
        l.addWidget(QLabel("Dateien – Doppelklick öffnet (Original bleibt unverändert):"))
        self.e_dateien = QListWidget()
        self.e_dateien.setMaximumHeight(110)
        self.e_dateien.setAccessibleName("Dateien des Eingangs")
        self.e_dateien.itemDoubleClicked.connect(self._datei_oeffnen)
        l.addWidget(self.e_dateien)
        # Erwartete Unterlagen
        self.e_erw_box = QWidget()
        el = QVBoxLayout(self.e_erw_box)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(QLabel("Passt zu erwarteten Unterlagen dieser Akte (Vorschlag – bitte prüfen):"))
        self.e_erwartungen = QListWidget()
        self.e_erwartungen.setMaximumHeight(80)
        self.e_erwartungen.setAccessibleName("Passende erwartete Unterlagen")
        el.addWidget(self.e_erwartungen)
        b = QPushButton("Mit diesem Eingang verknüpfen")
        b.setToolTip("Status wird „Eingegangen – zu prüfen“ – geprüft wird von Hand")
        b.clicked.connect(self.erwartung_verknuepfen)
        el.addWidget(b, 0, Qt.AlignLeft)
        l.addWidget(self.e_erw_box)
        # Schnellaktionen
        l.addWidget(theme.ueberschrift("Schnellaktionen", "h3"))
        reihe = QHBoxLayout()
        self.aktion_knoepfe = {}
        for art in ("kenntnis", "antwort", "unterlagen", "rueckruf", "frist"):
            kb = QPushButton(pk.AKTIONEN[art][0])
            kb.clicked.connect(lambda _=False, a=art: self.schnellaktion(a))
            reihe.addWidget(kb)
            self.aktion_knoepfe[art] = kb
        reihe.addStretch(1)
        l.addLayout(reihe)
        # Aufgaben zu diesem Eingang
        l.addWidget(QLabel("Aufgaben zu diesem Eingang:"))
        self.e_aufgaben = QTableWidget(0, 5)
        self.e_aufgaben.setHorizontalHeaderLabels(["Aufgabe", "Verantwortlich", "Fällig", "Status", "Erledigt"])
        self.e_aufgaben.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.e_aufgaben.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.e_aufgaben.verticalHeader().hide()
        self.e_aufgaben.setMaximumHeight(130)
        self.e_aufgaben.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.e_aufgaben.cellDoubleClicked.connect(lambda r, _c: self._aufgabe_aus_tabelle(r))
        l.addWidget(self.e_aufgaben)
        ak = QHBoxLayout()
        b1 = QPushButton("Erledigt")
        b1.clicked.connect(lambda: self._aufgabe_status_tabelle(True))
        b2 = QPushButton("Wieder öffnen")
        b2.clicked.connect(lambda: self._aufgabe_status_tabelle(False))
        ak.addWidget(b1)
        ak.addWidget(b2)
        ak.addStretch(1)
        l.addLayout(ak)
        l.addStretch(1)
        return w

    def _aufgabe_panel(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 0, 4, 0)
        self.a_titel = theme.ueberschrift("", "h2")
        self.a_meta = theme.rolle(QLabel(""), "gedimmt")
        self.a_meta.setWordWrap(True)
        self.a_hinweis = theme.rolle(QLabel(""), "gedimmt")
        self.a_hinweis.setWordWrap(True)
        l.addWidget(self.a_titel)
        l.addWidget(self.a_meta)
        l.addWidget(self.a_hinweis)
        form = QFormLayout()
        self.a_beschreibung = QPlainTextEdit()
        self.a_beschreibung.setFixedHeight(100)
        self.a_verantwortlich = QComboBox()
        self.a_prioritaet = QComboBox()
        for k, v in pk.PRIORITAETEN.items():
            self.a_prioritaet.addItem(v, k)
        self.a_faellig = QLineEdit()
        self.a_faellig.setPlaceholderText("optional, TT.MM.JJJJ")
        form.addRow("Beschreibung:", self.a_beschreibung)
        form.addRow("Verantwortlich:", self.a_verantwortlich)
        form.addRow("Priorität:", self.a_prioritaet)
        form.addRow("Zu erledigen bis:", self.a_faellig)
        l.addLayout(form)
        reihe = QHBoxLayout()
        b_sp = QPushButton("Änderungen speichern")
        b_sp.clicked.connect(self.aufgabe_speichern)
        self.b_erledigt = QPushButton(theme.icon("uebernehmen", "primaer_text", 16), "  Erledigt")
        theme.rolle(self.b_erledigt, "primaer")
        self.b_erledigt.clicked.connect(lambda: self._aufgabe_status(True))
        self.b_wieder = QPushButton("Wieder öffnen")
        self.b_wieder.clicked.connect(lambda: self._aufgabe_status(False))
        self.b_a_akte = QPushButton("Akte öffnen")
        self.b_a_akte.clicked.connect(lambda: self._aufgabe and self._aufgabe["akte"] and
                                      self.akte_oeffnen(self._aufgabe["akte"]))
        self.b_a_eingang = QPushButton("Eingang zeigen")
        self.b_a_eingang.clicked.connect(lambda: self._aufgabe and self._aufgabe.get("eingang_id") and
                                         self.eingang_zeigen(self._aufgabe["eingang_id"]))
        for b in (b_sp, self.b_erledigt, self.b_wieder, self.b_a_akte, self.b_a_eingang):
            reihe.addWidget(b)
        reihe.addStretch(1)
        l.addLayout(reihe)
        self.a_status = theme.rolle(QLabel(""), "gedimmt")
        l.addWidget(self.a_status)
        l.addStretch(1)
        return w

    # ------------------------------------------------------------------ Laden
    def _personen_laden(self):
        try:
            self._personen = self.pe.personen()
        except OFFLINE:
            return
        wahl = self.wer.currentData()
        self.wer.blockSignals(True)
        self.wer.clear()
        self.wer.addItem("Alle", "")
        for p in self._personen:
            self.wer.addItem(p["anzeige"], p["name"])
        i = self.wer.findData(wahl)
        self.wer.setCurrentIndex(max(i, 0))
        self.wer.blockSignals(False)
        for cb in (self.f_verantwortlich, self.a_verantwortlich):
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("— niemand —", "")
            for p in self._personen:
                cb.addItem(f"{p['anzeige']} ({_rolle(p.get('rolle'))})", p["name"])
            cb.blockSignals(False)

    @property
    def _ich(self) -> str:
        return self.ctx.benutzername

    @property
    def _darf_verteilen(self) -> bool:
        return self.ctx.rolle in pk.VERTEILEN

    def ansicht_setzen(self, schluessel: str):
        i = self.ansicht.findData(schluessel)
        if i >= 0:
            self.ansicht.setCurrentIndex(i)
        self.laden()

    def laden(self):
        if self._laedt:
            return
        self._laedt = True
        try:
            if not self._personen:
                self._personen_laden()
            art, _, schl = (self.ansicht.currentData() or "e:offen").partition(":")
            wer = self.wer.currentData() or ""
            suche = self.suche.text().strip()
            wahl = self._auswahl_schluessel()
            try:
                if art == "e":
                    zeilen = self.pe.liste(schl, verantwortlich=wer, suche=suche)
                else:
                    if schl == "meine":
                        zeilen = self.pe.aufgaben("offen", verantwortlich="ich")
                    else:
                        zeilen = self.pe.aufgaben(schl, verantwortlich=wer)
                    if suche:
                        s = suche.lower()
                        zeilen = [a for a in zeilen if s in (a["titel"] + a["beschreibung"] + a["akte"] +
                                                             (a.get("eingang_betreff") or "")).lower()]
            except OFFLINE as e:
                theme.status_setzen(self.status, "fehler", str(e))
                return
            self._modus = art
            self.liste.blockSignals(True)
            self.liste.clearContents()
            if art == "e":
                self.liste.setColumnCount(8)
                self.liste.setHorizontalHeaderLabels(["Eingang", "Von", "Betreff", "Belegart", "Akte",
                                                      "Verantwortlich", "Status", "Offene Aufg."])
                self.liste.setRowCount(len(zeilen))
                for r, e in enumerate(zeilen):
                    self.liste.setItem(r, 0, _item(_de(e["eingang_am"]), ("e", e["id"])))
                    self.liste.setItem(r, 1, _item(e["absender_name"] or e["absender"] or QUELLEN.get(e["quelle"], "")))
                    self.liste.setItem(r, 2, _item(e["betreff"]))
                    self.liste.setItem(r, 3, _item(e["belegart"]))
                    akte = e["akte"] or ("Vorschlag: " + e["vorschlag"][0]["referenz"] if e["vorschlag"] else
                                         "nicht zugeordnet")
                    it = _item(akte)
                    if not e["akte"]:
                        it.setForeground(theme.status_farbe("warn"))
                    self.liste.setItem(r, 4, it)
                    self.liste.setItem(r, 5, _item(e["verantwortlich_anzeige"]))
                    self.liste.setItem(r, 6, _item(e["status_text"]))
                    self.liste.setItem(r, 7, _item(e["offene_aufgaben"] or ""))
                    if ("e", e["id"]) == wahl:
                        self.liste.selectRow(r)
            else:
                self.liste.setColumnCount(7)
                self.liste.setHorizontalHeaderLabels(["Zu erledigen bis", "Aufgabe", "Akte", "Eingang",
                                                      "Verantwortlich", "Priorität", "Status"])
                self.liste.setRowCount(len(zeilen))
                for r, a in enumerate(zeilen):
                    f = _item(_tag(a["faellig"]) + ("  ⚠ überfällig" if a["ueberfaellig"] else ""), ("a", a["id"]))
                    if a["ueberfaellig"]:
                        f.setForeground(theme.status_farbe("fehler"))
                    self.liste.setItem(r, 0, f)
                    self.liste.setItem(r, 1, _item(a["titel"]))
                    self.liste.setItem(r, 2, _item(a["akte"]))
                    self.liste.setItem(r, 3, _item(a.get("eingang_betreff") or ""))
                    self.liste.setItem(r, 4, _item(a["verantwortlich_anzeige"]))
                    self.liste.setItem(r, 5, _item(a["prioritaet_text"]))
                    self.liste.setItem(r, 6, _item(a["status_text"]))
                    if ("a", a["id"]) == wahl:
                        self.liste.selectRow(r)
            self.liste.blockSignals(False)
            self.liste.resizeColumnsToContents()
            self.liste.horizontalHeader().setSectionResizeMode(2 if art == "e" else 1, QHeaderView.Stretch)
            if self._auswahl_schluessel() is None:
                self.stapel.setCurrentIndex(0)
            else:
                self.auswahl_zeigen()
        finally:
            self._laedt = False

    def von_aussen_aktualisieren(self):
        """Änderungen anderer Benutzer: Liste neu, offene Eingaben bleiben (gespeichert wird beim Verlassen)."""
        if self.focusWidget() in (self.f_schritt, self.f_datum, self.a_beschreibung, self.a_faellig):
            return
        self.laden()

    def _auswahl_schluessel(self):
        r = self.liste.currentRow()
        if r < 0 or not self.liste.selectedItems():
            return None
        it = self.liste.item(r, 0)
        return tuple(it.data(Qt.UserRole)) if it and it.data(Qt.UserRole) else None

    def auswahl_zeigen(self):
        s = self._auswahl_schluessel()
        if s is None:
            self.stapel.setCurrentIndex(0)
            return
        try:
            if s[0] == "e":
                self._eingang_fuellen(self.pe.eingang(s[1]))
            else:
                self._aufgabe_fuellen(self.pe.aufgabe(s[1]))
        except OFFLINE as e:
            theme.status_setzen(self.status, "fehler", str(e))

    def eingang_zeigen(self, eid: int):
        if not (self.ansicht.currentData() or "").startswith("e:"):
            self.ansicht.setCurrentIndex(self.ansicht.findData("e:alle"))
        self.suche.clear()
        self.laden()
        for r in range(self.liste.rowCount()):
            if self.liste.item(r, 0) and tuple(self.liste.item(r, 0).data(Qt.UserRole)) == ("e", eid):
                self.liste.selectRow(r)
                return

    def aufgabe_zeigen(self, aid: int):
        self.ansicht.setCurrentIndex(self.ansicht.findData("a:offen"))
        self.wer.setCurrentIndex(0)
        self.suche.clear()
        self.laden()
        for r in range(self.liste.rowCount()):
            if self.liste.item(r, 0) and tuple(self.liste.item(r, 0).data(Qt.UserRole)) == ("a", aid):
                self.liste.selectRow(r)
                return
        try:                                              # z. B. bereits erledigt
            a = self.pe.aufgabe(aid)
        except OFFLINE:
            return
        if a:
            self._aufgabe_fuellen(a)

    # ------------------------------------------------------------------ Eingang anzeigen
    def _eingang_fuellen(self, e: dict | None):
        if not e:
            self.stapel.setCurrentIndex(0)
            return
        self._eingang = e
        self.stapel.setCurrentIndex(1)
        self.e_titel.setText(e["betreff"] or "(ohne Betreff)")
        von = e["absender_name"] + (f" <{e['absender']}>" if e["absender"] else "") if e["absender_name"] \
            else e["absender"]
        teile = [f"Eingang: {_de(e['eingang_am'])}", f"Quelle: {QUELLEN.get(e['quelle'], e['quelle'])}"]
        if von:
            teile.insert(0, f"Von: {von}")
        teile.append(f"Erfasst von {e['erstellt_von_anzeige']} am {_de(e['erstellt_am'])}")
        if e.get("geaendert_am") and e["geaendert_am"] != e["erstellt_am"]:
            teile.append(f"zuletzt geändert von {e['geaendert_von_anzeige']} am {_de(e['geaendert_am'])}")
        self.e_meta.setText(" · ".join(teile))
        # Akte / Vorschlag
        self.e_vorschlaege.clear()
        if e["akte"]:
            self.e_akte.setText(f"<b>{e['akte']}</b> – bestätigt von {e['zugeordnet_von_anzeige']} am "
                                f"{_de(e['zugeordnet_am'])}")
            self.e_vorschlag_text.setText("")
            self.e_vorschlaege.setVisible(False)
            self.b_bestaetigen.setVisible(False)
            self.b_andere.setText("Zuordnung ändern…")
            self.b_akte_oeffnen.setVisible(True)
        else:
            self.b_akte_oeffnen.setVisible(False)
            self.b_andere.setText("Andere Akte wählen…")
            self.e_akte.setText("<span style='color:%s'>Noch nicht zugeordnet</span>" % theme.F["warn"])
            v = e["vorschlag"]
            self.e_vorschlaege.setVisible(bool(v))
            self.b_bestaetigen.setVisible(bool(v))
            if not v:
                self.e_vorschlag_text.setText("Kein Vorschlag gefunden (keine bekannte Nummer, kein bekannter "
                                              "Absender). Bitte Akte wählen – der Eingang bleibt bis dahin unter "
                                              "„Nicht zugeordnet“.")
            elif e["eindeutig"]:
                self.e_vorschlag_text.setText("Vorschlag (bitte bestätigen):")
            else:
                self.e_vorschlag_text.setText("Mehrere Akten kommen in Frage – bitte die richtige auswählen. Es wird "
                                              "nichts automatisch zugeordnet.")
            for x in v:
                it = QListWidgetItem(f"{x['referenz']}  –  " + "; ".join(x["gruende"]))
                it.setData(Qt.UserRole, x["referenz"])
                self.e_vorschlaege.addItem(it)
            if v and e["eindeutig"]:
                self.e_vorschlaege.setCurrentRow(0)
        # OCR-Knopf nur bei PDF-Dateien
        self.b_ocr.setVisible(not e["akte"] and any(d["name"].lower().endswith(".pdf") for d in e["dateien"]))
        # Angaben
        self._laedt_felder = True
        self.f_belegart.setCurrentText(e["belegart"] or "")
        self.l_belegart_hint.setText("Belegart erkannt – bitte prüfen" if e["belegart"] else "")
        self.f_datum.setText(_tag(e["dokument_datum"]))
        self.f_verantwortlich.setCurrentIndex(max(self.f_verantwortlich.findData(e["verantwortlich"]), 0))
        self.f_status.setCurrentIndex(max(self.f_status.findData(e["status"]), 0))
        self.f_schritt.setText(e["naechster_schritt"] or "")
        self._laedt_felder = False
        self._basis = {k: e.get(k) for k in pk.EINGANG_FELDER}
        self.l_gespeichert.setText("Änderungen werden automatisch gespeichert.")
        # Dateien
        self.e_dateien.clear()
        for d in e["dateien"]:
            rolle = {"mail": "E-Mail", "anhang": "Anhang", "datei": "Datei"}.get(d["rolle"], d["rolle"])
            it = QListWidgetItem(f"{rolle}: {d['name']}")
            it.setData(Qt.UserRole, d["pfad"])
            self.e_dateien.addItem(it)
        # erwartete Unterlagen
        self.e_erwartungen.clear()
        vorschl = []
        if e["akte"]:
            try:
                vorschl = self.ctx.unterlagen.vorschlaege_fuer_eingang(e["id"])
            except OFFLINE:
                vorschl = []
        for x in vorschl:
            it = QListWidgetItem(f"{x['titel']}  –  " + "; ".join(x["gruende"]))
            it.setData(Qt.UserRole, x["erwartung_id"])
            self.e_erwartungen.addItem(it)
        if vorschl:
            self.e_erwartungen.setCurrentRow(0)
        self.e_erw_box.setVisible(bool(vorschl))
        # Aufgaben
        self._aufgaben_tabelle(e["aufgaben"])

    def _aufgaben_tabelle(self, aufgaben: list[dict]):
        self.e_aufgaben.setRowCount(len(aufgaben))
        for r, a in enumerate(aufgaben):
            self.e_aufgaben.setItem(r, 0, _item(a["titel"] + (f" – {a['beschreibung'][:60]}" if a["beschreibung"]
                                                               else ""), a["id"]))
            self.e_aufgaben.setItem(r, 1, _item(a["verantwortlich_anzeige"]))
            f = _item(_tag(a["faellig"]) + (" ⚠" if a["ueberfaellig"] else ""))
            self.e_aufgaben.setItem(r, 2, f)
            self.e_aufgaben.setItem(r, 3, _item(a["status_text"]))
            self.e_aufgaben.setItem(r, 4, _item(f"{a['erledigt_von_anzeige']} {_de(a['erledigt_am'])}"
                                                if a["status"] == "erledigt" else ""))

    def _feld_speichern(self, feld: str, wert: str):
        if getattr(self, "_laedt_felder", False) or not self._eingang:
            return
        if feld == "dokument_datum":
            try:
                wert = pk._datum_pruefen(wert)
            except ValueError as e:
                theme.status_setzen(self.l_gespeichert, "warn", str(e))
                return
        if str(self._basis.get(feld) or "") == str(wert or ""):
            return
        try:
            e = self.pe.aendern(self._eingang["id"], _basis={feld: self._basis.get(feld)}, **{feld: wert})
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
            if isinstance(ex, Konflikt):
                self._eingang_fuellen(self.pe.eingang(self._eingang["id"]))
            return
        self._basis[feld] = e.get(feld)
        self._eingang = e
        theme.status_setzen(self.l_gespeichert, "ok", "Gespeichert.")
        self._liste_zeile_aktualisieren()

    def _liste_zeile_aktualisieren(self):
        self.laden()

    # ------------------------------------------------------------------ Akte zuordnen
    def vorschlag_bestaetigen(self):
        it = self.e_vorschlaege.currentItem()
        if not self._eingang or it is None:
            QMessageBox.information(self, "Akte", "Bitte zuerst eine der vorgeschlagenen Akten auswählen.")
            return
        self._zuordnen(it.data(Qt.UserRole))

    def andere_akte(self):
        if not self._eingang:
            return
        try:
            refs = sorted(self.ctx.journal.referenzen())
        except OFFLINE as e:
            fehler_zeigen(self, e)
            return
        if not refs:
            QMessageBox.information(self, "Akte", "Es gibt noch keine Akten. Bitte zuerst unter „Akten“ anlegen.")
            return
        optionen = (["— keine Akte (Zuordnung lösen) —"] if self._eingang["akte"] else []) + refs
        ref, ok = QInputDialog.getItem(self, "Akte wählen", f"Akte für „{self._eingang['betreff']}“:", optionen, 0,
                                       True)
        if not ok:
            return
        self._zuordnen("" if ref.startswith("—") else ref.strip())

    def _zuordnen(self, ref: str):
        try:
            e = self.pe.zuordnen(self._eingang["id"], ref, _basis_akte=self._eingang["akte"])
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
            return
        theme.status_setzen(self.status, "ok", f"Akte {ref} bestätigt – Dokumente stehen im Verlauf der Akte."
                            if ref else "Zuordnung gelöst – Eingang steht wieder unter „Nicht zugeordnet“.")
        self._eingang_fuellen(e)
        self.laden()
        self.geaendert.emit()

    def ocr_fuer_vorschlag(self):
        """Gescannte PDF: erste Seiten lokal erkennen (Tesseract im Hintergrund), Vorschlag neu berechnen."""
        if not self._eingang:
            return
        from core import pdf_engine as pe
        from .pdf_ui import im_thread
        texte = []
        self.setEnabled(False)
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for d in self._eingang["dateien"]:
                if not d["name"].lower().endswith(".pdf"):
                    continue
                lokal = self.ctx.dateien.lokal(d["pfad"], "")
                if not lokal:
                    continue
                doc = pe.oeffnen(Path(lokal))
                try:
                    for i in range(min(2, doc.page_count)):
                        if doc[i].get_text().strip():
                            texte.append(doc[i].get_text())
                            continue
                        png, _ = pe.ocr_bild(doc[i], 200)
                        self.status.setText(f"Texterkennung {d['name']}, Seite {i + 1} …")
                        worte = im_thread(lambda png=png: pe.ocr_erkennen(png, 200))
                        texte.append(" ".join(w[0] for w in worte))
                finally:
                    doc.close()
            v = self.pe.text_ergaenzen(self._eingang["id"], "\n".join(texte))
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex, "Texterkennung")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
            self.setEnabled(True)
        theme.status_setzen(self.status, "ok" if v else "warn", "Texterkennung fertig – Vorschlag neu berechnet."
                            if v else "Texterkennung fertig – weiterhin kein Vorschlag. Bitte Akte von Hand wählen.")
        self._eingang_fuellen(self.pe.eingang(self._eingang["id"]))

    def erwartung_verknuepfen(self):
        it = self.e_erwartungen.currentItem()
        if not self._eingang or it is None:
            return
        haupt = next((d for d in self._eingang["dateien"] if d["rolle"] != "mail"), None)
        try:
            e = self.ctx.unterlagen.eingang_verknuepfen(it.data(Qt.UserRole), self._eingang["id"],
                                                        haupt.get("dokument_id") if haupt else None)
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
            return
        theme.status_setzen(self.status, "ok", f"„{e['titel']}“: {e['status_text']}. Bitte prüfen und in der Akte "
                            "als „Geprüft / vollständig“ markieren, wenn alles passt.")
        self._eingang_fuellen(self.pe.eingang(self._eingang["id"]))
        self.geaendert.emit()

    def _datei_oeffnen(self, it: QListWidgetItem):
        pfad = it.data(Qt.UserRole)
        try:
            lokal = self.ctx.dateien.lokal(pfad, self._eingang.get("akte", "") if self._eingang else "")
        except OFFLINE as e:
            fehler_zeigen(self, e)
            return
        if lokal and Path(lokal).exists() and hasattr(os, "startfile"):
            os.startfile(str(lokal))  # type: ignore[attr-defined]
        else:
            QMessageBox.information(self, "Datei", "Die Datei ist nicht (mehr) vorhanden.")

    # ------------------------------------------------------------------ Aufgaben
    def schnellaktion(self, art: str):
        if not self._eingang:
            return
        if not self._personen:
            self._personen_laden()
        vorschlag = self._eingang.get("verantwortlich") or ""
        if self._darf_verteilen and art in ("unterlagen", "rueckruf", "kenntnis"):
            sek = next((p["name"] for p in self._personen if p.get("rolle") == "sekretariat"), "")
            vorschlag = vorschlag if vorschlag and vorschlag.lower() != self._ich.lower() else (sek or self._ich)
        dlg = AufgabeDialog(self, art, self._personen, self._ich, self._darf_verteilen, vorschlag,
                            self._eingang["betreff"][:50])
        if dlg.exec() != QDialog.Accepted:
            return
        self._aufgabe_anlegen(uuid.uuid4().hex, art, dlg.verantwortlich.currentData(),
                              dlg.beschreibung.toPlainText(), dlg.prioritaet.currentData(), dlg.faellig.text(),
                              self._eingang["id"])

    def _aufgabe_anlegen(self, client_id, art, wer, beschreibung, prio, faellig, eingang_id):
        while True:
            try:
                a = self.pe.aufgabe_anlegen(client_id, art, wer, beschreibung, prio, faellig, eingang_id=eingang_id)
                break
            except OFFLINE as e:
                if QMessageBox.question(self, "Nicht gespeichert", f"{e}\n\nErneut versuchen? (Die Aufgabe wird "
                                        "dabei nicht doppelt angelegt.)") != QMessageBox.Yes:
                    return
            except Exception as ex:  # noqa: BLE001
                fehler_zeigen(self, ex)
                return
        text = f"Aufgabe „{a['titel']}“ für {a['verantwortlich_anzeige']} angelegt."
        if self.nachricht_senden and a["verantwortlich"].lower() != self._ich.lower():
            ok = self.nachricht_senden(a["verantwortlich"], f"Neue Aufgabe: {a['titel']}"
                                       + (f" – {a['beschreibung']}" if a["beschreibung"] else "")
                                       + (f" (zu erledigen bis {_tag(a['faellig'])})" if a["faellig"] else ""),
                                       a["akte"], a["id"])
            text += " Benachrichtigung gesendet." if ok else " Benachrichtigung NICHT gesendet (keine Verbindung)."
        theme.status_setzen(self.status, "ok", text)
        if self._eingang:
            self._eingang_fuellen(self.pe.eingang(self._eingang["id"]))
        self.laden()
        self.geaendert.emit()

    def _aufgabe_aus_tabelle(self, r: int):
        it = self.e_aufgaben.item(r, 0)
        if it is not None:
            self._aufgabe_fuellen(self.pe.aufgabe(it.data(Qt.UserRole)))

    def _aufgabe_status_tabelle(self, erledigt: bool):
        r = self.e_aufgaben.currentRow()
        it = self.e_aufgaben.item(r, 0) if r >= 0 else None
        if it is None:
            QMessageBox.information(self, "Aufgabe", "Bitte zuerst eine Aufgabe in der Tabelle markieren.")
            return
        self._status_setzen(it.data(Qt.UserRole), erledigt)
        if self._eingang:
            self._eingang_fuellen(self.pe.eingang(self._eingang["id"]))

    def _aufgabe_fuellen(self, a: dict | None):
        if not a:
            self.stapel.setCurrentIndex(0)
            return
        self._aufgabe = a
        self.stapel.setCurrentIndex(2)
        self.a_titel.setText(a["titel"] + (f" · Akte {a['akte']}" if a["akte"] else ""))
        teile = [f"Status: {a['status_text']}", f"angelegt von {a['erstellt_von_anzeige']} am {_de(a['erstellt_am'])}"]
        if a["status"] == "erledigt":
            teile.append(f"erledigt von {a['erledigt_von_anzeige']} am {_de(a['erledigt_am'])}")
        if a.get("wiedereroeffnet_am"):
            teile.append(f"wieder geöffnet von {a['wiedereroeffnet_von_anzeige']} am {_de(a['wiedereroeffnet_am'])}")
        if a.get("eingang_betreff"):
            teile.append(f"Eingang: {a['eingang_betreff']}")
        self.a_meta.setText(" · ".join(teile))
        self.a_hinweis.setText("⚠ überfällig" if a["ueberfaellig"] else
                               ("Prüfauftrag – BnX-Raptor berechnet keine Frist." if a["art"] == "frist" else ""))
        self.a_beschreibung.setPlainText(a["beschreibung"])
        self.a_verantwortlich.setCurrentIndex(max(self.a_verantwortlich.findData(a["verantwortlich"]), 0))
        self.a_verantwortlich.setEnabled(self._darf_verteilen)
        self.a_prioritaet.setCurrentIndex(max(self.a_prioritaet.findData(a["prioritaet"]), 0))
        self.a_faellig.setText(_tag(a["faellig"]))
        self.b_erledigt.setVisible(a["status"] != "erledigt")
        self.b_wieder.setVisible(a["status"] == "erledigt")
        self.b_a_akte.setVisible(bool(a["akte"]))
        self.b_a_eingang.setVisible(bool(a.get("eingang_id")))
        self._a_basis = {k: a.get(k) for k in pk.AUFGABE_FELDER}
        self.a_status.setText("")

    def aufgabe_speichern(self):
        if not self._aufgabe:
            return
        werte = {"beschreibung": self.a_beschreibung.toPlainText().strip(),
                 "prioritaet": self.a_prioritaet.currentData(), "faellig": self.a_faellig.text().strip()}
        if self._darf_verteilen:
            werte["verantwortlich"] = self.a_verantwortlich.currentData() or self._aufgabe["verantwortlich"]
        try:
            werte["faellig"] = pk._datum_pruefen(werte["faellig"])
            a = self.pe.aufgabe_aendern(self._aufgabe["id"], _basis=self._a_basis, **werte)
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
            return
        alt = self._aufgabe["verantwortlich"]
        self._aufgabe_fuellen(a)
        theme.status_setzen(self.a_status, "ok", "Gespeichert.")
        if self.nachricht_senden and a["verantwortlich"].lower() not in (alt.lower(), self._ich.lower()):
            self.nachricht_senden(a["verantwortlich"], f"Aufgabe an Sie übergeben: {a['titel']}", a["akte"], a["id"])
        self.laden()
        self.geaendert.emit()

    def _aufgabe_status(self, erledigt: bool):
        if self._aufgabe:
            self._status_setzen(self._aufgabe["id"], erledigt)
            self._aufgabe_fuellen(self.pe.aufgabe(self._aufgabe["id"]))

    def _status_setzen(self, aid: int, erledigt: bool):
        try:
            a = self.pe.erledigen(aid) if erledigt else self.pe.wieder_oeffnen(aid)
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
            return
        theme.status_setzen(self.status, "ok", f"„{a['titel']}“: {a['status_text']}"
                            + (f" (von {a['erledigt_von_anzeige']} am {_de(a['erledigt_am'])})" if erledigt else ""))
        self.laden()
        self.geaendert.emit()

    # ------------------------------------------------------------------ Import
    def outlook_uebernehmen(self):
        from core.entwurf import mail_modus
        from core.outlook_eingang import ausgewaehlte_mails, mail_zu_stueck
        if mail_modus(self.ctx.cfg) == "eml":
            QMessageBox.information(self, "Outlook", "Das neue Outlook erlaubt keinen direkten Zugriff.\n\nSo geht es: "
                                    "E-Mail in Outlook markieren und mit der Maus hierher ziehen – oder über „Datei → "
                                    "Speichern unter“ als .eml/.msg speichern und „Dateien / E-Mails hinzufügen…“ "
                                    "wählen.")
            return
        tmp = Path(tempfile.mkdtemp(prefix="bnx-outlook-"))
        try:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                mails = ausgewaehlte_mails()
                if not mails:
                    QGuiApplication.restoreOverrideCursor()
                    QMessageBox.information(self, "Outlook", "In Outlook ist keine E-Mail markiert. Bitte die E-Mails in "
                                            "Outlook markieren und erneut „Aus Outlook übernehmen“ wählen.")
                    return
                stuecke = []
                for i, m in enumerate(mails):
                    self.status.setText(f"E-Mail {i + 1} von {len(mails)} wird gelesen …")
                    QApplication.processEvents()
                    stuecke.append(mail_zu_stueck(m, tmp / str(i)))
            finally:
                if QGuiApplication.overrideCursor():
                    QGuiApplication.restoreOverrideCursor()
            self.importieren(stuecke)
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex, "Outlook")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def dateien_waehlen(self):
        namen, _ = QFileDialog.getOpenFileNames(
            self, "Dateien oder E-Mails übernehmen", "",
            "Unterstützte Dateien (*.eml *.msg *.pdf *.docx *.docm *.doc *.rtf *.jpg *.jpeg *.png *.tif *.tiff *.txt "
            "*.xlsx);;Alle Dateien (*)")
        if namen:
            self.dateien_uebernehmen([Path(n) for n in namen])

    def dateien_uebernehmen(self, pfade: list[Path]):
        from core.outlook_eingang import msg_datei_zu_stueck
        stuecke, uebersprungen = [], []
        tmp = Path(tempfile.mkdtemp(prefix="bnx-msg-"))
        try:
            for i, p in enumerate(pfade):
                endung = p.suffix.lower()
                try:
                    if endung == ".eml":
                        stuecke.append(ps.aus_eml(p))
                    elif endung == ".msg":
                        try:
                            stuecke.append(msg_datei_zu_stueck(p, tmp / str(i)))
                        except Exception:  # noqa: BLE001 – ohne klassisches Outlook: Datei als solche übernehmen
                            stuecke.append(ps.aus_msg_ohne_outlook(p))
                    elif endung in ps.DATEI_ENDUNGEN:
                        stuecke.append(ps.aus_datei(p))
                    else:
                        uebersprungen.append(f"{p.name} (Dateityp nicht unterstützt)")
                except Exception as ex:  # noqa: BLE001
                    uebersprungen.append(f"{p.name} ({meldung(ex).splitlines()[0]})")
            if stuecke:
                self.importieren(stuecke, uebersprungen)
            elif uebersprungen:
                QMessageBox.warning(self, "Nicht übernommen", "\n".join(uebersprungen))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def importieren(self, stuecke: list[ps.Stueck], uebersprungen: list[str] | None = None):
        neu, doppelt, fehler = [], [], []
        hinweise = []
        self.setEnabled(False)
        try:
            for i, s in enumerate(stuecke):
                self.status.setText(f"„{s.titel}“ wird abgelegt ({i + 1}/{len(stuecke)}) …")
                QApplication.processEvents()
                try:
                    erg = ps.ablegen(self.ctx, s)
                except OFFLINE as ex:
                    self._ausstehend.append(s)
                    fehler.append(f"{s.titel}: {ex}")
                    continue
                except Exception as ex:  # noqa: BLE001
                    fehler.append(f"{s.titel}: {meldung(ex).splitlines()[0]}")
                    continue
                (doppelt if erg["doppelt"] else neu).append(erg)
                hinweise += [f"{s.titel}: {h}" for h in s.hinweise]
        finally:
            self.setEnabled(True)
        self.b_erneut.setVisible(bool(self._ausstehend))
        teile = [f"{len(neu)} Eingang/Eingänge übernommen"]
        if doppelt:
            teile.append(f"{len(doppelt)} bereits vorhanden (nicht doppelt angelegt)")
        if fehler:
            teile.append(f"{len(fehler)} NICHT übernommen")
        theme.status_setzen(self.status, "fehler" if fehler else ("warn" if doppelt or hinweise else "ok"),
                            " · ".join(teile))
        details = fehler + [f"Bereits vorhanden: {d['betreff']}" + (f" (Akte {d['akte']})" if d.get("akte") else "")
                            for d in doppelt] + hinweise + (uebersprungen or [])
        if details:
            QMessageBox.information(self, "Posteingang", " · ".join(teile) + "\n\n" + "\n".join(details[:30]))
        self.ansicht.setCurrentIndex(self.ansicht.findData("e:offen"))
        self.laden()
        ziel = (neu or doppelt)
        if ziel:
            self.eingang_zeigen(ziel[0]["id"])
        self.geaendert.emit()

    def ausstehende_ablegen(self):
        offen, self._ausstehend = self._ausstehend, []
        if offen:
            self.importieren(offen)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        pfade = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.toLocalFile()]
        if pfade:
            self.dateien_uebernehmen(pfade)


class UebersichtKarte(QFrame):
    """Startseite: Meine Aufgaben · Erwartete Unterlagen/Antworten · Überfällig / Nachfassen."""

    def __init__(self, ctx, ansicht_oeffnen, akte_oeffnen, aufgabe_oeffnen):
        super().__init__()
        theme.karte(self)
        self.ctx = ctx
        self.ansicht_oeffnen, self.akte_oeffnen, self.aufgabe_oeffnen = ansicht_oeffnen, akte_oeffnen, aufgabe_oeffnen
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(18)
        self.spalten = {}
        for schl, titel in (("meine", "Meine Aufgaben"), ("erwartet", "Erwartete Unterlagen & Antworten"),
                            ("faellig", "Überfällig / Nachfassen")):
            sp = QVBoxLayout()
            kopf = QPushButton(titel)
            theme.rolle(kopf, "link")
            kopf.clicked.connect(lambda _=False, s=schl: self._kopf(s))
            liste = QListWidget()
            liste.setAccessibleName(titel)
            liste.setFrameShape(QFrame.NoFrame)
            liste.setMaximumHeight(118)
            liste.itemDoubleClicked.connect(self._oeffnen)
            sp.addWidget(kopf, 0, Qt.AlignLeft)
            sp.addWidget(liste)
            lay.addLayout(sp, 1)
            self.spalten[schl] = (kopf, liste, titel)

    def _kopf(self, schl: str):
        self.ansicht_oeffnen({"meine": "a:meine", "erwartet": "", "faellig": "a:ueberfaellig"}[schl])

    def _oeffnen(self, it: QListWidgetItem):
        art, wert = it.data(Qt.UserRole)
        if art == "aufgabe":
            self.aufgabe_oeffnen(wert)
        elif art == "akte":
            self.akte_oeffnen(wert)

    def laden(self):
        try:
            p = self.ctx.posteingang.uebersicht()
            u = self.ctx.unterlagen.uebersicht()
        except OFFLINE:
            return
        except Exception:  # noqa: BLE001 – Startseite darf nie stören
            return
        daten = {
            "meine": [(f"{_tag(a['faellig']) + ' · ' if a['faellig'] else ''}{a['titel']}"
                       + (f" · {a['akte']}" if a["akte"] else "") + (" ⚠" if a["ueberfaellig"] else ""),
                       ("aufgabe", a["id"])) for a in p["meine"]],
            "erwartet": [(f"{e['akte']}: {e['titel']} ({e['status_text']}" + (f", von {e['von_text']}" if
                                                                               e.get("von_text") else "") + ")",
                          ("akte", e["akte"])) for e in (u["zu_pruefen"] + u["erwartet"])],
            "faellig": [(f"⚠ {_tag(a['faellig'])} · {a['titel']} · {a['verantwortlich_anzeige']}", ("aufgabe", a["id"]))
                        for a in p["ueberfaellig"]] +
                       [(f"Nachfassen {_tag(e['nachfassen'])} · {e['akte']}: {e['titel']}", ("akte", e["akte"]))
                        for e in u["nachfassen_faellig"]],
        }
        anzahl = {"meine": p["meine_anzahl"], "erwartet": u["erwartet_anzahl"] + len(u["zu_pruefen"]),
                  "faellig": len(daten["faellig"])}
        for schl, (kopf, liste, titel) in self.spalten.items():
            kopf.setText(f"{titel} ({anzahl[schl]})")
            liste.clear()
            for text, d in daten[schl][:8]:
                it = QListWidgetItem(text)
                it.setData(Qt.UserRole, d)
                it.setToolTip(text)
                liste.addItem(it)
            if not daten[schl]:
                it = QListWidgetItem("– nichts offen –")
                it.setFlags(Qt.NoItemFlags)
                liste.addItem(it)
        if p["nicht_zugeordnet"]:
            k, _, t = self.spalten["meine"]
            k.setToolTip(f"{p['nicht_zugeordnet']} Eingang/Eingänge noch keiner Akte zugeordnet")
