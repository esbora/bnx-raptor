"""Word-Dokument direkt im Programm bearbeiten (0.4.1).

Links der Text (ein Absatz je Zeile, Enter = neuer Absatz), rechts die Vorschau so, wie Word das Dokument
druckt. Bei einer Word-Arbeitskopie aus einem PDF zusätzlich das Original-PDF zum Vergleich (Layout kann
abweichen). „Speichern“ (Strg+S) schreibt über Word sicher in die Datei; danach wird die Vorschau neu erzeugt.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from . import theme


def _seitenbilder(pdf: Path, breite: int = 560) -> QWidget:
    import pymupdf
    from core import pdf_engine as pe
    from .pdf_ui import qpixmap
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setSpacing(12)
    with pymupdf.open(pdf) as d:
        for p in d:
            l_ = QLabel()
            l_.setPixmap(qpixmap(pe.seitenbild(p, breite)))
            l_.setAlignment(Qt.AlignHCenter)
            lay.addWidget(l_)
    lay.addStretch(1)
    sc = QScrollArea()
    sc.setWidget(w)
    sc.setWidgetResizable(True)
    return sc


class WordBearbeiter(QWidget):
    """Bearbeitet genau eine .docx-Datei. hintergrund(fn, frist) führt Word-Arbeit ohne Einfrieren aus."""
    gespeichert = Signal(object)          # Path

    def __init__(self, hintergrund, zeitlimit: float = 90, parent=None):
        super().__init__(parent)
        self.hintergrund, self.zeitlimit = hintergrund, zeitlimit
        self.pfad: Path | None = None
        self.original_pdf: Path | None = None
        self.absaetze: list[str] = []
        self.basis = ""
        self._td = Path(tempfile.mkdtemp(prefix="bnx-wordvorschau-"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        kopf = QHBoxLayout()
        self.l_datei = theme.rolle(QLabel("Kein Dokument ausgewählt"), "h3")
        kopf.addWidget(self.l_datei, 1)
        self.b_speichern = QPushButton(theme.icon("speichern", "titel", 18), "  Speichern")
        self.b_speichern.setToolTip("Änderungen in die Word-Datei speichern (Strg+S)")
        self.b_speichern.clicked.connect(self.speichern)
        kopf.addWidget(self.b_speichern)
        lay.addLayout(kopf)
        split = QSplitter()
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Dokument wird geladen …")
        f = QFont(self.text.font())
        f.setPointSizeF(f.pointSizeF() + 1)
        self.text.setFont(f)
        self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.text.textChanged.connect(self._status)
        split.addWidget(self.text)
        self.vorschau = QTabWidget()
        split.addWidget(self.vorschau)
        split.setSizes([520, 520])
        lay.addWidget(split, 1)
        self.l_status = QLabel()
        self.l_status.setWordWrap(True)
        lay.addWidget(self.l_status)
        a = QAction(self)
        a.setShortcut(QKeySequence.Save)
        a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        a.triggered.connect(self.speichern)
        self.addAction(a)
        self._status()

    # --- Laden ---------------------------------------------------------------
    def laden(self, pfad: Path, original_pdf: Path | None = None) -> bool:
        from core import word_dokument as wd
        from core.word_service import WordService
        self.pfad, self.original_pdf = Path(pfad), original_pdf
        self.l_datei.setText(self.pfad.name + (f"  ·  Word-Arbeitskopie von {original_pdf.name}" if original_pdf
                                               else ""))
        theme.status_setzen(self.l_status, None, "⏳ Word öffnet das Dokument …")
        vorschau = self._td / "vorschau.pdf"
        vorschau.unlink(missing_ok=True)

        def lauf():
            with WordService(self.zeitlimit) as w:
                ab = wd.absaetze_lesen(w, self.pfad)
                wd.vorschau_pdf(w, self.pfad, vorschau)
            return ab
        try:
            self.basis = wd.fingerabdruck(self.pfad)
            self.absaetze = self.hintergrund(lauf, self.zeitlimit * 2 + 30)
        except Exception as e:  # noqa: BLE001
            theme.status_setzen(self.l_status, "fehler", f"Dokument konnte nicht geöffnet werden: {e}")
            self.absaetze = []
            self.text.blockSignals(True)
            self.text.setPlainText("")
            self.text.blockSignals(False)
            return False
        self.text.blockSignals(True)
        self.text.setPlainText("\n".join(a.replace("\n", "⏎") for a in self.absaetze))
        self.text.blockSignals(False)
        self._vorschau_zeigen(vorschau)
        self._status()
        return True

    def _vorschau_zeigen(self, vorschau: Path):
        self.vorschau.clear()
        if vorschau.exists():
            kopie = self._td / f"v{id(vorschau)}_{len(list(self._td.iterdir()))}.pdf"
            shutil.copyfile(vorschau, kopie)
            self.vorschau.addTab(_seitenbilder(kopie), "Vorschau (Word)")
        if self.original_pdf and self.original_pdf.exists():
            self.vorschau.addTab(_seitenbilder(self.original_pdf), "Original-PDF")
            self.vorschau.setTabToolTip(1, "Zum Vergleich: Das Layout der Word-Fassung kann vom PDF abweichen.")

    # --- Zustand -------------------------------------------------------------
    def neue_absaetze(self) -> list[str]:
        return [z.replace("⏎", "\n") for z in self.text.toPlainText().split("\n")]

    @property
    def geaendert(self) -> bool:
        return self.pfad is not None and bool(self.absaetze or self.text.toPlainText()) and \
            self.neue_absaetze() != self.absaetze

    def _status(self):
        g = self.geaendert
        self.b_speichern.setEnabled(g)
        theme.rolle(self.b_speichern, "primaer" if g else "")
        if self.pfad and g:
            theme.status_setzen(self.l_status, "warn", "Nicht gespeicherte Änderungen – „Speichern“ oder Strg+S.")
        elif self.pfad and self.absaetze:
            theme.status_setzen(self.l_status, "ok", "Gespeichert – „Starten“ verwendet diesen Stand.")

    # --- Speichern -----------------------------------------------------------
    def speichern(self) -> bool:
        if not self.geaendert:
            return True
        from core import word_dokument as wd
        from core.word_service import WordService
        neu = self.neue_absaetze()
        vorschau = self._td / "vorschau.pdf"
        theme.status_setzen(self.l_status, None, "⏳ Word speichert …")

        def lauf():
            with WordService(self.zeitlimit) as w:
                erg = wd.speichern(w, self.pfad, self.absaetze, neu, self.basis)
                wd.vorschau_pdf(w, self.pfad, vorschau)
            return erg
        try:
            self.absaetze = self.hintergrund(lauf, self.zeitlimit * 2 + 30)
        except Exception as e:  # noqa: BLE001 – gesperrt, extern geändert, Word-Fehler: Text bleibt im Editor
            theme.status_setzen(self.l_status, "fehler", f"Nicht gespeichert: {e}")
            QMessageBox.warning(self, "Nicht gespeichert", f"{e}\n\nIhr Text bleibt im Editor erhalten.")
            return False
        self.basis = wd.fingerabdruck(self.pfad)
        self._vorschau_zeigen(vorschau)
        self._status()
        self.gespeichert.emit(self.pfad)
        return True

    def schliessen_ok(self) -> bool:
        """Vor dem Wechsel/Schließen: offene Änderungen speichern? (Speichern / Verwerfen / Abbrechen)"""
        if not self.geaendert:
            return True
        box = QMessageBox(QMessageBox.Warning, "Ungespeicherte Änderungen",
                          f"{self.pfad.name} wurde geändert und noch nicht gespeichert.", parent=self)
        b_sp = box.addButton("Speichern", QMessageBox.AcceptRole)
        b_weg = box.addButton("Verwerfen", QMessageBox.DestructiveRole)
        box.addButton("Abbrechen", QMessageBox.RejectRole)
        box.setDefaultButton(b_sp)
        box.exec()
        if box.clickedButton() is b_sp:
            return self.speichern()
        if box.clickedButton() is b_weg:
            self.text.blockSignals(True)
            self.text.setPlainText("\n".join(a.replace("\n", "⏎") for a in self.absaetze))
            self.text.blockSignals(False)
            self._status()
            return True
        return False


class WordDialog(QDialog):
    """Word-Datei aus dem Akten-Verlauf bearbeiten: „OK – Änderungen speichern“ speichert und schließt."""

    def __init__(self, parent, pfad: Path, hintergrund, zeitlimit: float = 90, original_pdf: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Word-Dokument bearbeiten – {Path(pfad).name}")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1200, 800)
        lay = QVBoxLayout(self)
        self.ed = WordBearbeiter(hintergrund, zeitlimit, self)
        lay.addWidget(self.ed, 1)
        unten = QHBoxLayout()
        unten.addStretch(1)
        b_abbr = QPushButton("Abbrechen")
        b_abbr.clicked.connect(self.reject)
        b_ok = QPushButton(theme.icon("uebernehmen", "primaer_text", 18), "  OK – Änderungen speichern")
        theme.rolle(b_ok, "primaer")
        b_ok.clicked.connect(self._ok)
        unten.addWidget(b_abbr)
        unten.addWidget(b_ok)
        lay.addLayout(unten)
        self.ed.laden(Path(pfad), original_pdf)

    def _ok(self):
        if self.ed.speichern():
            self.accept()

    def reject(self):
        if self.ed.schliessen_ok():
            super().reject()
