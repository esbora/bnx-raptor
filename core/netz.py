"""Mehrbenutzerbetrieb im Büronetz (0.4.2) – ohne zusätzliche Software, nur Python-Standardbibliothek.

Ein Rechner läuft als „Server“: Nur dieser Prozess öffnet die SQLite-Datenbank und die Dokumentablage
(kein gleichzeitiges Öffnen der Datenbankdatei über Netzwerkfreigaben oder OneDrive). Die anderen Rechner
(„Mit Server verbinden“) – und die Oberfläche auf dem Server selbst – arbeiten über einen TLS-Dienst:

- Anmeldung per Challenge-Response (PBKDF2 + HMAC) – das Passwort wird nie übertragen.
- Jede Anfrage ist mit einem Sitzungsschlüssel signiert und fortlaufend nummeriert (keine Übernahme fremder
  Sitzungen, keine Wiederholung). Rechte werden auf dem Server bei jeder Anfrage geprüft.
- Dokumente liegen zentral; Clients arbeiten mit lokalen Arbeitskopien und schreiben Änderungen mit
  Versionsprüfung zurück (gleichzeitige Bearbeitung → Konfliktkopie, nichts geht verloren).
- „Änderungen seit …“ für die automatische Aktualisierung; Wartungsmodus während einer Wiederherstellung.

Der TLS-Fingerabdruck muss vor der ersten Anmeldung am Server verglichen und bestätigt werden.
"""
from __future__ import annotations

import base64
import contextlib
import dataclasses
import hashlib
import http.client
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import socket
import ssl
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import benutzer as bn
from core import protokoll as pr
from core import zertifikat

LOG = logging.getLogger(__name__)
STANDARD_PORT = 47310
SUCH_PORT = 47311                    # UDP: „Wo ist der BnX-Raptor-Server?“ (nur im lokalen Netz)
SUCH_ANFRAGE = b"BNX-RAPTOR-SUCHE-1"
SITZUNG_GUELTIG = 12 * 3600
SPERRE_GUELTIG = 4 * 3600
DOKUMENTE = "Dokumente"

# Methoden, die über das Netz aufgerufen werden dürfen (alles andere – z. B. `con` – ist gesperrt)
LESEN = {
    "journal": {"recent", "verlauf", "bereits_importiert", "akte", "akten", "referenzen"},
    "stammdaten": {"mandanten", "mandant", "versicherungen", "versicherung", "akte", "akten_von_mandant",
                   "akten_von_versicherung", "dokumentordner", "aenderungsverlauf"},
    "archiv": {"id_von", "dokument", "liste", "abgeleitet", "arbeitskopie"},
    "adressbuch": {"alle", "treffer", "emails"},
    "kanzlei": {"laden", "logo_pfad"},
    "benutzer": {"liste"},
    "nachrichten": {"kontakte", "verlauf", "nachricht", "status"},
    "posteingang": {"personen", "vorhanden", "eingang", "liste", "aufgabe", "aufgaben", "uebersicht", "vorschlagen",
                    "akten_infos",
                    "aenderungsverlauf"},
    "unterlagen": {"liste", "erwartung", "vorschlaege_fuer_eingang", "uebersicht", "vorlagen", "aenderungsverlauf"},
    "versand": {"eintrag", "liste", "aenderungsverlauf"},
}
SCHREIBEN = {
    "journal": {"add", "bearbeitet_setzen", "akte_speichern"},
    "stammdaten": {"mandant_speichern", "mandant_loeschen", "versicherung_speichern", "email_hinzufuegen",
                   "standard_email_setzen", "email_entfernen", "akte_anlegen", "akte_setzen"},
    "archiv": {"erfassen", "bearbeitet", "zuordnen"},
    "adressbuch": {"lernen", "hinzufuegen", "aendern", "loeschen"},
    "kanzlei": {"speichern", "logo_hochladen"},
    "benutzer": {"anlegen", "passwort_setzen", "rolle_setzen", "aktiv_setzen", "anzeigename_setzen",
                 "eigenes_passwort"},
    "nachrichten": {"senden", "gelesen"},
    "posteingang": {"anlegen", "aendern", "zuordnen", "vorschlag_neu", "text_ergaenzen", "aufgabe_anlegen",
                    "aufgabe_aendern", "erledigen", "wieder_oeffnen"},
    "unterlagen": {"anlegen", "aendern", "angefordert_eintragen", "entwurf_vermerken", "eingang_verknuepfen",
                   "vorlage_speichern", "vorlage_loeschen", "vorlage_anwenden", "akte_art_setzen"},
    "versand": {"anlegen", "bestaetigen", "nicht_bestaetigt", "veraltet"},
}


class VerbindungFehler(Exception):
    pass


class ZertifikatFehler(VerbindungFehler):
    pass


class SitzungFehler(VerbindungFehler):
    pass


class WartungFehler(Exception):
    pass


# --------------------------------------------------------------------------- JSON mit Pfaden/Dataclasses
def _kodieren(o):
    if isinstance(o, Path):
        return {"__pfad__": str(o)}
    if isinstance(o, sqlite3.Row):
        return dict(o)
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {"__klasse__": type(o).__name__, "werte": dataclasses.asdict(o)}
    if isinstance(o, (set, tuple)):
        return list(o)
    if isinstance(o, bytes):
        return {"__bytes__": base64.b64encode(o).decode()}
    raise TypeError(f"nicht übertragbar: {type(o).__name__}")


def _dekodieren(d: dict):
    if "__pfad__" in d and len(d) == 1:
        return Path(d["__pfad__"])
    if "__bytes__" in d and len(d) == 1:
        return base64.b64decode(d["__bytes__"])
    if "__klasse__" in d:
        if d["__klasse__"] == "Kanzlei":
            from core.kanzlei import Kanzlei
            felder = {f.name for f in dataclasses.fields(Kanzlei)}
            return Kanzlei(**{k: v for k, v in d["werte"].items() if k in felder})
        return d["werte"]
    return d


def dumps(o) -> bytes:
    return json.dumps(o, default=_kodieren, ensure_ascii=False).encode("utf-8")


def loads(b: bytes):
    return json.loads(b.decode("utf-8"), object_hook=_dekodieren)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_datei(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _nc(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _sicherer_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s or "").strip(" .")
    return s[:120] or "_"


def lokale_adressen(port: int) -> list[str]:
    """Adressen, unter denen andere Rechner diesen Server erreichen."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))          # kein Paket wird gesendet – nur Routing-Auswahl
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    standard = ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            standard = s.getsockname()[0]
    except OSError:
        pass
    ips = sorted((i for i in ips if not i.startswith("127.")), key=lambda i: (i != standard, i))
    name = socket.gethostname()
    return [f"https://{i}:{port}" for i in ips] + [f"https://{name}:{port}"]


def _signatur(schluessel: bytes, pfad: str, zaehler: int, meta: str, body: bytes) -> str:
    return hmac.new(schluessel, f"{pfad}|{zaehler}|{meta}|{_sha(body)}".encode(), hashlib.sha256).hexdigest()


# =========================================================================== SERVER
class Dienst:
    """Der zentrale Dienst. Hält die einzige Datenbankverbindung (serialisiert über eine Sperre)."""

    def __init__(self, daten_ordner: Path, app_ordner: Path | None = None, port: int = STANDARD_PORT,
                 host: str = "0.0.0.0", cfg: dict | None = None, version: str = ""):
        from core.adressbuch import Adressbuch
        from core.archiv import Archiv
        from core.journal import Journal
        from core.kanzlei import KanzleiStore
        from core.stammdaten import Stammdaten
        self.daten = Path(daten_ordner)
        self.app_ordner = app_ordner
        self.version = version
        self.lock = threading.RLock()
        self.db = self.daten / "verlauf.sqlite"
        self.journal = Journal(self.db, threads=True)
        con = self.journal.con
        self.buch = Adressbuch(con, (cfg or {}).get("versicherer_abkuerzungen", {}))
        self.objekte = {"journal": self.journal, "stammdaten": Stammdaten(con, self.buch), "archiv": Archiv(con),
                        "adressbuch": self.buch, "kanzlei": _ServerKanzlei(KanzleiStore(self.daten)),
                        "benutzer": bn.Benutzerverwaltung(con)}
        from core.nachrichten import Nachrichten
        from core.posteingang import Posteingang
        from core.unterlagen import Unterlagen
        from core.versand import Versand
        self.objekte["nachrichten"] = Nachrichten(con)
        self.objekte["posteingang"] = Posteingang(con)          # 0.5
        self.objekte["unterlagen"] = Unterlagen(con)
        self.objekte["versand"] = Versand(con)
        self.prot = pr.Protokoll(con)
        self.sitzungen: dict[str, dict] = {}
        self.nonces: dict[str, tuple[str, float]] = {}
        self.sperren: dict[str, tuple[str, float]] = {}
        self.wiederherstellungen: dict[str, Path] = {}
        self.generation = 1
        self.wartung = ""
        (self.daten / DOKUMENTE).mkdir(parents=True, exist_ok=True)
        dienst = self

        class Handler(_Handler):
            pass
        Handler.dienst = dienst
        cert, key, _ = zertifikat.sicherstellen(self.daten, [urllib.parse.urlsplit(a).hostname
                                                             for a in lokale_adressen(port or STANDARD_PORT)])
        self.cert_pem = cert.read_bytes()
        self.fingerabdruck = zertifikat.fingerabdruck(self.cert_pem)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(str(cert), str(key))
        self.http = ThreadingHTTPServer((host, port), Handler)
        self.http.socket = tls.wrap_socket(self.http.socket, server_side=True)
        self.http.daemon_threads = True
        self.port = self.http.server_address[1]
        self._thread: threading.Thread | None = None

    # --- Start/Stopp -------------------------------------------------------------
    def starten(self, suchdienst: bool = True) -> "Dienst":
        self._thread = threading.Thread(target=self.http.serve_forever, name="BnX-Server", daemon=True)
        self._thread.start()
        if suchdienst:
            self._such_starten()
        return self

    def kanzleiname(self) -> str:
        try:
            return self.objekte["kanzlei"].laden().name or ""
        except Exception:  # noqa: BLE001
            return ""

    def _such_starten(self) -> None:
        """Antwortet auf die automatische Suche der anderen Arbeitsplätze (UDP im Büronetz)."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", SUCH_PORT))
        except OSError:
            LOG.warning("Suchdienst nicht verfügbar (Port %s belegt)", SUCH_PORT)
            return
        self._such_socket = s

        def antworten():
            while True:
                try:
                    daten, absender = s.recvfrom(512)
                except OSError:
                    return
                if daten.strip() != SUCH_ANFRAGE:
                    continue
                bevorzugt = lokale_adressen(self.port)[0].split("//", 1)[-1].rsplit(":", 1)[0]
                antwort = json.dumps({"app": "BnX-Raptor", "kanzlei": self.kanzleiname(), "port": self.port,
                                      "rechner": socket.gethostname(), "version": self.version,
                                      "ip": bevorzugt}).encode("utf-8")
                with contextlib.suppress(OSError):
                    s.sendto(antwort, absender)
        threading.Thread(target=antworten, name="BnX-Suche", daemon=True).start()

    def beenden(self) -> None:
        with contextlib.suppress(Exception):
            self.http.shutdown()
            self.http.server_close()
        with contextlib.suppress(Exception):
            self._such_socket.close()
        with contextlib.suppress(Exception):
            self.journal.con.close()

    @property
    def benutzerverwaltung(self) -> bn.Benutzerverwaltung:
        return self.objekte["benutzer"]

    # --- Hilfen ------------------------------------------------------------------
    def _freigegeben(self, pfad: str) -> bool:
        """Nur Dateien, auf die die Datenbank verweist (oder die in der Ablage liegen), werden ausgeliefert."""
        k = _nc(pfad)
        if k.startswith(_nc(self.daten / DOKUMENTE) + os.sep):
            return True
        con = self.journal.con
        for tab, sp in (("dokumente", "pfad"), ("vorgaenge", "dokument"), ("vorgaenge", "ergebnis")):
            with contextlib.suppress(sqlite3.Error):
                for (v,) in con.execute(f"SELECT [{sp}] FROM [{tab}] WHERE [{sp}] LIKE ?", (f"%{Path(pfad).name}",)):
                    if v and _nc(v) == k:
                        return True
        with contextlib.suppress(sqlite3.Error):
            for (o,) in con.execute("SELECT ordner FROM akten WHERE COALESCE(ordner, '') != ''"):
                if k.startswith(_nc(o) + os.sep):
                    return True
        logo = self.objekte["kanzlei"].store.logo_pfad(self.objekte["kanzlei"].store.laden())
        return bool(logo and _nc(logo) == k)

    def ablage_ordner(self, akte: str) -> Path:
        o = self.daten / DOKUMENTE / (_sicherer_name(akte) if akte else "_ohne_Akte")
        o.mkdir(parents=True, exist_ok=True)
        return o

    def _frei(self, p: Path) -> Path:
        i = 2
        basis = p
        while p.exists():
            p = basis.with_name(f"{basis.stem} ({i}){basis.suffix}")
            i += 1
        return p


class _ServerKanzlei:
    """Kanzleidaten auf dem Server (Logo wird als Datei hochgeladen)."""

    def __init__(self, store):
        self.store = store

    def laden(self):
        return self.store.laden()

    def speichern(self, k):
        self.store.speichern(k)

    def logo_pfad(self, k):
        return self.store.logo_pfad(k)

    def logo_hochladen(self, name: str, daten: bytes) -> str:
        tmp = Path(tempfile.mkdtemp(prefix="bnx-logo-")) / _sicherer_name(name)
        try:
            tmp.write_bytes(daten)
            return self.store.logo_uebernehmen(tmp)
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)


class _Handler(BaseHTTPRequestHandler):
    dienst: Dienst
    protocol_version = "HTTP/1.1"
    server_version = "BnX-Raptor"

    def log_message(self, *a):                           # keine Zugriffsprotokolle (keine Inhalte im Log)
        pass

    # --- Antworten -----------------------------------------------------------------
    def _senden(self, status: int, body: bytes, typ: str = "application/json", kopf: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (kopf or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, wert=None, kopf=None):
        self._senden(200, dumps({"ok": True, "wert": wert}), kopf=kopf)

    def _fehler(self, art: str, text: str, daten=None, status: int = 200):
        self._senden(status, dumps({"ok": False, "fehler": {"art": art, "text": text, "daten": daten}}))

    # --- Eingang -------------------------------------------------------------------
    def do_POST(self):  # noqa: C901
        d = self.dienst
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(laenge) if laenge else b""
            meta_roh = self.headers.get("X-Meta", "")
            meta = json.loads(base64.urlsafe_b64decode(meta_roh.encode()).decode()) if meta_roh else {}
            pfad = self.path
            if pfad == "/ping":
                with d.lock:
                    leer = d.benutzerverwaltung.anzahl() == 0
                return self._ok({"app": "BnX-Raptor", "version": d.version, "benutzer_vorhanden": not leer,
                                 "rechner": socket.gethostname(), "kanzlei": d.kanzleiname()})
            if pfad == "/anmelden/start":
                name = str(meta.get("name", ""))
                with d.lock:
                    salz, it = d.benutzerverwaltung.anmeldedaten(name)
                nonce = secrets.token_hex(16)
                jetzt = time.time()
                for alt in [k for k, (_, z) in d.nonces.items() if jetzt - z > 120]:
                    d.nonces.pop(alt, None)                   # abgelaufene Anmeldeversuche entfernen
                d.nonces[nonce] = (name.lower(), jetzt)       # je Versuch eigener Schlüssel (mehrere PCs gleichzeitig)
                return self._ok({"salz": salz, "iterationen": it, "nonce": nonce})
            if pfad == "/anmelden/ende":
                name = str(meta.get("name", ""))
                nonce = str(meta.get("nonce", ""))
                wer, t = d.nonces.pop(nonce, ("", 0))
                if not nonce or wer != name.lower() or time.time() - t > 120:
                    return self._fehler("anmeldung", "Anmeldung abgelaufen – bitte erneut versuchen.")
                with d.lock:
                    erg = d.benutzerverwaltung.verifizieren(name, nonce, str(meta.get("beweis", "")))
                if not erg:
                    time.sleep(0.6)
                    return self._fehler("anmeldung", "Benutzername oder Passwort falsch – oder das Konto ist "
                                                     "deaktiviert.")
                b, k = erg
                sid = secrets.token_hex(16)
                d.sitzungen[sid] = {"b": b, "k": bn.sitzungsschluessel(k, nonce), "z": 0, "t": time.time()}
                return self._ok({"sitzung": sid, "benutzer": b})
            if pfad == "/erster_admin":
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._fehler("berechtigung", "Der erste Administrator kann nur am Server angelegt werden.")
                with d.lock:
                    if d.benutzerverwaltung.anzahl():
                        return self._fehler("wert", "Es gibt bereits Benutzer.")
                    tok = pr.setzen(pr.Benutzer(meta.get("name", ""), "admin", meta.get("anzeigename", "")))
                    try:
                        d.benutzerverwaltung.anlegen(meta.get("name", ""), meta.get("passwort", ""), "admin",
                                                     meta.get("anzeigename", ""))
                    except ValueError as e:
                        return self._fehler("wert", str(e))
                    finally:
                        pr.zuruecksetzen(tok)
                return self._ok(True)
            # ---- ab hier: signierte Anfragen ----
            sitz = self._sitzung(pfad, meta_roh, body)
            if sitz is None:
                return
            b = sitz["b"]
            tok = pr.setzen(pr.Benutzer(b["name"], b["rolle"], b.get("anzeigename") or ""))
            try:
                return self._signiert(pfad, meta, body, b)
            finally:
                pr.zuruecksetzen(tok)
        except (ConnectionError, BrokenPipeError):
            return
        except Exception as e:  # noqa: BLE001
            LOG.exception("Serverfehler")
            with contextlib.suppress(Exception):
                self._fehler("intern", f"Interner Fehler auf dem Server: {type(e).__name__}")

    def _sitzung(self, pfad: str, meta_roh: str, body: bytes) -> dict | None:
        d = self.dienst
        sid = self.headers.get("X-Sitzung", "")
        s = d.sitzungen.get(sid)
        if not s or time.time() - s["t"] > SITZUNG_GUELTIG:
            d.sitzungen.pop(sid, None)
            self._fehler("sitzung", "Die Anmeldung ist abgelaufen – bitte erneut anmelden.", status=401)
            return None
        try:
            z = int(self.headers.get("X-Zaehler", "0"))
        except ValueError:
            z = 0
        sig = _signatur(s["k"], pfad, z, meta_roh, body)
        if z <= s["z"] or not hmac.compare_digest(sig, self.headers.get("X-Signatur", "")):
            self._fehler("sitzung", "Ungültige Anfrage – bitte erneut anmelden.", status=401)
            return None
        with d.lock:
            aktiv = d.benutzerverwaltung.ist_aktiv(s["b"]["id"])
        if not aktiv:
            d.sitzungen.pop(sid, None)
            self._fehler("sitzung", "Ihr Konto wurde deaktiviert.", status=401)
            return None
        s["b"]["rolle"] = aktiv["rolle"]                 # Rollenänderung gilt sofort
        s["z"], s["t"] = z, time.time()
        return s

    def _signiert(self, pfad: str, meta: dict, body: bytes, b: dict):  # noqa: C901
        d = self.dienst
        rolle = b["rolle"]
        if pfad == "/aenderungen":
            with d.lock:
                eintraege = d.prot.seit(int(meta.get("seit", 0)))
                letzte = d.prot.letzte_id()
            return self._ok({"eintraege": eintraege, "letzte_id": letzte, "generation": d.generation,
                             "wartung": d.wartung})
        if pfad == "/abmelden":
            d.sitzungen.pop(self.headers.get("X-Sitzung", ""), None)
            return self._ok(True)
        if d.wartung and pfad not in ("/sicherung/status",):
            return self._fehler("wartung", d.wartung)
        if pfad == "/rpc":
            anfrage = loads(body) if body else {}
            objekt, methode = anfrage.get("objekt", ""), anfrage.get("methode", "")
            schreibt = methode in SCHREIBEN.get(objekt, set())
            if not (schreibt or methode in LESEN.get(objekt, set())):
                return self._fehler("berechtigung", f"Unbekannte Funktion {objekt}.{methode}.")
            # Lesen ist für alle Rollen erlaubt, Benutzerliste nur für Administratoren
            if schreibt or objekt == "benutzer":
                try:
                    bn.pruefen_recht(rolle, objekt, methode)
                except bn.Berechtigung as e:
                    return self._fehler("berechtigung", str(e))
            args, kwargs = anfrage.get("args", []), anfrage.get("kwargs", {})
            try:
                with d.lock:
                    wert = getattr(d.objekte[objekt], methode)(*args, **kwargs)
            except pr.Konflikt as e:
                return self._fehler("konflikt", str(e), e.als_dict())
            except bn.Berechtigung as e:
                return self._fehler("berechtigung", str(e))
            except ValueError as e:
                return self._fehler("wert", str(e))
            return self._ok(wert)
        if pfad == "/datei/holen":
            p = str(meta.get("pfad", ""))
            with d.lock:
                ok = d._freigegeben(p)
            if not ok or not Path(p).is_file():
                return self._fehler("datei", f"Die Datei „{Path(p).name}“ ist auf dem Server nicht vorhanden.")
            daten = Path(p).read_bytes()
            return self._senden(200, daten, "application/octet-stream", {"X-Sha": _sha(daten)})
        if pfad == "/datei/senden":
            return self._datei_senden(meta, body, b)
        if pfad == "/datei/sperren":
            return self._sperren(meta, b)
        if pfad.startswith("/sicherung/"):
            try:
                bn.pruefen_recht(rolle, "sicherung", pfad.rsplit("/", 1)[-1])
            except bn.Berechtigung as e:
                return self._fehler("berechtigung", str(e))
            return self._sicherung(pfad, meta, body)
        return self._fehler("intern", "Unbekannte Anfrage.")

    # --- Dateien ---------------------------------------------------------------------
    def _datei_senden(self, meta: dict, body: bytes, b: dict):
        d = self.dienst
        name = _sicherer_name(str(meta.get("name", "Datei")))
        akte = str(meta.get("akte", "") or "")
        ersetzt = str(meta.get("ersetzt", "") or "")
        with d.lock:
            if ersetzt:
                try:
                    bn.pruefen_recht(b["rolle"], "datei", "ersetzen")
                except bn.Berechtigung as e:
                    return self._fehler("berechtigung", str(e))
                ziel = Path(ersetzt)
                if not d._freigegeben(ersetzt):
                    return self._fehler("datei", "Diese Datei ist auf dem Server nicht bekannt.")
                aktuell = _sha_datei(ziel) if ziel.is_file() else ""
                if aktuell and aktuell == _sha(body):
                    return self._ok({"pfad": str(ziel), "konflikt": False, "sha": aktuell})
                if aktuell and aktuell != meta.get("basis_sha"):
                    # Gleichzeitig von jemand anderem gespeichert → nichts überschreiben: Konfliktkopie
                    stempel = datetime.now().strftime("%Y-%m-%d_%H-%M")
                    kopie = d._frei(ziel.with_name(f"{ziel.stem}_Konflikt_{_sicherer_name(b['name'])}_{stempel}"
                                                   f"{ziel.suffix}"))
                    kopie.write_bytes(body)
                    arch = d.objekte["archiv"]
                    doc = arch.dokument(arch.id_von(ziel)) if arch.id_von(ziel) else None
                    arch.erfassen(kopie, akte=(doc or {}).get("akte", "") or akte, rolle="bearbeitet", quelle=ziel,
                                  notiz=f"Konfliktkopie: {ziel.name} wurde gleichzeitig von jemand anderem geändert")
                    ref = (doc or {}).get("akte", "") or akte
                    if ref:                                   # im Verlauf der Akte sichtbar und zu öffnen
                        d.journal.add("akte", str(kopie), "", "", ref, art="dokument",
                                      meldung=f"Konfliktkopie von {ziel.name} (gleichzeitig gespeichert)")
                    return self._ok({"pfad": str(kopie), "konflikt": True, "sha": _sha(body)})
                tmp = ziel.with_name(ziel.name + ".bnx-tmp")
                tmp.write_bytes(body)
                os.replace(tmp, ziel)
                d.objekte["archiv"].bearbeitet(ziel)
                return self._ok({"pfad": str(ziel), "konflikt": False, "sha": _sha(body)})
            ordner = d.ablage_ordner(akte)
            ziel = ordner / name
            if ziel.exists() and _sha_datei(ziel) != _sha(body):
                ziel = d._frei(ziel)
            if not ziel.exists():
                ziel.write_bytes(body)
            if akte:
                a = d.journal.akte(akte)
                if a is not None and not a.get("ordner"):
                    d.journal.akte_speichern(akte, ordner=str(ordner))
        return self._ok({"pfad": str(ziel), "konflikt": False, "sha": _sha(body)})

    def _sperren(self, meta: dict, b: dict):
        d = self.dienst
        k = _nc(meta.get("pfad", ""))
        jetzt = time.time()
        for p, (_, t) in list(d.sperren.items()):
            if jetzt - t > SPERRE_GUELTIG:
                d.sperren.pop(p, None)
        wer = b.get("anzeigename") or b["name"]
        if meta.get("an"):
            anderer = d.sperren.get(k)
            if anderer and anderer[0] != wer:
                return self._ok({"von": anderer[0]})
            d.sperren[k] = (wer, jetzt)
            return self._ok({"von": ""})
        if d.sperren.get(k, ("",))[0] == wer:
            d.sperren.pop(k, None)
        return self._ok({"von": ""})

    # --- Sicherung ---------------------------------------------------------------------
    def _sicherung(self, pfad: str, meta: dict, body: bytes):
        from core import sicherung as s
        d = self.dienst
        if pfad == "/sicherung/erstellen":
            try:
                paket = s.paket_erstellen(d.db, d.daten, d.app_ordner, d.version)
            except s.SicherungFehler as e:
                return self._fehler("sicherung", str(e))
            try:
                daten = paket.zip_pfad.read_bytes()
                info = {"name": paket.zip_pfad.name, "anzahl": paket.manifest["anzahl"],
                        "dateien": sum(1 for e in paket.manifest["dateien"] if e.get("art") == "datei"),
                        "fehlend": paket.fehlend[:300]}
            finally:
                s.verwerfen(paket)
            d.prot.eintragen("sicherung", "", "erstellt_sicherung", [], info["name"])
            kopf = {"X-Info": base64.urlsafe_b64encode(dumps(info)).decode(), "X-Sha": _sha(daten)}
            return self._senden(200, daten, "application/octet-stream", kopf)
        if pfad == "/sicherung/pruefen":
            tmp = Path(tempfile.mkdtemp(prefix="bnx-hochgeladen-")) / "sicherung.zip"
            tmp.write_bytes(body)
            try:
                info = s.pruefen(tmp, d.version)
            except s.SicherungFehler as e:
                shutil.rmtree(tmp.parent, ignore_errors=True)
                return self._fehler("sicherung", str(e))
            token = secrets.token_hex(12)
            d.wiederherstellungen[token] = tmp
            with d.lock:
                con = d.journal.con
                aktuell = s._zaehlen(con)
            return self._ok({"token": token, "erstellt": info.erstellt, "programm_version": info.programm_version,
                             "anzahl": info.anzahl, "aktuell": aktuell, "dateien": info.dateien,
                             "sicherheitskopien": str(d.daten / s.SICHERHEITSKOPIEN)})
        if pfad == "/sicherung/wiederherstellen":
            tmp = d.wiederherstellungen.pop(str(meta.get("token", "")), None)
            if not tmp or not tmp.exists():
                return self._fehler("sicherung", "Die hochgeladene Sicherung ist nicht mehr vorhanden – bitte "
                                                 "erneut auswählen.")
            d.wartung = ("Auf dem Server wird gerade eine Sicherung wiederhergestellt – bitte kurz warten. Ihre "
                         "Eingaben bleiben erhalten.")
            try:
                time.sleep(0.3)                        # laufende Anfragen beenden lassen
                with d.lock:
                    erg = s.wiederherstellen(tmp, d.db, d.daten, d.app_ordner, d.version)
                    d.prot.eintragen("sicherung", "", "wiederhergestellt", [], tmp.name)
                d.generation += 1
                return self._ok({"sicherheitskopie": str(erg.sicherheitskopie), "dateien": erg.dateien,
                                 "umgezogen": erg.umgezogen})
            except s.SicherungFehler as e:
                return self._fehler("sicherung", str(e))
            finally:
                d.wartung = ""
                shutil.rmtree(tmp.parent, ignore_errors=True)
        return self._fehler("intern", "Unbekannte Anfrage.")


# =========================================================================== CLIENT
class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ZertifikatFehler("Server hat eine Weiterleitung gesendet; keine Daten übertragen.")


class _PinHandler(urllib.request.HTTPSHandler):
    def __init__(self, context: ssl.SSLContext, fingerabdruck: str):
        super().__init__(context=context)
        self._fp = fingerabdruck

    def https_open(self, req):
        fp = self._fp

        class Geprueft(http.client.HTTPSConnection):
            def connect(self):
                super().connect()
                der = self.sock.getpeercert(binary_form=True)
                if not hmac.compare_digest(zertifikat.fingerabdruck(der), fp):
                    self.close()
                    raise ZertifikatFehler(zertifikat_meldung(ssl.DER_cert_to_PEM_cert(der)))

        return self.do_open(Geprueft, req, context=self._context)


def zertifikat_meldung(pem: bytes | str) -> str:
    """Deutlicher Text, wenn das vorgelegte Zertifikat nicht das bestätigte ist (nie akzeptiert)."""
    name = zertifikat.scanner(pem) if pem else ""
    if name:
        return zertifikat.scanner_text(name)
    return ("Server-Zertifikat geändert oder ungültig – keine Daten übertragen. Bitte am Hauptrechner unter "
            "Einstellungen → Netzwerk den Kontrollcode prüfen und neu verbinden.")


class Verbindung:
    def __init__(self, adresse: str, timeout: float = 15.0, cert_pem: bytes | str | None = None):
        a = (adresse or "").strip().rstrip("/")
        if a and "://" not in a:
            a = "https://" + a
        url = urllib.parse.urlsplit(a)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.path or url.query \
                or url.fragment:
            raise ZertifikatFehler("Nur HTTPS-Adressen ohne Zugangsdaten sind erlaubt. Alte HTTP-Adressen müssen "
                                   "über die Server-Einstellungen neu verbunden werden.")
        self.adresse = f"https://{url.netloc}" if url.port else f"https://{url.netloc}:{STANDARD_PORT}"
        self.timeout = timeout
        self.cert_pem = cert_pem.encode() if isinstance(cert_pem, str) else cert_pem
        self.fingerabdruck = zertifikat.fingerabdruck(self.cert_pem) if self.cert_pem else ""
        self.sitzung = ""
        self.schluessel = b""
        self.zaehler = 0
        self.benutzer: dict | None = None
        self._lock = threading.Lock()
        self._anmeldung: tuple[str, str] | None = None

    def zertifikat_lesen(self) -> tuple[bytes, str]:
        """Yalnızca kimlik önizlemesi; doğrulama yapılmadan uygulama isteği gönderilmez."""
        url = urllib.parse.urlsplit(self.adresse)
        try:
            with socket.create_connection((url.hostname, url.port), timeout=self.timeout) as raw:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                with ctx.wrap_socket(raw, server_hostname=url.hostname) as tls:
                    der = tls.getpeercert(binary_form=True)
                    return ssl.DER_cert_to_PEM_cert(der).encode(), zertifikat.fingerabdruck(der)
        except (OSError, ssl.SSLError) as e:
            raise VerbindungFehler("TLS-Server nicht erreichbar; keine Daten übertragen.") from e

    def zertifikat_bestaetigen(self, erwarteter_fingerabdruck: str) -> None:
        """Karşılaştırma sunucudaki ekrandan yapılır; ağdan gelen iz tek başına kanıt değildir."""
        pem, fp = self.zertifikat_lesen()
        if not hmac.compare_digest(fp, erwarteter_fingerabdruck.strip().upper()):
            raise ZertifikatFehler("Zertifikat stimmt nicht mit dem Fingerabdruck am Hauptrechner überein. "
                                   "Keine Daten übertragen.")
        self.cert_pem = pem
        self.fingerabdruck = fp

    @property
    def lokal(self) -> bool:
        host = self.adresse.split("//", 1)[-1].rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost", "::1") or host.lower() == socket.gethostname().lower()

    def _http(self, pfad: str, meta: dict | None, body: bytes, signiert: bool, timeout: float | None = None):
        if not self.cert_pem:
            raise ZertifikatFehler("Server-Zertifikat nicht bestätigt. Bitte den Fingerabdruck am Hauptrechner "
                                   "vergleichen, bevor Sie sich anmelden.")
        meta_roh = base64.urlsafe_b64encode(dumps(meta or {})).decode() if meta else ""
        kopf = {"Content-Type": "application/octet-stream"}
        if meta_roh:
            kopf["X-Meta"] = meta_roh
        with self._lock:
            if signiert:
                if not self.sitzung:
                    raise SitzungFehler("Nicht angemeldet.")
                self.zaehler += 1
                kopf.update({"X-Sitzung": self.sitzung, "X-Zaehler": str(self.zaehler),
                             "X-Signatur": _signatur(self.schluessel, pfad, self.zaehler, meta_roh, body)})
            req = urllib.request.Request(self.adresse + pfad, data=body, headers=kopf, method="POST")
            try:
                ctx = ssl.create_default_context(cadata=self.cert_pem.decode("ascii"))
                ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
                ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
                # IP değişikliklerinde ad yerine onaylanmış tam sertifika ve parmak izi doğrulanır.
                ctx.check_hostname = False
                opener = urllib.request.build_opener(_PinHandler(ctx, self.fingerabdruck),
                                                    urllib.request.ProxyHandler({}), _KeineWeiterleitung())
                with opener.open(req, timeout=timeout or self.timeout) as r:
                    return r.read(), dict(r.headers)
            except urllib.error.HTTPError as e:
                return e.read(), dict(e.headers)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                grund = getattr(e, "reason", e)
                if isinstance(grund, ZertifikatFehler):
                    raise grund from e
                if isinstance(grund, ssl.SSLCertVerificationError) or isinstance(e, ssl.SSLCertVerificationError):
                    try:
                        pem = self.zertifikat_lesen()[0]
                    except VerbindungFehler:
                        pem = b""
                    raise ZertifikatFehler(zertifikat_meldung(pem)) from e
                raise VerbindungFehler(
                    f"Keine Verbindung zum Server ({self.adresse}). Ist der Server-Rechner eingeschaltet und "
                    "BnX-Raptor dort gestartet? Ihre Eingaben bleiben erhalten – es wurde nichts gespeichert.") from e

    def _json(self, pfad: str, meta: dict | None = None, body: bytes = b"", signiert: bool = True,
              timeout: float | None = None):
        daten, kopf = self._http(pfad, meta, body, signiert, timeout)
        if "json" not in (kopf.get("Content-Type") or ""):
            return daten, kopf
        antwort = loads(daten)
        if antwort.get("ok"):
            return antwort.get("wert"), kopf
        f = antwort.get("fehler") or {}
        art, text = f.get("art"), f.get("text") or "Fehler auf dem Server."
        if art == "sitzung":
            self.sitzung = ""
            if self._anmeldung and pfad not in ("/anmelden/start", "/anmelden/ende"):
                self.anmelden(*self._anmeldung)        # automatisch neu anmelden (z. B. nach Server-Neustart)
                return self._json(pfad, meta, body, signiert, timeout)
            raise SitzungFehler(text)
        if art == "konflikt":
            dd = f.get("daten") or {}
            raise pr.Konflikt(dd.get("art", ""), dd.get("objekt"), dd.get("felder", []), dd.get("aktuell", {}))
        if art == "berechtigung":
            raise bn.Berechtigung(text)
        if art == "wartung":
            raise WartungFehler(text)
        if art == "sicherung":
            from core.sicherung import SicherungFehler
            raise SicherungFehler(text)
        raise ValueError(text)

    # --- öffentlich -----------------------------------------------------------------
    def ping(self) -> dict:
        return self._json("/ping", signiert=False, timeout=5)[0]

    def anmelden(self, name: str, passwort: str) -> dict:
        start, _ = self._json("/anmelden/start", {"name": name}, signiert=False)
        k = bn.ableiten(passwort, start["salz"], int(start["iterationen"]))
        erg, _ = self._json("/anmelden/ende", {"name": name, "nonce": start["nonce"],
                                               "beweis": bn.beweis(k, start["nonce"])}, signiert=False)
        self.sitzung = erg["sitzung"]
        self.schluessel = bn.sitzungsschluessel(k, start["nonce"])
        self.zaehler = 0
        self.benutzer = erg["benutzer"]
        self._anmeldung = (name, passwort)
        return self.benutzer

    def erster_admin(self, name: str, passwort: str, anzeigename: str = "") -> None:
        self._json("/erster_admin", {"name": name, "passwort": passwort, "anzeigename": anzeigename},
                   signiert=False)

    def abmelden(self) -> None:
        with contextlib.suppress(Exception):
            self._json("/abmelden")
        self.sitzung = ""
        self._anmeldung = None

    def aufrufen(self, objekt: str, methode: str, args=(), kwargs=None):
        return self._json("/rpc", body=dumps({"objekt": objekt, "methode": methode, "args": list(args),
                                              "kwargs": kwargs or {}}))[0]

    def aenderungen(self, seit: int) -> dict:
        return self._json("/aenderungen", {"seit": seit}, timeout=8)[0]

    def datei_holen(self, pfad: str) -> tuple[bytes, str]:
        daten, kopf = self._json("/datei/holen", {"pfad": str(pfad)}, timeout=120)
        return daten, kopf.get("X-Sha") or _sha(daten)

    def datei_senden(self, daten: bytes, name: str, akte: str = "", ersetzt: str = "", basis_sha: str = "") -> dict:
        return self._json("/datei/senden", {"name": name, "akte": akte, "ersetzt": ersetzt, "basis_sha": basis_sha},
                          daten, timeout=300)[0]

    def sperren(self, pfad: str, an: bool = True) -> str:
        return (self._json("/datei/sperren", {"pfad": str(pfad), "an": an})[0] or {}).get("von", "")

    def sicherung_erstellen(self) -> tuple[bytes, dict]:
        daten, kopf = self._json("/sicherung/erstellen", timeout=3600)
        if isinstance(daten, (bytes, bytearray)):
            info = loads(base64.urlsafe_b64decode(kopf.get("X-Info", "").encode())) if kopf.get("X-Info") else {}
            if kopf.get("X-Sha") and kopf["X-Sha"] != _sha(daten):
                from core.sicherung import SicherungFehler
                raise SicherungFehler("Die Sicherung wurde bei der Übertragung beschädigt – bitte erneut versuchen.")
            return bytes(daten), info
        raise ValueError("Unerwartete Antwort des Servers.")

    def sicherung_pruefen(self, zip_daten: bytes) -> dict:
        return self._json("/sicherung/pruefen", body=zip_daten, timeout=3600)[0]

    def sicherung_wiederherstellen(self, token: str) -> dict:
        return self._json("/sicherung/wiederherstellen", {"token": token}, timeout=3600)[0]


# --------------------------------------------------------------------------- Client-Objekte (Proxys)
class _Fern:
    def __init__(self, v: Verbindung, objekt: str):
        self._v, self._objekt = v, objekt

    def __getattr__(self, methode: str):
        if methode.startswith("_"):
            raise AttributeError(methode)
        return lambda *a, **k: self._v.aufrufen(self._objekt, methode, a, k)


class Arbeitskopien:
    """Lokale Arbeitskopien der zentralen Dokumente. Merkt sich Server-Pfad und Prüfsumme beim Herunterladen,
    damit Änderungen mit Versionsprüfung zurückgeschrieben werden (nie stilles Überschreiben)."""

    def __init__(self, v: Verbindung, ordner: Path, direkt: bool = False):
        self.v = v
        self.ordner = Path(ordner)
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.index_datei = self.ordner / "index.json"
        try:
            self.index: dict[str, dict] = json.loads(self.index_datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.index = {}
        self.direkt = direkt                             # nur der Server-Rechner arbeitet direkt auf den Dateien
        self.konflikte: list[str] = []                   # beim Zurückschreiben entstandene Konfliktkopien
        self.in_bearbeitung: set[str] = set()            # gerade in Word/PDF-Editor geöffnete Arbeitskopien

    def _speichern(self):
        tmp = self.index_datei.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.index, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.index_datei)

    def _eintrag_lokal(self, lokal: Path) -> dict | None:
        return self.index.get(_nc(lokal))

    def akte_ordner(self, ref: str) -> Path:
        o = self.ordner / (_sicherer_name(ref) if ref else "_ohne_Akte")
        o.mkdir(parents=True, exist_ok=True)
        return o

    def lokal(self, server_pfad: str, ref: str = "") -> Path | None:
        """Datei zum Ansehen/Bearbeiten. Lokale, noch nicht zurückgeschriebene Änderungen werden NIE
        durch den Server-Stand ersetzt."""
        if not server_pfad:
            return None
        if self.direkt and Path(server_pfad).is_file():
            return Path(server_pfad)
        for k, e in self.index.items():
            if _nc(e["server"]) == _nc(server_pfad) and Path(e["lokal"]).is_file():
                lok = Path(e["lokal"])
                if _nc(lok) in self.in_bearbeitung or _sha_datei(lok) != e["sha"]:
                    return lok                           # geöffnet oder lokal geändert → nie ersetzen
                try:
                    daten, sha = self.v.datei_holen(server_pfad)
                except ValueError:
                    return lok
                if sha != e["sha"]:
                    lok.write_bytes(daten)
                    e["sha"] = sha
                    self._speichern()
                return lok
        try:
            daten, sha = self.v.datei_holen(server_pfad)
        except ValueError:
            return None
        ziel = self.akte_ordner(ref) / Path(server_pfad).name
        i = 2
        while ziel.exists() and _nc(ziel) in self.index:
            ziel = ziel.with_name(f"{Path(server_pfad).stem} ({i}){Path(server_pfad).suffix}")
            i += 1
        ziel.write_bytes(daten)
        self.index[_nc(ziel)] = {"lokal": str(ziel), "server": str(server_pfad), "sha": sha}
        self._speichern()
        return ziel

    def server_pfad(self, lokal, akte: str = "") -> str:
        """Lokale Datei → Pfad auf dem Server (lädt neue Dateien hoch, schreibt geänderte Arbeitskopien zurück)."""
        if not lokal:
            return lokal
        p = Path(lokal)
        e = self._eintrag_lokal(p)
        if e:
            if p.is_file() and _sha_datei(p) != e["sha"]:
                return self.zurueckschreiben(p)[0]
            return e["server"]
        if self.direkt and p.exists():
            return str(p)
        if not p.is_file():
            return str(lokal)
        erg = self.v.datei_senden(p.read_bytes(), p.name, akte)
        self.index[_nc(p)] = {"lokal": str(p), "server": erg["pfad"], "sha": erg["sha"]}
        self._speichern()
        return erg["pfad"]

    def zurueckschreiben(self, lokal: Path) -> tuple[str, bool]:
        """Geänderte Arbeitskopie hochladen. → (Server-Pfad, Konflikt?)"""
        p = Path(lokal)
        e = self._eintrag_lokal(p)
        if not e:
            return self.server_pfad(p), False
        erg = self.v.datei_senden(p.read_bytes(), p.name, ersetzt=e["server"], basis_sha=e["sha"])
        if erg.get("konflikt"):
            # Eigene Fassung liegt als Konfliktkopie auf dem Server: lokal unter deren Namen ablegen; die
            # Arbeitskopie des Originals gilt als unverändert und wird beim nächsten Öffnen aktualisiert.
            kopie = p.with_name(Path(erg["pfad"]).name)
            shutil.copy2(p, kopie)
            self.index[_nc(kopie)] = {"lokal": str(kopie), "server": erg["pfad"], "sha": erg["sha"]}
            e["sha"] = _sha_datei(p)
            self.konflikte.append(erg["pfad"])
            self._speichern()
            return erg["pfad"], True
        e["sha"] = erg["sha"]
        self._speichern()
        return erg["pfad"], bool(erg.get("konflikt"))


class FernArchiv(_Fern):
    def __init__(self, v, kopien: Arbeitskopien):
        super().__init__(v, "archiv")
        self._k = kopien

    def _konflikt_melden(self):
        if self._k.konflikte:
            sp = self._k.konflikte.pop()
            self._k.konflikte.clear()
            raise pr.Konflikt("dokument", sp, ["Datei"], {"geaendert_von": "einem anderen Benutzer"})

    def erfassen(self, pfad, akte: str = "", rolle: str = "original", quelle=None, notiz: str = ""):
        self._k.konflikte.clear()
        sp = self._k.server_pfad(pfad, akte)
        q = self._k.server_pfad(quelle, akte) if quelle else None
        erg = self._v.aufrufen("archiv", "erfassen", [sp], {"akte": akte, "rolle": rolle, "quelle": q,
                                                            "notiz": notiz})
        self._konflikt_melden()                          # gleichzeitig gespeichert → Konfliktkopie, Benutzer informieren
        return erg

    def bearbeitet(self, pfad):
        e = self._k._eintrag_lokal(Path(pfad))
        if e:
            self._k.konflikte.clear()
            self._k.zurueckschreiben(Path(pfad))
            self._konflikt_melden()
            return None
        return self._v.aufrufen("archiv", "bearbeitet", [str(pfad)])

    def id_von(self, pfad):
        e = self._k._eintrag_lokal(Path(pfad)) if pfad else None
        return self._v.aufrufen("archiv", "id_von", [e["server"] if e else str(pfad)])

    def arbeitskopie(self, quelle):
        e = self._k._eintrag_lokal(Path(quelle))
        sp = self._v.aufrufen("archiv", "arbeitskopie", [e["server"] if e else str(quelle)])
        return self._k.lokal(str(sp)) if sp else None


class FernJournal(_Fern):
    def __init__(self, v, kopien: Arbeitskopien):
        super().__init__(v, "journal")
        self._k = kopien

    def add(self, workflow, dokument, ergebnis="", empfaenger="", referenz="", status="ok", meldung="",
            art="ausgang", quelle_id=""):
        dok = self._k.server_pfad(dokument, referenz) if dokument and Path(str(dokument)).is_file() else dokument
        erg = self._k.server_pfad(ergebnis, referenz) if ergebnis and Path(str(ergebnis)).is_file() else ergebnis
        return self._v.aufrufen("journal", "add", [workflow, str(dok or ""), str(erg or "")],
                                {"empfaenger": empfaenger, "referenz": referenz, "status": status,
                                 "meldung": meldung, "art": art, "quelle_id": quelle_id})

    def akte_speichern(self, referenz, **werte):
        o = werte.get("ordner")
        if o and not self._k.direkt:
            werte.pop("ordner")                          # lokale Ordner gelten nicht für die anderen Rechner
        return self._v.aufrufen("journal", "akte_speichern", [referenz], werte)


class FernKanzlei:
    """Kanzleidaten vom Server (Logo als lokale Kopie)."""

    def __init__(self, v: Verbindung, kopien: Arbeitskopien):
        self._v, self._k = v, kopien
        self.ordner = kopien.ordner

    def laden(self):
        return self._v.aufrufen("kanzlei", "laden")

    def speichern(self, k):
        return self._v.aufrufen("kanzlei", "speichern", [k])

    def logo_uebernehmen(self, quelle) -> str:
        p = Path(quelle)
        return self._v.aufrufen("kanzlei", "logo_hochladen", [p.name, p.read_bytes()])

    def logo_pfad(self, k):
        sp = self._v.aufrufen("kanzlei", "logo_pfad", [k])
        return self._k.lokal(str(sp)) if sp else None


class LokaleDateien:
    """Einzelplatz: Dateien liegen direkt auf diesem Rechner."""
    direkt = True

    def lokal(self, pfad: str, ref: str = "") -> Path | None:
        return Path(pfad) if pfad and Path(pfad).exists() else None

    def akte_ordner(self, ref: str, ordner: str = "") -> Path | None:
        return Path(ordner) if ordner else None

    def sperren(self, pfad: str, an: bool = True) -> str:
        return ""


class FernDateien:
    """Client: Arbeitskopien + Bearbeitungssperren."""
    direkt = False

    def __init__(self, v: Verbindung, kopien: Arbeitskopien):
        self.v, self.k = v, kopien
        self.direkt = kopien.direkt

    def lokal(self, pfad: str, ref: str = "") -> Path | None:
        return self.k.lokal(pfad, ref)

    def akte_ordner(self, ref: str, ordner: str = "") -> Path | None:
        if self.k.direkt and ordner:
            return Path(ordner)
        return self.k.akte_ordner(ref)

    def sperren(self, pfad: str, an: bool = True) -> str:
        """Bearbeitungssperre auf dem Server + Schutz der geöffneten Arbeitskopie vor Aktualisierungen."""
        if an:
            self.k.in_bearbeitung.add(_nc(pfad))
        else:
            self.k.in_bearbeitung.discard(_nc(pfad))
        e = self.k._eintrag_lokal(Path(pfad))
        return self.v.sperren(e["server"] if e else str(pfad), an)


# --------------------------------------------------------------------------- automatische Suche (Client)
def suchen(wartezeit: float = 2.0) -> list[dict]:
    """Sucht BnX-Raptor-Server im Büronetz. → [{adresse, kanzlei, rechner, version}] (ohne Doppelte)."""
    ziele = {"255.255.255.255", "127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ziele.add(".".join(ip.split(".")[:3]) + ".255")      # gerichteter Broadcast (übliches /24-Netz)
    except OSError:
        pass
    gefunden: dict[str, dict] = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        for z in ziele:
            with contextlib.suppress(OSError):
                s.sendto(SUCH_ANFRAGE, (z, SUCH_PORT))
        ende = time.time() + wartezeit
        while time.time() < ende:
            try:
                daten, (ip, _) = s.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            try:
                d = json.loads(daten.decode("utf-8"))
            except ValueError:
                continue
            if d.get("app") != "BnX-Raptor":
                continue
            schluessel = f"{d.get('rechner')}:{d.get('port')}"
            haupt = d.get("ip") or ip
            eintrag = gefunden.setdefault(schluessel, {
                "adresse": f"https://{haupt}:{d.get('port')}", "ip": haupt, "alternativen": [],
                "kanzlei": d.get("kanzlei") or "", "rechner": d.get("rechner") or "", "version": d.get("version") or ""})
            alt = f"https://{ip}:{d.get('port')}"
            if alt != eintrag["adresse"] and alt not in eintrag["alternativen"]:
                eintrag["alternativen"].append(alt)
            # Aynı bilgisayardaki sunucu yalnızca loopback dinliyor olabilir;
            # LAN adresi bu durumda erişilemez. Uzak sunucuya loopback verilmez.
            if d.get("rechner", "").lower() == socket.gethostname().lower():
                loopback = f"https://127.0.0.1:{d.get('port')}"
                if loopback != eintrag["adresse"] and loopback not in eintrag["alternativen"]:
                    eintrag["alternativen"].append(loopback)
    finally:
        s.close()
    return sorted(gefunden.values(), key=lambda x: (x["kanzlei"], x["rechner"]))
