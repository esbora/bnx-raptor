"""PDF arayüzü için ortak parçalar: görüntü dönüştürme, arka plan işi, ek önizlemesi."""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QVBoxLayout)


def qpixmap(pix) -> QPixmap:
    """PyMuPDF-Pixmap (RGB/GRAY) → QPixmap."""
    fmt = QImage.Format_RGB888 if pix.n >= 3 else QImage.Format_Grayscale8
    if pix.n == 4:
        fmt = QImage.Format_RGBA8888
    return QPixmap.fromImage(QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy())


def im_thread(fn):
    """fn im Hintergrund ausführen, Fenster bleibt bedienbar (Ereignisschleife läuft weiter).

    Nur für Arbeit ohne PyMuPDF-Objekte (z. B. Tesseract-Aufrufe) – PyMuPDF bleibt im Hauptthread.
    """
    erg: dict = {}

    def lauf():
        try:
            erg["wert"] = fn()
        except BaseException as e:  # noqa: BLE001
            erg["fehler"] = e
    t = threading.Thread(target=lauf, daemon=True)
    t.start()
    schleife = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: schleife.quit() if not t.is_alive() else None)
    timer.start(50)
    if t.is_alive():
        schleife.exec()
    timer.stop()
    if "fehler" in erg:
        raise erg["fehler"]
    return erg.get("wert")


def datei_info(p: Path) -> tuple[int, str]:
    """(Seitenzahl, SHA-256) einer Ausgabedatei; .docx hat 0 Seiten."""
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    if p.suffix.lower() != ".pdf":
        return 0, sha
    import pymupdf
    with pymupdf.open(p) as d:
        return d.page_count, sha


class AnhangVorschau(QDialog):
    """Zeigt vor dem Erstellen des Entwurfs genau die Dateien (Reihenfolge, Version, Prüfsumme),
    die angehängt werden. Der Nutzer kann einzelne abwählen. Es wird nichts gesendet."""

    def __init__(self, parent, dateien: list[tuple[Path, str, bool]], titel: str = "Anhänge prüfen"):
        super().__init__(parent)
        self.setWindowTitle(f"{titel} – BnX-Raptor")
        self.resize(820, 560)
        self.dateien = dateien
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Diese Dateien werden in dieser Reihenfolge an den Entwurf angehängt.</b> "
                             "Die E-Mail wird <b>nicht</b> gesendet."))
        zeile = QHBoxLayout()
        self.liste = QListWidget()
        self.info = {}
        for pfad, beschreibung, an in dateien:
            seiten, sha = datei_info(pfad)
            zeit = datetime.fromtimestamp(pfad.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
            text = (f"{pfad.name}  –  {beschreibung}  ·  "
                    + (f"{seiten} S. · " if seiten else "") + f"{pfad.stat().st_size / 1024:.0f} KB · {zeit}"
                    + f" · SHA-256 {sha[:12]}…")
            it = QListWidgetItem(text)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if an else Qt.Unchecked)
            it.setData(Qt.UserRole, str(pfad))
            self.info[str(pfad)] = sha
            self.liste.addItem(it)
        self.liste.currentRowChanged.connect(self._zeigen)
        zeile.addWidget(self.liste, 3)
        self.bild = QLabel()
        self.bild.setMinimumWidth(240)
        self.bild.setAlignment(Qt.AlignCenter)
        zeile.addWidget(self.bild, 1)
        lay.addLayout(zeile, 1)
        bb = QDialogButtonBox()
        self.ok = bb.addButton("In Outlook-Entwurf übernehmen", QDialogButtonBox.AcceptRole)
        bb.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        self.ok.setDefault(True)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.liste.setCurrentRow(0)

    def _zeigen(self, i: int):
        if i < 0:
            return
        p = Path(self.liste.item(i).data(Qt.UserRole))
        if p.suffix.lower() == ".pdf":
            import pymupdf
            from core.pdf_engine import seitenbild
            with pymupdf.open(p) as d:
                self.bild.setPixmap(qpixmap(seitenbild(d[0], 230)))
        else:
            self.bild.setText("Word-Dokument")

    def auswahl(self) -> list[tuple[Path, str]]:
        """Angehakte Dateien in Reihenfolge + die hier angezeigte Prüfsumme."""
        out = []
        for i in range(self.liste.count()):
            it = self.liste.item(i)
            if it.checkState() == Qt.Checked:
                out.append((Path(it.data(Qt.UserRole)), self.info[it.data(Qt.UserRole)]))
        return out
