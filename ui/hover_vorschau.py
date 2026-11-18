"""Große Vorschau beim Darüberfahren (0.4.2) – eine wiederverwendbare Komponente.

Verwendung:
    hv = HoverVorschau(parent, aktiv=lambda: cfg.get("grosse_vorschau", True))
    hv.anmelden(widget, quelle)          # quelle(pos_im_widget) -> Quelle | None

- Öffnet nach ca. 400 ms Verweilen ein großes Vorschaufenster (ca. 80 % der Bildschirmhöhe, scharf auf hoher DPI),
  nahe der Maus, immer vollständig auf dem Bildschirm, auf dem sich die Maus befindet.
- Beim Weiterfahren über andere Zeilen wird der Inhalt im selben Fenster getauscht (kein Flackern).
- Schließt, wenn die Maus Quelle UND Vorschau verlassen hat, bei Esc oder Klick außerhalb. Bleibt offen, solange
  die Maus im Vorschaufenster ist. Nimmt keinen Fokus – Liste und Häkchen bedienen sich normal weiter.
- Mehrseitig: Mausrad oder ←/→ blättert. Ohne Vorschau (Word, beschädigt, leer): deutsche Meldung, nie ein Fehlerfenster.
- Gerenderte Seiten liegen in einem speicherbegrenzten Cache.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from core.vorschau_logik import BildCache, fenster_position, vorschau_groesse

from . import theme

VERWEILEN_MS = 400
SCHLIESSEN_MS = 300
KEINE_VORSCHAU = "Keine Vorschau verfügbar – Datei ist beschädigt oder leer."
BILDER = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
_CACHE = BildCache(160 * 1024 * 1024)            # gemeinsam für alle großen Vorschauen


@dataclass
class Quelle:
    schluessel: object                           # eindeutig je Inhalt/Version (für Cache und „gleiche Quelle?“)
    dateiname: str
    bezeichnung: str = ""
    pfad: Path | None = None                     # Datei auf der Platte …
    daten: bytes | None = None                   # … oder PDF-Bytes im Speicher (Arbeitskopie einer Anlage)
    seite: int = 0
    hinweis: str = ""                            # feste Meldung statt Bild (z. B. Word-Dokument)
    extra: dict = field(default_factory=dict)


def quelle_aus_datei(pfad: Path, bezeichnung: str = "", seite: int = 0) -> Quelle:
    pfad = Path(pfad)
    endung = pfad.suffix.lower()
    try:
        st = pfad.stat()
        version = (st.st_size, st.st_mtime_ns)
    except OSError:
        version = None
    q = Quelle(("datei", str(pfad).lower(), version), pfad.name, bezeichnung, pfad=pfad, seite=seite)
    if endung in (".docx", ".doc", ".docm", ".rtf"):
        q.hinweis = "Keine Vorschau verfügbar – Word-Dokument (wird beim Erstellen in PDF umgewandelt bzw. in Word geöffnet)."
    elif endung not in BILDER | {".pdf"}:
        q.hinweis = "Keine Vorschau verfügbar – Dateityp wird nicht angezeigt."
    elif version is None or version[0] == 0:
        q.hinweis = KEINE_VORSCHAU
    return q


class _Fenster(QFrame):
    """Rahmenloses Fenster, das keinen Fokus nimmt."""

    def __init__(self, steuerung: "HoverVorschau"):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.steuerung = steuerung
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("grossvorschau")
        self.setStyleSheet(f"QFrame#grossvorschau {{ background: {theme.F['karte']}; border: 2px solid "
                           f"{theme.F['pfirsich_stark']}; border-radius: 12px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(6)
        self.kopf = QLabel()
        self.kopf.setTextFormat(Qt.RichText)
        self.kopf.setWordWrap(True)
        lay.addWidget(self.kopf)
        self.bild = QLabel()
        self.bild.setAlignment(Qt.AlignCenter)
        from PySide6.QtWidgets import QSizePolicy
        self.bild.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)   # Fenstergröße bestimmt _darstellen
        lay.addWidget(self.bild, 1)
        self.fuss = theme.rolle(QLabel(""), "gedimmt")
        lay.addWidget(self.fuss)

    def enterEvent(self, e):
        self.steuerung._schliessen_takt.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.steuerung._schliessen_spaeter()
        super().leaveEvent(e)

    def wheelEvent(self, e):
        self.steuerung.blaettern(-1 if e.angleDelta().y() > 0 else 1)
        e.accept()


class HoverVorschau(QObject):
    def __init__(self, parent: QWidget, aktiv: Callable[[], bool] = lambda: True):
        super().__init__(parent)
        self.aktiv = aktiv
        self._quellen: dict[QObject, Callable[[QPoint], Quelle | None]] = {}
        self._fenster: _Fenster | None = None
        self._aktuell: Quelle | None = None
        self._kandidat: Quelle | None = None
        self._seiten = 1
        self._seite = 0
        self._doc = None
        self._verweilen = QTimer(self)
        self._verweilen.setSingleShot(True)
        self._verweilen.setInterval(VERWEILEN_MS)
        self._verweilen.timeout.connect(self._zeigen)
        self._schliessen_takt = QTimer(self)
        self._schliessen_takt.setSingleShot(True)
        self._schliessen_takt.setInterval(SCHLIESSEN_MS)
        self._schliessen_takt.timeout.connect(self._schliessen_pruefen)

    # --- Anmeldung -----------------------------------------------------------
    def anmelden(self, widget: QWidget, quelle: Callable[[QPoint], Quelle | None]):
        ziel = widget.viewport() if hasattr(widget, "viewport") else widget
        ziel.setMouseTracking(True)
        ziel.installEventFilter(self)
        self._quellen[ziel] = quelle

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj in self._quellen:
            if t == QEvent.MouseMove:
                self._bewegt(obj, ev.position().toPoint())
            elif t == QEvent.Leave:
                self._verweilen.stop()
                self._schliessen_spaeter()
            elif t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.Wheel):
                self._verweilen.stop()
                if t != QEvent.Wheel:
                    self.schliessen()
            return False
        if self._fenster is not None and self._fenster.isVisible():
            if t == QEvent.KeyPress:
                if ev.key() == Qt.Key_Escape:
                    self.schliessen()
                    return True
                if ev.key() in (Qt.Key_Left, Qt.Key_Right) and self._seiten > 1:
                    self.blaettern(-1 if ev.key() == Qt.Key_Left else 1)
                    return True
            elif t == QEvent.MouseButtonPress and not self._fenster.geometry().contains(QCursor.pos()):
                self.schliessen()
        return False

    # --- Ablauf --------------------------------------------------------------
    def _bewegt(self, obj, pos: QPoint):
        if not self.aktiv():
            return
        self._schliessen_takt.stop()
        try:
            q = self._quellen[obj](pos)
        except Exception:  # noqa: BLE001 – Vorschau darf nie stören
            q = None
        if q is None:
            self._kandidat = None
            self._verweilen.stop()
            self._schliessen_spaeter()
            return
        gleich = self._aktuell is not None and q.schluessel == self._aktuell.schluessel and q.seite == self._aktuell.seite
        if gleich and self._fenster is not None and self._fenster.isVisible():
            return
        if self._kandidat is None or q.schluessel != self._kandidat.schluessel or q.seite != self._kandidat.seite:
            self._kandidat = q
            self._verweilen.start()                   # erst nach ruhigem Verweilen anzeigen bzw. tauschen

    def _schliessen_spaeter(self):
        if self._fenster is not None and self._fenster.isVisible():
            self._schliessen_takt.start()

    def _schliessen_pruefen(self):
        if self._fenster is None:
            return
        pos = QCursor.pos()
        if self._fenster.geometry().contains(pos):
            return
        for w in self._quellen:
            if w.isVisible() and w.rect().contains(w.mapFromGlobal(pos)):
                return
        self.schliessen()

    def schliessen(self):
        self._verweilen.stop()
        self._schliessen_takt.stop()
        if self._fenster is not None:
            self._fenster.hide()
        QApplication.instance().removeEventFilter(self)
        self._aktuell = None
        self._kandidat = None
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def _zeigen(self):
        q = self._kandidat
        if q is None or not self.aktiv():
            return
        if self._fenster is None:
            self._fenster = _Fenster(self)
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._aktuell, self._seite, self._seiten = q, q.seite, 1
        fehler = q.hinweis
        if not fehler and (q.pfad is None or q.pfad.suffix.lower() not in BILDER):
            try:
                from core import pdf_engine as pe
                self._doc = pe.oeffnen(q.pfad, q.daten) if q.daten is not None else pe.oeffnen(q.pfad)
                self._seiten = self._doc.page_count
                self._seite = max(0, min(self._seite, self._seiten - 1))
            except Exception:  # noqa: BLE001 – beschädigt/leer/kein PDF → Meldung statt Fehlerfenster
                fehler = KEINE_VORSCHAU
        self._darstellen(fehler)
        QApplication.instance().installEventFilter(self)

    def blaettern(self, richtung: int):
        if self._doc is None or self._seiten < 2:
            return
        neu = max(0, min(self._seite + richtung, self._seiten - 1))
        if neu != self._seite:
            self._seite = neu
            self._darstellen("")

    # --- Darstellung ---------------------------------------------------------
    def _bildschirm(self):
        s = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        return s

    def _darstellen(self, fehler: str):
        f, q = self._fenster, self._aktuell
        s = self._bildschirm()
        g = s.availableGeometry()
        dpr = s.devicePixelRatio()
        kopf = f"<b>{_e(q.dateiname)}</b>" + (f"<br>{_e(q.bezeichnung)}" if q.bezeichnung else "")
        pix = None
        if not fehler:
            try:
                pix, verh = self._seitenbild(q, g.height(), dpr)
            except Exception:  # noqa: BLE001 – nie ein Fehlerfenster aus der Vorschau
                fehler = KEINE_VORSCHAU
        if fehler:
            f.kopf.setText(kopf)
            f.bild.setPixmap(QPixmap())
            f.bild.setText(fehler)
            f.bild.setWordWrap(True)
            f.fuss.setText("")
            groesse = (460, 200)
        else:
            b, h = vorschau_groesse(g.height(), verh, 0.8, g.width())
            f.kopf.setText(kopf + (f"<br>Seite {self._seite + 1} von {self._seiten}" if self._seiten else ""))
            f.fuss.setText("Mausrad oder ←/→: blättern · Esc: schließen" if self._seiten > 1 else "Esc: schließen")
            f.bild.setText("")
            ziel = QPixmap(pix)
            ziel.setDevicePixelRatio(dpr)
            f.bild.setPixmap(ziel.scaled(int(b * dpr), int(h * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                             if ziel.width() > b * dpr * 1.05 else ziel)
            groesse = (b + 24, h + 90)
        f.resize(*groesse)
        x, y = fenster_position((QCursor.pos().x(), QCursor.pos().y()), (f.width(), f.height()),
                                (g.x(), g.y(), g.width(), g.height()))
        f.move(x, y)
        f.show()
        f.raise_()

    def _seitenbild(self, q: Quelle, bildschirm_h: int, dpr: float) -> tuple[QPixmap, float]:
        ziel_h = int(bildschirm_h * 0.8 * dpr)
        schluessel = (q.schluessel, self._seite, ziel_h)
        treffer = _CACHE.get(schluessel)
        if treffer is not None:
            return treffer
        if q.pfad is not None and q.pfad.suffix.lower() in BILDER and self._doc is None:
            img = QImage(str(q.pfad))
            if img.isNull():
                raise ValueError("Bild nicht lesbar")
            pix = QPixmap.fromImage(img.scaledToHeight(min(ziel_h, img.height() * 2), Qt.SmoothTransformation))
        else:
            import pymupdf
            from .pdf_ui import qpixmap
            page = self._doc[self._seite]
            zoom = ziel_h / max(page.rect.height, 1)
            pix = qpixmap(page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False))
        verh = pix.width() / max(pix.height(), 1)
        _CACHE.put(schluessel, (pix, verh), pix.width() * pix.height() * 4)
        return pix, verh


def _e(t: str) -> str:
    from html import escape
    return escape(t or "")
