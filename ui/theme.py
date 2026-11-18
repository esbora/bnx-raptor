"""Gemeinsames Erscheinungsbild von BnX-Raptor: Farben, Schrift, Knopfstile, Statusfarben und Symbole.

Einzige Stelle für das Design (0.4.0): warmer, heller Grund, weiße Karten, dunkles Marineblau für Überschriften,
kräftiges Blau für Hauptaktionen, Pfirsich für Auswahl und kleine Akzente. 0.4.1: IMMER hell – auch wenn
Windows auf „Dunkel“ steht (Wunsch der Kanzlei). Knöpfe rund und lebendig (Verlauf, Hover, Druckzustand).
Status wird nie nur über Farbe gezeigt, sondern immer mit Symbol und kurzem Text.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsDropShadowEffect, QLabel, QWidget

HELL = {
    "grund": "#FBF7F2", "karte": "#FFFFFF", "leiste": "#FFFDFA", "rand": "#ECE4DA", "rand_stark": "#D9CEC1",
    "titel": "#16264A", "text": "#283040", "gedimmt": "#6B7280", "eingabe": "#FFFFFF",
    "primaer": "#1F6FEB", "primaer_hover": "#185BC4", "primaer_text": "#FFFFFF",
    "pfirsich": "#FFE3D1", "pfirsich_stark": "#F28C5B", "pfirsich_text": "#7A3414",
    "auswahl": "#FFE9DB", "auswahl_text": "#16264A",
    "ok": "#157F3B", "ok_grund": "#E7F5EC", "warn": "#9A5B00", "warn_grund": "#FFF3D6",
    "fehler": "#B42318", "fehler_grund": "#FDECEA", "schatten": "#3A2A1A",
}
F: dict[str, str] = dict(HELL)            # aktuelle Farben (nach anwenden())

SCHRIFT = "Segoe UI"
STATUS = {  # Art → (Symbol, Farbe, Grundfarbe, Kurztext)
    "ok": ("✓", "ok", "ok_grund", "Erledigt"),
    "warn": ("⚠", "warn", "warn_grund", "Bitte prüfen"),
    "fehler": ("✖", "fehler", "fehler_grund", "Gestoppt"),
    "info": ("ℹ", "gedimmt", "karte", ""),
}


def dunkel() -> bool:
    """Bewusst immer False: BnX-Raptor wird nie dunkel dargestellt."""
    return False


def farbe(name: str) -> QColor:
    return QColor(F[name])


def qss(f: dict[str, str]) -> str:
    return f"""
* {{ font-family: "{SCHRIFT}"; }}
QWidget {{ color: {f['text']}; }}
QMainWindow, QDialog, QWidget#seite, QStackedWidget, QTabWidget::pane {{ background: {f['grund']}; }}
QTabWidget::pane {{ border: none; }}
QWidget#seitenleiste {{ background: {f['leiste']}; border-right: 1px solid {f['rand']}; }}
QLabel#marke {{ color: {f['titel']}; font-size: 15pt; font-weight: 700; }}
QLabel#marke_klein {{ color: {f['gedimmt']}; font-size: 8.5pt; }}
QListWidget#navigation {{ background: transparent; border: none; outline: 0; font-size: 10.5pt; }}
QListWidget#navigation::item {{ padding: 9px 12px; margin: 2px 8px; border-radius: 10px; color: {f['text']}; }}
QListWidget#navigation::item:hover {{ background: {f['grund']}; }}
QListWidget#navigation::item:selected {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {f['pfirsich']},
    stop:1 #FFF1E8); color: {f['pfirsich_text']}; font-weight: 600; border-left: 4px solid {f['pfirsich_stark']}; }}
QListWidget#navigation:focus {{ outline: 0; }}
QFrame[karte="true"] {{ background: {f['karte']}; border: 1px solid {f['rand']}; border-radius: 16px; }}
QFrame[karte="true"]:hover[klickbar="true"] {{ border: 1px solid {f['pfirsich_stark']}; }}
QLabel[rolle="h1"] {{ color: {f['titel']}; font-size: 18pt; font-weight: 700; }}
QLabel[rolle="h2"] {{ color: {f['titel']}; font-size: 13pt; font-weight: 600; }}
QLabel[rolle="h3"] {{ color: {f['titel']}; font-size: 11pt; font-weight: 600; }}
QLabel[rolle="gedimmt"] {{ color: {f['gedimmt']}; }}
QLabel[rolle="akzent"] {{ color: {f['pfirsich_text']}; background: {f['pfirsich']}; border-radius: 9px;
                          padding: 2px 9px; font-size: 8.5pt; font-weight: 600; }}
QLabel[status="ok"] {{ color: {f['ok']}; background: {f['ok_grund']}; border-radius: 8px; padding: 6px 10px; }}
QLabel[status="warn"] {{ color: {f['warn']}; background: {f['warn_grund']}; border-radius: 8px; padding: 6px 10px; }}
QLabel[status="fehler"] {{ color: {f['fehler']}; background: {f['fehler_grund']}; border-radius: 8px; padding: 6px 10px; }}
QLabel[status="info"] {{ color: {f['gedimmt']}; padding: 6px 2px; }}
QPushButton {{ background: {f['karte']}; color: {f['titel']}; border: 1.5px solid {f['rand_stark']}; border-radius: 16px;
              padding: 6px 13px; min-height: 20px; }}
QPushButton:hover {{ border-color: {f['pfirsich_stark']}; background: #FFF4EC; color: {f['pfirsich_text']}; }}
QPushButton:pressed {{ background: {f['pfirsich']}; border-color: {f['pfirsich_stark']}; }}
QPushButton:focus {{ border: 2px solid {f['primaer']}; }}
QPushButton:disabled {{ color: #A8AEB8; background: {f['grund']}; border-color: {f['rand']}; }}
QPushButton[rolle="primaer"] {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3D8BFF, stop:1 #1A5FE0);
    color: #FFFFFF; border: none; font-weight: 700; padding: 8px 20px; border-radius: 18px; }}
QPushButton[rolle="primaer"]:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5AA0FF, stop:1 #2A6FF0); }}
QPushButton[rolle="primaer"]:pressed {{ background: #164FC0; }}
QPushButton[rolle="primaer"]:focus {{ border: 2px solid {f['pfirsich_stark']}; }}
QPushButton[rolle="primaer"]:disabled {{ background: {f['rand']}; color: {f['gedimmt']}; border: none; }}
QPushButton[rolle="gefahr"] {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #E5483A, stop:1 #B42318);
    color: #FFFFFF; border: none; font-weight: 700; }}
QPushButton[rolle="gefahr"]:disabled {{ background: {f['rand']}; color: {f['gedimmt']}; border-color: {f['rand']}; }}
QPushButton[rolle="link"] {{ background: transparent; border: none; color: {f['primaer']}; padding: 4px 6px; text-align: left; }}
QPushButton[rolle="link"]:hover {{ text-decoration: underline; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDoubleSpinBox {{
    background: {f['eingabe']}; border: 1px solid {f['rand_stark']}; border-radius: 8px; padding: 5px 8px;
    selection-background-color: {f['primaer']}; selection-color: {f['primaer_text']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus {{ border: 2px solid {f['primaer']}; }}
QListWidget, QTreeWidget, QTableWidget {{ background: {f['karte']}; border: 1px solid {f['rand']}; border-radius: 12px;
    alternate-background-color: {f['grund']}; outline: 0; }}
QListWidget::item, QTreeWidget::item {{ padding: 4px 4px; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
    background: {f['auswahl']}; color: {f['auswahl_text']}; }}
QTreeWidget::item:focus, QListWidget::item:focus {{ border: 1px solid {f['pfirsich_stark']}; }}
QHeaderView::section {{ background: {f['grund']}; color: {f['gedimmt']}; border: none; border-bottom: 1px solid {f['rand']};
    padding: 6px 6px; font-weight: 600; }}
QMenuBar {{ background: {f['leiste']}; border-bottom: 1px solid {f['rand']}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {f['pfirsich']}; border-radius: 6px; }}
QMenu {{ background: {f['karte']}; border: 1px solid {f['rand']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {f['pfirsich']}; color: {f['pfirsich_text']}; }}
QToolBar {{ background: {f['karte']}; border: none; border-bottom: 1px solid {f['rand']}; spacing: 4px; padding: 4px 8px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 12px; padding: 5px 9px; color: {f['titel']}; }}
QToolButton:hover {{ background: #FFF4EC; border-color: {f['pfirsich_stark']}; }}
QToolButton:pressed {{ background: {f['pfirsich']}; }}
QToolButton:checked {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFE9DB, stop:1 {f['pfirsich']});
    color: {f['pfirsich_text']}; border: 1.5px solid {f['pfirsich_stark']}; }}
QToolButton:focus {{ border: 2px solid {f['primaer']}; }}
QToolButton[gruppe="haupt"] {{ font-weight: 600; min-width: 74px; }}
QCheckBox {{ spacing: 8px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 18px; }}
QToolButton::menu-button {{ border: none; width: 14px; }}
QSplitter::handle {{ background: {f['grund']}; }}
QScrollArea {{ border: none; background: {f['grund']}; }}
QWidget#karteninhalt {{ background: {f['karte']}; }}
QScrollArea > QWidget > QWidget {{ background: {f['grund']}; }}
QToolTip {{ background: {f['titel']}; color: {f['karte']}; border: none; padding: 5px; }}
"""


def anwenden(app: QApplication) -> None:
    """Design einmal beim Start setzen (nach QApplication, vor dem ersten Fenster)."""
    F.clear()
    F.update(HELL)                               # immer hell
    try:                                         # Qt ≥ 6.8: auch Titelleisten/Systemdialoge hell
        QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except Exception:  # noqa: BLE001
        pass
    app.setStyle("Fusion")
    schrift = QFont(SCHRIFT, 10)
    schrift.setHintingPreference(QFont.PreferFullHinting)
    app.setFont(schrift)
    p = QPalette()
    for rolle, name in ((QPalette.Window, "grund"), (QPalette.Base, "karte"), (QPalette.AlternateBase, "grund"),
                        (QPalette.WindowText, "text"), (QPalette.Text, "text"), (QPalette.Button, "karte"),
                        (QPalette.ButtonText, "text"), (QPalette.Highlight, "primaer"),
                        (QPalette.HighlightedText, "primaer_text"), (QPalette.ToolTipBase, "titel"),
                        (QPalette.ToolTipText, "karte"), (QPalette.PlaceholderText, "gedimmt"),
                        (QPalette.Link, "primaer")):
        p.setColor(rolle, QColor(F[name]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(F["gedimmt"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(F["gedimmt"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(F["gedimmt"]))
    app.setPalette(p)
    app.setStyleSheet(qss(F))


def rolle(w: QWidget, wert: str, eigenschaft: str = "rolle") -> QWidget:
    w.setProperty(eigenschaft, wert)
    w.style().unpolish(w)
    w.style().polish(w)
    return w


def karte(w: QFrame, schatten: bool = True, klickbar: bool = False) -> QFrame:
    w.setProperty("karte", True)
    w.setProperty("klickbar", klickbar)
    if schatten:
        s = QGraphicsDropShadowEffect(w)
        s.setBlurRadius(28)
        s.setOffset(0, 4)
        c = QColor(F["schatten"])
        c.setAlpha(28 if not dunkel() else 90)
        s.setColor(c)
        w.setGraphicsEffect(s)
    return w


def ueberschrift(text: str, stufe: str = "h2") -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("rolle", stufe)
    lbl.setWordWrap(True)
    return lbl


def status_text(art: str, text: str) -> str:
    """„✓ Erledigt: …“ – Symbol + Kurztext + Meldung (Farbe kommt zusätzlich über status_setzen)."""
    sym, _, _, kurz = STATUS.get(art, STATUS["info"])
    return f"{sym} {kurz}: {text}" if kurz and text else f"{sym} {kurz or text}"


def status_setzen(lbl: QLabel, art: str | None, text: str) -> None:
    """Status-Zeile: Farbe + Symbol + Kurztext. art=None → neutral (nur Text)."""
    if not text:
        lbl.setText("")
        rolle(lbl, "", "status")
        return
    lbl.setText(status_text(art, text) if art in ("ok", "warn", "fehler") else text)
    rolle(lbl, art or "info", "status")


def status_farbe(art: str) -> QColor:
    return QColor(F[STATUS.get(art, STATUS["info"])[1]])


# --------------------------------------------------------------------------- Symbole (eigene, einfache Linien)
_SVG = {
    "start": '<path d="M4 11.5 12 5l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z"/>',
    "anlagen": '<path d="M16.5 7.5 9.4 14.6a2.1 2.1 0 0 0 3 3l7.4-7.4a4.2 4.2 0 0 0-6-6L6.4 11.6a6.3 6.3 0 0 0 8.9 8.9l5.2-5.2"/>',
    "pdf": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M8.5 13h7M8.5 16.5h5"/>',
    "akten": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "einstellungen": '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.8v2.6M12 18.6v2.6M4.2 7.5l2.3 1.3M17.5 15.2l2.3 1.3M4.2 16.5l2.3-1.3M17.5 8.8l2.3-1.3"/><circle cx="12" cy="12" r="7.2"/>',
    "seiten": '<rect x="4" y="6" width="11" height="14" rx="1.5"/><path d="M9 3h9.5A1.5 1.5 0 0 1 20 4.5V16"/>',
    "text": '<path d="M5 6V4.5h14V6M12 4.5V19M9 19h6"/>',
    "ocr": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M8 9.5h8M8 12.5h8M8 15.5h5"/>',
    "schwaerzen": '<rect x="4" y="9" width="16" height="6" rx="1" fill="CURRENT"/><path d="M4 5.5h16M4 18.5h11"/>',
    "auswahl": '<path d="M6 3.5 18 12l-5.2 1.2L16 19.5l-2.4 1.1-3.2-6.3L6 18z"/>',
    "einfuegen": '<path d="M5 6V4.5h9V6M9.5 4.5V15"/><path d="M17 13v8M13 17h8"/>',
    "wort": '<path d="M4 18h8M14.5 5.5l4 4L10 18H6v-4z"/>',
    "zuschnitt": '<path d="M7 3v14h14M3 7h14v14"/>',
    "oeffnen": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H7.5L5 19H5a2 2 0 0 1-2-2z"/><path d="M7.5 10H22l-3 9H5z"/>',
    "speichern": '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z"/><path d="M8 3v5h7V3M8 21v-6h8v6"/>',
    "rueckgaengig": '<path d="M9 7 4.5 11.5 9 16"/><path d="M5 11.5h9a5 5 0 0 1 0 10h-2"/>',
    "wiederholen": '<path d="m15 7 4.5 4.5L15 16"/><path d="M19 11.5h-9a5 5 0 0 0 0 10h2"/>',
    "uebernehmen": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "paket": '<path d="M12 3 4 7v10l8 4 8-4V7z"/><path d="m4 7 8 4 8-4M12 11v10"/>',
    "brief": '<path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M14 3v5h5M8.5 12h7M8.5 15h7M8.5 18h4"/>',
    "lupe": '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5.5 5.5"/>',
    "drehen": '<path d="M19 12a7 7 0 1 1-2.1-5"/><path d="M19 4v4.5h-4.5"/>',
    "ordner": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "verlauf": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "adressbuch": '<rect x="5" y="3" width="14" height="18" rx="2"/><circle cx="12" cy="10" r="2.6"/><path d="M8 17c.8-2 2.2-3 4-3s3.2 1 4 3"/>',
    "kanzlei": '<path d="M3 10 12 4l9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20.5h18"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.4"/>',
}


def icon(name: str, farbe_name: str = "titel", groesse: int = 24, farbe_hex: str | None = None) -> QIcon:
    from PySide6.QtSvg import QSvgRenderer
    col = farbe_hex or F.get(farbe_name, farbe_name)
    inhalt = _SVG[name].replace("CURRENT", col)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{col}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{inhalt}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    ic = QIcon()
    for faktor in (1, 1.25, 1.5, 2):
        px = QPixmap(QSize(int(groesse * faktor), int(groesse * faktor)))
        px.fill(Qt.transparent)
        g = QPainter(px)
        g.setRenderHint(QPainter.Antialiasing)
        r.render(g, QRectF(0, 0, px.width(), px.height()))
        g.end()
        px.setDevicePixelRatio(faktor)
        ic.addPixmap(px)
    return ic


class Marke(QWidget):
    """Bildmarke: abgerundetes Quadrat (Blau) mit Akte und Pfirsich-Akzent."""

    def __init__(self, groesse: int = 34):
        super().__init__()
        self.setFixedSize(groesse, groesse)

    def paintEvent(self, _):
        g = QPainter(self)
        g.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        g.setPen(Qt.NoPen)
        g.setBrush(QColor(F["primaer"]))
        g.drawRoundedRect(QRectF(0, 0, s, s), s * 0.28, s * 0.28)
        g.setBrush(QColor("#FFFFFF"))
        g.drawRoundedRect(QRectF(s * 0.27, s * 0.2, s * 0.46, s * 0.6), s * 0.06, s * 0.06)
        g.setBrush(QColor(F["pfirsich_stark"]))
        g.drawRoundedRect(QRectF(s * 0.52, s * 0.52, s * 0.34, s * 0.34), s * 0.1, s * 0.1)
        g.setPen(QColor(F["primaer"]))
        for i in range(3):
            y = s * (0.33 + i * 0.1)
            g.drawLine(int(s * 0.34), int(y), int(s * 0.62), int(y))


class SchriftsatzGrafik(QWidget):
    """Schlichte Zeichnung für die Startseite: Schriftsatz mit nummerierten Anlagen (K1–K3)."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(250, 170)

    def paintEvent(self, _):
        g = QPainter(self)
        g.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        s = min(w / 300, h / 200)
        ox, oy = (w - 300 * s) / 2, (h - 200 * s) / 2

        def R(x, y, bw, bh):
            return QRectF(ox + x * s, oy + y * s, bw * s, bh * s)
        g.setPen(Qt.NoPen)
        g.setBrush(QColor(F["pfirsich"]))
        g.drawEllipse(R(40, 10, 230, 190))
        farben = [F["primaer"], F["pfirsich_stark"], "#16264A"]
        for i, (txt, c) in enumerate(zip(("K1", "K2", "K3"), farben)):
            x, y = 150 + i * 22, 38 + i * 24
            g.setBrush(QColor(F["karte"]))
            g.setPen(QColor(F["rand_stark"]))
            g.drawRoundedRect(R(x, y, 92, 118), 8 * s, 8 * s)
            g.setPen(Qt.NoPen)
            g.setBrush(QColor(c))
            g.drawRoundedRect(R(x + 52, y + 10, 32, 18), 6 * s, 6 * s)
            g.setPen(QColor("#FFFFFF"))
            f = g.font()
            f.setPixelSize(max(8, int(11 * s)))
            f.setBold(True)
            g.setFont(f)
            g.drawText(R(x + 52, y + 10, 32, 18), Qt.AlignCenter, txt)
            g.setPen(QColor(F["rand_stark"]))
            for j in range(4):
                g.drawLine(int(ox + (x + 12) * s), int(oy + (y + 44 + j * 14) * s), int(ox + (x + 76) * s), int(oy + (y + 44 + j * 14) * s))
        g.setBrush(QColor(F["karte"]))
        g.setPen(QColor(F["titel"]))
        g.drawRoundedRect(R(62, 24, 110, 150), 10 * s, 10 * s)
        g.setPen(Qt.NoPen)
        g.setBrush(QColor(F["titel"]))
        g.drawRoundedRect(R(76, 40, 60, 9), 3 * s, 3 * s)
        g.setBrush(QColor(F["rand_stark"]))
        for j in range(6):
            g.drawRoundedRect(R(76, 60 + j * 14, 82 - (j % 3) * 12, 5), 2 * s, 2 * s)
        g.setBrush(QColor(F["primaer"]))
        g.drawEllipse(R(140, 146, 22, 22))
        g.setPen(QColor("#FFFFFF"))
        g.drawLine(int(ox + 145 * s), int(oy + 157 * s), int(ox + 150 * s), int(oy + 162 * s))
        g.drawLine(int(ox + 150 * s), int(oy + 162 * s), int(ox + 158 * s), int(oy + 151 * s))
