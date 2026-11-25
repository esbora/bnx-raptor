"""„Nachrichten“ (0.4.2): Büro-interne Eins-zu-eins-Nachrichten im Mehrbenutzerbetrieb.

Links Kontakte/Gespräche (Name, Rolle, ungelesen), rechts das Gespräch. Enter sendet, Umschalt+Enter neue Zeile.
Status je eigener Nachricht: „Wird gesendet“ → „Gesendet“ → „Gelesen“, bei fehlender Verbindung „Nicht gesendet“
(Text bleibt erhalten, wird mit derselben Kennung erneut gesendet – keine Doppelung).
"""
from __future__ import annotations

import html
import uuid
from datetime import datetime

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter,
                               QTextBrowser, QVBoxLayout, QWidget)

from core import netz

from . import theme

OFFLINE = (netz.VerbindungFehler, netz.WartungFehler, netz.SitzungFehler)


def _zeit(t: str) -> str:
    try:
        d = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return t or ""
    return d.strftime("%H:%M") if d.date() == datetime.now().date() else d.strftime("%d.%m.%Y %H:%M")


class _Eingabe(QPlainTextEdit):
    senden = Signal()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.senden.emit()
            return
        super().keyPressEvent(e)


class NachrichtenTab(QWidget):
    """Nachrichtenseite. `oeffnen_akte(ref)` / `oeffnen_mandant(id)` kommen vom Hauptfenster."""
    ungelesen_geaendert = Signal(int)

    def __init__(self, ctx, oeffnen_akte, oeffnen_mandant, oeffnen_aufgabe=None):
        super().__init__()
        self.ctx, self.oeffnen_akte, self.oeffnen_mandant = ctx, oeffnen_akte, oeffnen_mandant
        self.oeffnen_aufgabe = oeffnen_aufgabe            # 0.5: Nachricht verweist auf eine Aufgabe
        self.partner: str | None = None
        self.ausstehend: dict[str, list[dict]] = {}          # Partner → noch nicht gesendete Nachrichten
        self.verlauf_cache: list[dict] = []
        split = QSplitter()
        links = theme.karte(QFrame(), schatten=False)
        ll = QVBoxLayout(links)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.addWidget(theme.ueberschrift("Kolleginnen und Kollegen", "h3"))
        self.kontakte = QListWidget()
        self.kontakte.setAccessibleName("Gespräche")
        self.kontakte.currentItemChanged.connect(lambda *_: self._kontakt_gewaehlt())
        ll.addWidget(self.kontakte, 1)
        split.addWidget(links)
        rechts = theme.karte(QFrame(), schatten=False)
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(16, 12, 16, 12)
        self.titel = theme.ueberschrift("Gespräch wählen", "h2")
        rl.addWidget(self.titel)
        self.verlauf = QTextBrowser()
        self.verlauf.setOpenLinks(False)
        self.verlauf.anchorClicked.connect(self._link)
        self.verlauf.setAccessibleName("Nachrichtenverlauf")
        rl.addWidget(self.verlauf, 1)
        self.eingabe = _Eingabe()
        self.eingabe.setPlaceholderText("Nachricht schreiben … (Enter = senden, Umschalt+Enter = neue Zeile)")
        self.eingabe.setFixedHeight(70)
        self.eingabe.setAccessibleName("Nachricht")
        self.eingabe.senden.connect(self.senden)
        rl.addWidget(self.eingabe)
        unten = QHBoxLayout()
        self.l_status = theme.rolle(QLabel(""), "gedimmt")
        unten.addWidget(self.l_status, 1)
        self.b_erneut = QPushButton("Erneut senden")
        self.b_erneut.clicked.connect(self.ausstehende_senden)
        self.b_erneut.hide()
        unten.addWidget(self.b_erneut)
        self.b_senden = QPushButton("Senden")
        theme.rolle(self.b_senden, "primaer")
        self.b_senden.clicked.connect(self.senden)
        unten.addWidget(self.b_senden)
        rl.addLayout(unten)
        split.addWidget(rechts)
        split.setSizes([300, 700])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split, 1)
        self._aktiv(False)

    # --- Daten ----------------------------------------------------------------------
    @property
    def n(self):
        return self.ctx.nachrichten

    def _aktiv(self, an: bool):
        for w in (self.eingabe, self.b_senden):
            w.setEnabled(an)

    def laden(self):
        try:
            kontakte = self.n.kontakte()
        except OFFLINE:
            return
        wahl = self.partner
        self.kontakte.blockSignals(True)
        self.kontakte.clear()
        for k in kontakte:
            text = f"{k['anzeigename']}  ({k['rolle_text']})"
            if k["ungelesen"]:
                text += f"   ● {k['ungelesen']}"
            if not k["aktiv"]:
                text += "  – deaktiviert"
            it = QListWidgetItem(theme.icon("start", "titel"), text)
            it.setData(Qt.UserRole, k)
            it.setToolTip(k["letzter_text"] or "Noch keine Nachrichten")
            if k["ungelesen"]:
                f = it.font(); f.setBold(True); it.setFont(f)
            self.kontakte.addItem(it)
            if k["name"] == wahl:
                self.kontakte.setCurrentItem(it)
        self.kontakte.blockSignals(False)
        self.ungelesen_geaendert.emit(sum(k["ungelesen"] for k in kontakte))
        if self.partner:
            self._verlauf_laden()

    def gespraech_oeffnen(self, partner: str):
        for i in range(self.kontakte.count()):
            if self.kontakte.item(i).data(Qt.UserRole)["name"].lower() == (partner or "").lower():
                self.kontakte.setCurrentRow(i)
                return

    def _kontakt_gewaehlt(self):
        it = self.kontakte.currentItem()
        if it is None:
            return
        k = it.data(Qt.UserRole)
        self.partner = k["name"]
        self.titel.setText(f"{k['anzeigename']} · {k['rolle_text']}")
        self._aktiv(k["aktiv"])
        self._verlauf_laden()
        self.eingabe.setFocus()

    def sichtbar(self) -> bool:
        w = self.window()
        return self.isVisible() and w is not None and w.isActiveWindow() and not w.isMinimized()

    def _verlauf_laden(self):
        if not self.partner:
            return
        try:
            self.verlauf_cache = self.n.verlauf(self.partner)
        except OFFLINE:
            pass
        self._zeichnen()
        eingang = [m for m in self.verlauf_cache if not m["von_mir"] and not m["gelesen"]]
        if eingang and self.sichtbar():                      # „Gelesen“ nur, wenn wirklich angezeigt
            try:
                self.n.gelesen(self.partner, max(m["id"] for m in eingang))
                for m in eingang:
                    m["gelesen"] = "jetzt"
                QTimer.singleShot(0, self._kontakte_still)
            except OFFLINE:
                pass

    def _kontakte_still(self):
        try:
            kontakte = self.n.kontakte()
        except OFFLINE:
            return
        for i in range(self.kontakte.count()):
            it = self.kontakte.item(i)
            k = next((x for x in kontakte if x["name"] == it.data(Qt.UserRole)["name"]), None)
            if k:
                text = f"{k['anzeigename']}  ({k['rolle_text']})" + (f"   ● {k['ungelesen']}" if k["ungelesen"] else "")
                it.setText(text)
                f = it.font(); f.setBold(bool(k["ungelesen"])); it.setFont(f)
        self.ungelesen_geaendert.emit(sum(k["ungelesen"] for k in kontakte))

    def _zeichnen(self):
        teile = []
        nachrichten = list(self.verlauf_cache) + [dict(a, von_mir=True) for a in self.ausstehend.get(self.partner, [])]
        for m in nachrichten:
            if m.get("status"):
                status = m["status"]
            elif m["von_mir"]:
                status = "Gelesen" if m.get("gelesen") else "Gesendet"
            else:
                status = ""
            farbe = theme.F["primaer"] if m["von_mir"] else theme.F["titel"]
            links = ""
            if m.get("akte"):
                links += f" <a href='bnx:akte/{html.escape(m['akte'])}'>📁 Akte {html.escape(m['akte'])}</a>"
            if m.get("mandant_id"):
                links += f" <a href='bnx:mandant/{m['mandant_id']}'>👤 Mandant öffnen</a>"
            if m.get("aufgabe_id"):
                links += f" <a href='bnx:aufgabe/{m['aufgabe_id']}'>☑ Aufgabe öffnen</a>"
            kopf = (f"<b style='color:{farbe}'>{html.escape(m.get('absender_anzeige') or 'Ich')}</b> "
                    f"<span style='color:{theme.F['gedimmt']}'>· {_zeit(m.get('zeit', ''))}"
                    + (f" · {status}" if status else "") + "</span>")
            text = html.escape(m["text"]).replace("\n", "<br>")
            teile.append(f"<p style='margin:6px 0'>{kopf}<br>{text}{('<br>' + links) if links else ''}</p>")
        self.verlauf.setHtml("".join(teile) or "<p style='color:gray'>Noch keine Nachrichten.</p>")
        self.verlauf.verticalScrollBar().setValue(self.verlauf.verticalScrollBar().maximum())
        offen = any(a["status"] == "Nicht gesendet" for a in self.ausstehend.get(self.partner, []))
        self.b_erneut.setVisible(offen)

    def _link(self, url: QUrl):
        art, _, wert = url.toString().removeprefix("bnx:").partition("/")
        if art == "akte":
            self.oeffnen_akte(QUrl.fromPercentEncoding(wert.encode()))
        elif art == "mandant" and wert.isdigit():
            self.oeffnen_mandant(int(wert))
        elif art == "aufgabe" and wert.isdigit() and self.oeffnen_aufgabe:
            self.oeffnen_aufgabe(int(wert))           # Gelesen heißt nicht erledigt – die Aufgabe bleibt offen

    # --- Senden ---------------------------------------------------------------------
    def senden(self, akte: str = "", mandant_id: int | None = None, text: str | None = None, partner: str | None = None):
        partner = partner or self.partner
        text = (text if text is not None else self.eingabe.toPlainText()).strip()
        if not partner or not text:
            return False
        eintrag = {"client_id": uuid.uuid4().hex, "text": text, "akte": akte or "", "mandant_id": mandant_id,
                   "zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": "Wird gesendet",
                   "absender_anzeige": "Ich", "partner": partner}
        self.ausstehend.setdefault(partner, []).append(eintrag)
        if text is not None and partner == self.partner:
            self.eingabe.clear()
        self._zeichnen()
        QApplication.processEvents()
        return self._uebertragen(eintrag)

    def _uebertragen(self, e: dict) -> bool:
        try:
            self.n.senden(e["partner"], e["text"], e["client_id"], akte=e["akte"], mandant_id=e["mandant_id"])
        except OFFLINE:
            e["status"] = "Nicht gesendet"
            theme.status_setzen(self.l_status, "fehler", "Nicht gesendet – keine Verbindung zum Server. Der Text bleibt "
                                "erhalten und wird automatisch erneut gesendet.")
            self._zeichnen()
            return False
        except ValueError as ex:
            e["status"] = "Nicht gesendet"
            theme.status_setzen(self.l_status, "warn", str(ex))
            self._zeichnen()
            return False
        self.ausstehend[e["partner"]].remove(e)
        self.l_status.setText("")
        if e["partner"] == self.partner:
            self._verlauf_laden()
        return True

    def ausstehende_senden(self):
        """Nach dem Wiederverbinden: offene Nachrichten mit DERSELBEN Kennung erneut senden (keine Doppelung)."""
        for partner, liste in list(self.ausstehend.items()):
            for e in list(liste):
                e["status"] = "Wird gesendet"
                self._uebertragen(e)


class Benachrichtigung(QFrame):
    """Kleiner Hinweis unten rechts im Programm – Klick öffnet das Gespräch."""
    geklickt = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("benachrichtigung")
        self.setStyleSheet(f"#benachrichtigung {{ background:{theme.F['karte']}; border:1px solid {theme.F['primaer']};"
                           " border-radius:10px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.text = QLabel("")
        self.text.setAccessibleName("Neue Nachricht")
        lay.addWidget(self.text, 1)
        self.partner = ""
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def zeigen(self, absender: str, anzeige: str):
        self.partner = absender
        self.text.setText(f"<b>{html.escape(anzeige)}</b>: Neue Nachricht – hier klicken")
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 24, 34)                 # oben rechts – verdeckt keine Knöpfe
        self.show()
        self.raise_()
        self._timer.start(12000)

    def mousePressEvent(self, e):
        self.hide()
        self.geklickt.emit(self.partner)


class AkteNachrichtDialog(QDialog):
    """„Nachricht zur Akte…“: Empfänger wählen, Text schreiben – Akte (und optional Mandant) werden verknüpft."""

    def __init__(self, parent, kontakte: list[dict], ref: str, mandant: dict | None):
        super().__init__(parent)
        self.setWindowTitle(f"Nachricht zur Akte {ref}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Akte <b>{html.escape(ref)}</b> wird als Link mitgeschickt."))
        self.an = QComboBox()
        self.an.setAccessibleName("Empfänger")
        for k in kontakte:
            if k["aktiv"]:
                self.an.addItem(f"{k['anzeigename']} ({k['rolle_text']})", k["name"])
        anwalt = next((i for i in range(self.an.count())
                       if any(k["name"] == self.an.itemData(i) and k["rolle"] == "anwalt" for k in kontakte)), 0)
        self.an.setCurrentIndex(anwalt)
        zeile = QHBoxLayout()
        zeile.addWidget(QLabel("An:"))
        zeile.addWidget(self.an, 1)
        lay.addLayout(zeile)
        self.text = QPlainTextEdit()
        self.text.setAccessibleName("Nachricht")
        self.text.setPlaceholderText("z. B. Mandant hat angerufen. Bitte zurückrufen.")
        self.text.setFixedHeight(90)
        lay.addWidget(self.text)
        self.cb_mandant = QCheckBox(f"Mandant verknüpfen ({mandant['name']})" if mandant else "Mandant verknüpfen")
        self.cb_mandant.setChecked(bool(mandant))
        self.cb_mandant.setEnabled(bool(mandant))
        lay.addWidget(self.cb_mandant)
        bb = QDialogButtonBox()
        ok = bb.addButton("Senden", QDialogButtonBox.AcceptRole)
        theme.rolle(ok, "primaer")
        bb.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.text.setFocus()
