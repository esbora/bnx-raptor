"""Word-Dokument ansehen und im echten Word bearbeiten (0.4.1).

Die Vorschau zeigt das Dokument so, wie Word es druckt (bei einer Word-Arbeitskopie aus einem PDF zusätzlich das
Original-PDF). „In Word bearbeiten“:
  1. prüft vorher Schutz und gesperrte Inhaltssteuerelemente (verständliche Meldung),
  2. legt eine datierte Kopie an (11_Vollmacht_2026-11-18.docx) – das Original wird nie überschrieben,
  3. öffnet die Kopie im sichtbaren Word und beobachtet NUR diese eine Datei,
  4. erzeugt nach dem Schließen in Word die Vorschau neu und meldet die Kopie (für Verlauf/Archiv).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QTabWidget,
                               QVBoxLayout, QWidget)

from core.fehlertexte import meldung

from . import theme


def _seitenbilder(pdf: Path, breite: int = 620) -> QWidget:
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
    """Zeigt genau eine .docx-Datei; hintergrund(fn, frist) führt Word-Arbeit ohne Einfrieren aus."""
    kopie_erstellt = Signal(object, object)       # (Original, Kopie)
    bearbeitet = Signal(object)                   # Datei nach dem Schließen in Word

    def __init__(self, hintergrund, zeitlimit: float = 90, parent=None):
        super().__init__(parent)
        self.hintergrund, self.zeitlimit = hintergrund, zeitlimit
        self.pfad: Path | None = None
        self.original_pdf: Path | None = None
        self.in_bearbeitung = False
        self._gesehen = False                     # Datei war schon gesperrt (Word hat sie geöffnet)
        self._wartezeit = 0
        self._td = Path(tempfile.mkdtemp(prefix="bnx-wordvorschau-"))
        self._takt = QTimer(self)
        self._takt.setInterval(1500)
        self._takt.timeout.connect(self._pruefen)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        kopf = QHBoxLayout()
        self.l_datei = theme.rolle(QLabel("Kein Dokument ausgewählt"), "h3")
        self.l_datei.setWordWrap(True)
        kopf.addWidget(self.l_datei, 1)
        self.b_word = QPushButton(theme.icon("wort", "primaer_text", 18), "  In Word bearbeiten")
        theme.rolle(self.b_word, "primaer")
        self.b_word.setToolTip("Öffnet eine Kopie im echten Word – das Original bleibt unverändert")
        self.b_word.clicked.connect(self.in_word_bearbeiten)
        self.b_word.setEnabled(False)
        kopf.addWidget(self.b_word)
        lay.addLayout(kopf)
        self.vorschau = QTabWidget()
        lay.addWidget(self.vorschau, 1)
        self.l_status = QLabel()
        self.l_status.setWordWrap(True)
        lay.addWidget(self.l_status)

    # --- Laden / Vorschau --------------------------------------------------------
    def laden(self, pfad: Path, original_pdf: Path | None = None) -> bool:
        self._takt.stop()
        self.in_bearbeitung = False
        self.pfad, self.original_pdf = Path(pfad), original_pdf
        self.l_datei.setText(self.pfad.name + (f"  ·  Word-Arbeitskopie von {original_pdf.name}" if original_pdf
                                               else ""))
        self.b_word.setEnabled(True)
        ok = self._vorschau_erzeugen()
        if ok:
            theme.status_setzen(self.l_status, None, "Zum Ändern „In Word bearbeiten“ – das Original bleibt "
                                "unverändert, bearbeitet wird eine datierte Kopie.")
        return ok

    def leeren(self):
        self._takt.stop()
        self.pfad, self.original_pdf, self.in_bearbeitung = None, None, False
        self.vorschau.clear()
        self.l_datei.setText("Kein Dokument ausgewählt")
        self.b_word.setEnabled(False)
        self.l_status.setText("")

    def _vorschau_erzeugen(self) -> bool:
        from core import word_dokument as wd
        from core.word_service import WordService
        vorschau = self._td / f"vorschau_{len(list(self._td.iterdir()))}.pdf"
        theme.status_setzen(self.l_status, None, "⏳ Word erstellt die Vorschau …")
        pfad = self.pfad

        def lauf():
            with WordService(self.zeitlimit) as w:
                wd.vorschau_pdf(w, pfad, vorschau)
        try:
            self.hintergrund(lauf, self.zeitlimit + 30)
        except Exception as e:  # noqa: BLE001
            theme.status_setzen(self.l_status, "fehler", meldung(e, "Vorschau nicht möglich"))
            self.vorschau.clear()
            return False
        self.vorschau.clear()
        self.vorschau.addTab(_seitenbilder(vorschau), "Vorschau (Word)")
        if self.original_pdf and self.original_pdf.exists():
            self.vorschau.addTab(_seitenbilder(self.original_pdf), "Original-PDF")
            self.vorschau.setTabToolTip(1, "Zum Vergleich: Das Layout der Word-Fassung kann vom PDF abweichen.")
        return True

    # --- In Word bearbeiten -------------------------------------------------------
    def in_word_bearbeiten(self):
        from core import word_dokument as wd
        from core.word_service import WordService
        if self.pfad is None or self.in_bearbeitung:
            return
        theme.status_setzen(self.l_status, None, "⏳ Prüfe, ob das Dokument geschützt ist …")
        pfad = self.pfad

        def pruefen():
            with WordService(self.zeitlimit) as w:
                return wd.schutz_pruefen(w, pfad)
        try:
            hinweise = self.hintergrund(pruefen, self.zeitlimit + 30)
        except Exception as e:  # noqa: BLE001
            theme.status_setzen(self.l_status, "fehler", meldung(e, "Prüfung nicht möglich"))
            return
        if hinweise:
            box = QMessageBox(QMessageBox.Warning, "Dokument ist geschützt",
                              "Dieses Dokument lässt sich nicht vollständig bearbeiten:\n\n• " + "\n• ".join(hinweise)
                              + "\n\nTrotzdem in Word öffnen? (Es wird eine Kopie geöffnet.)", parent=self)
            b_ja = box.addButton("In Word öffnen", QMessageBox.AcceptRole)
            box.addButton("Abbrechen", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not b_ja:
                theme.status_setzen(self.l_status, "warn", "Nicht geöffnet – " + hinweise[0])
                return
        ziel = self.pfad
        if not wd.ist_bnx_kopie(self.pfad):
            try:
                ziel = wd.bearbeitungskopie(self.pfad)
            except OSError as e:
                theme.status_setzen(self.l_status, "fehler", meldung(e, "Kopie konnte nicht angelegt werden"))
                return
            self.kopie_erstellt.emit(self.pfad, ziel)
            self.pfad = ziel
            self.l_datei.setText(ziel.name + "  ·  Kopie (Original unverändert)")
        try:
            os.startfile(str(ziel))           # type: ignore[attr-defined]  # sichtbares Word des Nutzers
        except OSError as e:
            theme.status_setzen(self.l_status, "fehler", meldung(e, "Word konnte nicht geöffnet werden"))
            return
        self.in_bearbeitung, self._gesehen, self._wartezeit = True, False, 0
        self.b_word.setEnabled(False)
        theme.status_setzen(self.l_status, "warn", f"In Word geöffnet: {ziel.name}. Nach dem Speichern und Schließen "
                            "in Word wird die Vorschau hier automatisch aktualisiert.")
        self._takt.start()

    def _pruefen(self):
        """Nur diese eine Datei beobachten: gesperrt = in Word geöffnet; wieder frei = in Word geschlossen."""
        from core import word_dokument as wd
        if self.pfad is None:
            self._takt.stop()
            return
        if wd.wird_bearbeitet(self.pfad):
            self._gesehen = True
            return
        self._wartezeit += 1
        if not self._gesehen and self._wartezeit < 40:      # Word startet noch (bis ca. 60 s)
            return
        self._takt.stop()
        self.in_bearbeitung = False
        self.b_word.setEnabled(True)
        if self._vorschau_erzeugen():
            theme.status_setzen(self.l_status, "ok", f"Word geschlossen – Vorschau aktualisiert: {self.pfad.name}")
        self.bearbeitet.emit(self.pfad)

    def schliessen_ok(self) -> bool:
        """Wechsel/Schließen: Ist die Kopie noch in Word offen, nachfragen (Word selbst bleibt unberührt)."""
        if not self.in_bearbeitung:
            return True
        return QMessageBox.question(
            self, "Noch in Word geöffnet", f"{self.pfad.name} ist noch in Word geöffnet. Die Vorschau wird dann nicht "
            "automatisch aktualisiert. Trotzdem fortfahren?") == QMessageBox.Yes


class WordDialog(QDialog):
    """Word-Datei aus dem Akten-Verlauf: Vorschau, „In Word bearbeiten“ (Kopie), „Schließen“."""

    def __init__(self, parent, pfad: Path, hintergrund, zeitlimit: float = 90, original_pdf: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Word-Dokument – {Path(pfad).name}")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1100, 820)
        self.kopie: Path | None = None
        self.original: Path = Path(pfad)
        self.bearbeitet = False
        lay = QVBoxLayout(self)
        self.ed = WordBearbeiter(hintergrund, zeitlimit, self)
        self.ed.kopie_erstellt.connect(lambda o, k: setattr(self, "kopie", Path(k)))
        self.ed.bearbeitet.connect(lambda p: setattr(self, "bearbeitet", True))
        lay.addWidget(self.ed, 1)
        unten = QHBoxLayout()
        unten.addStretch(1)
        b_zu = QPushButton("Schließen")
        b_zu.clicked.connect(self.accept)
        unten.addWidget(b_zu)
        lay.addLayout(unten)
        self.ed.laden(Path(pfad), original_pdf)

    def accept(self):
        if self.ed.schliessen_ok():
            super().accept()

    def reject(self):
        if self.ed.schliessen_ok():
            super().reject()
