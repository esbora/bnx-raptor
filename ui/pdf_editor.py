"""„PDF bearbeiten“: Seiten, echter Textaustausch, OCR, Wortkorrektur im Scan, Schwärzen.

Arbeitet immer auf einer Kopie im Speicher (core.pdf_sitzung). Das Original wird nie überschrieben;
gespeichert wird über „Speichern unter…“ in eine neue Datei.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QToolBar, QVBoxLayout, QWidget)

from core import pdf_engine as pe
from core.pdf_sitzung import PdfSitzung

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
            g.setPen(QPen(farbe, 2))
            if gefuellt:
                f = QColor(farbe)
                f.setAlpha(70)
                g.fillRect(self._zu_bild(r), f)
            g.drawRect(self._zu_bild(r))
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
class _VorschauDialog(QDialog):
    """Gemeinsame Basis: Formular links, Vorschau der geänderten Seite rechts, Warnungen unten."""

    def __init__(self, parent, titel: str, sitzung: PdfSitzung, seite: int):
        super().__init__(parent)
        self.setWindowTitle(titel)
        self.resize(1050, 720)
        self.sitzung, self.seite = sitzung, seite
        self.geprueft = False
        haupt = QHBoxLayout(self)
        links = QVBoxLayout()
        self.form = QFormLayout()
        links.addLayout(self.form)
        self.hinweis = QLabel()
        self.hinweis.setWordWrap(True)
        links.addWidget(self.hinweis)
        links.addStretch(1)
        b_vor = QPushButton("&Vorschau aktualisieren")
        b_vor.clicked.connect(self.vorschau)
        links.addWidget(b_vor)
        bb = QDialogButtonBox()
        self.ok = bb.addButton("Ü&bernehmen", QDialogButtonBox.AcceptRole)
        bb.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._annehmen)
        bb.rejected.connect(self.reject)
        links.addWidget(bb)
        haupt.addLayout(links, 2)
        self.bild = QLabel("Vorschau …")
        self.bild.setAlignment(Qt.AlignCenter)
        sc = QScrollArea()
        sc.setWidget(self.bild)
        sc.setWidgetResizable(True)
        haupt.addWidget(sc, 3)
        self.ergebnis = None

    def aenderung(self, doc):        # in Unterklassen
        raise NotImplementedError

    def vorschau(self) -> bool:
        try:
            pix, erg = self.sitzung.vorschau(self.aenderung, self.seite, 620)
        except pe.PdfFehler as e:
            self.hinweis.setText(f"<span style='color:#b91c1c'>{e}</span>")
            self.geprueft = False
            return False
        self.bild.setPixmap(qpixmap(pix))
        w = getattr(erg, "warnungen", [])
        self.hinweis.setText(
            "<b style='color:#b45309'>Bitte prüfen:</b><br>" + "<br>".join(f"⚠ {x}" for x in w) if w
            else "<span style='color:#15803d'>✓ Keine Auffälligkeiten.</span>")
        if getattr(erg, "schrift", ""):
            self.hinweis.setText(self.hinweis.text() + f"<br>Schrift: {erg.schrift}")
        self.geprueft = True
        return True

    def _annehmen(self):
        # Erst übernehmen, wenn die Vorschau mit den aktuellen Eingaben gezeigt wurde
        if not self.geprueft:
            if self.vorschau():
                self.hinweis.setText(self.hinweis.text() + "<br><b>Vorschau aktualisiert – bitte erneut "
                                     "„Übernehmen“ klicken.</b>")
            return
        self.accept()

    def _geaendert(self, *_):
        self.geprueft = False


class TextDialog(_VorschauDialog):
    def __init__(self, parent, sitzung, seite: int, block: dict | None, punkt=None):
        super().__init__(parent, "Text bearbeiten" if block else "Text einfügen", sitzung, seite)
        self.block, self.punkt = block, punkt
        fmt = pe.block_format(block) if block else None
        self.text = QPlainTextEdit(fmt.text if fmt else "")
        self.groesse = QDoubleSpinBox()
        self.groesse.setRange(5, 72)
        self.groesse.setValue(fmt.groesse if fmt else 11)
        self.farbe = fmt.farbe if fmt else (0, 0, 0)
        self.b_farbe = QPushButton("Farbe …")
        self.b_farbe.clicked.connect(self._farbe)
        self.ausr = QComboBox()
        for k, v in AUSRICHTUNG_DE.items():
            self.ausr.addItem(v, k)
        self.ausr.setCurrentIndex(list(AUSRICHTUNG_DE).index(fmt.ausrichtung if fmt else "links"))
        self.form.addRow("Text:", self.text)
        self.form.addRow("Schriftgröße (pt):", self.groesse)
        self.form.addRow("Schriftfarbe:", self.b_farbe)
        self.form.addRow("Ausrichtung:", self.ausr)
        if fmt:
            self.form.addRow("Schrift:", QLabel(fmt.schrift + ("  (gemischte Formatierung!)" if fmt.gemischt else "")))
            if fmt.gemischt:
                self.form.addRow(QLabel("<b style='color:#b45309'>⚠ Der Absatz enthält mehrere Formatierungen. "
                                        "Nach dem Ändern wird er einheitlich gesetzt.</b>"))
        for w in (self.text.textChanged, self.groesse.valueChanged, self.ausr.currentIndexChanged):
            w.connect(self._geaendert)
        self.vorschau()

    def _farbe(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.farbe), self, "Schriftfarbe")
        if c.isValid():
            self.farbe = (c.redF(), c.greenF(), c.blueF())
            self._geaendert()

    def aenderung(self, doc):
        page = doc[self.seite]
        text = self.text.toPlainText()
        if self.block:
            b = pe.block_an(page, (self.block["bbox"][0] + 1, (self.block["bbox"][1] + self.block["bbox"][3]) / 2))
            return pe.block_ersetzen(page, b, text, self.groesse.value(), self.farbe, self.ausr.currentData())
        return pe.text_einfuegen(page, self.punkt, text, self.groesse.value(), self.farbe,
                                 ausrichtung=self.ausr.currentData())


class WortDialog(_VorschauDialog):
    def __init__(self, parent, sitzung, seite: int, wort: str, rect, ocr_info=None):
        super().__init__(parent, "Wort im Scan korrigieren", sitzung, seite)
        self.alt, self.rect = wort, rect
        self.neu = QLineEdit(wort)
        self.form.addRow("Erkannt:", QLabel(f"<b>{wort}</b>" + (f"  (Sicherheit {ocr_info.conf:.0f} %)"
                                                                 if ocr_info else "")))
        self.form.addRow("Korrigiert:", self.neu)
        if ocr_info and ocr_info.geschuetzt or any(m.search(wort) for m in pe.SCHUTZ_MUSTER[1:]):
            self.form.addRow(QLabel("<b style='color:#b91c1c'>Geschütztes Feld (Aktenzeichen/E-Mail/IBAN/Nr.): "
                                    "wird nie automatisch geändert – bitte Zeichen für Zeichen prüfen.</b>"))
        self.neu.textChanged.connect(self._geaendert)
        self.vorschau()

    def aenderung(self, doc):
        return pe.scan_wort_ersetzen(doc[self.seite], self.alt, self.neu.text().strip(), self.rect)


# ---------------------------------------------------------------- Hauptfenster
class PdfEditor(QDialog):
    """Eigenständig („PDF bearbeiten…“) oder aus Word→PDF / Anlagen-Assistent geöffnet.

    uebernehmen_text: wenn gesetzt, gibt es zusätzlich einen Knopf, der das Ergebnis an den Aufrufer
    zurückgibt (self.ergebnis_bytes), z. B. „In Anlage übernehmen“.
    """

    def __init__(self, parent=None, pfad: Path | None = None, daten: bytes | None = None, name: str = "",
                 uebernehmen_text: str = "", sprachen: tuple[str, ...] = pe.SPRACHEN):
        super().__init__(parent)
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
        else:
            self._titel()

    # --- Aufbau ---
    def _aufbau(self, uebernehmen_text: str):
        lay = QVBoxLayout(self)
        tb = QToolBar()
        lay.addWidget(tb)

        def act(text, fn, kurz=None, leiste=tb):
            a = QAction(text, self)
            a.triggered.connect(fn)
            if kurz:
                a.setShortcut(QKeySequence(kurz))
            leiste.addAction(a)
            return a
        act("Öffnen…", self.oeffnen_dialog, "Ctrl+O")
        self.a_speichern = act("Speichern unter…", self.speichern_unter, "Ctrl+Shift+S")
        if uebernehmen_text:
            self.a_uebernehmen = act(uebernehmen_text, self.uebernehmen, "Ctrl+Return")
        tb.addSeparator()
        self.a_undo = act("Rückgängig", self.rueckgaengig, "Ctrl+Z")
        self.a_redo = act("Wiederholen", self.wiederholen, "Ctrl+Y")
        tb.addSeparator()
        act("−", lambda: self.zoomen(1 / 1.2), "Ctrl+-")
        act("+", lambda: self.zoomen(1.2), "Ctrl++")
        tb.addSeparator()
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Suchen …")
        self.suche.setMaximumWidth(220)
        self.suche.returnPressed.connect(self.suchen)
        tb.addWidget(self.suche)
        act("Weiter", self.naechster_treffer, "F3")
        a_suche = QAction(self)
        a_suche.setShortcut(QKeySequence("Ctrl+F"))
        a_suche.triggered.connect(lambda: (self.suche.setFocus(), self.suche.selectAll()))
        self.addAction(a_suche)

        modus = QToolBar()
        lay.addWidget(modus)
        modus.addWidget(QLabel(" Werkzeug: "))
        self.modus_gruppe = QActionGroup(self)
        self.modus = "auswahl"
        for key, text in MODI:
            a = QAction(text, self)
            a.setCheckable(True)
            a.setChecked(key == "auswahl")
            a.triggered.connect(lambda _=False, k=key: self._modus_setzen(k))
            self.modus_gruppe.addAction(a)
            modus.addAction(a)

        seiten = QToolBar()
        lay.addWidget(seiten)
        seiten.addWidget(QLabel(" Seiten: "))
        act("↺ Links drehen", lambda: self.drehen(-90), leiste=seiten)
        act("↻ Rechts drehen", lambda: self.drehen(90), leiste=seiten)
        act("Löschen", self.seiten_loeschen, leiste=seiten)
        act("Duplizieren", self.duplizieren, leiste=seiten)
        act("PDF/Bild einfügen…", self.einfuegen_datei, leiste=seiten)
        act("Auswahl als PDF…", self.auswahl_speichern, leiste=seiten)
        act("Aufteilen…", self.aufteilen, leiste=seiten)
        seiten.addSeparator()
        seiten.addWidget(QLabel(" Texterkennung: "))
        self.ocr_umfang = QComboBox()
        self.ocr_umfang.addItems(["Diese Seite", "Ausgewählte Seiten", "Alle Seiten"])
        seiten.addWidget(self.ocr_umfang)
        act("OCR starten", self.ocr, leiste=seiten)
        act("Ausrichtung prüfen", self.ausrichtung_pruefen, leiste=seiten)
        hinweis = QLabel("  Schräglagenkorrektur: noch nicht verfügbar")
        hinweis.setStyleSheet("color:#6b7280")
        seiten.addWidget(hinweis)

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
        rl.addWidget(QLabel("<b>Hinweise / zu prüfen</b>"))
        self.hinweise = QListWidget()
        self.hinweise.itemActivated.connect(self._hinweis_gewaehlt)
        self.hinweise.itemClicked.connect(self._hinweis_gewaehlt)
        rl.addWidget(self.hinweise, 1)
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
        split.addWidget(rechts)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
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
        self.b_schwaerzen.setText(f"Schwärzungen &anwenden ({len(self.offen)})")
        self._titel()

    def _anzeigen(self):
        s = self.sitzung
        page = s.doc[self.seite]
        self.ansicht.zeigen(page, self.zoom)
        m = [(r, QColor("#dc2626"), True) for n, r in self.offen if n == self.seite]
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
            if not b:
                gescannt = bool(page.get_images()) and not any(pe.textbloecke(page))
                self.status.setText("Kein digitaler Text an dieser Stelle."
                                    + (" Für Scans: „Wort korrigieren (Scan)“ nach OCR." if gescannt else ""))
                return
            if self._unsichtbar(b):
                self.status.setText("Das ist OCR-Text eines Scans – bitte „Wort korrigieren (Scan)“ verwenden.")
                return
            d = TextDialog(self, self.sitzung, self.seite, b)
            if d.exec() == QDialog.Accepted:
                self._ausfuehren("Text geändert", d.aenderung)
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
            self.b_schwaerzen.setText(f"Schwärzungen &anwenden ({len(self.offen)})")
            self._anzeigen()
        elif self.modus == "zuschnitt":
            if QMessageBox.question(self, "Zuschneiden", "Seite auf den markierten Bereich zuschneiden?") \
                    == QMessageBox.Yes:
                self._ausfuehren("Zugeschnitten", lambda d: pe.seite_zuschneiden(d[self.seite], r))

    # --- Schwärzen ---
    def treffer_vormerken(self):
        self.offen += [(n, r + (-1, -1, 1, 1)) for n, r in self.treffer]
        self.b_schwaerzen.setText(f"Schwärzungen &anwenden ({len(self.offen)})")
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
        seiten, fehler, ergebnisse = self._ocr_seiten(), [], {}
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

    def speichern_unter(self) -> bool:
        s = self.sitzung
        if not s:
            return False
        if self.offen and QMessageBox.question(
                self, "Speichern", f"{len(self.offen)} vorgemerkte Schwärzung(en) sind noch nicht angewendet "
                "und würden NICHT gespeichert. Trotzdem speichern?") != QMessageBox.Yes:
            return False
        zusammenfassung = "\n".join(f"• {p}" for p in s.protokoll) or "• keine Änderungen"
        warn = "\n".join(f"⚠ {w}" for w in s.warnungen)
        text = f"Änderungen:\n{zusammenfassung}"
        if warn:
            text += f"\n\nBitte prüfen:\n{warn}"
        if s.schwaerzungen:
            text += ("\n\nSchwärzung: eingebettete Dateien, Metadaten und Vorschaubilder werden entfernt; "
                     "die gespeicherte Datei wird danach automatisch geprüft.")
        if s.signaturen:
            text += "\n\n⚠ Die digitale Signatur des Originals gilt für die Kopie nicht mehr."
        if QMessageBox.question(self, "Vor dem Speichern", text + "\n\nWeiter zu „Speichern unter…“?") \
                != QMessageBox.Yes:
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
            QMessageBox.critical(self, "Speichern", str(e))
            return False
        self.gespeichert = erg.pfad
        meldung = f"Gespeichert: {erg.pfad}"
        if erg.pruefung:
            meldung += ("\n\nSchwärzung geprüft (Datei neu geöffnet): Text ✓, OCR-Ebene ✓, Bilder ✓, "
                        "eingebettete Dateien ✓, Rohdaten ✓")
            if erg.entfernt:
                meldung += "\nEntfernt: " + ", ".join(erg.entfernt)
        QMessageBox.information(self, "Gespeichert", meldung)
        self._titel()
        return True

    def uebernehmen(self):
        if self.offen and QMessageBox.question(
                self, "Übernehmen", "Vorgemerkte Schwärzungen sind noch nicht angewendet. Trotzdem übernehmen?") \
                != QMessageBox.Yes:
            return
        if self.sitzung.schwaerzungen:
            # gleiche Sicherheit wie beim Speichern: bereinigen, speichern, neu öffnen und prüfen
            import tempfile
            with tempfile.TemporaryDirectory(prefix="bnx-uebernahme-") as td:
                try:
                    erg = self.sitzung.speichern_unter(Path(td) / "geprueft.pdf")
                except pe.PdfFehler as e:
                    QMessageBox.critical(self, "Übernehmen", str(e))
                    return
                self.ergebnis_bytes = erg.pfad.read_bytes()
            QMessageBox.information(self, "Schwärzung geprüft",
                                    "Schwärzung geprüft (neu geöffnet): Text ✓, OCR-Ebene ✓, Bilder ✓, "
                                    "eingebettete Dateien ✓, Rohdaten ✓"
                                    + (f"\nEntfernt: {', '.join(erg.entfernt)}" if erg.entfernt else ""))
        else:
            self.ergebnis_bytes = self.sitzung.als_bytes()
        self.sitzung.geaendert = False
        self.accept()

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
        b_sp = box.addButton("Speichern unter…", QMessageBox.AcceptRole)
        b_weg = box.addButton("Verwerfen", QMessageBox.DestructiveRole)
        box.addButton("Abbrechen", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_sp:
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


def pymupdf_qsize(w: int, h: int):
    from PySide6.QtCore import QSize
    return QSize(w, h)
