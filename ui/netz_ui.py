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
    def __init__(self, verbindung: netz.Verbindung, erster_admin: bool = False, hinweis: str = "",
                 kanzlei: str = "", name: str = ""):
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
        info = QLabel(("Dieser PC stellt die Kanzlei-Daten bereit. Legen Sie jetzt den ersten Administrator an – er "
                       "kann danach weitere Benutzer anlegen.") if erster_admin else
                      f"Kanzlei: {kanzlei or '–'}  ·  {verbindung.adresse}")
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
        if name:
            self.name.setText(name)
            self.pw.setFocus()
        else:
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


FIREWALL_TEXT = (
    "Windows-Firewall: Beim ersten Bereitstellen fragt Windows, ob BnX-Raptor im Netzwerk kommunizieren darf – "
    "„Private Netzwerke“ anhaken und „Zugriff zulassen“ klicken. Wurde die Frage weggeklickt: Start → "
    "„Windows-Sicherheit“ → „Firewall- & Netzwerkschutz“ → „Zugriff von App durch Firewall zulassen“ → "
    "„Einstellungen ändern“ → bei „BnX-Raptor“ den Haken unter „Privat“ setzen.")


def _merken(cfg: dict, server: dict) -> None:
    from core.config import einstellung_speichern
    werte = {"modus": "client", "server_adresse": server["adresse"], "server_kanzlei": server.get("kanzlei", ""),
             "server_rechner": server.get("rechner", ""), "server_zertifikat": server["zertifikat"]}
    for k, v in werte.items():
        cfg[k] = v
        einstellung_speichern(k, v)


class VerbindenDialog(QDialog):
    """„Mit bestehender Kanzlei verbinden“: sucht den Hauptrechner automatisch – ein Klick genügt."""

    def __init__(self, parent=None, cfg: dict | None = None, hinweis: str = ""):
        super().__init__(parent)
        self.cfg = cfg if cfg is not None else {}
        self.server: dict | None = None
        self.setWindowTitle("Mit bestehender Kanzlei verbinden")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(theme.ueberschrift("Mit bestehender Kanzlei verbinden", "h2"))
        self.status = QLabel(hinweis or "Suche im Büronetz …")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        self._item = QListWidgetItem
        self.liste = QListWidget()
        self.liste.setAccessibleName("Gefundene Kanzleien")
        self.liste.setMinimumHeight(110)
        self.liste.itemDoubleClicked.connect(lambda *_: self.verbinden())
        lay.addWidget(self.liste)
        self.b_manuell = QPushButton("Verbindungsadresse eingeben…")
        theme.rolle(self.b_manuell, "link")
        self.b_manuell.clicked.connect(self.manuell)
        lay.addWidget(self.b_manuell)
        knoepfe = QHBoxLayout()
        self.b_suchen = QPushButton("Erneut suchen")
        self.b_suchen.clicked.connect(self.suchen)
        knoepfe.addWidget(self.b_suchen)
        knoepfe.addStretch(1)
        ab = QPushButton("Abbrechen")
        ab.clicked.connect(self.reject)
        knoepfe.addWidget(ab)
        self.b_ok = QPushButton("Verbinden")
        theme.rolle(self.b_ok, "primaer")
        self.b_ok.clicked.connect(self.verbinden)
        knoepfe.addWidget(self.b_ok)
        lay.addLayout(knoepfe)
        QTimer.singleShot(100, self.suchen)

    def suchen(self):
        self.liste.clear()
        theme.status_setzen(self.status, None, "Suche im Büronetz …")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            QApplication.processEvents()
            gefunden = netz.suchen(2.0)
        finally:
            QApplication.restoreOverrideCursor()
        for s in gefunden:
            it = self._item(f"{s['kanzlei'] or 'Kanzlei'}  ·  Rechner {s['rechner']}  ·  {s['adresse']}")
            it.setData(Qt.UserRole, s)
            self.liste.addItem(it)
        if gefunden:
            self.liste.setCurrentRow(0)
            theme.status_setzen(self.status, "ok", "Gefunden – „Verbinden“ klicken." if len(gefunden) == 1 else
                                "Mehrere gefunden – bitte die eigene Kanzlei wählen und „Verbinden“ klicken.")
        else:
            theme.status_setzen(self.status, "warn", "Keine Kanzlei im Büronetz gefunden. Ist der Hauptrechner "
                                "eingeschaltet und BnX-Raptor dort geöffnet? Sonst „Verbindungsadresse eingeben…“ "
                                "(steht am Hauptrechner unter Einstellungen → Netzwerk).")

    def manuell(self):
        adr, ok = QInputDialog.getText(self, "Verbindungsadresse", "Adresse vom Hauptrechner (Einstellungen → "
                                       f"Netzwerk), z. B. https://192.168.1.20:{netz.STANDARD_PORT}:")
        if ok and adr.strip():
            try:
                self._pruefen(netz.Verbindung(adr.strip()).adresse)
            except netz.ZertifikatFehler as e:
                theme.status_setzen(self.status, "fehler", str(e))

    def verbinden(self):
        it = self.liste.currentItem()
        if it is None:
            theme.status_setzen(self.status, "warn", "Bitte zuerst eine Kanzlei wählen (oder Adresse eingeben).")
            return
        s = it.data(Qt.UserRole)
        self._pruefen(s["adresse"], s.get("alternativen") or [])

    def _pruefen(self, adresse: str, alternativen: list[str] | None = None):
        v = None
        pem = None
        fp = ""
        for adr in [adresse, *(alternativen or [])]:
            try:
                v = netz.Verbindung(adr)
                pem, fp = v.zertifikat_lesen()
                break
            except netz.VerbindungFehler:
                continue
        if pem is None:
            theme.status_setzen(self.status, "fehler", f"TLS-Server nicht erreichbar ({adresse}). Bitte "
                                "Hauptrechner und Windows-Firewall prüfen. → „Erneut suchen“")
            return
        # Kod burada bilerek gösterilmez: kullanıcı onu ana bilgisayarın ekranından okumalıdır.
        from core import zertifikat
        scanner = zertifikat.scanner(pem)
        if scanner:                              # Virenscanner bricht TLS auf → Code würde nie passen
            theme.status_setzen(self.status, "fehler", zertifikat.scanner_text(scanner))
            return
        gefragt, ok = QInputDialog.getText(self, "Server-Identität prüfen",
            "Einmalige Sicherheitsprüfung: Öffnen Sie am Hauptrechner Einstellungen → Netzwerk und tippen Sie\n"
            "den dort angezeigten Kontrollcode (16 Zeichen, z. B. 1A2B 3C4D 5E6F 7A8B) hier ab.\n"
            "Leerzeichen und Groß-/Kleinschreibung spielen keine Rolle.\n\nKontrollcode vom Hauptrechner:")
        if not ok:
            return
        if not zertifikat.bestaetigung_passt(fp, gefragt):
            theme.status_setzen(self.status, "fehler", "Kontrollcode stimmt nicht mit diesem Server überein – "
                                "Verbindung abgebrochen. Bitte den Code am Hauptrechner erneut ablesen.")
            return
        try:
            v.zertifikat_bestaetigen(fp)
            info = v.ping()
        except netz.VerbindungFehler as e:
            theme.status_setzen(self.status, "fehler", str(e))
            return
        self.server = {"adresse": v.adresse, "kanzlei": info.get("kanzlei", ""),
                       "rechner": info.get("rechner", ""), "zertifikat": pem.decode("ascii")}
        _merken(self.cfg, self.server)
        self.accept()


def verbinden(cfg: dict, server_laeuft: bool) -> netz.Verbindung | None:
    """Beim Start: Server-Rechner → eigener Dienst; Arbeitsplatz → gemerkter Server (bei geänderter Adresse
    automatisch neu gefunden). Danach Anmeldung mit eigenem Benutzernamen."""
    if cfg.get("modus") == "server":
        from core.config import data_dir
        cert = (data_dir(cfg) / "tls" / "server.pem").read_bytes()
        v = netz.Verbindung(f"127.0.0.1:{int(cfg.get('server_port') or netz.STANDARD_PORT)}", cert_pem=cert)
    else:
        if not cfg.get("server_zertifikat") or not cfg.get("server_adresse") \
                or str(cfg.get("server_adresse", "")).lower().startswith("http://"):
            dlg = VerbindenDialog(None, cfg, "Alte oder unbestätigte Verbindung: Bitte Server-Zertifikat "
                                             "erneut am Hauptrechner prüfen.")
            if dlg.exec() != QDialog.Accepted:
                return None
        v = netz.Verbindung(cfg.get("server_adresse") or "", cert_pem=cfg.get("server_zertifikat"))
    while True:
        try:
            info = v.ping()
            erster = cfg.get("modus") == "server" and not info.get("benutzer_vorhanden")
            dlg = AnmeldeDialog(v, erster_admin=erster, kanzlei=info.get("kanzlei", ""),
                                name=cfg.get("letzter_benutzer", ""))
            if dlg.exec() != QDialog.Accepted:
                return None
            from core.config import einstellung_speichern
            einstellung_speichern("letzter_benutzer", (v.benutzer or {}).get("name", ""))
            return v
        except netz.VerbindungFehler as fehler:
            if cfg.get("modus") == "client" and not isinstance(fehler, netz.ZertifikatFehler):
                # Keşif güvenilir değildir: yeni adreste yalnızca kayıtlı sertifika doğrulanır.
                gefunden = False
                for s in netz.suchen(2.0):
                    if s["rechner"] != cfg.get("server_rechner"):
                        continue
                    for adr in [s["adresse"], *s.get("alternativen", [])]:
                        if adr == v.adresse:
                            continue
                        try:
                            neu_v = netz.Verbindung(adr, cert_pem=cfg["server_zertifikat"])
                            neu_info = neu_v.ping()
                        except netz.VerbindungFehler:
                            continue
                        _merken(cfg, {"adresse": adr, "kanzlei": neu_info.get("kanzlei", ""),
                                      "rechner": neu_info.get("rechner", ""),
                                      "zertifikat": cfg["server_zertifikat"]})
                        v = neu_v
                        gefunden = True
                        break
                    if gefunden:
                        break
                if gefunden:
                    continue
            box = QMessageBox(QMessageBox.Warning, "BnX-Raptor – Verbindung gesperrt",
                              (str(fehler) if isinstance(fehler, netz.ZertifikatFehler)
                               else "Server nicht erreichbar." if cfg.get("modus") == "client" else
                               "Der eigene Server-Dienst antwortet nicht."))
            box.setInformativeText(
                f"Kanzlei: {cfg.get('server_kanzlei') or '–'} (Rechner {cfg.get('server_rechner') or '–'})\n"
                "Bitte den Hauptrechner einschalten und BnX-Raptor dort öffnen.\n\n" + FIREWALL_TEXT)
            erneut = box.addButton("Erneut versuchen", QMessageBox.AcceptRole)
            neu = box.addButton("Andere Kanzlei / Adresse…", QMessageBox.ActionRole) \
                if cfg.get("modus") == "client" else None
            box.addButton("Beenden", QMessageBox.RejectRole)
            box.setDefaultButton(erneut)
            box.exec()
            if neu is not None and box.clickedButton() is neu:
                dlg = VerbindenDialog(None, cfg)
                if dlg.exec() == QDialog.Accepted:
                    v = netz.Verbindung(cfg["server_adresse"], cert_pem=cfg["server_zertifikat"])
                continue
            if box.clickedButton() is not erneut:
                return None


class Willkommen(QDialog):
    """Erster Start auf einem neuen PC: neue Kanzlei hier – oder mit bestehender Kanzlei verbinden."""

    def __init__(self):
        super().__init__()
        self.wahl = ""
        self.setWindowTitle("BnX-Raptor – Willkommen")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        kopf = QHBoxLayout()
        kopf.addWidget(theme.Marke(34))
        kopf.addWidget(theme.ueberschrift("Willkommen bei BnX-Raptor", "h2"), 1)
        lay.addLayout(kopf)
        lay.addWidget(QLabel("Wie soll dieser PC arbeiten?"))
        b1 = QPushButton("Mit bestehender Kanzlei verbinden\n(die Daten liegen auf dem Hauptrechner im Büro)")
        theme.rolle(b1, "primaer")
        b1.setMinimumHeight(64)
        b1.clicked.connect(lambda: self._fertig("verbinden"))
        b2 = QPushButton("Neue Kanzlei auf diesem PC\n(erster oder einziger Arbeitsplatz)")
        b2.setMinimumHeight(64)
        b2.clicked.connect(lambda: self._fertig("neu"))
        lay.addWidget(b1)
        lay.addWidget(b2)

    def _fertig(self, w: str):
        self.wahl = w
        self.accept()


# --------------------------------------------------------------------------- Status + Aktualisierung
class Beobachter(QObject):
    """Fragt alle 3 s die Änderungen anderer Benutzer ab (im Hintergrund) und meldet Verbindungsstatus."""
    neu = Signal(list)              # Einträge anderer Benutzer
    neu_geladen = Signal()          # Wiederherstellung auf dem Server → alles neu laden
    status = Signal(str, str)       # art (ok|warn|fehler), Text
    nachrichten = Signal(dict)      # {ungelesen, neu: [...], erst: bool}
    wieder_online = Signal()

    def __init__(self, v: netz.Verbindung, intervall_ms: int = 3000):
        super().__init__()
        self.v = v
        self.letzte = -1
        self.generation = None
        self.offline = False
        self._laeuft = False
        self.nachrichten_seit = -1
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
            try:
                st = self.v.aufrufen("nachrichten", "status", [max(self.nachrichten_seit, 0)])
                erst = self.nachrichten_seit < 0
                self.nachrichten_seit = st["hoechste_id"]
                self.nachrichten.emit({**st, "erst": erst})
            except Exception:  # noqa: BLE001 – Nachrichten sind Zusatz; Abfrage beim nächsten Mal
                pass
            if war_offline:
                self.wieder_online.emit()
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
    """Einstellungen → Netzwerk: „Daten auf diesem PC bereitstellen“ / „Mit bestehender Kanzlei verbinden“."""

    def __init__(self, ctx, neustart):
        super().__init__()
        self.ctx, self.neustart = ctx, neustart
        cfg = ctx.cfg
        modus = cfg.get("modus") or "einzelplatz"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.hinweis = QLabel("")
        self.hinweis.setWordWrap(True)
        darf = (not ctx.mehrbenutzer) or ctx.rolle == "admin"
        if modus == "server":
            port = int(cfg.get("server_port") or netz.STANDARD_PORT)
            adressen = netz.lokale_adressen(port)
            t = QLabel("<b>Dieser PC stellt die Kanzlei-Daten bereit.</b> Er muss eingeschaltet bleiben und BnX-Raptor "
                       "muss hier geöffnet sein, solange an anderen PCs gearbeitet wird.")
            t.setWordWrap(True)
            lay.addWidget(t)
            zeile = QHBoxLayout()
            zeile.addWidget(QLabel("Verbindungsadresse:"))
            self.l_adresse = QLabel(adressen[0] if adressen else "–")
            self.l_adresse.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.l_adresse.setAccessibleName("Verbindungsadresse")
            self.l_adresse.setStyleSheet("font-weight: 700;")
            self.l_adresse.setToolTip("\n".join(adressen))
            zeile.addWidget(self.l_adresse)
            b_kopie = QPushButton("Kopieren")
            b_kopie.clicked.connect(lambda: (QApplication.clipboard().setText(self.l_adresse.text()),
                                             theme.status_setzen(self.hinweis, "ok", "Adresse kopiert.")))
            zeile.addWidget(b_kopie)
            zeile.addStretch(1)
            lay.addLayout(zeile)
            from core import zertifikat
            from core.config import data_dir
            cert_datei = data_dir(cfg) / "tls" / "server.pem"
            if cert_datei.is_file():
                fp = zertifikat.fingerabdruck(cert_datei.read_bytes())
                kennung = QLabel("<b>Kontrollcode für neue Arbeitsplätze:</b> "
                                 f"<span style='font-size:15pt; font-family:Consolas,monospace'><b>"
                                 f"{zertifikat.kurz(fp)}</b></span><br>"
                                 "<span style='color:#6B7280'>Vollständiger SHA-256-Fingerabdruck des TLS-Zertifikats: "
                                 f"{fp}</span>")
                kennung.setWordWrap(True)
                kennung.setTextInteractionFlags(Qt.TextSelectableByMouse)
                kennung.setAccessibleName("Vollständiger Server-Zertifikat-Fingerabdruck")
                lay.addWidget(kennung)
            auto = theme.rolle(QLabel("Weitere PCs finden diesen PC automatisch: dort „Mit bestehender Kanzlei "
                                      "verbinden“ wählen. Die Adresse wird nur gebraucht, wenn die automatische Suche "
                                      "nichts findet."), "gedimmt")
            auto.setWordWrap(True)
            lay.addWidget(auto)
            fw = theme.rolle(QLabel(FIREWALL_TEXT), "gedimmt")
            fw.setWordWrap(True)
            lay.addWidget(fw)
            unten = QHBoxLayout()
            b = QPushButton("Bereitstellung beenden (nur dieser PC)")
            b.setEnabled(darf)
            b.clicked.connect(lambda: self._wechseln("einzelplatz"))
            unten.addWidget(b)
            unten.addStretch(1)
            lay.addLayout(unten)
        elif modus == "client":
            t = QLabel(f"<b>Verbunden mit Kanzlei „{cfg.get('server_kanzlei') or '–'}“</b> (Hauptrechner "
                       f"{cfg.get('server_rechner') or '–'}, {cfg.get('server_adresse') or '–'}). Die Daten liegen auf "
                       "dem Hauptrechner – er muss eingeschaltet sein.")
            t.setWordWrap(True)
            lay.addWidget(t)
            unten = QHBoxLayout()
            b = QPushButton("Mit anderer Kanzlei / Adresse verbinden…")
            b.clicked.connect(self._neu_verbinden)
            unten.addWidget(b)
            b2 = QPushButton("Verbindung trennen (nur dieser PC)")
            b2.setEnabled(darf)
            b2.clicked.connect(lambda: self._wechseln("einzelplatz"))
            unten.addWidget(b2)
            unten.addStretch(1)
            lay.addLayout(unten)
        else:
            lay.addWidget(QLabel("Arbeiten mehrere PCs im Büro mit denselben Mandanten und Akten?"))
            reihe = QHBoxLayout()
            b1 = QPushButton("Daten auf diesem PC bereitstellen")
            theme.rolle(b1, "primaer")
            b1.setToolTip("Dieser PC wird der Hauptrechner: vorhandene Daten bleiben hier und stehen den anderen PCs "
                          "zur Verfügung.")
            b1.clicked.connect(self._bereitstellen)
            b2 = QPushButton("Mit bestehender Kanzlei verbinden")
            b2.setToolTip("Dieser PC arbeitet mit den Daten des Hauptrechners.")
            b2.clicked.connect(self._neu_verbinden)
            for b in (b1, b2):
                b.setEnabled(darf)
                reihe.addWidget(b)
            reihe.addStretch(1)
            lay.addLayout(reihe)
            theme.status_setzen(self.hinweis, None, "Zurzeit arbeitet nur dieser PC mit den Daten.")
        lay.addWidget(self.hinweis)
        if not darf:
            theme.status_setzen(self.hinweis, None, "Nur Administratoren können die Verbindung ändern.")

    def _bereitstellen(self):
        box = QMessageBox(QMessageBox.Question, "Daten bereitstellen",
                          "Dieser PC wird der Hauptrechner der Kanzlei.")
        box.setInformativeText("Die vorhandenen Daten bleiben hier. Dieser PC muss eingeschaltet bleiben und "
                               "BnX-Raptor geöffnet sein, solange andere arbeiten. Nach dem Neustart legen Sie den "
                               "ersten Administrator an.\n\n" + FIREWALL_TEXT)
        ja = box.addButton("Bereitstellen und neu starten", QMessageBox.AcceptRole)
        box.addButton("Abbrechen", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is ja:
            self._wechseln("server", frage=False)

    def _neu_verbinden(self):
        dlg = VerbindenDialog(self, self.ctx.cfg)
        if dlg.exec() == QDialog.Accepted:
            QMessageBox.information(self, "Verbunden", f"Verbunden mit „{dlg.server.get('kanzlei') or dlg.server['adresse']}“."
                                    " BnX-Raptor startet neu – danach mit eigenem Benutzernamen anmelden.")
            self.neustart()

    def _wechseln(self, modus: str, frage: bool = True):
        from core.config import einstellung_speichern
        if frage and QMessageBox.question(self, "Netzwerk", "Wirklich umstellen? BnX-Raptor startet neu.",
                                          QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if not einstellung_speichern("modus", modus):
            theme.status_setzen(self.hinweis, "fehler", "config.json ist nicht schreibbar – nicht umgestellt.")
            return
        self.ctx.cfg["modus"] = modus
        self.neustart()


def akte_lokal(ctx, ref: str) -> Path:
    """Client: alle Dokumente einer Akte als lokale Kopien bereitstellen und den Ordner zurückgeben."""
    for d in ctx.archiv.liste(akte=ref):
        try:
            ctx.dateien.lokal(d["pfad"], ref)
        except (netz.VerbindungFehler, ValueError):
            continue
    return ctx.dateien.akte_ordner(ref)
