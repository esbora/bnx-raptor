"""Benutzer und Rollen (0.4.2, Mehrbenutzerbetrieb).

Passwörter werden nur als PBKDF2-HMAC-SHA256-Hash (zufälliges Salz, 240 000 Iterationen) gespeichert.
Die Anmeldung über das Netz ist ein Challenge-Response-Verfahren: das Passwort selbst wird nie übertragen.

Rollen und Rechte (werden auf dem Server bei JEDER Anfrage geprüft):
- Administrator: alles, zusätzlich Benutzer, Verbindungseinstellungen, Sicherung/Wiederherstellung
- Sekretariat:   Mandanten, Akten/Mandate, Versicherungen anlegen und ändern, Kontaktdaten, Dokumente hinzufügen
- Rechtsanwalt:  sieht und korrigiert alles, bearbeitet Dokumente, Outlook-Entwürfe (lokal), Verlauf
0.5 (Posteingang/Aufgaben/Unterlagen): Sekretariat erfasst, ordnet zu und bereitet vor; Aufgaben für andere,
„Geprüft / vollständig“ und Checklisten-Vorlagen: Rechtsanwalt/Administrator (Prüfung im Kern = auf dem Server).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime

ITERATIONEN = 240_000
ROLLEN = {"admin": "Administrator", "sekretariat": "Sekretariat", "anwalt": "Rechtsanwalt"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS benutzer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    anzeigename TEXT DEFAULT '',
    rolle TEXT NOT NULL,
    salz TEXT NOT NULL, hash TEXT NOT NULL, iterationen INTEGER NOT NULL,
    aktiv INTEGER DEFAULT 1,
    erstellt_am TEXT, erstellt_von TEXT DEFAULT '', geaendert_am TEXT DEFAULT '');
"""

# Rechte: Methoden, die eine Rolle NICHT aufrufen darf (alles andere ist erlaubt). Benutzer-/Sicherungs-
# Funktionen sind zusätzlich nur für Administratoren (siehe NUR_ADMIN).
NUR_ADMIN = {"benutzer.*", "sicherung.*", "server.*"}
VERBOTEN = {
    "sekretariat": {"archiv.bearbeitet", "datei.ersetzen", "journal.bearbeitet_setzen",
                    "unterlagen.vorlage_speichern", "unterlagen.vorlage_loeschen"},
    "anwalt": set(),
    "admin": set(),
}


class Berechtigung(Exception):
    pass


def erlaubt(rolle: str, objekt: str, methode: str) -> bool:
    schluessel = f"{objekt}.{methode}"
    if schluessel == "benutzer.eigenes_passwort":       # jeder darf sein eigenes Passwort ändern
        return rolle in ROLLEN
    if rolle != "admin" and (f"{objekt}.*" in NUR_ADMIN or schluessel in NUR_ADMIN):
        return False
    return schluessel not in VERBOTEN.get(rolle, {"*"}) and rolle in ROLLEN


def pruefen_recht(rolle: str, objekt: str, methode: str) -> None:
    if not erlaubt(rolle, objekt, methode):
        raise Berechtigung(f"Keine Berechtigung: Diese Aktion ist für die Rolle „{ROLLEN.get(rolle, rolle)}“ "
                           "nicht freigegeben. Bitte an einen Administrator oder Rechtsanwalt wenden.")


def ableiten(passwort: str, salz: str, iterationen: int = ITERATIONEN) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), bytes.fromhex(salz), iterationen)


def beweis(schluessel: bytes, nonce: str) -> str:
    return hmac.new(schluessel, ("anmelden|" + nonce).encode(), hashlib.sha256).hexdigest()


def sitzungsschluessel(schluessel: bytes, nonce: str) -> bytes:
    return hmac.new(schluessel, ("sitzung|" + nonce).encode(), hashlib.sha256).digest()


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _passwort_regeln(pw: str) -> None:
    if len(pw or "") < 8:
        raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")


class Benutzerverwaltung:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.executescript(SCHEMA)
        self.con.commit()
        self._pfeffer = secrets.token_hex(16)        # nur für Schein-Salz unbekannter Namen

    # --- Abfragen ---------------------------------------------------------------
    def liste(self) -> list[dict]:
        cur = self.con.execute("SELECT id, name, anzeigename, rolle, aktiv, erstellt_am, erstellt_von, geaendert_am "
                               "FROM benutzer ORDER BY aktiv DESC, name COLLATE NOCASE")
        namen = [c[0] for c in cur.description]
        out = [dict(zip(namen, r)) for r in cur.fetchall()]
        for b in out:
            b["rolle_text"] = ROLLEN.get(b["rolle"], b["rolle"])
        return out

    def anzahl(self) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM benutzer").fetchone()[0])

    def _zeile(self, name: str) -> dict | None:
        cur = self.con.execute("SELECT * FROM benutzer WHERE name = ?", (name.strip(),))
        r = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], r)) if r else None

    def benutzer(self, bid: int) -> dict | None:
        cur = self.con.execute("SELECT id, name, anzeigename, rolle, aktiv FROM benutzer WHERE id = ?", (bid,))
        r = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], r)) if r else None

    # --- Anmeldung --------------------------------------------------------------
    def anmeldedaten(self, name: str) -> tuple[str, int]:
        """Salz + Iterationen. Für unbekannte Namen ein gleichbleibendes Schein-Salz (verrät nicht, ob es den
        Benutzer gibt)."""
        z = self._zeile(name)
        if z:
            return z["salz"], z["iterationen"]
        return hashlib.sha256((self._pfeffer + name.lower()).encode()).hexdigest()[:32], ITERATIONEN

    def verifizieren(self, name: str, nonce: str, gesendet: str) -> tuple[dict, bytes] | None:
        z = self._zeile(name)
        if not z or not z["aktiv"]:
            return None
        k = bytes.fromhex(z["hash"])
        if not hmac.compare_digest(beweis(k, nonce), gesendet or ""):
            return None
        return {"id": z["id"], "name": z["name"], "anzeigename": z["anzeigename"], "rolle": z["rolle"]}, k

    def passwort_pruefen(self, name: str, passwort: str) -> dict | None:
        """Lokale Prüfung (Server-Rechner)."""
        z = self._zeile(name)
        if not z or not z["aktiv"]:
            return None
        if not hmac.compare_digest(ableiten(passwort, z["salz"], z["iterationen"]).hex(), z["hash"]):
            return None
        return {"id": z["id"], "name": z["name"], "anzeigename": z["anzeigename"], "rolle": z["rolle"]}

    def ist_aktiv(self, bid: int) -> dict | None:
        b = self.benutzer(bid)
        return b if b and b["aktiv"] else None

    # --- Verwaltung (nur Administrator) ----------------------------------------
    def anlegen(self, name: str, passwort: str, rolle: str, anzeigename: str = "") -> int:
        from core.protokoll import Protokoll, aktuell
        name = (name or "").strip()
        if not name:
            raise ValueError("Bitte einen Benutzernamen eingeben.")
        if rolle not in ROLLEN:
            raise ValueError("Unbekannte Rolle.")
        _passwort_regeln(passwort)
        if self._zeile(name):
            raise ValueError(f"Den Benutzer „{name}“ gibt es schon.")
        salz = secrets.token_hex(16)
        cur = self.con.execute(
            "INSERT INTO benutzer (name, anzeigename, rolle, salz, hash, iterationen, aktiv, erstellt_am, erstellt_von)"
            " VALUES (?,?,?,?,?,?,1,?,?)",
            (name, anzeigename.strip(), rolle, salz, ableiten(passwort, salz).hex(), ITERATIONEN, _jetzt(),
             aktuell().text if self.anzahl() else name))
        Protokoll(self.con).eintragen("benutzer", cur.lastrowid, "erstellt", ["rolle"], name, commit=False)
        self.con.commit()
        return int(cur.lastrowid)

    def passwort_setzen(self, bid: int, passwort: str) -> None:
        from core.protokoll import Protokoll
        _passwort_regeln(passwort)
        salz = secrets.token_hex(16)
        self.con.execute("UPDATE benutzer SET salz = ?, hash = ?, iterationen = ?, geaendert_am = ? WHERE id = ?",
                         (salz, ableiten(passwort, salz).hex(), ITERATIONEN, _jetzt(), bid))
        b = self.benutzer(bid) or {}
        Protokoll(self.con).eintragen("benutzer", bid, "passwort", [], b.get("name", ""), commit=False)
        self.con.commit()

    def _admins_aktiv(self, ausser: int) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM benutzer WHERE rolle = 'admin' AND aktiv = 1 AND id != ?",
                                    (ausser,)).fetchone()[0])

    def rolle_setzen(self, bid: int, rolle: str) -> None:
        from core.protokoll import Protokoll
        if rolle not in ROLLEN:
            raise ValueError("Unbekannte Rolle.")
        b = self.benutzer(bid)
        if b and b["rolle"] == "admin" and rolle != "admin" and not self._admins_aktiv(bid):
            raise ValueError("Es muss mindestens ein aktiver Administrator bleiben.")
        self.con.execute("UPDATE benutzer SET rolle = ?, geaendert_am = ? WHERE id = ?", (rolle, _jetzt(), bid))
        Protokoll(self.con).eintragen("benutzer", bid, "rolle", ["rolle"], (b or {}).get("name", ""), commit=False)
        self.con.commit()

    def aktiv_setzen(self, bid: int, aktiv: bool) -> None:
        from core.protokoll import Protokoll
        b = self.benutzer(bid)
        if b and not aktiv and b["rolle"] == "admin" and not self._admins_aktiv(bid):
            raise ValueError("Der letzte aktive Administrator kann nicht deaktiviert werden.")
        self.con.execute("UPDATE benutzer SET aktiv = ?, geaendert_am = ? WHERE id = ?", (1 if aktiv else 0,
                                                                                         _jetzt(), bid))
        Protokoll(self.con).eintragen("benutzer", bid, "aktiviert" if aktiv else "deaktiviert", [],
                                      (b or {}).get("name", ""), commit=False)
        self.con.commit()

    def eigenes_passwort(self, alt: str, neu: str) -> None:
        from core.protokoll import aktuell
        ich = self.passwort_pruefen(aktuell().name, alt)
        if not ich:
            raise ValueError("Das bisherige Passwort ist falsch.")
        self.passwort_setzen(ich["id"], neu)

    def anzeigename_setzen(self, bid: int, anzeigename: str) -> None:
        self.con.execute("UPDATE benutzer SET anzeigename = ?, geaendert_am = ? WHERE id = ?",
                         (anzeigename.strip(), _jetzt(), bid))
        self.con.commit()
