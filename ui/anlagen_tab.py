"""Anlagen-Assistent: Schriftsatz + Anlagen auf einem Bildschirm zu einem Paket zusammenstellen.

Ablauf: Dateien hineinziehen → Schriftsatz festlegen → Anlagen sortieren/benennen/prüfen →
„Paket prüfen und erstellen…“ (eine Kontrollansicht) → einzelne PDFs + Anlagenverzeichnis.docx →
optional „Outlook-Entwurf erstellen…“ (nur Entwurf, nie Versand).
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from core import anlagen as an
from core import pdf_engine as pe
from core.mail_service import MailDraft, MailError

from .pdf_ui import AnhangVorschau, im_thread, qpixmap

ROT, ORANGE, GRUEN = QColor("#b91c1c"), QColor("#b45309"), QColor("#15803d")


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


class KontrollDialog(QDialog):
    """Eine Kontrollansicht vor dem Erstellen: Schriftsatz, Reihenfolge, Dateinamen, Seiten, Hinweise."""

    def __init__(self, parent, schriftsatz: an.Eintrag | None, anlagen: list[an.Eintrag], bez: list[str],
                 hinweise: list[an.Hinweis], ordner: Path, gesamt: bool):
        super().__init__(parent)
        self.setWindowTitle("Anlagenpaket prüfen – BnX-Raptor")
        self.resize(1000, 620)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>Zielordner:</b> {ordner}"))
        t = QTableWidget(0, 5)
        t.setHorizontalHeaderLabels(["Anlage", "Bezeichnung", "Quelldatei", "Ausgabedatei", "Seiten"])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        zeilen = []
        if schriftsatz:
            zeilen.append(("Schriftsatz", schriftsatz.titel, schriftsatz.quelle.name, "Schriftsatz.pdf",
                           "Word → PDF" if schriftsatz.art == "word" else str(schriftsatz.seiten), schriftsatz))
        for e, b in zip(anlagen, bez):
            zeilen.append((b, e.titel, e.quelle.name, an.dateiname(b),
                           "Word → PDF" if e.art == "word" and e.daten is None else str(e.seiten) if e.ok else "–", e))
        zeilen.append(("", "Anlagenverzeichnis (Word, bearbeitbar)", "", an.VERZEICHNIS, "", None))
        if gesamt:
            zeilen.append(("", "Gesamt-PDF nur zur internen Prüfung", "", an.GESAMT, "", None))
        for z in zeilen:
            r = t.rowCount()
            t.insertRow(r)
            for c, v in enumerate(z[:5]):
                it = QTableWidgetItem(v)
                if z[5] is not None and z[5].fehler:
                    it.setForeground(QBrush(ROT))
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(t, 2)
        lay.addWidget(QLabel("<b>Hinweise</b>"))
        hl = QListWidget()
        for h in hinweise:
            it = QListWidgetItem(("✖ " if h.stufe == "fehler" else "⚠ ") + h.text)
            it.setForeground(QBrush(ROT if h.stufe == "fehler" else ORANGE))
            hl.addItem(it)
        if not hinweise:
            hl.addItem(QListWidgetItem("✓ Keine Auffälligkeiten"))
        lay.addWidget(hl, 1)
        self.blockiert = an.blockiert(hinweise)
        if self.blockiert:
            lay.addWidget(QLabel("<b style='color:#b91c1c'>Das Paket kann nicht erstellt werden. Bitte die rot "
                                 "markierten Punkte beheben (z. B. beschädigte Datei entfernen).</b>"))
        elif any(h.art in ("identisch", "aehnlich") for h in hinweise):
            lay.addWidget(QLabel("Doppelte/ähnliche Dateien werden <b>nicht</b> automatisch entfernt – "
                                 "bitte selbst entscheiden („Zurück“ → Anlage auswählen → Entfernen)."))
        bb = QDialogButtonBox()
        self.ok = bb.addButton("&Erstellen", QDialogButtonBox.AcceptRole)
        bb.addButton("&Zurück", QDialogButtonBox.RejectRole)
        self.ok.setEnabled(not self.blockiert)
        self.ok.setDefault(not self.blockiert)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


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
        lay = QVBoxLayout(self)
        kopf = QHBoxLayout()
        kopf.addWidget(QLabel("<b>Schriftsatz:</b>"))
        self.l_schriftsatz = QLabel("— noch keiner (Word-Datei hineinziehen) —")
        kopf.addWidget(self.l_schriftsatz, 1)
        self.b_als_schriftsatz = QPushButton("Auswahl als &Schriftsatz")
        self.b_als_schriftsatz.clicked.connect(self.als_schriftsatz)
        kopf.addWidget(self.b_als_schriftsatz)
        b_add = QPushButton("Dateien &hinzufügen…")
        b_add.clicked.connect(self.dateien_waehlen)
        kopf.addWidget(b_add)
        b_neu = QPushButton("&Neu")
        b_neu.clicked.connect(self.leeren)
        kopf.addWidget(b_neu)
        lay.addLayout(kopf)

        split = QSplitter()
        links = QWidget()
        ll = QVBoxLayout(links)
        ll.setContentsMargins(0, 0, 0, 0)
        l_liste = QLabel("Anlagen&liste – Schriftsatz und Anlagen hierher ziehen (Word, PDF, JPG, PNG); "
                         "Reihenfolge per Ziehen oder Alt+↑/↓; Bezeichnung mit F2 ändern:")
        ll.addWidget(l_liste)
        self.liste = AnlagenListe()
        l_liste.setBuddy(self.liste)
        self.liste.dateien.connect(self.hinzufuegen)
        self.liste.umsortiert.connect(self._geaendert)
        self.liste.itemChanged.connect(self._titel_geaendert)
        self.liste.currentItemChanged.connect(lambda *_: self._vorschau())
        ll.addWidget(self.liste, 1)
        knoepfe = QHBoxLayout()
        for text, fn in (("▲ Nach oben", lambda: self.verschieben(-1)), ("▼ Nach unten", lambda: self.verschieben(1)),
                         ("Entfernen", self.entfernen), ("Ausrichtung ko&rrigieren", self.ausrichtung_korrigieren)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            knoepfe.addWidget(b)
        ll.addLayout(knoepfe)
        split.addWidget(links)

        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(0, 0, 0, 0)
        l_vor = QLabel("&Vorschau der ausgewählten Anlage (Seiten wählen für Seitenaktionen):")
        rl.addWidget(l_vor)
        self.seiten = QListWidget()
        l_vor.setBuddy(self.seiten)
        self.seiten.setViewMode(QListWidget.IconMode)
        self.seiten.setIconSize(QSize(120, 170))
        self.seiten.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.seiten.setResizeMode(QListWidget.Adjust)
        self.seiten.setMovement(QListWidget.Static)
        rl.addWidget(self.seiten, 1)
        sk = QGridLayout()
        for i, (text, fn) in enumerate((("↻ &Drehen", lambda: self.seitenaktion("drehen")),
                                        ("Seite l&öschen", lambda: self.seitenaktion("loeschen")),
                                        ("Als ei&gene Anlage", lambda: self.seitenaktion("eigene")),
                                        ("&Texterkennung (OCR)", self.ocr),
                                        ("Im PDF-&Editor öffnen…", self.im_editor))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            sk.addWidget(b, i // 3, i % 3)
        rl.addLayout(sk)
        split.addWidget(rechts)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

        einst = QHBoxLayout()
        einst.addWidget(QLabel("Präfix:"))
        self.praefix = QLineEdit(self.cfg.get("anlagen_praefix", "Anlage K"))
        self.praefix.setMaximumWidth(110)
        self.praefix.textChanged.connect(self._geaendert)
        einst.addWidget(self.praefix)
        einst.addWidget(QLabel("beginnt bei:"))
        self.start = QSpinBox()
        self.start.setRange(1, 999)
        self.start.valueChanged.connect(self._geaendert)
        einst.addWidget(self.start)
        einst.addWidget(QLabel("  Zielordner:"))
        self.ordner = QLineEdit()
        self.ordner.textChanged.connect(lambda *_: self._ungueltig())
        einst.addWidget(self.ordner, 1)
        b_ord = QPushButton("Wählen…")
        b_ord.clicked.connect(self.ordner_waehlen)
        einst.addWidget(b_ord)
        self.gesamt = QCheckBox("Gesamt-PDF zur internen Prüfung")
        einst.addWidget(self.gesamt)
        lay.addLayout(einst)

        self.hinweise = QListWidget()
        self.hinweise.setMaximumHeight(110)
        lay.addWidget(self.hinweise)
        unten = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        unten.addWidget(self.status, 1)
        self.b_paket = QPushButton("&Paket prüfen und erstellen…")
        self.b_paket.clicked.connect(self.paket_erstellen)
        unten.addWidget(self.b_paket)
        self.b_ordner = QPushButton("Ordner öffnen")
        self.b_ordner.clicked.connect(lambda: os.startfile(str(self.paket.ordner)) if self.paket else None)
        unten.addWidget(self.b_ordner)
        self.b_outlook = QPushButton("&Outlook-Entwurf erstellen…")
        self.b_outlook.clicked.connect(self.outlook)
        unten.addWidget(self.b_outlook)
        lay.addLayout(unten)

        for taste, fn in (("Alt+Up", lambda: self.verschieben(-1)), ("Alt+Down", lambda: self.verschieben(1))):
            QShortcut(QKeySequence(taste), self, fn, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_Delete), self.liste, self.entfernen, context=Qt.WidgetShortcut)
        self._ungueltig()

    # ------------------------------------------------------------- Daten
    BITTE_WARTEN = " – bitte warten …"

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

    def leeren(self):
        self.eintraege.clear()
        self.schriftsatz_id = None
        self.liste.clear()
        self.seiten.clear()
        self.ordner.clear()
        self.l_schriftsatz.setText("— noch keiner (Word-Datei hineinziehen) —")
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
            eigene = [h for h in hinweise if e.id in h.ids]
            fehler = next((h for h in eigene if h.stufe == "fehler"), None)
            text = ("✖ " + e.fehler) if fehler else ("⚠ " + ", ".join(sorted({
                {"identisch": "identisch", "aehnlich": "ähnlich", "ausrichtung": "Seite gedreht?",
                 "ocr": "OCR-Problem"}.get(h.art, h.art) for h in eigene})) if eigene else
                ("✓ bearbeitet" if e.bearbeitet else "✓"))
            it.setText(4, text)
            for c in range(5):
                if fehler or eigene:
                    it.setForeground(c, QBrush(ROT if fehler else ORANGE))
                else:
                    it.setData(c, Qt.ForegroundRole, None)      # Standardfarbe (auch im dunklen Design lesbar)
        self.liste.blockSignals(False)
        self.hinweise.clear()
        for h in hinweise:
            li = QListWidgetItem(("✖ " if h.stufe == "fehler" else "⚠ ") + h.text)
            li.setForeground(QBrush(ROT if h.stufe == "fehler" else ORANGE))
            self.hinweise.addItem(li)
        if not hinweise and self.eintraege:
            self.hinweise.addItem(QListWidgetItem("✓ Keine Hinweise"))
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
        self.seiten.clear()
        e = self.ausgewaehlt()
        if not e or not e.daten:
            if e and e.art == "word":
                self.seiten.addItem(QListWidgetItem("Word-Dokument – wird beim Erstellen in PDF umgewandelt"))
            elif e and e.fehler:
                self.seiten.addItem(QListWidgetItem(f"✖ {e.quelle.name}: {e.fehler}"))
            return
        doc = e.dokument()
        for p in doc:
            hinweis = ""
            if p.number in e.drehvorschlag:
                hinweis = " ⚠ gedreht?"
            it = QListWidgetItem(f"S. {p.number + 1}{hinweis}")
            it.setIcon(qpixmap(pe.seitenbild(p, 120)))
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
            QMessageBox.warning(self, "Seiten", str(ex))
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

    def im_editor(self):
        e = self.ausgewaehlt()
        if not e or not e.daten:
            return
        from .pdf_editor import PdfEditor
        ed = PdfEditor(self, daten=e.daten, name=f"{e.titel}.pdf", uebernehmen_text="In Anlage übernehmen",
                       sprachen=tuple(self.cfg.get("ocr_sprachen", pe.SPRACHEN)))
        if ed.exec() == QDialog.Accepted and ed.ergebnis_bytes:
            import pymupdf
            e.aktualisieren(pymupdf.open("pdf", ed.ergebnis_bytes), "im PDF-Editor bearbeitet")
            self.schritte += 1
            self._geaendert()

    # ------------------------------------------------------------- Paket
    def ordner_waehlen(self):
        d = QFileDialog.getExistingDirectory(self, "Zielordner für das Anlagenpaket", self.ordner.text())
        if d:
            self.ordner.setText(d)

    def paket_erstellen(self):
        s, anl, bez = self.schriftsatz(), self.anlagen(), self.bezeichnungen()
        ordner = Path(self.ordner.text().strip()) if self.ordner.text().strip() else None
        hinweise = an.pruefen(s, anl)
        if ordner is None:
            hinweise.append(an.Hinweis("fehler", "leer", "Kein Zielordner gewählt."))
        self.schritte += 1
        dlg = KontrollDialog(self, s, anl, bez, hinweise, ordner or Path("—"), self.gesamt.isChecked())
        if dlg.exec() != QDialog.Accepted or dlg.blockiert:
            self.status.setText("Paket nicht erstellt." + (" Bitte rot markierte Punkte beheben."
                                                           if dlg.blockiert else ""))
            return
        self.schritte += 1
        from core.word_service import WordService
        if s.art == "word" and WordService.unsaved_in_running_word(s.quelle):
            QMessageBox.warning(self, "Nicht gespeichert", f"{s.quelle.name} ist in Word geöffnet und nicht "
                                                          "gespeichert. Bitte zuerst speichern.")
            return
        word_zu_pdf = self._word_zu_pdf
        umbenennen = False
        while True:
            self.setEnabled(False)
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                paket = an.paket_erstellen(ordner, s, anl, bez, word_zu_pdf, self.gesamt.isChecked(),
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
                self.ctx.journal.add("anlagen", str(s.quelle), status="fehler", meldung=str(ex), art="anlagen")
                QMessageBox.critical(self, "Paket nicht erstellt",
                                     f"Das Paket wurde NICHT erstellt (keine Dateien abgelegt):\n\n{ex}")
                self.status.setText("✖ Paket nicht erstellt – siehe Meldung.")
                return
            finally:
                if QGuiApplication.overrideCursor():
                    QGuiApplication.restoreOverrideCursor()
                self.setEnabled(True)
        self.paket = paket
        self.b_outlook.setEnabled(True)
        self.b_ordner.setEnabled(True)
        namen = ", ".join(d.pfad.name for d in paket.dateien)
        self.ctx.journal.add("anlagen", str(s.quelle), str(paket.ordner), meldung=namen, art="anlagen")
        self.status.setText(f"<b style='color:#15803d'>✓ Paket fertig</b> ({len(paket.dateien)} Dateien) in "
                            f"{paket.ordner}: {namen}")

    def outlook(self):
        if not self.paket:
            return
        self.schritte += 1
        dateien = [(d.pfad, ("Schriftsatz" if d.rolle == "schriftsatz" else
                             f"{d.bezeichnung}: {d.titel}" if d.rolle == "anlage" else
                             "Anlagenverzeichnis (Word)" if d.rolle == "verzeichnis" else "nur intern"),
                    d.rolle in ("schriftsatz", "anlage")) for d in self.paket.dateien]
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
                to="", subject=an.mail_betreff(self.schriftsatz().titel, bez),
                html_body=an.mail_text(gewaehlt), attachments=[p for p, _ in auswahl]),
                self.paket.ordner, anhaenge_pruefen=True)
        except MailError as ex:
            self.ctx.journal.add("anlagen", str(self.paket.ordner), status="fehler", meldung=str(ex), art="entwurf")
            QMessageBox.critical(self, "Entwurf", str(ex))
            return
        self.ctx.journal.add("anlagen", str(self.paket.ordner), meldung=msg, art="entwurf")
        self.status.setText(f"✓ {msg}. Die E-Mail wurde nicht gesendet.")
        QMessageBox.information(self, "Entwurf erstellt", f"{msg}.\n\nDie E-Mail wurde nicht gesendet – "
                                                          "bitte Empfänger eintragen und selbst prüfen.")
