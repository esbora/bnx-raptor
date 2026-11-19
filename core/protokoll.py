"""Wer hat was geändert (0.4.2): aktueller Benutzer, Änderungsverlauf, Konfliktprüfung.

- Der aktuelle Benutzer steckt in einer Kontextvariablen: im Einzelplatz der Windows-Benutzer bzw. der
  angemeldete Benutzer, auf dem Server der Benutzer der jeweiligen Anfrage.
- `aenderungen`: Benutzer, Rolle, Zeit, Art (Mandant/Akte/…), Objekt, Aktion, geänderte Felder (nur Feldnamen –
  niemals Werte, Passwörter oder Zugangsdaten). Bleibt auch für deaktivierte Benutzer sichtbar.
- Konflikt: Änderungen werden feldweise gegen den beim Laden gesehenen Stand („Basis“) geprüft. Hat ein anderer
  dasselbe Feld inzwischen geändert, wird NICHT überschrieben, sondern `Konflikt` ausgelöst.
"""
from __future__ import annotations

import contextvars
import getpass
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS aenderungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT, benutzer TEXT, rolle TEXT,
    art TEXT, objekt TEXT, objekt_name TEXT DEFAULT '',
    aktion TEXT, felder TEXT DEFAULT '[]');
CREATE INDEX IF NOT EXISTS ix_aenderungen_objekt ON aenderungen(art, objekt);
"""

# Deutsche Feldnamen für den Änderungsverlauf
FELDNAMEN = {
    "name": "Name", "art": "Art", "strasse": "Straße", "plz": "PLZ", "ort": "Ort", "telefon": "Telefon",
    "email": "E-Mail", "notiz": "Notiz", "aktenzeichen": "Aktenzeichen", "mandant_id": "Mandant",
    "versicherung_id": "Versicherung", "versicherungsnummer": "Versicherungsnummer", "schaden_nr": "Schaden-Nr.",
    "mandant_name": "Name Mandant", "mandant_email": "E-Mail Mandant", "versicherer_email": "E-Mail Versicherung",
    "ordner": "Aktenordner", "standard_email": "Standard-E-Mail", "nummer_art": "Nummernart",
}
ROLLEN_TEXT = {"admin": "Administrator", "sekretariat": "Sekretariat", "anwalt": "Rechtsanwalt"}
ARTEN_TEXT = {"mandant": "Mandant", "akte": "Akte", "versicherung": "Versicherung", "dokument": "Dokument",
              "benutzer": "Benutzer", "sicherung": "Sicherung"}
AKTIONEN_TEXT = {"erstellt": "angelegt", "geaendert": "geändert", "geloescht": "gelöscht",
                 "dokument_hinzugefuegt": "Dokument hinzugefügt", "dokument_gespeichert": "Dokument gespeichert",
                 "dokument_zugeordnet": "Dokument zugeordnet", "email_hinzugefuegt": "E-Mail hinzugefügt",
                 "email_entfernt": "E-Mail entfernt", "passwort": "Passwort geändert",
                 "deaktiviert": "deaktiviert", "aktiviert": "aktiviert", "rolle": "Rolle geändert",
                 "wiederhergestellt": "Sicherung wiederhergestellt", "erstellt_sicherung": "Sicherung erstellt"}


@dataclass(frozen=True)
class Benutzer:
    name: str
    rolle: str = "admin"
    anzeigename: str = ""

    @property
    def text(self) -> str:
        return self.anzeigename or self.name


def _windows_benutzer() -> Benutzer:
    try:
        return Benutzer(getpass.getuser() or "Benutzer", "admin")
    except Exception:  # noqa: BLE001
        return Benutzer("Benutzer", "admin")


_AKTUELL: contextvars.ContextVar[Benutzer | None] = contextvars.ContextVar("bnx_benutzer", default=None)
_STANDARD: list[Benutzer] = []


def setzen(b: Benutzer | None, standard: bool = False):
    """Aktuellen Benutzer setzen. standard=True: gilt für alle Threads ohne eigenen Wert (Desktop-Programm)."""
    if standard:
        _STANDARD[:] = [b] if b else []
    return _AKTUELL.set(b)


def zuruecksetzen(token) -> None:
    _AKTUELL.reset(token)


def aktuell() -> Benutzer:
    return _AKTUELL.get() or (_STANDARD[0] if _STANDARD else _windows_benutzer())


def jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Konflikt(Exception):
    """Ein anderer Benutzer hat dieselben Felder inzwischen geändert. Nichts wurde überschrieben."""

    def __init__(self, art: str, objekt, felder: list[str], aktuell: dict):
        self.art, self.objekt, self.felder, self.aktuell = art, objekt, felder, aktuell
        von = aktuell.get("geaendert_von") or "einem anderen Benutzer"
        am = aktuell.get("geaendert_am") or aktuell.get("geaendert") or ""
        namen = ", ".join(FELDNAMEN.get(f, f) for f in felder)
        super().__init__(f"{ARTEN_TEXT.get(art, art)} wurde inzwischen von {von}"
                         + (f" am {_de(am)}" if am else "") + f" geändert ({namen}). Ihre Eingabe wurde nicht "
                         "gespeichert, aber nicht verworfen.")

    def als_dict(self) -> dict:
        return {"art": self.art, "objekt": self.objekt, "felder": self.felder, "aktuell": self.aktuell}


def _de(zeit: str) -> str:
    try:
        return datetime.strptime(zeit, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return zeit or ""


def gleich(a, b) -> bool:
    norm = (lambda v: "" if v is None else str(v).strip())
    return norm(a) == norm(b)


def konflikte(aktuell: dict, neu: dict, basis: dict | None) -> list[str]:
    """Felder, die der Benutzer ändern will, die aber seit dem Laden (basis) jemand anders geändert hat –
    und zwar auf einen anderen Wert als den neuen."""
    if basis is None:
        return []
    out = []
    for k, v in neu.items():
        if k in basis and not gleich(aktuell.get(k), basis[k]) and not gleich(aktuell.get(k), v):
            out.append(k)
    return out


def geaendert(aktuell: dict, neu: dict) -> dict:
    return {k: v for k, v in neu.items() if not gleich(aktuell.get(k), v)}


class Protokoll:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.executescript(SCHEMA)
        self.con.commit()

    def eintragen(self, art: str, objekt, aktion: str, felder: list[str] | None = None, objekt_name: str = "",
                  commit: bool = True) -> None:
        b = aktuell()
        self.con.execute(
            "INSERT INTO aenderungen (zeit, benutzer, rolle, art, objekt, objekt_name, aktion, felder)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (jetzt(), b.text, b.rolle, art, str(objekt), objekt_name, aktion,
             json.dumps([f for f in (felder or []) if f not in ("passwort", "hash", "salt")], ensure_ascii=False)))
        if commit:
            self.con.commit()

    def fuer(self, art: str, objekt) -> list[dict]:
        cur = self.con.execute("SELECT * FROM aenderungen WHERE art = ? AND objekt = ? ORDER BY id DESC",
                               (art, str(objekt)))
        return [_eintrag(dict(zip([c[0] for c in cur.description], r))) for r in cur.fetchall()]

    def seit(self, letzte_id: int, limit: int = 500) -> list[dict]:
        cur = self.con.execute("SELECT * FROM aenderungen WHERE id > ? ORDER BY id LIMIT ?", (letzte_id, limit))
        return [_eintrag(dict(zip([c[0] for c in cur.description], r))) for r in cur.fetchall()]

    def letzte_id(self) -> int:
        return int(self.con.execute("SELECT COALESCE(MAX(id), 0) FROM aenderungen").fetchone()[0])


def _eintrag(d: dict) -> dict:
    try:
        felder = json.loads(d.get("felder") or "[]")
    except ValueError:
        felder = []
    d["felder"] = felder
    feldtext = ", ".join(FELDNAMEN.get(f, f) for f in felder)
    aktion = AKTIONEN_TEXT.get(d["aktion"], d["aktion"])
    if d["aktion"].startswith("dokument_") or d["aktion"].startswith("email_"):
        d["text"] = f"{aktion}: {d.get('objekt_name') or ''}".rstrip(": ")
    elif d["aktion"] == "geaendert" and feldtext:
        d["text"] = f"{feldtext} geändert"
    else:
        d["text"] = f"{ARTEN_TEXT.get(d['art'], d['art'])} {aktion}" + (f" ({feldtext})" if feldtext else "")
    d["rolle_text"] = ROLLEN_TEXT.get(d.get("rolle") or "", d.get("rolle") or "")
    d["zeit_text"] = _de(d["zeit"])
    return d


def meta_text(d: dict | None) -> str:
    """„Erstellt von … am … · Zuletzt geändert von … am …“"""
    if not d:
        return ""
    teile = []
    e_von, e_am = d.get("erstellt_von") or "", d.get("erstellt_am") or d.get("angelegt") or ""
    g_von, g_am = d.get("geaendert_von") or "", d.get("geaendert_am") or d.get("geaendert") or ""
    if e_von or e_am:
        teile.append("Erstellt" + (f" von {e_von}" if e_von else "") + (f" am {_de(e_am)}" if e_am else ""))
    if g_von or g_am:
        teile.append("Zuletzt geändert" + (f" von {g_von}" if g_von else "") + (f" am {_de(g_am)}" if g_am else ""))
    return " · ".join(teile)
