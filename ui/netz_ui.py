"""Mehrbenutzer-Oberfläche (0.4.2): Anmeldung, Verbindungsstatus, automatische Aktualisierung, Konflikt-Dialog,
Benutzerverwaltung, Netzwerk-Einstellungen („Einzelplatz“, „Server“, „Mit Server verbinden“)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core import benutzer as bn
from core import netz
from core import protokoll as pr

from . import theme

LOG = logging.getLogger(__name__)
MODI = {"einzelplatz": "Einzelplatz", "server": "Server", "client": "Mit Server verbinden"}


# --------------------------------------------------------------------------- Anmeldung
class AnmeldeDialog(QDialog):
    def __init__(self, verbindung: netz.Verbindung, erster_admin: bool = False, hinweis: str = ""):
        super().__init__()
        self.v = verbindung
        self.erster = erster_admin
        self.setWindowTitle("BnX-Raptor – Erster Administrator" if erster_admin else "BnX-Raptor – Anmelden")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        kopf = QHBoxLayout()
        kopf.addWidget(theme.Marke(30))
        kopf.addWidget(theme.ueberschrift("Ersten Administrator anlegen" if erster_admin else "Anmelden", "h2"), 1)
        lay.addLayout(kopf)
        info = QLabel(("Dieser Rechner ist der Server. Legen Sie jetzt den ersten Administrator an – er kann danach "
                       "weitere Benutzer anlegen.") if erster_admin else f"Server: {verbindung.adresse}")
        info.setWordWrap(True)
        theme.rolle(info, "gedimmt")
        lay.addWidget(info)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setAccessibleName("Benutzername")
        form.addRow("Benutzername:", self.name)
        self.anzeige = QLineEdit()
        self.anzeige.setAccessibleName("Anzeigename")
        if erster_admin:
            self.anzeige.setPlaceholderText("z. B. Dr. Muster (optional)")
            form.addRow("Anzeigename:", self.anzeige)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setAccessibleName("Passwort")
        form.addRow("Passwort:", self.pw)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.pw2.setAccessibleName("Passwort wiederholen")
        if erster_admin:
            form.addRow("Passwort wiederholen:", self.pw2)
        lay.addLayout(form)
        self.status = QLabel(hinweis)
        self.status.setWordWrap(True)
        if hinweis:
            theme.status_setzen(self.status, "warn", hinweis)
        lay.addWidget(self.status)
        knoepfe = QDialogButtonBox()
        self.b_ok = knoepfe.addButton("Anlegen und anmelden" if erster_admin else "Anmelden",
                                      QDialogButtonBox.AcceptRole)
        theme.rolle(self.b_ok, "primaer")
        knoepfe.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        knoepfe.accepted.connect(self.anmelden)
        knoepfe.rejected.connect(self.reject)
        lay.addWidget(knoepfe)
        self.name.setFocus()

    def anmelden(self):
        name, pw = self.name.text().strip(), self.pw.text()
        if not name or not pw:
            theme.status_setzen(self.status, "warn", "Bitte Benutzername und Passwort eingeben.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if self.erster:
                if pw != self.pw2.text():
                    theme.status_setzen(self.status, "warn", "Die Passwörter stimmen nicht überein.")
                    return
                self.v.erster_admin(name, pw, self.anzeige.text().strip())
            self.v.anmelden(name, pw)
        except netz.VerbindungFehler as e:
            theme.status_setzen(self.status, "fehler", str(e))
            return
        except ValueError as e:
            theme.status_setzen(self.status, "warn", str(e))
            self.pw.clear()
            self.pw.setFocus()
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.pw2.clear()
        self.accept()


def verbinden(cfg: dict, server_laeuft: bool) -> netz.Verbindung | None:
    """Anmeldung beim Start (Server-Rechner: an den eigenen Dienst; Client: an die eingetragene Adresse)."""
    if cfg.get("modus") == "server":
        v = netz.Verbindung(f"127.0.0.1:{int(cfg.get('server_port') or netz.STANDARD_PORT)}")
    else:
        v = netz.Verbindung(cfg.get("server_adresse") or "")
    while True:
        try:
            info = v.ping()
            erster = cfg.get("modus") == "server" and not info.get("benutzer_vorhanden")
            dlg = AnmeldeDialog(v, erster_admin=erster)
            return v if dlg.exec() == QDialog.Accepted else None
        except netz.VerbindungFehler as e:
            box = QMessageBox(QMessageBox.Warning, "BnX-Raptor – Verbindung", str(e))
            box.setInformativeText("Adresse in config.json bzw. unter Einstellungen → Netzwerk prüfen. "
                                   f"Eingetragene Adresse: {v.adresse or '(keine)'}")
            erneut = box.addButton("Erneut versuchen", QMessageBox.AcceptRole)
            adresse = box.addButton("Adresse ändern…", QMessageBox.ActionRole)
            box.addButton("Beenden", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is adresse:
                neu, ok = QInputDialog.getText(None, "Server-Adresse", "Adresse des Servers (z. B. "
                                               f"http://192.168.1.20:{netz.STANDARD_PORT}):", text=v.adresse)
                if ok and neu.strip():
                    from core.config import einstellung_speichern
                    cfg["server_adresse"] = neu.strip()
                    einstellung_speichern("server_adresse", neu.strip())
                    v = netz.Verbindung(neu.strip())
                continue
            if box.clickedButton() is not erneut:
                return None


# --------------------------------------------------------------------------- Status + Aktualisierung
class Beobachter(QObject):
    """Fragt alle 3 s die Änderungen anderer Benutzer ab (im Hintergrund) und meldet Verbindungsstatus."""
    neu = Signal(list)              # Einträge anderer Benutzer
    neu_geladen = Signal()          # Wiederherstellung auf dem Server → alles neu laden
    status = Signal(str, str)       # art (ok|warn|fehler), Text

    def __init__(self, v: netz.Verbindung, intervall_ms: int = 3000):
        super().__init__()
        self.v = v
        self.letzte = -1
        self.generation = None
        self.offline = False
        self._laeuft = False
        self.timer = QTimer(self)
        self.timer.setInterval(intervall_ms)
        self.timer.timeout.connect(self._anstossen)
        self.timer.start()
        QTimer.singleShot(200, self._anstossen)

    def _anstossen(self):
        if self._laeuft:
            return
        self._laeuft = True
        threading.Thread(target=self._abfragen, daemon=True).start()

    def jetzt(self):
        self._anstossen()

    def _abfragen(self):
        try:
            erg = self.v.aenderungen(max(self.letzte, 0))
        except (netz.VerbindungFehler, netz.SitzungFehler) as e:
            self.offline = True
            self.status.emit("fehler", "Keine Verbindung zum Server – Eingaben bleiben erhalten, es wird nichts "
                                       "gespeichert. " + ("" if isinstance(e, netz.VerbindungFehler) else str(e)))
            self._laeuft = False
            return
        except Exception:  # noqa: BLE001
            LOG.exception("Änderungen abfragen")
            self._laeuft = False
            return
        try:
            war_offline = self.offline
            self.offline = False
            if erg.get("wartung"):
                self.status.emit("warn", erg["wartung"])
            else:
                b = self.v.benutzer or {}
                self.status.emit("ok", f"Verbunden · {b.get('anzeigename') or b.get('name', '')} "
                                       f"({bn.ROLLEN.get(b.get('rolle', ''), '')})" +
                                 (" · Verbindung wiederhergestellt" if war_offline else ""))
            if self.generation is not None and erg["generation"] != self.generation:
                self.neu_geladen.emit()
            self.generation = erg["generation"]
            ich = (self.v.benutzer or {})
            ich_text = ich.get("anzeigename") or ich.get("name")
            if self.letzte >= 0:
                fremde = [e for e in erg["eintraege"] if e.get("benutzer") != ich_text]
                if fremde or war_offline:
                    self.neu.emit(fremde)
            self.letzte = erg["letzte_id"]
        finally:
            self._laeuft = False


class StatusLeiste(QWidget):
    """Unten in der Seitenleiste: Verbindung + „Erneut verbinden“."""

    def __init__(self, beobachter: Beobachter):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        self.text = QLabel("Verbinde …")
        self.text.setWordWrap(True)
        self.text.setAccessibleName("Verbindungsstatus")
        lay.addWidget(self.text)
        self.b = QPushButton("Erneut verbinden")
        self.b.hide()
        self.b.clicked.connect(beobachter.jetzt)
        lay.addWidget(self.b)
        beobachter.status.connect(self.setzen)

    def setzen(self, art: str, text: str):
        theme.status_setzen(self.text, art, text)
        self.b.setVisible(art == "fehler")


def ausnahme_behandeln(parent, e: BaseException) -> bool:
    """Netzwerk-/Rechte-/Konfliktfehler verständlich melden. True = behandelt."""
    if isinstance(e, (netz.VerbindungFehler, netz.WartungFehler)):
        QMessageBox.warning(parent, "Nicht gespeichert", str(e))
        return True
    if isinstance(e, bn.Berechtigung):
        QMessageBox.information(parent, "Keine Berechtigung", str(e))
        return True
    if isinstance(e, pr.Konflikt):
        QMessageBox.warning(parent, "Gleichzeitige Änderung", str(e))
        return True
    return False


# --------------------------------------------------------------------------- Konflikt-Dialog
class KonfliktDialog(QDialog):
    """Zeigt Ihre Eingabe und den aktuellen Stand nebeneinander. Ergebnis: „meine“, „aktuell“ oder None."""

    def __init__(self, parent, k: pr.Konflikt, meine: dict):
        super().__init__(parent)
        self.setWindowTitle("Gleichzeitige Änderung")
        self.ergebnis: str | None = None
        lay = QVBoxLayout(self)
        von = k.aktuell.get("geaendert_von") or "einem anderen Benutzer"
        am = pr._de(k.aktuell.get("geaendert_am") or k.aktuell.get("geaendert") or "")
        t = QLabel(f"<b>{pr.ARTEN_TEXT.get(k.art, k.art)} wurde inzwischen von {von}"
                   + (f" am {am}" if am else "") + " geändert.</b><br>Ihre Eingabe ist NICHT gespeichert, aber auch "
                   "nicht verloren. Bitte vergleichen und entscheiden:")
        t.setWordWrap(True)
        lay.addWidget(t)
        tab = QTableWidget(len(k.felder), 3)
        tab.setHorizontalHeaderLabels(["Feld", "Ihre Eingabe", "Aktueller Stand"])
        tab.verticalHeader().setVisible(False)
        tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r, f in enumerate(k.felder):
            tab.setItem(r, 0, QTableWidgetItem(pr.FELDNAMEN.get(f, f)))
            tab.setItem(r, 1, QTableWidgetItem(str(meine.get(f, "") or "")))
            tab.setItem(r, 2, QTableWidgetItem(str(k.aktuell.get(f, "") or "")))
        tab.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tab.setMinimumWidth(560)
        tab.setMaximumHeight(60 + 32 * max(len(k.felder), 1))
        lay.addWidget(tab)
        knoepfe = QHBoxLayout()
        b1 = QPushButton("Meine Eingabe speichern")
        theme.rolle(b1, "primaer")
        b1.clicked.connect(lambda: self._fertig("meine"))
        b2 = QPushButton("Aktuellen Stand übernehmen")
        b2.clicked.connect(lambda: self._fertig("aktuell"))
        b3 = QPushButton("Später entscheiden")
        b3.setToolTip("Ihre Eingabe bleibt im Formular stehen (nicht gespeichert)")
        b3.clicked.connect(self.reject)
        for b in (b1, b2, b3):
            knoepfe.addWidget(b)
        lay.addLayout(knoepfe)

    def _fertig(self, e: str):
        self.ergebnis = e
        self.accept()


# --------------------------------------------------------------------------- Benutzerverwaltung
class BenutzerDialog(QDialog):
    def __init__(self, parent, v: netz.Verbindung):
        super().__init__(parent)
        self.v = v
        self.setWindowTitle("Benutzer verwalten")
        self.resize(760, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(theme.ueberschrift("Benutzer verwalten", "h2"))
        self.tab = QTableWidget(0, 5)
        self.tab.setHorizontalHeaderLabels(["Benutzername", "Anzeigename", "Rolle", "Status", "Angelegt"])
        self.tab.verticalHeader().setVisible(False)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tab.setAccessibleName("Benutzer")
        lay.addWidget(self.tab, 1)
        knoepfe = QHBoxLayout()
        for text, fn in (("Neuer Benutzer…", self.neu), ("Rolle ändern…", self.rolle),
                         ("Passwort zurücksetzen…", self.passwort), ("Deaktivieren / Aktivieren", self.aktiv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            knoepfe.addWidget(b)
        knoepfe.addStretch(1)
        zu = QPushButton("Schließen")
        zu.clicked.connect(self.accept)
        knoepfe.addWidget(zu)
        lay.addLayout(knoepfe)
        self.status = QLabel("")
        lay.addWidget(self.status)
        self.laden()

    def _aufruf(self, methode, *args):
        try:
            erg = self.v.aufrufen("benutzer", methode, args)
            self.laden()
            theme.status_setzen(self.status, "ok", "Gespeichert")
            return erg
        except ValueError as e:
            theme.status_setzen(self.status, "warn", str(e))
        except Exception as e:  # noqa: BLE001
            if not ausnahme_behandeln(self, e):
                raise
        return None

    def laden(self):
        self.liste = self.v.aufrufen("benutzer", "liste")
        self.tab.setRowCount(len(self.liste))
        for r, b in enumerate(self.liste):
            for c, t in enumerate((b["name"], b["anzeigename"], b["rolle_text"],
                                   "aktiv" if b["aktiv"] else "deaktiviert", pr._de(b["erstellt_am"] or ""))):
                self.tab.setItem(r, c, QTableWidgetItem(t))

    def _gewaehlt(self) -> dict | None:
        r = self.tab.currentRow()
        if r < 0:
            theme.status_setzen(self.status, "warn", "Bitte zuerst einen Benutzer markieren.")
            return None
        return self.liste[r]

    def neu(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Neuer Benutzer")
        f = QFormLayout(dlg)
        name, anzeige, pw = QLineEdit(), QLineEdit(), QLineEdit()
        pw.setEchoMode(QLineEdit.Password)
        rolle = QComboBox()
        for k, t in bn.ROLLEN.items():
            rolle.addItem(t, k)
        rolle.setCurrentIndex(1)
        f.addRow("Benutzername:", name)
        f.addRow("Anzeigename:", anzeige)
        f.addRow("Rolle:", rolle)
        f.addRow("Anfangspasswort (min. 8 Zeichen):", pw)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Anlegen")
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            self._aufruf("anlegen", name.text(), pw.text(), rolle.currentData(), anzeige.text())

    def rolle(self):
        b = self._gewaehlt()
        if not b:
            return
        namen = list(bn.ROLLEN.values())
        t, ok = QInputDialog.getItem(self, "Rolle ändern", f"Rolle für {b['name']}:", namen,
                                     namen.index(b["rolle_text"]) if b["rolle_text"] in namen else 0, False)
        if ok:
            self._aufruf("rolle_setzen", b["id"], next(k for k, v in bn.ROLLEN.items() if v == t))

    def passwort(self):
        b = self._gewaehlt()
        if not b:
            return
        pw, ok = QInputDialog.getText(self, "Passwort zurücksetzen", f"Neues Passwort für {b['name']} "
                                      "(mindestens 8 Zeichen):", QLineEdit.Password)
        if ok and pw:
            self._aufruf("passwort_setzen", b["id"], pw)

    def aktiv(self):
        b = self._gewaehlt()
        if b:
            self._aufruf("aktiv_setzen", b["id"], not b["aktiv"])


def eigenes_passwort(parent, v: netz.Verbindung):
    alt, ok = QInputDialog.getText(parent, "Passwort ändern", "Bisheriges Passwort:", QLineEdit.Password)
    if not ok or not alt:
        return
    neu, ok = QInputDialog.getText(parent, "Passwort ändern", "Neues Passwort (mindestens 8 Zeichen):",
                                   QLineEdit.Password)
    if not ok or not neu:
        return
    neu2, ok = QInputDialog.getText(parent, "Passwort ändern", "Neues Passwort wiederholen:", QLineEdit.Password)
    if not ok:
        return
    if neu != neu2:
        QMessageBox.warning(parent, "Passwort ändern", "Die Passwörter stimmen nicht überein.")
        return
    try:
        v.aufrufen("benutzer", "eigenes_passwort", [alt, neu])
        v._anmeldung = (v._anmeldung[0], neu) if v._anmeldung else None
        QMessageBox.information(parent, "Passwort ändern", "Das Passwort wurde geändert.")
    except ValueError as e:
        QMessageBox.warning(parent, "Passwort ändern", str(e))
    except Exception as e:  # noqa: BLE001
        if not ausnahme_behandeln(parent, e):
            raise


# --------------------------------------------------------------------------- Netzwerk-Einstellungen
class NetzEinstellungen(QWidget):
    """„Einzelplatz“ / „Server“ / „Mit Server verbinden“ – mit Adresse für die anderen Rechner."""

    def __init__(self, ctx, neustart):
        super().__init__()
        self.ctx, self.neustart = ctx, neustart
        cfg = ctx.cfg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        reihe = QHBoxLayout()
        self.gruppe = QButtonGroup(self)
        self.radios = {}
        for k, t in MODI.items():
            r = QRadioButton(t)
            r.setAccessibleName(t)
            self.gruppe.addButton(r)
            self.radios[k] = r
            reihe.addWidget(r)
        reihe.addStretch(1)
        lay.addLayout(reihe)
        self.radios.get(cfg.get("modus") or "einzelplatz", self.radios["einzelplatz"]).setChecked(True)
        form = QFormLayout()
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(cfg.get("server_port") or netz.STANDARD_PORT))
        self.port.setAccessibleName("Port")
        form.addRow("Port:", self.port)
        self.l_adresse = QLabel("")
        self.l_adresse.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.l_adresse.setWordWrap(True)
        self.l_adresse.setAccessibleName("Adresse für die anderen Rechner")
        form.addRow("Adresse für die anderen Rechner:", self.l_adresse)
        adr = QHBoxLayout()
        self.adresse = QLineEdit(cfg.get("server_adresse") or "")
        self.adresse.setPlaceholderText(f"z. B. http://192.168.1.20:{netz.STANDARD_PORT}")
        self.adresse.setAccessibleName("Server-Adresse")
        adr.addWidget(self.adresse, 1)
        b_test = QPushButton("Verbindung testen")
        b_test.clicked.connect(self.testen)
        adr.addWidget(b_test)
        form.addRow("Server-Adresse:", adr)
        lay.addLayout(form)
        self.hinweis = QLabel("")
        self.hinweis.setWordWrap(True)
        lay.addWidget(self.hinweis)
        unten = QHBoxLayout()
        self.b_ok = QPushButton("Übernehmen und neu starten")
        theme.rolle(self.b_ok, "primaer")
        self.b_ok.clicked.connect(self.uebernehmen)
        unten.addWidget(self.b_ok)
        unten.addStretch(1)
        lay.addLayout(unten)
        self.gruppe.buttonToggled.connect(lambda *_: self._zeigen())
        self.port.valueChanged.connect(lambda *_: self._zeigen())
        self._zeigen()
        darf = (not ctx.mehrbenutzer) or ctx.rolle == "admin"
        for w in (*self.radios.values(), self.port, self.adresse, self.b_ok):
            w.setEnabled(darf)
        if not darf:
            theme.status_setzen(self.hinweis, None, "Nur Administratoren können die Verbindung ändern.")

    def modus(self) -> str:
        return next(k for k, r in self.radios.items() if r.isChecked())

    def _zeigen(self):
        m = self.modus()
        self.port.setEnabled(m == "server")
        self.adresse.setEnabled(m == "client")
        self.l_adresse.setText("\n".join(netz.lokale_adressen(self.port.value())) if m == "server" else "–")
        texte = {
            "einzelplatz": "Nur dieser Rechner arbeitet mit den Daten (bisheriges Verhalten).",
            "server": "Dieser Rechner verwaltet Datenbank und Dokumente für alle. Er muss eingeschaltet sein und "
                      "BnX-Raptor muss hier laufen, solange andere arbeiten. Beim ersten Start fragt Windows evtl., ob "
                      "BnX-Raptor im privaten Netzwerk kommunizieren darf – bitte erlauben. Vorhandene Daten bleiben "
                      "erhalten.",
            "client": "Dieser Rechner arbeitet mit den Daten des Servers. Outlook-Entwürfe, Word-Umwandlung und "
                      "Texterkennung laufen hier auf diesem Rechner.",
        }
        theme.status_setzen(self.hinweis, None, texte[m])

    def testen(self):
        v = netz.Verbindung(self.adresse.text())
        try:
            info = v.ping()
            theme.status_setzen(self.hinweis, "ok", f"Verbindung in Ordnung: BnX-Raptor {info.get('version')} auf "
                                                    f"„{info.get('rechner')}“ ({v.adresse}).")
        except netz.VerbindungFehler as e:
            theme.status_setzen(self.hinweis, "fehler", str(e))

    def uebernehmen(self):
        from core.config import einstellung_speichern
        m = self.modus()
        if m == "client" and not self.adresse.text().strip():
            theme.status_setzen(self.hinweis, "warn", "Bitte die Adresse des Servers eintragen.")
            return
        werte = {"modus": m, "server_port": self.port.value(), "server_adresse": self.adresse.text().strip()}
        if all(einstellung_speichern(k, v) for k, v in werte.items()):
            self.ctx.cfg.update(werte)
            if QMessageBox.question(self, "Netzwerk", f"Modus „{MODI[m]}“ gespeichert. BnX-Raptor jetzt neu "
                                    "starten?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                self.neustart()
        else:
            theme.status_setzen(self.hinweis, "fehler", "config.json ist nicht schreibbar – nicht gespeichert.")


def akte_lokal(ctx, ref: str) -> Path:
    """Client: alle Dokumente einer Akte als lokale Kopien bereitstellen und den Ordner zurückgeben."""
    for d in ctx.archiv.liste(akte=ref):
        try:
            ctx.dateien.lokal(d["pfad"], ref)
        except (netz.VerbindungFehler, ValueError):
            continue
    return ctx.dateien.akte_ordner(ref)
