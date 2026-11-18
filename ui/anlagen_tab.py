"""Anlagen-Assistent: Schriftsatz + Anlagen auf einem Bildschirm zu einem Paket zusammenstellen.

Ablauf: Dateien hineinziehen → (optional) Hauptdokument festlegen → Anlagen sortieren/benennen →
„Paket erstellen“ (ohne Zwischenfenster) → einzelne PDFs + Anlagenverzeichnis.docx →
optional „Outlook-Entwurf erstellen…“ (nur Entwurf, nie Versand). Doppelklick auf eine Vorschauseite
öffnet die Anlage genau dort zum Bearbeiten; Speichern aktualisiert Vorschau und Angaben sofort.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from core import anlagen as an
from core import pdf_engine as pe
from core.mail_service import MailDraft, MailError
from core.fehlertexte import meldung

from . import theme
from .pdf_ui import AnhangVorschau, im_thread, qpixmap


def _gleiche_datei(a: Path, b: Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a).lower() == str(b).lower()


class AnlagenListe(QTreeWidget):
    """Anlagen-Liste: Dateien von außen hineinziehen, intern per Drag & Drop umsortieren."""
    dateien = Signal(list)
    umsortiert = Signal()

    def __init__(self):
        super().__init__()
        self.setColumnCount(5)
        self.setHeaderLabels(["Anlage", "Bezeichnung (änderbar)", "Quelldatei", "Seiten", "Hinweis"])
        self.setRootIsDecorated(False)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        h = self.header()
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for i in (0, 2, 3, 4):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.source() is self:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self:
            self.dateien.emit([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
            return
        super().dropEvent(e)
        QTimer.singleShot(0, self.umsortiert.emit)


class AnlagenTab(QWidget):
    def __init__(self, ctx, hintergrund=None):
        super().__init__()
        self.ctx, self.cfg = ctx, ctx.cfg
        self.hintergrund = hintergrund            # main_window.im_hintergrund (Word mit Zeitlimit)
        self.eintraege: dict[int, an.Eintrag] = {}
        self.schriftsatz_id: int | None = None
        self.paket: an.Paket | None = None
        self.schritte = 0                          # Bedienschritte (für Auswertung/Protokoll)
        self._aufbau()

    # ------------------------------------------------------------- Aufbau
    def _aufbau(self):
        """Drei Spalten: Anlagenliste (links) · große Vorschau (Mitte) · ausgewählte Anlage + Paket (rechts);
        unten die Schritte in Arbeitsreihenfolge. Alt-Kürzel unverändert (H, S, N, L, R, V, D, Ö, G, T, E, P, O)."""
        self.setObjectName("seite")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 12)
        lay.setSpacing(10)
        titelzeile = QHBoxLayout()
        titelzeile.addWidget(theme.ueberschrift("Anlagen-Assistent", "h1"), 1)
        lay.addLayout(titelzeile)
        kopf = QHBoxLayout()
        kopf.addWidget(theme.rolle(QLabel("Hauptdokument:"), "gedimmt"))
        self.l_schriftsatz = QLabel(self.KEIN_HAUPT)
        self.l_schriftsatz.setProperty("rolle", "h3")
        kopf.addWidget(self.l_schriftsatz, 1)
        self.b_als_schriftsatz = QPushButton("Als Hauptdokument fe&stlegen")
        self.b_als_schriftsatz.setToolTip("Dieses Dokument wird als Schriftsatz vor den Anlagen ausgegeben.")
        self.b_als_schriftsatz.clicked.connect(self.als_schriftsatz)
        kopf.addWidget(self.b_als_schriftsatz)
        self.b_kein_haupt = QPushButton("Kein Hauptdokument")
        self.b_kein_haupt.setToolTip("Hauptdokument wieder als normale Anlage in die Liste nehmen")
        self.b_kein_haupt.clicked.connect(self.kein_hauptdokument)
        kopf.addWidget(self.b_kein_haupt)
        b_neu = QPushButton("&Neu")
        b_neu.setToolTip("Liste leeren und neu beginnen")
        b_neu.clicked.connect(self.leeren)
        titelzeile.addWidget(b_neu)
        lay.addLayout(kopf)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        # --- links: Anlagenliste
        links = theme.karte(QFrame(), schatten=False)
        ll = QVBoxLayout(links)
        ll.setContentsMargins(14, 12, 14, 12)
        l_liste = QLabel("Anlagen&liste")
        l_liste.setProperty("rolle", "h3")
        ll.addWidget(l_liste)
        tipp = theme.rolle(QLabel("Dateien hierher ziehen · Alt+↑/↓ sortiert · F2 benennt"), "gedimmt")
        tipp.setWordWrap(True)
        ll.addWidget(tipp)
        self.liste = AnlagenListe()
        self.liste.setColumnHidden(2, True)                 # Quelldatei steht rechts bei der Auswahl
        l_liste.setBuddy(self.liste)
        self.liste.dateien.connect(self.hinzufuegen)
        self.liste.umsortiert.connect(self._geaendert)
        self.liste.itemChanged.connect(self._titel_geaendert)
        self.liste.currentItemChanged.connect(lambda *_: self._vorschau())
        ll.addWidget(self.liste, 1)
        haupt_info = theme.rolle(QLabel("„Als Hauptdokument festlegen“: Dieses Dokument wird als Schriftsatz vor "
                                        "den Anlagen ausgegeben (optional)."), "gedimmt")
        haupt_info.setWordWrap(True)
        ll.addWidget(haupt_info)
        knoepfe = QGridLayout()
        for i, (text, fn) in enumerate((("▲ Nach oben", lambda: self.verschieben(-1)),
                                        ("▼ Nach unten", lambda: self.verschieben(1)),
                                        ("Entfernen", self.entfernen),
                                        ("Ausrichtung ko&rrigieren", self.ausrichtung_korrigieren))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            knoepfe.addWidget(b, i // 2, i % 2)
        ll.addLayout(knoepfe)
        split.addWidget(links)
        # --- Mitte: große Vorschau
        mitte = theme.karte(QFrame(), schatten=False)
        ml = QVBoxLayout(mitte)
        ml.setContentsMargins(14, 12, 14, 12)
        l_vor = QLabel("&Vorschau")
        l_vor.setProperty("rolle", "h3")
        ml.addWidget(l_vor)
        hinw = theme.rolle(QLabel("Doppelklick auf eine Seite: dort bearbeiten. Seiten anklicken (Strg/Umschalt "
                                  "für mehrere), dann Seitenaktion wählen."), "gedimmt")
        hinw.setWordWrap(True)
        ml.addWidget(hinw)
        self.seiten = QListWidget()
        self.seiten.setAccessibleName("Vorschauseiten")
        l_vor.setBuddy(self.seiten)
        self.seiten.setViewMode(QListWidget.IconMode)
        self.seiten.setIconSize(QSize(170, 240))
        self.seiten.setSpacing(10)
        self.seiten.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.seiten.setResizeMode(QListWidget.Adjust)
        self.seiten.setMovement(QListWidget.Static)
        self.seiten.setWordWrap(True)
        self.seiten.itemDoubleClicked.connect(lambda it: self.im_editor(self.seiten.row(it)))
        ml.addWidget(self.seiten, 1)
        sk = QGridLayout()
        for i, (text, fn) in enumerate((("↻ &Drehen", lambda: self.seitenaktion("drehen")),
                                        ("Seite l&öschen", lambda: self.seitenaktion("loeschen")),
                                        ("Als ei&gene Anlage", lambda: self.seitenaktion("eigene")))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            sk.addWidget(b, i // 2, i % 2)
        ml.addLayout(sk)
        split.addWidget(mitte)
        # --- rechts: ausgewählte Anlage + Paket
        rechts_karte = theme.karte(QFrame(), schatten=False)
        rk = QVBoxLayout(rechts_karte)
        rk.setContentsMargins(2, 2, 2, 2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rechts = QWidget()
        rechts.setObjectName("karteninhalt")
        scroll.setWidget(rechts)
        rk.addWidget(scroll)
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(16, 12, 16, 12)
        rl.setSpacing(6)
        rl.addWidget(theme.ueberschrift("Ausgewählte Anlage", "h3"))
        self.d_nummer = theme.rolle(QLabel("–"), "akzent")
        rl.addWidget(self.d_nummer, 0, Qt.AlignLeft)
        rl.addWidget(theme.rolle(QLabel("Bezeichnung"), "gedimmt"))
        self.d_titel = QLineEdit()
        self.d_titel.setPlaceholderText("Bezeichnung der Anlage")
        self.d_titel.editingFinished.connect(self._detail_titel)
        rl.addWidget(self.d_titel)
        self.d_info = QLabel()
        self.d_info.setWordWrap(True)
        rl.addWidget(self.d_info)
        self.d_status = QLabel()
        self.d_status.setWordWrap(True)
        rl.addWidget(self.d_status)
        for text, fn in (("&Texterkennung (OCR)", self.ocr), ("Im PDF-&Editor öffnen…", self.im_editor)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            rl.addWidget(b)
        rl.addSpacing(10)
        rl.addWidget(theme.ueberschrift("Paket", "h3"))
        form = QHBoxLayout()
        form.addWidget(QLabel("Präfix:"))
        self.praefix = QLineEdit(self.cfg.get("anlagen_praefix", "Anlage K"))
        self.praefix.setMinimumWidth(80)
        self.praefix.textChanged.connect(self._geaendert)
        form.addWidget(self.praefix, 1)
        form.addWidget(QLabel("ab"))
        self.start = QSpinBox()
        self.start.setToolTip("beginnt bei")
        self.start.setRange(1, 999)
        self.start.valueChanged.connect(self._geaendert)
        form.addWidget(self.start)
        rl.addLayout(form)
        rl.addWidget(QLabel("Zielordner:"))
        self.ordner = QLineEdit()
        self.ordner.setMinimumWidth(60)
        self.ordner.textChanged.connect(lambda *_: self._ungueltig())
        rl.addWidget(self.ordner)
        b_ord = QPushButton("Wählen…")
        b_ord.clicked.connect(self.ordner_waehlen)
        rl.addWidget(b_ord, 0, Qt.AlignLeft)
        self.gesamt = QCheckBox("Gesamt-PDF (intern)")
        self.gesamt.setToolTip("Zusätzlich ein Gesamt-PDF zur internen Prüfung erstellen (wird nicht versendet)")
        rl.addWidget(self.gesamt)
        rl.addStretch(1)
        split.addWidget(rechts_karte)
        for w_, mn in ((links, 250), (mitte, 220), (rechts_karte, max(230, rechts.minimumSizeHint().width() + 26))):
            w_.setMinimumWidth(mn)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 4)
        split.setStretchFactor(2, 3)
        split.setSizes([430, 430, 300])
        lay.addWidget(split, 1)

        self.hinweise = QListWidget()
        self.hinweise.setMaximumHeight(84)
        self.hinweise.setToolTip("Hinweise zu allen Anlagen: ✖ stoppt das Paket, ⚠ bitte prüfen, ✓ in Ordnung")
        lay.addWidget(self.hinweise)
        unten = theme.karte(QFrame(), schatten=False)
        ul = QHBoxLayout(unten)
        ul.setContentsMargins(14, 10, 14, 10)
        ul.setSpacing(10)
        b_add = QPushButton(theme.icon("plus", "titel", 18), "  1  Dateien &hinzufügen…")
        b_add.clicked.connect(self.dateien_waehlen)
        ul.addWidget(b_add)
        ul.addWidget(theme.rolle(QLabel("→"), "gedimmt"))
        self.b_paket = QPushButton(theme.icon("paket", "primaer_text", 18), "  2  &Paket erstellen")
        theme.rolle(self.b_paket, "primaer")
        self.b_paket.clicked.connect(self.paket_erstellen)
        ul.addWidget(self.b_paket)
        ul.addWidget(theme.rolle(QLabel("→"), "gedimmt"))
        self.b_outlook = QPushButton(theme.icon("mail", "titel", 18), "  3  &Outlook-Entwurf erstellen…")
        self.b_outlook.clicked.connect(self.outlook)
        ul.addWidget(self.b_outlook)
        self.b_ordner = QPushButton(theme.icon("ordner", "titel", 18), "  Ordner öffnen")
        self.b_ordner.clicked.connect(lambda: os.startfile(str(self.paket.ordner)) if self.paket else None)
        ul.addWidget(self.b_ordner)
        ul.addStretch(1)
        for b_ in (b_add, self.b_paket, self.b_outlook, self.b_ordner):
            b_.setMinimumWidth(b_.sizeHint().width())
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("rolle", "gedimmt")
        lay.addWidget(self.status)
        lay.addWidget(unten)

        for taste, fn in (("Alt+Up", lambda: self.verschieben(-1)), ("Alt+Down", lambda: self.verschieben(1))):
            QShortcut(QKeySequence(taste), self, fn, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_Delete), self.liste, self.entfernen, context=Qt.WidgetShortcut)
        self._ungueltig()
        self._details()

    def _details(self):
        """Rechte Spalte: Nummer, Bezeichnung, Quelle, Seiten und Status der ausgewählten Anlage."""
        it = self.liste.currentItem()
        e = self.ausgewaehlt()
        if not it or not e:
            self.d_nummer.setText("–")
            self.d_titel.setText("")
            self.d_titel.setEnabled(False)
            self.d_info.setText("Keine Anlage ausgewählt.")
            theme.status_setzen(self.d_status, None, "")
            return
        self.d_titel.setEnabled(True)
        self.d_nummer.setText(it.text(0))
        if not self.d_titel.hasFocus():
            self.d_titel.setText(it.text(1))
        seiten = it.text(3)
        self.d_info.setText(f"Quelldatei: {e.quelle.name}\nSeiten: "
                            + ("wird beim Erstellen aus Word umgewandelt" if seiten == "Word" else seiten))
        h = it.text(4)
        if h.startswith("✖"):
            theme.status_setzen(self.d_status, "fehler", h[1:].strip())
        elif h.startswith("⚠"):
            theme.status_setzen(self.d_status, "warn", h[1:].strip())
        else:
            theme.status_setzen(self.d_status, "ok", "bearbeitet" if "bearbeitet" in h else "In Ordnung")

    def _detail_titel(self):
        it = self.liste.currentItem()
        if it and self.d_titel.text().strip() and self.d_titel.text() != it.text(1):
            it.setText(1, self.d_titel.text().strip())

    # ------------------------------------------------------------- Daten
    BITTE_WARTEN = " – bitte warten …"
    KEIN_HAUPT = "— keines (optional) —"

    def setEnabled(self, an_: bool):
        """Sperren während längerer Arbeit (Word, OCR, Paket) – mit Hinweis im Fenstertitel.
        Gezählt, damit verschachtelte Abschnitte die Sperre nicht zu früh aufheben."""
        self._sperren = max(getattr(self, "_sperren", 0) + (-1 if an_ else 1), 0)
        super().setEnabled(self._sperren == 0)
        w = self.window()
        if w is not self:
            titel = w.windowTitle().replace(self.BITTE_WARTEN, "")
            w.setWindowTitle(titel if self._sperren == 0 else titel + self.BITTE_WARTEN)

    def anlagen(self) -> list[an.Eintrag]:
        return [self.eintraege[self.liste.topLevelItem(i).data(0, Qt.UserRole)]
                for i in range(self.liste.topLevelItemCount())]

    def schriftsatz(self) -> an.Eintrag | None:
        return self.eintraege.get(self.schriftsatz_id)

    def bezeichnungen(self) -> list[str]:
        return an.bezeichnungen(len(self.anlagen()), self.praefix.text(), self.start.value())

    def ausgewaehlt(self) -> an.Eintrag | None:
        it = self.liste.currentItem()
        return self.eintraege.get(it.data(0, Qt.UserRole)) if it else None

    # ------------------------------------------------------------- Dateien
    def dateien_waehlen(self):
        namen, _ = QFileDialog.getOpenFileNames(
            self, "Schriftsatz und Anlagen wählen", "",
            "Unterstützte Dateien (*.docx *.doc *.pdf *.jpg *.jpeg *.png *.tif *.tiff);;Alle Dateien (*)")
        self.hinzufuegen([Path(n) for n in namen])

    def hinzufuegen(self, pfade: list[Path]):
        pfade = [p for p in pfade if p.is_file()]
        if not pfade:
            return
        self.schritte += 1
        self.setEnabled(False)
        try:
            self._hinzufuegen(pfade)
        finally:
            self.setEnabled(True)

    def _hinzufuegen(self, pfade: list[Path]):
        haupt = self.schriftsatz()
        if haupt is not None:
            pfade = [p for p in pfade if not _gleiche_datei(p, haupt.quelle)]
        neu = []
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, p in enumerate(pfade, 1):
                self.status.setText(f"Lese {p.name} ({i}/{len(pfade)}) …")
                QGuiApplication.processEvents()
                e = an.einlesen(p)
                self.eintraege[e.id] = e
                neu.append(e)
        finally:
            QGuiApplication.restoreOverrideCursor()
        if self.schriftsatz_id is None:
            word = an.schriftsatz_vorschlag(neu)
            if word:
                self._schriftsatz_setzen(word)
                neu.remove(word)
        for e in neu:
            self.liste.addTopLevelItem(self._item(e))
        self._word_umwandeln(neu)
        self._ausrichtung_erkennen([e for e in neu if e.scan_seiten])
        self._geaendert()
        if self.liste.topLevelItemCount() and not self.liste.currentItem():
            self.liste.setCurrentItem(self.liste.topLevelItem(0), 1)

    def _item(self, e: an.Eintrag) -> QTreeWidgetItem:
        it = QTreeWidgetItem(["", e.titel, e.quelle.name, "", ""])
        it.setData(0, Qt.UserRole, e.id)
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsEditable)
        return it

    def _word_zu_pdf(self, quelle: Path, ziel: Path):
        """Word → PDF mit dem vorhandenen Ablauf (unsichtbares Word, Zeitlimit, PDF/A-Einstellung)."""
        from core.word_service import WordService
        zeit = float(self.cfg.get("word_zeitlimit_sekunden", 90))

        def lauf():
            with WordService(zeit) as w:
                w.export_pdf(quelle, ziel, pdfa=self.cfg.get("pdfa", True))
        if self.hintergrund:
            self.hintergrund(lauf, zeit + 30)
        else:
            lauf()

    def _word_umwandeln(self, eintraege: list[an.Eintrag]):
        """Word-Anlagen gleich beim Hinzufügen umwandeln → Vorschau, Seitenzahl und Prüfungen wie bei PDFs."""
        word = [e for e in eintraege if e.art == "word" and e.daten is None and e.id != self.schriftsatz_id]
        if not word:
            return
        self.setEnabled(False)
        try:
            for i, e in enumerate(word, 1):
                self.status.setText(f"Word → PDF: {e.quelle.name} ({i}/{len(word)}) …")
                QGuiApplication.processEvents()
                an.word_umwandeln(e, self._word_zu_pdf)
        finally:
            self.setEnabled(True)

    def _ausrichtung_erkennen(self, eintraege: list[an.Eintrag]):
        if not eintraege or not pe.tesseract_ordner():
            return
        self.setEnabled(False)
        try:
            for e in eintraege:
                self.status.setText(f"Prüfe Scan-Seiten (Ausrichtung, Doppelte): {e.quelle.name} …")
                an.ausrichtung_pruefen(e, lambda png: im_thread(lambda: pe.ausrichtung_aus_png(png)))
                an.textprobe_ergaenzen(e, lambda png, dpi: im_thread(lambda: pe.ocr_tsv(png, dpi, "deu")))
        finally:
            self.setEnabled(True)

    def _schriftsatz_setzen(self, e: an.Eintrag):
        self.schriftsatz_id = e.id
        # gleiche Datei nicht zusätzlich als Anlage behalten
        for i in reversed(range(self.liste.topLevelItemCount())):
            it = self.liste.topLevelItem(i)
            x = self.eintraege.get(it.data(0, Qt.UserRole))
            if x is not None and x.id != e.id and _gleiche_datei(x.quelle, e.quelle):
                self.liste.takeTopLevelItem(i)
                self.eintraege.pop(x.id, None)
        art = "Word" if e.art == "word" else f"{e.seiten} S."
        self.l_schriftsatz.setText(f"<b>{e.quelle.name}</b> ({art})" + (f" – <span style='color:#b91c1c'>"
                                                                           f"{e.fehler}</span>" if e.fehler else ""))
        if not self.ordner.text():
            self.ordner.setText(str(e.quelle.parent / f"Anlagenpaket_{e.quelle.stem}"))

    def als_schriftsatz(self):
        e = self.ausgewaehlt()
        if not e:
            return
        self.schritte += 1
        alt = self.schriftsatz()
        self.liste.takeTopLevelItem(self.liste.indexOfTopLevelItem(self.liste.currentItem()))
        if alt:
            self.liste.insertTopLevelItem(0, self._item(alt))
        self.ordner.clear()
        self._schriftsatz_setzen(e)
        if alt:
            self._word_umwandeln([alt])          # bisheriger Word-Schriftsatz wird jetzt Anlage
        self._geaendert()

    def kein_hauptdokument(self):
        """Hauptdokument ist optional: wieder als normale Anlage oben in die Liste (nichts geht verloren)."""
        alt = self.schriftsatz()
        if not alt:
            return
        self.schritte += 1
        self.schriftsatz_id = None
        self.l_schriftsatz.setText(self.KEIN_HAUPT)
        self.liste.insertTopLevelItem(0, self._item(alt))
        self._word_umwandeln([alt])
        self._geaendert()

    def leeren(self):
        self.eintraege.clear()
        self.schriftsatz_id = None
        self.liste.clear()
        self.seiten.clear()
        self.ordner.clear()
        self.l_schriftsatz.setText(self.KEIN_HAUPT)
        self.schritte = 0
        self._geaendert()

    # ------------------------------------------------------------- Liste
    def verschieben(self, richtung: int):
        it = self.liste.currentItem()
        if not it:
            return
        i = self.liste.indexOfTopLevelItem(it)
        j = i + richtung
        if not 0 <= j < self.liste.topLevelItemCount():
            return
        self.schritte += 1
        self.liste.blockSignals(True)
        self.liste.takeTopLevelItem(i)
        self.liste.insertTopLevelItem(j, it)
        self.liste.blockSignals(False)
        self.liste.setCurrentItem(it, 1)
        self._geaendert()

    def entfernen(self):
        it = self.liste.currentItem()
        if not it:
            return
        self.schritte += 1
        i = self.liste.indexOfTopLevelItem(it)
        e = self.eintraege.pop(it.data(0, Qt.UserRole))
        self.liste.takeTopLevelItem(i)
        self.status.setText(f"{e.quelle.name} aus dem Paket entfernt (Datei selbst bleibt unverändert).")
        if self.liste.topLevelItemCount():
            self.liste.setCurrentItem(self.liste.topLevelItem(min(i, self.liste.topLevelItemCount() - 1)), 1)
        self._geaendert()

    def _titel_geaendert(self, it: QTreeWidgetItem, spalte: int):
        e = self.eintraege.get(it.data(0, Qt.UserRole))
        if not e:
            return
        if spalte == 1 and it.text(1).strip() != e.titel:
            e.titel = it.text(1).strip()
            self.schritte += 1
            self._geaendert()
        elif spalte != 1:
            self._geaendert()

    def _geaendert(self, *_):
        """Nummern, Hinweise und Vorschau neu – jedes vorhandene Paket ist damit veraltet."""
        bez = self.bezeichnungen()
        hinweise = an.pruefen(self.schriftsatz(), self.anlagen())
        self.liste.blockSignals(True)
        for i, b in enumerate(bez):
            it = self.liste.topLevelItem(i)
            e = self.eintraege[it.data(0, Qt.UserRole)]
            it.setText(0, b)
            it.setText(1, e.titel)
            it.setText(3, "Word" if e.art == "word" and e.daten is None else (str(e.seiten) if e.ok else "–"))
            eigene = [h for h in hinweise if e.id in h.ids and h.stufe != "info"]
            info = [h for h in hinweise if e.id in h.ids and h.stufe == "info"]
            fehler = next((h for h in eigene if h.stufe == "fehler"), None)
            if fehler:
                text = "✖ wird nicht kopiert – " + e.fehler
            elif e.fehler:
                text = "⚠ " + an.ORIGINAL_TEXT
            elif eigene:
                text = "⚠ " + ", ".join(sorted({{"ausrichtung": "Seite gedreht?", "ocr": "OCR-Problem",
                                                 "leer": "Bezeichnung fehlt"}.get(h.art, h.art) for h in eigene}))
            else:
                text = ("✓ bearbeitet" if e.bearbeitet else "✓") + (
                    "  ℹ " + ("identisch" if any(h.art == "identisch" for h in info) else "ähnlich") if info else "")
            it.setText(4, text)
            for c in range(5):
                if fehler or eigene:
                    it.setForeground(c, QBrush(theme.status_farbe("fehler" if fehler else "warn")))
                else:
                    it.setData(c, Qt.ForegroundRole, None)      # Standardfarbe (auch im dunklen Design lesbar)
        self.liste.blockSignals(False)
        self.hinweise.clear()
        for h in hinweise:
            if h.stufe == "info":
                li = QListWidgetItem("ℹ " + h.text)
            else:
                art = "fehler" if h.stufe == "fehler" else "warn"
                li = QListWidgetItem(theme.status_text(art, h.text))
                li.setForeground(QBrush(theme.status_farbe(art)))
            self.hinweise.addItem(li)
        if not hinweise and self.eintraege:
            li = QListWidgetItem(theme.status_text("ok", "Keine Hinweise – das Paket kann erstellt werden"))
            li.setForeground(QBrush(theme.status_farbe("ok")))
            self.hinweise.addItem(li)
        self._ungueltig()
        self._vorschau()

    def _ungueltig(self):
        if self.paket:
            self.status.setText("Änderung nach dem Erstellen – Paket bitte neu erstellen.")
        self.paket = None
        self.b_outlook.setEnabled(False)
        self.b_ordner.setEnabled(False)

    # ------------------------------------------------------------- Vorschau / Seitenaktionen
    def _vorschau(self):
        self._details()
        self.seiten.clear()
        e = self.ausgewaehlt()
        if not e or not e.daten:
            if e and e.fehler and an.lesbar(e):
                self.seiten.addItem(QListWidgetItem(f"{an.ORIGINAL_TEXT}\n{e.quelle.name}\n({e.fehler})"))
            elif e and e.fehler:
                self.seiten.addItem(QListWidgetItem(f"✖ {e.quelle.name}: wird nicht kopiert – {e.fehler}"))
            elif e and e.art == "word":
                self.seiten.addItem(QListWidgetItem("Word-Dokument – wird beim Erstellen in PDF umgewandelt"))
            return
        doc = e.dokument()
        for p in doc:
            hinweis = ""
            if p.number in e.drehvorschlag:
                hinweis = " ⚠ gedreht?"
            it = QListWidgetItem(f"S. {p.number + 1}{hinweis}")
            it.setIcon(qpixmap(pe.seitenbild(p, 260)))
            self.seiten.addItem(it)
        doc.close()

    def _seitenwahl(self) -> list[int]:
        return sorted(self.seiten.row(i) for i in self.seiten.selectedItems())

    def seitenaktion(self, art: str):
        e = self.ausgewaehlt()
        if not e or not e.daten:
            return
        seiten = self._seitenwahl()
        if not seiten:
            QMessageBox.information(self, "Seiten", "Bitte zuerst in der Vorschau Seite(n) auswählen.")
            return
        self.schritte += 1
        try:
            if art == "drehen":
                an.seiten_drehen(e, seiten, 90)
            elif art == "loeschen":
                an.seiten_loeschen(e, seiten)
            elif art == "eigene":
                neu = an.als_eigene_anlage(e, seiten)
                self.eintraege[neu.id] = neu
                i = self.liste.indexOfTopLevelItem(self.liste.currentItem())
                self.liste.insertTopLevelItem(i + 1, self._item(neu))
        except pe.PdfFehler as ex:
            QMessageBox.warning(self, "Seiten", meldung(ex))
            return
        self._geaendert()

    def ausrichtung_korrigieren(self):
        n = sum(an.ausrichtung_korrigieren(e) for e in self.anlagen())
        if n:
            self.schritte += 1
        self.status.setText(f"Ausrichtung von {n} Seite(n) korrigiert." if n else "Keine Ausrichtungsvorschläge.")
        self._geaendert()

    def ocr(self):
        e = self.ausgewaehlt()
        if not e or not e.daten:
            return
        if not e.scan_seiten:
            self.status.setText(f"{e.quelle.name}: keine Scan-Seiten ohne Text.")
            return
        if not pe.tesseract_ordner():
            QMessageBox.critical(self, "Texterkennung", "OCR-Komponente fehlt (Ordner „ocr“ neben BnX-Raptor.exe).")
            return
        self.schritte += 1
        sprachen = tuple(self.cfg.get("ocr_sprachen", pe.SPRACHEN))
        self.setEnabled(False)
        try:
            self.status.setText(f"Texterkennung {e.quelle.name} …")
            n = an.ocr_ausfuehren(e, lambda png, dpi: im_thread(lambda: pe.ocr_erkennen(png, dpi, sprachen)))
        finally:
            self.setEnabled(True)
        self.status.setText(f"{e.quelle.name}: {n} Seite(n) durchsuchbar gemacht"
                            + (f"; Probleme: {'; '.join(e.ocr_fehler)}" if e.ocr_fehler else "."))
        self._geaendert()

    def im_editor(self, seite: int | None = None):
        """Anlage im Editor öffnen – bei Doppelklick in der Vorschau direkt auf dieser Seite im Werkzeug
        „Text bearbeiten“. „Speichern“/„OK“ übernimmt sofort in diese Anlage (Vorschau + Angaben neu)."""
        e = self.ausgewaehlt()
        if not e or not e.daten:
            return
        from .pdf_editor import PdfEditor
        import pymupdf

        def uebernehmen(daten: bytes):
            e.aktualisieren(pymupdf.open("pdf", daten), "im PDF-Editor bearbeitet")
            self.schritte += 1
            self._geaendert()
        ed = PdfEditor(self, daten=e.daten, name=f"{e.titel}.pdf", uebernehmen_text="in die Anlage",
                       sprachen=tuple(self.cfg.get("ocr_sprachen", pe.SPRACHEN)),
                       start_seite=seite or 0, text_modus=seite is not None, bei_speichern=uebernehmen)
        ed.exec()

    # ------------------------------------------------------------- Paket
    def ordner_waehlen(self):
        d = QFileDialog.getExistingDirectory(self, "Zielordner für das Anlagenpaket", self.ordner.text())
        if d:
            self.ordner.setText(d)

    def paket_erstellen(self):
        """Direkt erstellen – ohne Prüffenster. Fehlt der Zielordner, öffnet sich sofort die Ordnerauswahl."""
        s, anl, bez = self.schriftsatz(), self.anlagen(), self.bezeichnungen()
        if not s and not anl:
            self.status.setText("Keine Dateien in der Liste.")
            return
        if not self.ordner.text().strip():
            self.ordner_waehlen()
            if not self.ordner.text().strip():
                self.status.setText("Kein Zielordner gewählt – Paket nicht erstellt.")
                return
        ordner = Path(self.ordner.text().strip())
        self.schritte += 1
        from core.word_service import WordService
        if s and s.art == "word" and WordService.unsaved_in_running_word(s.quelle):
            QMessageBox.warning(self, "Nicht gespeichert", f"{s.quelle.name} ist in Word geöffnet und nicht "
                                                          "gespeichert. Bitte zuerst speichern.")
            return
        umbenennen = False
        while True:
            self.setEnabled(False)
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                paket = an.paket_erstellen(ordner, s, anl, bez, self._word_zu_pdf, self.gesamt.isChecked(),
                                           umbenennen_erlaubt=umbenennen,
                                           fortschritt=lambda t: (self.status.setText(t),
                                                                  QGuiApplication.processEvents()))
                break
            except an.Namenskonflikt as k:
                QGuiApplication.restoreOverrideCursor()
                self.setEnabled(True)
                neu = "\n".join(f"• {z.name}" for z in k.vorschlag)
                if QMessageBox.question(
                        self, "Dateien existieren bereits",
                        "Im Zielordner gibt es bereits:\n" + "\n".join(f"• {v.name}" for v in k.vorhanden)
                        + "\n\nVorhandene Dateien werden nicht überschrieben. Mit diesen Namen speichern?\n"
                        + neu) != QMessageBox.Yes:
                    self.status.setText("Paket nicht erstellt (Namen bereits vorhanden).")
                    return
                umbenennen = True
                continue
            except Exception as ex:  # noqa: BLE001
                QGuiApplication.restoreOverrideCursor()
                self.setEnabled(True)
                self.ctx.journal.add("anlagen", str(s.quelle if s else ordner), status="fehler", meldung=meldung(ex),
                                     art="anlagen")
                box = QMessageBox(QMessageBox.Critical, "Paket nicht erstellt",
                                  "Das Paket wurde NICHT erstellt. Es wurden keine Dateien abgelegt; vorhandene "
                                  f"Dateien im Zielordner sind unverändert.\n\n{ex}\n\nIhre Auswahl bleibt erhalten.",
                                  parent=self)
                b_neu = box.addButton("Erneut versuchen", QMessageBox.AcceptRole)
                box.addButton("Schließen", QMessageBox.RejectRole)
                box.setDefaultButton(b_neu)
                box.exec()
                theme.status_setzen(self.status, "fehler", "Paket nicht erstellt – " + meldung(ex).splitlines()[0])
                if box.clickedButton() is b_neu:
                    continue
                return
            finally:
                if QGuiApplication.overrideCursor():
                    QGuiApplication.restoreOverrideCursor()
                self.setEnabled(True)
        self.paket = paket
        self.b_outlook.setEnabled(True)
        self.b_ordner.setEnabled(True)
        namen = ", ".join(d.pfad.name for d in paket.dateien if d.rolle != "fehlt")
        self.ctx.journal.add("anlagen", str(s.quelle if s else ordner), str(paket.ordner),
                             meldung=namen + ("\n" + "\n".join(paket.hinweise) if paket.hinweise else ""),
                             art="anlagen")
        archiv = getattr(self.ctx, "archiv", None)
        if archiv is not None:
            for d in paket.dateien:
                if d.rolle != "fehlt":
                    try:
                        archiv.erfassen(d.pfad, rolle="paket", notiz=f"{d.bezeichnung}: {d.titel}")
                    except Exception:  # noqa: BLE001
                        pass
        self._geaendert()
        self.paket = paket                                   # _geaendert() setzt es zurück – hier gilt es
        self.b_outlook.setEnabled(True)
        self.b_ordner.setEnabled(True)
        text = f"Paket erstellt ({len([d for d in paket.dateien if d.rolle != 'fehlt'])} Dateien) in {paket.ordner}"
        if paket.hinweise:
            theme.status_setzen(self.status, "warn", text + " – " + " · ".join(paket.hinweise))
            for h in paket.hinweise:
                li = QListWidgetItem(theme.status_text("warn" if "NICHT" not in h else "fehler", h))
                li.setForeground(QBrush(theme.status_farbe("warn" if "NICHT" not in h else "fehler")))
                self.hinweise.insertItem(0, li)
        else:
            theme.status_setzen(self.status, "ok", text)

    def outlook(self):
        if not self.paket:
            return
        self.schritte += 1
        dateien = [(d.pfad, ("Schriftsatz" if d.rolle == "schriftsatz" else
                             f"{d.bezeichnung}: {d.titel}" if d.rolle in ("anlage", "original") else
                             "Anlagenverzeichnis (Word)" if d.rolle == "verzeichnis" else "nur intern"),
                    d.rolle in ("schriftsatz", "anlage", "original")) for d in self.paket.dateien
                   if d.rolle != "fehlt"]
        dlg = AnhangVorschau(self, dateien, "Anhänge für den Outlook-Entwurf")
        if dlg.exec() != QDialog.Accepted:
            return
        self.schritte += 1
        auswahl = dlg.auswahl()
        geaendert = [p.name for p, sha in auswahl if pe.sha256(p) != sha]
        if geaendert:
            QMessageBox.critical(self, "Entwurf", "Diese Dateien wurden nach der Vorschau verändert:\n"
                                 + "\n".join(geaendert))
            return
        gewaehlt = [d for d in self.paket.dateien if d.pfad in {p for p, _ in auswahl}]
        bez = [d.bezeichnung for d in gewaehlt if d.rolle == "anlage"]
        from core.entwurf import entwurf_erstellen
        try:
            msg = entwurf_erstellen(self.ctx, MailDraft(
                to="", subject=an.mail_betreff(self.schriftsatz().titel if self.schriftsatz() else "Anlagen", bez),
                html_body=an.mail_text(gewaehlt), attachments=[p for p, _ in auswahl]),
                self.paket.ordner, anhaenge_pruefen=True)
        except MailError as ex:
            self.ctx.journal.add("anlagen", str(self.paket.ordner), status="fehler", meldung=meldung(ex), art="entwurf")
            QMessageBox.critical(self, "Entwurf", meldung(ex))
            return
        self.ctx.journal.add("anlagen", str(self.paket.ordner), meldung=msg, art="entwurf")
        self.status.setText(f"✓ {msg}. Die E-Mail wurde nicht gesendet.")
        QMessageBox.information(self, "Entwurf erstellt", f"{msg}.\n\nDie E-Mail wurde nicht gesendet – "
                                                          "bitte Empfänger eintragen und selbst prüfen.")
