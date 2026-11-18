"""„PDF bearbeiten“: Seiten, echter Textaustausch, OCR, Wortkorrektur im Scan, Schwärzen.

Arbeitet auf einer Kopie im Speicher (core.pdf_sitzung). 0.4.1: „Speichern“ (Strg+S) schreibt sicher in
dieselbe Datei (Temp-Datei → Prüfung → Ersetzen; extern geändert/gesperrt → nichts überschrieben),
„Speichern unter…“ bleibt. „OK – Änderungen speichern“ speichert und kehrt zum Aufrufer zurück.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QMenu, QScrollArea, QSplitter, QToolBar, QToolButton, QVBoxLayout, QWidget)

from core import pdf_engine as pe
from core.pdf_sitzung import PdfSitzung

from . import theme
from .pdf_ui import im_thread, qpixmap

MODI = [("auswahl", "Auswählen/Kopieren"), ("text", "Text bearbeiten"), ("einfuegen", "Text einfügen"),
        ("wort", "Wort korrigieren (Scan)"), ("schwaerzen", "Schwärzen"), ("zuschnitt", "Zuschneiden")]
AUSRICHTUNG_DE = {"links": "Linksbündig", "zentriert": "Zentriert", "rechts": "Rechtsbündig",
                  "blocksatz": "Blocksatz"}


# ---------------------------------------------------------------- Seitenansicht
class SeitenAnsicht(QWidget):
    klick = Signal(object)            # pymupdf.Point (ungedrehte Seitenkoordinaten)
    rechteck = Signal(object)         # pymupdf.Rect

    def __init__(self):
        super().__init__()
        self.page = None
        self.zoom = 1.25
        self.bild = None
        self.markierungen: list[tuple[pymupdf.Rect, QColor, bool]] = []
        self._start: QPoint | None = None
        self._ende: QPoint | None = None
        self.setMouseTracking(False)

    def zeigen(self, page, zoom: float):
        self.page, self.zoom = page, zoom
        self.bild = qpixmap(page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False))
        self.setFixedSize(self.bild.size())
        self.update()

    def _zu_seite(self, p: QPoint) -> pymupdf.Point:
        return pymupdf.Point(p.x(), p.y()) * ~pymupdf.Matrix(self.zoom, self.zoom) * self.page.derotation_matrix

    def _zu_bild(self, r: pymupdf.Rect) -> QRect:
        b = pymupdf.Rect(r) * self.page.rotation_matrix * pymupdf.Matrix(self.zoom, self.zoom)
        return QRect(int(b.x0), int(b.y0), int(b.width), int(b.height))

    def paintEvent(self, _):
        if not self.bild:
            return
        g = QPainter(self)
        g.drawPixmap(0, 0, self.bild)
        for r, farbe, gefuellt in self.markierungen:
            q = self._zu_bild(r)
            if gefuellt:                       # vorgemerkte Schwärzung: schraffiert, kräftiger Rand, Etikett
                f = QColor(farbe)
                f.setAlpha(60)
                g.fillRect(q, f)
                g.fillRect(q, QBrush(QColor(farbe), Qt.BDiagPattern))
                g.setPen(QPen(farbe, 3))
                g.drawRect(q)
                etikett = QRect(q.left(), q.top() - 16, 92, 15)
                g.fillRect(etikett, farbe)
                g.setPen(QColor("#FFFFFF"))
                fnt = g.font()
                fnt.setPixelSize(10)
                fnt.setBold(True)
                g.setFont(fnt)
                g.drawText(etikett, Qt.AlignCenter, "WIRD GESCHWÄRZT")
            else:
                g.setPen(QPen(farbe, 2))
                g.drawRect(q)
        if self._start and self._ende:
            g.setPen(QPen(QColor("#2563eb"), 1, Qt.DashLine))
            g.drawRect(QRect(self._start, self._ende).normalized())

    def mousePressEvent(self, e):
        if self.page is None:
            return
        self._start = self._ende = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._start:
            self._ende = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if not self._start:
            return
        a, b = self._start, e.position().toPoint()
        self._start = self._ende = None
        self.update()
        if abs(a.x() - b.x()) < 4 and abs(a.y() - b.y()) < 4:
            self.klick.emit(self._zu_seite(a))
        else:
            p1, p2 = self._zu_seite(a), self._zu_seite(b)
            self.rechteck.emit(pymupdf.Rect(p1, p2).normalize())


# ---------------------------------------------------------------- Dialoge mit Vorschau
class KlickBild(QLabel):
    """Vorschaubild, das Klicks (Pixelposition im Bild) meldet."""
    geklickt = Signal(QPoint)

    def mousePressEvent(self, e):
        self.geklickt.emit(e.position().toPoint())


class _VorschauDialog(QDialog):
    """Gemeinsame Basis: Formular links, Vorschau der geänderten Seite rechts (aktualisiert sich selbst)."""
    BREITE = 620

    def __init__(self, parent, titel: str, sitzung: PdfSitzung, seite: int):
        super().__init__(parent)
        self.setWindowTitle(titel)
        self.resize(1080, 740)
        self.sitzung, self.seite = sitzung, seite
        self.geprueft = False
        self.markierung: pymupdf.Rect | None = None          # gewählter Absatz (Seitenkoordinaten)
        haupt = QHBoxLayout(self)
        links = QVBoxLayout()
        self.kopf = QVBoxLayout()
        links.addLayout(self.kopf)
        self.form = QFormLayout()
        links.addLayout(self.form)
        self.hinweis = QLabel()
        self.hinweis.setWordWrap(True)
        links.addWidget(self.hinweis)
        links.addStretch(1)
        bb = QDialogButtonBox()
        self.ok = bb.addButton("OK", QDialogButtonBox.AcceptRole)
        theme.rolle(self.ok, "primaer")
        bb.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._annehmen)
        bb.rejected.connect(self.reject)
        links.addWidget(bb)
        haupt.addLayout(links, 2)
        self.bild = KlickBild("Vorschau …")
        self.bild.setAlignment(Qt.AlignCenter)
        self.bild.setCursor(Qt.PointingHandCursor)
        sc = QScrollArea()
        sc.setWidget(self.bild)
        sc.setWidgetResizable(False)            # Bild = feste Größe → Klickposition = Bildposition
        sc.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        haupt.addWidget(sc, 3)
        self.ergebnis = None
        self._takt = QTimer(self)               # Live-Vorschau: kurz nach der letzten Eingabe
        self._takt.setSingleShot(True)
        self._takt.setInterval(350)
        self._takt.timeout.connect(self.vorschau)

    def aenderung(self, doc):        # in Unterklassen
        raise NotImplementedError

    def _seite_obj(self):
        return self.sitzung.doc[self.seite]

    def vorschau(self) -> bool:
        try:
            pix, erg = self.sitzung.vorschau(self.aenderung, self.seite, self.BREITE)
        except pe.PdfFehler as e:
            self.hinweis.setText(f"<span style='color:{theme.F['fehler']}'>{e}</span>")
            self.geprueft = False
            return False
        bild = qpixmap(pix)
        if self.markierung is not None:          # gewählten Absatz hervorheben
            page = self._seite_obj()
            f = pix.width / max(page.rect.width, 1)
            r = pymupdf.Rect(self.markierung) * page.rotation_matrix * pymupdf.Matrix(f, f)
            g = QPainter(bild)
            g.setPen(QPen(QColor(theme.F["primaer"]), 2))
            farbe = QColor(theme.F["primaer"])
            farbe.setAlpha(28)
            g.fillRect(QRect(int(r.x0) - 3, int(r.y0) - 3, int(r.width) + 6, int(r.height) + 6), farbe)
            g.drawRect(QRect(int(r.x0) - 3, int(r.y0) - 3, int(r.width) + 6, int(r.height) + 6))
            g.end()
        self.bild.setPixmap(bild)
        self.bild.adjustSize()
        w = getattr(erg, "warnungen", [])
        self.hinweis.setText(
            f"<b style='color:{theme.F['warn']}'>Bitte prüfen:</b><br>" + "<br>".join(f"⚠ {x}" for x in w) if w
            else f"<span style='color:{theme.F['ok']}'>✓ Vorschau aktuell – keine Auffälligkeiten.</span>")
        if getattr(erg, "schrift", ""):
            self.hinweis.setText(self.hinweis.text() + f"<br>Schrift: {erg.schrift}")
        self.geprueft = True
        return True

    def _annehmen(self):
        # Vorschau ist live; falls die letzte Eingabe noch nicht gezeigt wurde, jetzt prüfen
        if not self.geprueft and not self.vorschau():
            return
        self.accept()

    def _geaendert(self, *_):
        self.geprueft = False
        self._takt.start()


class TextDialog(_VorschauDialog):
    """Absatz bearbeiten oder neuen Text einfügen.

    Bearbeiten: Klick in die Vorschau wählt einen anderen Absatz (auch ganz unten); ◀/▶ gehen Absatz für
    Absatz weiter, auch auf die Folgeseiten. Beim Wechsel wird die Änderung am bisherigen Absatz übernommen.
    Digitaler Text nutzt die vorhandene Textebene, Scans die OCR-Blöcke (Bild + OCR-Text werden ersetzt).
    """

    def __init__(self, parent, sitzung, seite: int, block: dict | None, punkt=None, anwenden=None):
        super().__init__(parent, "Text bearbeiten" if block else "Text einfügen", sitzung, seite)
        self.punkt = punkt
        self.anwenden = anwenden              # fn(beschreibung, aenderung, seite) -> bool
        self.bearbeiten = block is not None
        self.index, self.bbox, self.scan = -1, None, False
        self.text = QPlainTextEdit()
        self.groesse = QDoubleSpinBox()
        self.groesse.setRange(5, 72)
        self.farbe = (0, 0, 0)
        self.b_farbe = QPushButton("Farbe …")
        self.b_farbe.clicked.connect(self._farbe)
        self.ausr = QComboBox()
        for k, v in AUSRICHTUNG_DE.items():
            self.ausr.addItem(v, k)
        self.l_schrift = QLabel()
        self.l_schrift.setWordWrap(True)
        if self.bearbeiten:
            nav = QHBoxLayout()
            self.b_zurueck = QPushButton("◀ Vorheriger Absatz")
            self.b_zurueck.clicked.connect(lambda: self._schritt(-1))
            self.b_weiter = QPushButton("Nächster Absatz ▶")
            self.b_weiter.clicked.connect(lambda: self._schritt(1))
            nav.addWidget(self.b_zurueck)
            nav.addWidget(self.b_weiter)
            self.kopf.addLayout(nav)
            self.l_pos = theme.rolle(QLabel(), "gedimmt")
            self.l_pos.setWordWrap(True)
            self.kopf.addWidget(self.l_pos)
            self.bild.geklickt.connect(self._bild_klick)
            self.bild.setToolTip("Absatz anklicken, um ihn zu bearbeiten")
        self.form.addRow("Text:", self.text)
        self.form.addRow("Schriftgröße (pt):", self.groesse)
        self.form.addRow("Schriftfarbe:", self.b_farbe)
        self.form.addRow("Ausrichtung:", self.ausr)
        self.form.addRow("Schrift:", self.l_schrift)
        for w in (self.text.textChanged, self.groesse.valueChanged, self.ausr.currentIndexChanged):
            w.connect(self._geaendert)
        if self.bearbeiten:
            page = self._seite_obj()
            self._waehlen(self.seite, self._index_von(page, block))
        else:
            self.groesse.setValue(11)
            self.ausr.setCurrentIndex(0)
            self.vorschau()
        self.text.setFocus()

    # --- Absatzwahl -----------------------------------------------------------
    @staticmethod
    def _index_von(page, block: dict) -> int:
        r = pymupdf.Rect(block["bbox"])
        for i, b in enumerate(pe.textbloecke(page)):
            if pymupdf.Rect(b["bbox"]) == r:
                return i
        return 0

    def _block(self, doc=None):
        page = (doc or self.sitzung.doc)[self.seite]
        return pe.block_finden(page, self.index, self.bbox)

    def _waehlen(self, seite: int, index: int):
        self.seite = seite
        page = self._seite_obj()
        bloecke = pe.textbloecke(page)
        if not bloecke:
            return
        self.index = max(0, min(index, len(bloecke) - 1))
        b = bloecke[self.index]
        self.bbox = tuple(b["bbox"])
        self.markierung = pymupdf.Rect(b["bbox"])
        self.scan = pe.block_ist_ocr(page, b)
        fmt = pe.block_format(b)
        for w in (self.text, self.groesse, self.ausr):
            w.blockSignals(True)
        self.text.setPlainText(fmt.text)
        self.groesse.setValue(fmt.groesse)
        self.farbe = fmt.farbe
        self.ausr.setCurrentIndex(list(AUSRICHTUNG_DE).index(fmt.ausrichtung))
        for w in (self.text, self.groesse, self.ausr):
            w.blockSignals(False)
        self._original = (fmt.text, fmt.groesse, fmt.ausrichtung)
        self.l_schrift.setText(("Scan (OCR-Text) – wird als echter Text neu gesetzt" if self.scan else fmt.schrift)
                               + ("  ⚠ gemischte Formatierung – wird einheitlich gesetzt" if fmt.gemischt else ""))
        self.l_pos.setText(f"Seite {seite + 1} · Absatz {self.index + 1} von {len(bloecke)}"
                           + (" · Scan" if self.scan else ""))
        self.b_zurueck.setEnabled(seite > 0 or self.index > 0)
        self.b_weiter.setEnabled(seite < self.sitzung.doc.page_count - 1 or self.index < len(bloecke) - 1)
        self.geprueft = False
        self.vorschau()
        self.text.setFocus()

    def _veraendert(self) -> bool:
        return self.bearbeiten and (self.text.toPlainText(), self.groesse.value(),
                                    self.ausr.currentData()) != self._original

    def _uebernehmen_falls_geaendert(self) -> bool:
        """Änderung am aktuellen Absatz in das Dokument übernehmen (bei Absatzwechsel und OK)."""
        if not self._veraendert():
            return True
        if self.anwenden is None:
            return True
        return bool(self.anwenden("Text geändert", self.aenderung, self.seite))

    def _schritt(self, richtung: int):
        if not self._uebernehmen_falls_geaendert():
            return
        bloecke = pe.textbloecke(self._seite_obj())
        i = self._index_neu() + richtung
        seite = self.seite
        while not 0 <= i < len(bloecke):
            seite += richtung
            if not 0 <= seite < self.sitzung.doc.page_count:
                return
            bloecke = pe.textbloecke(self.sitzung.doc[seite])
            i = 0 if richtung > 0 else len(bloecke) - 1
        self._waehlen(seite, i)

    def _index_neu(self) -> int:
        """Index des (evtl. gerade geänderten) Absatzes in der aktuellen Seite."""
        page = self._seite_obj()
        b = pe.block_finden(page, self.index, self.bbox)
        return self._index_von(page, b) if b else self.index

    def _bild_klick(self, pos: QPoint):
        page = self._seite_obj()
        pm = self.bild.pixmap()
        if pm is None or pm.isNull():
            return
        f = pm.width() / max(page.rect.width, 1)
        punkt = pymupdf.Point(pos.x() / f, pos.y() / f) * page.derotation_matrix
        b = pe.block_an(page, punkt)
        if not b:
            return
        if not self._uebernehmen_falls_geaendert():
            return
        page = self._seite_obj()                      # nach dem Übernehmen neu (Inhalt hat sich geändert)
        b = pe.block_an(page, punkt)
        if b:
            self._waehlen(self.seite, self._index_von(page, b))

    # --- Formular -------------------------------------------------------------
    def _farbe(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.farbe), self, "Schriftfarbe")
        if c.isValid():
            self.farbe = (c.redF(), c.greenF(), c.blueF())
            self._geaendert()

    def aenderung(self, doc):
        page = doc[self.seite]
        text = self.text.toPlainText()
        if self.bearbeiten:
            b = pe.block_finden(page, self.index, self.bbox)
            if b is None:
                raise pe.PdfFehler("Absatz nicht mehr gefunden – bitte erneut anklicken.")
            if self.scan:
                return pe.scan_block_ersetzen(page, b, text, self.groesse.value(), self.farbe,
                                              self.ausr.currentData())
            return pe.block_ersetzen(page, b, text, self.groesse.value(), self.farbe, self.ausr.currentData())
        return pe.text_einfuegen(page, self.punkt, text, self.groesse.value(), self.farbe,
                                 ausrichtung=self.ausr.currentData())

    def _annehmen(self):
        if self.bearbeiten:                     # Änderung direkt übernehmen und schließen
            if not self.geprueft and not self.vorschau():
                return
            if self._uebernehmen_falls_geaendert():
                self.accept()
            return
        super()._annehmen()


class WortDialog(_VorschauDialog):
    def __init__(self, parent, sitzung, seite: int, wort: str, rect, ocr_info=None):
        super().__init__(parent, "Wort im Scan korrigieren", sitzung, seite)
        self.alt, self.rect = wort, rect
        self.markierung = pymupdf.Rect(rect)
        self.neu = QLineEdit(wort)
        self.form.addRow("Erkannt:", QLabel(f"<b>{wort}</b>" + (f"  (Sicherheit {ocr_info.conf:.0f} %)"
                                                                 if ocr_info else "")))
        self.form.addRow("Korrigiert:", self.neu)
        if ocr_info and ocr_info.geschuetzt or any(m.search(wort) for m in pe.SCHUTZ_MUSTER[1:]):
            self.form.addRow(QLabel(f"<b style='color:{theme.F['fehler']}'>Geschütztes Feld (Aktenzeichen/E-Mail/"
                                    "IBAN/Nr.): wird nie automatisch geändert – bitte Zeichen für Zeichen prüfen.</b>"))
        self.neu.textChanged.connect(self._geaendert)
        self.vorschau()

    def aenderung(self, doc):
        return pe.scan_wort_ersetzen(doc[self.seite], self.alt, self.neu.text().strip(), self.rect)


# ---------------------------------------------------------------- Hauptfenster
class PdfEditor(QDialog):
    """Eigenständig („PDF bearbeiten…“) oder aus Word→PDF / Anlagen-Assistent geöffnet.

    Datei geöffnet → „Speichern“ schreibt in dieselbe Datei.
    Nur Bytes (z. B. Anlage im Anlagen-Assistenten) → „Speichern“ ruft bei_speichern(bytes) auf, das Ergebnis
    steht zusätzlich in self.ergebnis_bytes. start_seite/text_modus: direkt auf einer Seite im Werkzeug
    „Text bearbeiten“ öffnen (Scan ohne Text → Texterkennung dieser Seite läuft automatisch).
    """

    def __init__(self, parent=None, pfad: Path | None = None, daten: bytes | None = None, name: str = "",
                 uebernehmen_text: str = "", sprachen: tuple[str, ...] = pe.SPRACHEN, start_seite: int = 0,
                 text_modus: bool = False, bei_speichern=None):
        super().__init__(parent)
        self.bei_speichern = bei_speichern
        self.ziel_text = uebernehmen_text
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1250, 860)
        self.sprachen = tuple(sprachen)
        self.sitzung: PdfSitzung | None = None
        self.seite = 0
        self.zoom = 1.25
        self.treffer: list[tuple[int, pymupdf.Rect]] = []
        self.treffer_i = -1
        self.offen: list[tuple[int, pymupdf.Rect]] = []      # vorgemerkte Schwärzungen
        self.ocr_worte: dict[int, list[pe.OcrWort]] = {}
        self.gespeichert: Path | None = None
        self.ergebnis_bytes: bytes | None = None
        self._aufbau(uebernehmen_text)
        if pfad or daten is not None:
            self.laden(pfad, daten, name)
            if self.sitzung and start_seite:
                self.aktualisieren(start_seite)
            if self.sitzung and text_modus:
                self._modus_aktion["text"].setChecked(True)
                self._modus_setzen("text")
                if pe.ist_gescannt(self.sitzung.doc[self.seite]) and pe.tesseract_ordner():
                    QTimer.singleShot(200, lambda: self._ocr_seiten_ausfuehren([self.seite]))
        else:
            self._titel()

    # --- Aufbau ---
    def _aufbau(self, uebernehmen_text: str):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        tb = QToolBar()
        tb.setIconSize(pymupdf_qsize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        lay.addWidget(tb)

        def act(text, fn, kurz=None, leiste=tb, symbol=None):
            a = QAction(theme.icon(symbol, "titel") if symbol else QIcon_leer(), text, self)
            a.triggered.connect(fn)
            if kurz:
                a.setShortcut(QKeySequence(kurz))
                a.setToolTip(f"{text} ({QKeySequence(kurz).toString(QKeySequence.NativeText)})")
            if leiste is not None:
                leiste.addAction(a)
            return a
        act("Öffnen…", self.oeffnen_dialog, "Ctrl+O", symbol="oeffnen")
        self.a_speichern = act("Speichern", self.speichern, "Ctrl+S", symbol="speichern")
        self.a_speichern_unter = act("Speichern unter…", self.speichern_unter, "Ctrl+Shift+S")
        tb.addSeparator()
        self.a_undo = act("Rückgängig", self.rueckgaengig, "Ctrl+Z", symbol="rueckgaengig")
        self.a_redo = act("Wiederholen", self.wiederholen, "Ctrl+Y", symbol="wiederholen")
        tb.addSeparator()
        act("−", lambda: self.zoomen(1 / 1.2), "Ctrl+-")
        act("+", lambda: self.zoomen(1.2), "Ctrl++")
        tb.addSeparator()
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Suchen … (Strg+F)")
        self.suche.setMaximumWidth(240)
        self.suche.returnPressed.connect(self.suchen)
        tb.addWidget(self.suche)
        act("Weiter", self.naechster_treffer, "F3", symbol="lupe")
        a_suche = QAction(self)
        a_suche.setShortcut(QKeySequence("Ctrl+F"))
        a_suche.triggered.connect(lambda: (self.suche.setFocus(), self.suche.selectAll()))
        self.addAction(a_suche)

        # Werkzeuge: Symbol + Beschriftung (Seiten · Text bearbeiten · OCR · Schwärzen …)
        wz = QToolBar()
        wz.setIconSize(pymupdf_qsize(26, 26))
        wz.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        lay.addWidget(wz)
        self.modus_gruppe = QActionGroup(self)
        self.modus = "auswahl"
        modus_aktion = {}
        symbole = {"auswahl": "auswahl", "text": "text", "einfuegen": "einfuegen", "wort": "wort",
                   "schwaerzen": "schwaerzen", "zuschnitt": "zuschnitt"}
        for key, text in MODI:
            a = QAction(theme.icon(symbole[key], "titel"), text, self)
            a.setCheckable(True)
            a.setChecked(key == "auswahl")
            a.triggered.connect(lambda _=False, k=key: self._modus_setzen(k))
            self.modus_gruppe.addAction(a)
            modus_aktion[key] = a
        self._modus_aktion = modus_aktion

        def gruppe(a):
            wz.addAction(a)
            w = wz.widgetForAction(a)
            if w:
                theme.rolle(w, "haupt", "gruppe")
        gruppe(modus_aktion["auswahl"])
        wz.addSeparator()
        # Seiten (Menü)
        seiten_menu = QMenu(self)
        act("↺ Links drehen", lambda: self.drehen(-90), leiste=seiten_menu)
        act("↻ Rechts drehen", lambda: self.drehen(90), leiste=seiten_menu)
        act("Löschen", self.seiten_loeschen, leiste=seiten_menu)
        act("Duplizieren", self.duplizieren, leiste=seiten_menu)
        seiten_menu.addSeparator()
        act("PDF/Bild einfügen…", self.einfuegen_datei, leiste=seiten_menu)
        act("Auswahl als PDF…", self.auswahl_speichern, leiste=seiten_menu)
        act("Aufteilen…", self.aufteilen, leiste=seiten_menu)
        b_seiten = QToolButton()
        b_seiten.setText("Seiten")
        b_seiten.setIcon(theme.icon("seiten", "titel"))
        b_seiten.setIconSize(pymupdf_qsize(26, 26))
        b_seiten.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b_seiten.setPopupMode(QToolButton.InstantPopup)
        b_seiten.setMenu(seiten_menu)
        b_seiten.setToolTip("Seiten drehen, löschen, duplizieren, einfügen, aufteilen (markierte Seiten links)")
        theme.rolle(b_seiten, "haupt", "gruppe")
        wz.addWidget(b_seiten)
        wz.addSeparator()
        for k in ("text", "einfuegen", "wort"):
            gruppe(modus_aktion[k])
        wz.addSeparator()
        # OCR (Klick = starten; Pfeil = Umfang, Ausrichtung)
        self.ocr_umfang = QComboBox()
        self.ocr_umfang.addItems(["Diese Seite", "Ausgewählte Seiten", "Alle Seiten"])
        self.ocr_umfang.setToolTip("Umfang der Texterkennung")
        ocr_menu = QMenu(self)
        for i, text in enumerate(("Diese Seite", "Ausgewählte Seiten", "Alle Seiten")):
            ocr_menu.addAction(f"OCR: {text}", lambda i=i: (self.ocr_umfang.setCurrentIndex(i), self.ocr()))
        ocr_menu.addSeparator()
        act("Ausrichtung prüfen", self.ausrichtung_pruefen, leiste=ocr_menu)
        schraeg = ocr_menu.addAction("Schräglagenkorrektur: noch nicht verfügbar")
        schraeg.setEnabled(False)
        a_ocr = QAction(theme.icon("ocr", "titel"), "OCR", self)
        a_ocr.setToolTip("Texterkennung (Deutsch, Türkisch, Englisch) für den gewählten Umfang starten")
        a_ocr.triggered.connect(self.ocr)
        b_ocr = QToolButton()
        b_ocr.setDefaultAction(a_ocr)
        b_ocr.setIconSize(pymupdf_qsize(26, 26))
        b_ocr.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b_ocr.setPopupMode(QToolButton.MenuButtonPopup)
        b_ocr.setMenu(ocr_menu)
        theme.rolle(b_ocr, "haupt", "gruppe")
        wz.addWidget(b_ocr)
        umfang = QWidget()
        ul = QVBoxLayout(umfang)
        ul.setContentsMargins(4, 0, 4, 0)
        ul.addWidget(theme.rolle(QLabel("Umfang:"), "gedimmt"))
        ul.addWidget(self.ocr_umfang)
        wz.addWidget(umfang)
        wz.addSeparator()
        gruppe(modus_aktion["schwaerzen"])
        wz.addSeparator()
        gruppe(modus_aktion["zuschnitt"])
        self.a_ocr = a_ocr

        split = QSplitter()
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ListMode)
        self.thumbs.setIconSize(pymupdf_qsize(110, 150))
        self.thumbs.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.thumbs.setDragDropMode(QAbstractItemView.InternalMove)
        self.thumbs.setMaximumWidth(200)
        self.thumbs.currentRowChanged.connect(self.seite_waehlen)
        self.thumbs.model().rowsMoved.connect(self._umsortiert)
        split.addWidget(self.thumbs)
        self.ansicht = SeitenAnsicht()
        self.ansicht.klick.connect(self._klick)
        self.ansicht.rechteck.connect(self._rechteck)
        sc = QScrollArea()
        sc.setWidget(self.ansicht)
        sc.setAlignment(Qt.AlignCenter)
        split.addWidget(sc)
        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.addWidget(theme.ueberschrift("Hinweise / zu prüfen", "h3"))
        self.hinweise = QListWidget()
        self.hinweise.itemActivated.connect(self._hinweis_gewaehlt)
        self.hinweise.itemClicked.connect(self._hinweis_gewaehlt)
        rl.addWidget(self.hinweise, 1)
        rl.addSpacing(8)
        rl.addWidget(theme.ueberschrift("Schwärzen", "h3"))
        self.l_schwaerzen = QLabel()
        self.l_schwaerzen.setWordWrap(True)
        rl.addWidget(self.l_schwaerzen)
        self.b_schwaerzen = QPushButton("Schwärzungen &anwenden (0)")
        self.b_schwaerzen.clicked.connect(self.schwaerzungen_anwenden)
        rl.addWidget(self.b_schwaerzen)
        b_treffer = QPushButton("Suchtreffer zum Schwärzen vor&merken")
        b_treffer.clicked.connect(self.treffer_vormerken)
        rl.addWidget(b_treffer)
        b_verwerfen = QPushButton("Vormerkungen verwerfen")
        b_verwerfen.clicked.connect(self._vormerkungen_verwerfen)
        rl.addWidget(b_verwerfen)
        rechts.setMaximumWidth(330)
        rl.setContentsMargins(10, 10, 10, 10)
        split.addWidget(rechts)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        unten = QHBoxLayout()
        unten.setContentsMargins(12, 6, 12, 10)
        self.status = QLabel()
        self.status.setWordWrap(True)
        unten.addWidget(self.status, 1)
        b_abbr = QPushButton("Abbrechen")
        b_abbr.clicked.connect(self.reject)
        self.b_ok = QPushButton(theme.icon("uebernehmen", "primaer_text", 18), "  OK – Änderungen speichern")
        self.b_ok.setToolTip("Speichern und zurück" + (f" ({uebernehmen_text})" if uebernehmen_text else "")
                             + " – Strg+Eingabe")
        theme.rolle(self.b_ok, "primaer")
        self.b_ok.clicked.connect(self.ok_speichern)
        unten.addWidget(b_abbr)
        unten.addWidget(self.b_ok)
        lay.addLayout(unten)
        a_ok = QAction(self)
        a_ok.setShortcuts([QKeySequence("Ctrl+Return"), QKeySequence("Ctrl+Enter")])
        a_ok.triggered.connect(self.ok_speichern)
        self.addAction(a_ok)
        self._schwaerz_anzeige()
        # Kein "Standardknopf": Enter im Suchfeld darf nicht versehentlich „Schwärzungen anwenden“ auslösen
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)
            b.setDefault(False)

    # --- Laden / Anzeige ---
    def laden(self, pfad: Path | None, daten: bytes | None = None, name: str = ""):
        try:
            self.sitzung = PdfSitzung(pfad, daten, name)
        except pe.PdfFehler as e:
            QMessageBox.critical(self, "PDF bearbeiten", str(e))
            return
        self.seite = 0
        self.ocr_worte.clear()
        self.offen.clear()
        self.hinweise.clear()
        if self.sitzung.signaturen:
            self._hinweis("⚠ Dokument ist digital signiert. Jede Änderung macht die Signatur ungültig; "
                          "gespeichert wird immer eine separate Kopie.")
            QMessageBox.warning(self, "Signiertes Dokument",
                                "Dieses PDF ist digital signiert.\nÄnderungen machen die Signatur ungültig. "
                                "Das Original bleibt unverändert – gespeichert wird eine separate Kopie.")
        self.aktualisieren()

    def _titel(self):
        s = self.sitzung
        name = s.name if s else "kein Dokument"
        self.setWindowTitle(f"PDF bearbeiten – {name}{' *' if s and s.geaendert else ''}")
        if hasattr(self, "a_speichern"):
            self.a_speichern.setEnabled(bool(s))

    def aktualisieren(self, seite: int | None = None):
        s = self.sitzung
        if not s:
            return
        if seite is not None:
            self.seite = seite
        self.seite = max(0, min(self.seite, s.doc.page_count - 1))
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for p in s.doc:
            it = QListWidgetItem(f"Seite {p.number + 1}")
            it.setIcon(qpixmap(pe.seitenbild(p, 110)))
            it.setData(Qt.UserRole, p.number)
            self.thumbs.addItem(it)
        self.thumbs.setCurrentRow(self.seite)
        self.thumbs.blockSignals(False)
        self._anzeigen()
        self.a_undo.setEnabled(s.kann_rueckgaengig)
        self.a_redo.setEnabled(s.kann_wiederholen)
        self._schwaerz_anzeige()
        self._titel()

    def _anzeigen(self):
        s = self.sitzung
        page = s.doc[self.seite]
        self.ansicht.zeigen(page, self.zoom)
        m = [(r, theme.status_farbe("fehler"), True) for n, r in self.offen if n == self.seite]
        m += [(r, QColor("#f59e0b"), False) for n, r in self.treffer if n == self.seite]
        m += [(w.rect, QColor("#2563eb"), False) for w in self.ocr_worte.get(self.seite, [])
              if w.conf < 80 or w.geschuetzt]
        self.ansicht.markierungen = m
        self.ansicht.update()
        bild = any(pymupdf.Rect(i["bbox"]).get_area() > 0.5 * page.rect.get_area() for i in page.get_image_info())
        art = ("Scan ohne Text – OCR möglich" if pe.ist_gescannt(page)
               else "Scan mit Textebene" if bild else "digital")
        self.status.setText(f"Seite {self.seite + 1} von {s.doc.page_count} · {art} · Zoom {self.zoom * 100:.0f} %"
                            f" · Werkzeug: {dict(MODI)[self.modus]}")

    def seite_waehlen(self, i: int):
        if i >= 0 and self.sitzung:
            self.seite = i
            self._anzeigen()

    def zoomen(self, f: float):
        self.zoom = max(0.4, min(4.0, self.zoom * f))
        if self.sitzung:
            self._anzeigen()

    def _modus_setzen(self, k: str):
        self.modus = k
        if self.sitzung:
            self._anzeigen()

    def _schwaerz_anzeige(self):
        """Zähler + Hinweis: vorgemerkte Bereiche sind noch NICHT geschwärzt (gelb), keine (neutral)."""
        n = len(self.offen)
        self.b_schwaerzen.setText(f"Schwärzungen &anwenden ({n})")
        theme.rolle(self.b_schwaerzen, "gefahr" if n else "")
        if n:
            theme.status_setzen(self.l_schwaerzen, "warn", f"{n} Bereich(e) vorgemerkt – noch nicht geschwärzt. "
                                "Erst „Schwärzungen anwenden“ entfernt Text und Bild endgültig.")
        else:
            theme.status_setzen(self.l_schwaerzen, None, "Werkzeug „Schwärzen“ wählen und Bereich aufziehen "
                                "oder Suchtreffer vormerken.")

    def _hinweis(self, text: str, daten=None):
        it = QListWidgetItem(text)
        it.setData(Qt.UserRole, daten)
        self.hinweise.addItem(it)

    def _hinweis_gewaehlt(self, it: QListWidgetItem):
        d = it.data(Qt.UserRole)
        if d:
            self.aktualisieren(d[0])

    def _ausfuehren(self, beschreibung: str, fn, seite: int | None = None):
        try:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            erg = self.sitzung.aendern(beschreibung, fn)
        except pe.PdfFehler as e:
            QMessageBox.warning(self, "PDF bearbeiten", str(e))
            return None
        finally:
            QGuiApplication.restoreOverrideCursor()
        for w in getattr(erg, "warnungen", []) or []:
            self._hinweis(f"⚠ S. {(seite if seite is not None else self.seite) + 1}: {w}")
        self.aktualisieren(seite)
        return erg

    # --- Klicks auf die Seite ---
    def _klick(self, punkt):
        page = self.sitzung.doc[self.seite]
        if self.modus == "auswahl":
            return
        if self.modus == "text":
            b = pe.block_an(page, punkt)
            if not b and pe.ist_gescannt(page) and pe.tesseract_ordner():
                self.status.setText("Scan ohne Text – Texterkennung dieser Seite läuft …")
                self._ocr_seiten_ausfuehren([self.seite])
                page = self.sitzung.doc[self.seite]
                b = pe.block_an(page, punkt)
            if not b:
                self.status.setText("Kein Text an dieser Stelle – bitte direkt auf einen Absatz klicken.")
                return
            TextDialog(self, self.sitzung, self.seite, b, anwenden=self._anwenden).exec()
        elif self.modus == "einfuegen":
            d = TextDialog(self, self.sitzung, self.seite, None, (punkt.x, punkt.y))
            if d.exec() == QDialog.Accepted:
                self._ausfuehren("Text eingefügt", d.aenderung)
        elif self.modus == "wort":
            w = pe.wort_an(page, punkt)
            if not w:
                self.status.setText("Kein erkanntes Wort an dieser Stelle – zuerst „OCR starten“.")
                return
            info = next((o for o in self.ocr_worte.get(self.seite, []) if o.rect.intersects(w[1])
                         and o.text == w[0]), None)
            try:
                d = WortDialog(self, self.sitzung, self.seite, w[0], w[1], info)
            except pe.PdfFehler as e:
                QMessageBox.warning(self, "Wort korrigieren", str(e))
                return
            if d.exec() == QDialog.Accepted:
                if self._ausfuehren(f"Wort „{w[0]}“ korrigiert", d.aenderung) is not None:
                    self.ocr_worte[self.seite] = [o for o in self.ocr_worte.get(self.seite, [])
                                                  if not o.rect.intersects(w[1])]
                    self._anzeigen()

    def _anwenden(self, beschreibung: str, fn, seite: int) -> bool:
        """Für den Textdialog: Änderung als eigenen Schritt (rückgängig machbar) übernehmen."""
        alt = self.seite
        self.seite = seite
        ok = self._ausfuehren(beschreibung, fn, seite) is not None
        if not ok:
            self.seite = alt
        return ok

    def _unsichtbar(self, b: dict) -> bool:
        """Block besteht nur aus unsichtbarem OCR-Text (render mode 3)?"""
        page = self.sitzung.doc[self.seite]
        trace = [t for t in page.get_texttrace() if pymupdf.Rect(t["bbox"]).intersects(pymupdf.Rect(b["bbox"]))]
        return bool(trace) and all(t.get("type") == 3 for t in trace)

    def _rechteck(self, r):
        page = self.sitzung.doc[self.seite]
        if self.modus == "auswahl":
            text = page.get_textbox(r).strip()
            QGuiApplication.clipboard().setText(text)
            self.status.setText(f"{len(text)} Zeichen kopiert." if text else "Kein Text im Bereich.")
        elif self.modus == "schwaerzen":
            self.offen.append((self.seite, r))
            self._schwaerz_anzeige()
            self._anzeigen()
        elif self.modus == "zuschnitt":
            if QMessageBox.question(self, "Zuschneiden", "Seite auf den markierten Bereich zuschneiden?") \
                    == QMessageBox.Yes:
                self._ausfuehren("Zugeschnitten", lambda d: pe.seite_zuschneiden(d[self.seite], r))

    # --- Schwärzen ---
    def treffer_vormerken(self):
        self.offen += [(n, r + (-1, -1, 1, 1)) for n, r in self.treffer]
        self._schwaerz_anzeige()
        self._anzeigen()

    def _vormerkungen_verwerfen(self):
        self.offen.clear()
        self.aktualisieren()

    def schwaerzungen_anwenden(self):
        if not self.offen:
            QMessageBox.information(self, "Schwärzen", "Bitte zuerst Bereiche im Werkzeug „Schwärzen“ markieren.")
            return
        if QMessageBox.question(
                self, "Endgültig schwärzen",
                f"{len(self.offen)} Bereich(e) endgültig schwärzen?\n\nText, OCR-Text und Bildpunkte darunter "
                "werden aus dem Dokument entfernt. Beim Speichern werden außerdem eingebettete Dateien, "
                "Metadaten und Vorschaubilder entfernt und das Ergebnis wird geprüft.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        offen = list(self.offen)

        def alle(doc):
            return [pe.schwaerzen(doc[n], r) for n, r in offen]
        if self._ausfuehren(f"{len(offen)} Bereich(e) geschwärzt", alle) is not None:
            self.offen.clear()
            self.aktualisieren()

    # --- Seiten ---
    def _ausgewaehlt(self) -> list[int]:
        return sorted(self.thumbs.row(i) for i in self.thumbs.selectedItems()) or [self.seite]

    def drehen(self, grad: int):
        if self.sitzung:
            self._ausfuehren("Gedreht", lambda d: pe.seiten_drehen(d, self._ausgewaehlt(), grad))

    def seiten_loeschen(self):
        if not self.sitzung:
            return
        n = self._ausgewaehlt()
        if QMessageBox.question(self, "Seiten löschen", f"{len(n)} Seite(n) löschen?") == QMessageBox.Yes:
            self._ausfuehren("Seiten gelöscht", lambda d: pe.seiten_loeschen(d, n), min(n))

    def duplizieren(self):
        if self.sitzung:
            self._ausfuehren("Seite dupliziert", lambda d: pe.seite_duplizieren(d, self.seite), self.seite + 1)

    def _umsortiert(self, *_):
        neu = [self.thumbs.item(i).data(Qt.UserRole) for i in range(self.thumbs.count())]
        if neu != list(range(len(neu))):
            self._ausfuehren("Seiten umsortiert", lambda d: pe.reihenfolge_setzen(d, neu), self.thumbs.currentRow())

    def einfuegen_datei(self):
        if not self.sitzung:
            return
        name, _ = QFileDialog.getOpenFileName(self, "PDF oder Bild einfügen", "",
                                              "PDF und Bilder (*.pdf *.jpg *.jpeg *.png *.tif *.tiff)")
        if not name:
            return
        try:
            quelle = pe.oeffnen(Path(name), Path(name).read_bytes() if name.lower().endswith(".pdf") else None)
        except pe.PdfFehler as e:
            QMessageBox.warning(self, "Einfügen", str(e))
            return
        self._ausfuehren(f"{Path(name).name} eingefügt", lambda d: pe.pdf_einfuegen(d, quelle, self.seite),
                         self.seite + 1)

    def auswahl_speichern(self):
        if not self.sitzung:
            return
        n = self._ausgewaehlt()
        name, _ = QFileDialog.getSaveFileName(self, "Ausgewählte Seiten speichern",
                                              str(self.sitzung.vorschlag().with_name(
                                                  f"{Path(self.sitzung.name).stem}_Seiten.pdf")), "PDF (*.pdf)")
        if name:
            self._neue_datei(pe.seiten_extrahieren(self.sitzung.doc, n), Path(name))

    def aufteilen(self):
        if not self.sitzung:
            return
        starts = self._ausgewaehlt()
        ordner = QFileDialog.getExistingDirectory(self, "Zielordner für die Teile")
        if not ordner:
            return
        stamm = Path(self.sitzung.name).stem
        teile = pe.aufteilen(self.sitzung.doc, starts if len(starts) > 1 or starts != [0] else
                             list(range(self.sitzung.doc.page_count)))
        for i, t in enumerate(teile, 1):
            self._neue_datei(t, Path(ordner) / f"{stamm}_Teil{i}.pdf", melden=False)
        self.status.setText(f"{len(teile)} Teile gespeichert in {ordner}")

    def _neue_datei(self, doc, ziel: Path, melden: bool = True):
        if self.sitzung.original and ziel.resolve() == self.sitzung.original.resolve():
            QMessageBox.warning(self, "Speichern", "Das Original wird nicht überschrieben.")
            return
        i = 2
        basis = ziel
        while ziel.exists():                       # nie stillschweigend überschreiben
            ziel = basis.with_name(f"{basis.stem}_{i}.pdf")
            i += 1
        pe.sicher_speichern(doc, ziel)
        if melden:
            self.status.setText(f"Gespeichert: {ziel}")

    # --- Suche ---
    def suchen(self):
        q = self.suche.text().strip()
        self.treffer = [(p.number, r) for p in self.sitzung.doc for r in p.search_for(q)] if q and self.sitzung else []
        self.treffer_i = -1
        self.status.setText(f"{len(self.treffer)} Treffer für „{q}“" if q else "")
        self.naechster_treffer()

    def naechster_treffer(self):
        if not self.treffer:
            self._anzeigen() if self.sitzung else None
            return
        self.treffer_i = (self.treffer_i + 1) % len(self.treffer)
        self.aktualisieren(self.treffer[self.treffer_i][0])

    # --- OCR ---
    def _ocr_seiten(self) -> list[int]:
        u = self.ocr_umfang.currentIndex()
        return [self.seite] if u == 0 else self._ausgewaehlt() if u == 1 else list(range(self.sitzung.doc.page_count))

    def ocr(self):
        if not self.sitzung:
            return
        if not pe.tesseract_ordner():
            QMessageBox.critical(self, "Texterkennung", "OCR-Komponente fehlt (Ordner „ocr“ neben BnX-Raptor.exe).")
            return
        self._ocr_seiten_ausfuehren(self._ocr_seiten())

    def _ocr_seiten_ausfuehren(self, seiten: list[int]):
        fehler, ergebnisse = [], {}
        for i, n in enumerate(seiten, 1):
            page = self.sitzung.doc[n]
            if page.get_text().strip():
                fehler.append(f"Seite {n + 1}: hat bereits Text – übersprungen")
                continue
            self.status.setText(f"Texterkennung Seite {n + 1} ({i}/{len(seiten)}) – "
                                f"{', '.join(pe.SPRACH_NAMEN.get(s, s) for s in self.sprachen)} …")
            png, rueck = pe.ocr_bild(page)
            self.setEnabled(False)
            try:
                tsv = im_thread(lambda: pe.ocr_erkennen(png, 300, self.sprachen))
            except Exception as e:  # noqa: BLE001
                fehler.append(f"Seite {n + 1}: Texterkennung fehlgeschlagen ({e})")
                continue
            finally:
                self.setEnabled(True)
            worte = pe.worte_bilden(tsv, rueck)
            if not worte:
                fehler.append(f"Seite {n + 1}: kein Text erkannt")
                continue
            ergebnisse[n] = worte
        if ergebnisse:
            self._ausfuehren(f"OCR ({len(ergebnisse)} Seite(n))",
                             lambda d: [pe.textebene_einfuegen(d[n], w) for n, w in ergebnisse.items()])
            self.ocr_worte.update(ergebnisse)
            for n, worte in ergebnisse.items():
                for w in worte:
                    if w.geschuetzt:
                        self._hinweis(f"S. {n + 1}: „{w.text}“ – geschütztes Feld, wird nicht automatisch "
                                      "geändert (bitte prüfen)", (n, w))
                    elif w.conf < 80:
                        self._hinweis(f"S. {n + 1}: „{w.text}“ – unsicher erkannt ({w.conf:.0f} %)", (n, w))
        for f in fehler:
            self._hinweis(f"⚠ {f}")
        self.status.setText(f"Texterkennung: {len(ergebnisse)} Seite(n) durchsuchbar"
                            + (f", {len(fehler)} Hinweis(e) – siehe rechts" if fehler else "")
                            + ". Schräglagenkorrektur ist noch nicht verfügbar.")
        self._anzeigen()

    def ausrichtung_pruefen(self):
        if not self.sitzung or not pe.tesseract_ordner():
            return
        vorschlag = {}
        for p in self.sitzung.doc:
            if not (pe.ist_gescannt(p) or p.get_images()):
                continue
            png = pe.ausrichtung_png(p)
            grad, sicher = im_thread(lambda: pe.ausrichtung_aus_png(png))
            if grad and sicher >= 2:
                vorschlag[p.number] = grad
        if not vorschlag:
            QMessageBox.information(self, "Ausrichtung", "Alle Scan-Seiten stehen richtig.")
            return
        liste = "\n".join(f"Seite {n + 1}: um {g}° drehen" for n, g in vorschlag.items())
        if QMessageBox.question(self, "Ausrichtung", f"Vorschlag:\n{liste}\n\nSo drehen?") == QMessageBox.Yes:
            self._ausfuehren("Ausrichtung korrigiert",
                             lambda d: [d[n].set_rotation((d[n].rotation + g) % 360) for n, g in vorschlag.items()])

    # --- Rückgängig / Speichern ---
    def rueckgaengig(self):
        if self.sitzung and self.sitzung.rueckgaengig():
            self.aktualisieren()

    def wiederholen(self):
        if self.sitzung and self.sitzung.wiederholen():
            self.aktualisieren()

    def _offene_schwaerzungen_ok(self) -> bool:
        return not self.offen or QMessageBox.question(
            self, "Speichern", f"{len(self.offen)} vorgemerkte Schwärzung(en) sind noch nicht angewendet und würden "
            "NICHT gespeichert. Trotzdem speichern?") == QMessageBox.Yes

    def _gespeichert_melden(self, erg, wohin: str):
        text = f"✓ Gespeichert: {wohin}"
        if erg is not None and getattr(erg, "pruefung", None):
            text += " · Schwärzung geprüft (Text, OCR-Ebene, Bilder, eingebettete Dateien, Rohdaten ✓)"
        theme.status_setzen(self.status, "ok", text)
        self._titel()

    def speichern(self) -> bool:
        """Strg+S: in dieselbe Datei (bzw. an den Aufrufer zurück). Bei Fehler bleibt alles offen."""
        s = self.sitzung
        if not s:
            return False
        if not self._offene_schwaerzungen_ok():
            return False
        if not s.kann_speichern and self.bei_speichern is None:
            return self.speichern_unter()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if s.kann_speichern:
                erg = s.speichern()
                self.gespeichert = erg.pfad
                wohin = str(erg.pfad)
            else:                                           # Anlage im Speicher → an den Aufrufer
                erg = None
                if s.schwaerzungen:                         # gleiche Sicherheit wie beim Speichern in eine Datei
                    import tempfile
                    with tempfile.TemporaryDirectory(prefix="bnx-uebernahme-") as td:
                        erg = s.speichern_unter(Path(td) / "geprueft.pdf")
                        daten = erg.pfad.read_bytes()
                    s.original, s._basis = None, ""         # bleibt eine Arbeitskopie im Speicher
                else:
                    daten = s.als_bytes()
                self.ergebnis_bytes = daten
                self.bei_speichern(daten)
                s.geaendert = False
                wohin = self.ziel_text or "übernommen"
        except Exception as e:  # noqa: BLE001 – Datei gesperrt, extern geändert, Prüfung fehlgeschlagen …
            QGuiApplication.restoreOverrideCursor()
            from core.pdf_sitzung import ExternGeaendert
            box = QMessageBox(QMessageBox.Warning, "Nicht gespeichert", f"{e}\n\nIhre Änderungen sind noch offen.",
                              parent=self)
            b_unter = box.addButton("Speichern unter…", QMessageBox.AcceptRole) if isinstance(e, (ExternGeaendert,
                                                                                                 pe.PdfFehler)) else None
            box.addButton("OK", QMessageBox.RejectRole)
            box.exec()
            if b_unter is not None and box.clickedButton() is b_unter:
                return self.speichern_unter()
            return False
        QGuiApplication.restoreOverrideCursor()
        self._gespeichert_melden(erg, wohin)
        return True

    def speichern_unter(self) -> bool:
        s = self.sitzung
        if not s or not self._offene_schwaerzungen_ok():
            return False
        name, _ = QFileDialog.getSaveFileName(self, "Speichern unter", str(s.vorschlag()), "PDF (*.pdf)")
        if not name:
            return False
        try:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                erg = s.speichern_unter(Path(name))
            finally:
                QGuiApplication.restoreOverrideCursor()
        except pe.PdfFehler as e:
            QMessageBox.critical(self, "Nicht gespeichert", f"{e}\n\nIhre Änderungen sind noch offen.")
            return False
        self.gespeichert = erg.pfad
        self._gespeichert_melden(erg, str(erg.pfad))
        return True

    def ok_speichern(self):
        """„OK – Änderungen speichern“: speichern und zurück. Scheitert das Speichern, bleibt der Editor offen."""
        if self.sitzung and self.sitzung.geaendert and not self.speichern():
            return
        self.accept()

    def uebernehmen(self):          # frühere Schnittstelle (Anlagen-Assistent)
        self.ok_speichern()

    def oeffnen_dialog(self):
        if not self._verwerfen_ok():
            return
        name, _ = QFileDialog.getOpenFileName(self, "PDF öffnen", "", "PDF (*.pdf)")
        if name:
            self.laden(Path(name))

    def _verwerfen_ok(self) -> bool:
        if not self.sitzung or not self.sitzung.geaendert:
            return True
        box = QMessageBox(QMessageBox.Warning, "Ungespeicherte Änderungen",
                          "Das Dokument wurde geändert und noch nicht gespeichert.", parent=self)
        b_sp = box.addButton("Speichern", QMessageBox.AcceptRole)
        b_unter = box.addButton("Speichern unter…", QMessageBox.ActionRole)
        b_weg = box.addButton("Verwerfen", QMessageBox.DestructiveRole)
        box.addButton("Abbrechen", QMessageBox.RejectRole)
        box.setDefaultButton(b_sp)
        box.exec()
        if box.clickedButton() is b_sp:
            return self.speichern()
        if box.clickedButton() is b_unter:
            return self.speichern_unter()
        return box.clickedButton() is b_weg

    def reject(self):
        if self._verwerfen_ok():
            super().reject()

    def closeEvent(self, e):
        if self._verwerfen_ok():
            e.accept()
        else:
            e.ignore()


def QIcon_leer():
    from PySide6.QtGui import QIcon
    return QIcon()


def pymupdf_qsize(w: int, h: int):
    from PySide6.QtCore import QSize
    return QSize(w, h)
