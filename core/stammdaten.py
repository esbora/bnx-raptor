"""Mandanten und Versicherungen (0.4.1) – in derselben SQLite-Datenbank wie Akten und Verlauf.

- Mandant: Person oder Firma (Name, Anschrift, Telefon, E-Mail, Notiz). Ein Mandant kann mehrere Akten haben.
- Versicherung: Firma mit Anschrift, Telefon, Notiz. Die E-Mail-Adressen kommen aus dem bestehenden
  Versicherer-Adressbuch (Tabelle `versicherer`) – es gibt nur EINE Stelle für Versicherer-E-Mails.
  Adressbuch-Einträge ohne eigenen Versicherungs-Datensatz erscheinen trotzdem in der Liste.
- Akte: zusätzlich Aktenzeichen, Mandant, Versicherung, Versicherungsnummer und Schaden-Nr. (getrennte
  Felder). Alte Akten (nur `referenz` + `nummer_art`) funktionieren unverändert weiter.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from core.adressbuch import Adressbuch

SCHEMA = """
CREATE TABLE IF NOT EXISTS mandanten (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    art TEXT DEFAULT 'person', name TEXT NOT NULL,
    strasse TEXT DEFAULT '', plz TEXT DEFAULT '', ort TEXT DEFAULT '',
    telefon TEXT DEFAULT '', email TEXT DEFAULT '', notiz TEXT DEFAULT '',
    angelegt TEXT, geaendert TEXT);
CREATE TABLE IF NOT EXISTS versicherungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    strasse TEXT DEFAULT '', plz TEXT DEFAULT '', ort TEXT DEFAULT '',
    telefon TEXT DEFAULT '', notiz TEXT DEFAULT '',
    angelegt TEXT, geaendert TEXT);
"""
AKTEN_SPALTEN = [("aktenzeichen", "TEXT DEFAULT ''"), ("mandant_id", "INTEGER"), ("versicherung_id", "INTEGER"),
                 ("versicherungsnummer", "TEXT DEFAULT ''"), ("schaden_nr", "TEXT DEFAULT ''")]
MANDANT_FELDER = ("art", "name", "strasse", "plz", "ort", "telefon", "email", "notiz")
VERSICHERUNG_FELDER = ("name", "strasse", "plz", "ort", "telefon", "notiz")


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _zeilen(cur) -> list[dict]:
    namen = [c[0] for c in cur.description]
    return [dict(zip(namen, r)) for r in cur.fetchall()]


class Stammdaten:
    def __init__(self, con: sqlite3.Connection, adressbuch: Adressbuch):
        self.con, self.buch = con, adressbuch
        self.con.executescript(SCHEMA)
        vorhanden = {r[1] for r in self.con.execute("PRAGMA table_info(akten)")}
        for spalte, typ in AKTEN_SPALTEN:
            if vorhanden and spalte not in vorhanden:
                self.con.execute(f"ALTER TABLE akten ADD COLUMN {spalte} {typ}")
        self.con.commit()

    # --- Mandanten -------------------------------------------------------------
    def mandanten(self, suche: str = "") -> list[dict]:
        like = f"%{suche}%"
        return _zeilen(self.con.execute(
            "SELECT m.*, (SELECT COUNT(*) FROM akten a WHERE a.mandant_id = m.id) AS akten FROM mandanten m"
            " WHERE m.name LIKE ? OR m.email LIKE ? OR m.ort LIKE ? ORDER BY m.name COLLATE NOCASE",
            (like, like, like)))

    def mandant(self, mid: int) -> dict | None:
        r = _zeilen(self.con.execute("SELECT * FROM mandanten WHERE id = ?", (mid,)))
        return r[0] if r else None

    def mandant_speichern(self, mid: int | None, **werte) -> int:
        werte = {k: str(v or "").strip() for k, v in werte.items() if k in MANDANT_FELDER}
        if not werte.get("name", "x"):
            raise ValueError("Bitte einen Namen oder Firmennamen eingeben.")
        if mid is None:
            werte.setdefault("art", "person")
            cur = self.con.execute(
                f"INSERT INTO mandanten ({', '.join(werte)}, angelegt, geaendert) VALUES "
                f"({', '.join('?' * len(werte))}, ?, ?)", (*werte.values(), _jetzt(), _jetzt()))
            self.con.commit()
            return int(cur.lastrowid)
        self.con.execute(f"UPDATE mandanten SET {', '.join(f'{k} = ?' for k in werte)}, geaendert = ? WHERE id = ?",
                         (*werte.values(), _jetzt(), mid))
        self.con.commit()
        return mid

    def mandant_loeschen(self, mid: int) -> None:
        """Akten bleiben erhalten (nur die Verknüpfung wird gelöst)."""
        self.con.execute("UPDATE akten SET mandant_id = NULL WHERE mandant_id = ?", (mid,))
        self.con.execute("DELETE FROM mandanten WHERE id = ?", (mid,))
        self.con.commit()

    # --- Versicherungen (E-Mails = Adressbuch) --------------------------------
    def versicherungen(self, suche: str = "") -> list[dict]:
        """Eigene Datensätze + Adressbuch-Namen ohne Datensatz (id = None, quelle = 'Adressbuch')."""
        eigene = _zeilen(self.con.execute("SELECT * FROM versicherungen ORDER BY name COLLATE NOCASE"))
        for v in eigene:
            v["emails"] = [e for e, _ in self.buch.emails(v["name"])]
            v["quelle"] = "Stammdaten"
        schluessel = [self.buch._key(v["name"]) for v in eigene]
        nur_buch: dict[str, dict] = {}
        for r in self.buch.alle():
            k = self.buch._key(r["name"])
            if any(k == s for s in schluessel):
                continue
            eintrag = nur_buch.setdefault(k.voll, {"id": None, "name": r["name"], "strasse": "", "plz": "", "ort": "",
                                                  "telefon": "", "notiz": "", "emails": [], "quelle": "Adressbuch"})
            if r["email"] not in eintrag["emails"]:
                eintrag["emails"].append(r["email"])
        alle = eigene + list(nur_buch.values())
        s = suche.lower().strip()
        if s:
            alle = [v for v in alle if s in v["name"].lower() or any(s in e.lower() for e in v["emails"])]
        return sorted(alle, key=lambda v: v["name"].lower())

    def versicherung(self, vid: int) -> dict | None:
        r = _zeilen(self.con.execute("SELECT * FROM versicherungen WHERE id = ?", (vid,)))
        if not r:
            return None
        r[0]["emails"] = [e for e, _ in self.buch.emails(r[0]["name"])]
        return r[0]

    def versicherung_speichern(self, vid: int | None, **werte) -> int:
        """Anlegen/ändern. Bei Umbenennung werden die Adressbuch-Einträge mit umbenannt."""
        werte = {k: str(v or "").strip() for k, v in werte.items() if k in VERSICHERUNG_FELDER}
        if "name" in werte and not werte["name"]:
            raise ValueError("Bitte den Namen der Versicherung eingeben.")
        if vid is None:
            vorhanden = next((v for v in self.versicherungen() if v["id"] is not None
                              and self.buch._key(v["name"]) == self.buch._key(werte.get("name", ""))), None)
            if vorhanden:
                vid = vorhanden["id"]
            else:
                cur = self.con.execute(
                    f"INSERT INTO versicherungen ({', '.join(werte)}, angelegt, geaendert) VALUES "
                    f"({', '.join('?' * len(werte))}, ?, ?)", (*werte.values(), _jetzt(), _jetzt()))
                self.con.commit()
                return int(cur.lastrowid)
        alt = self.versicherung(vid)
        if alt and "name" in werte and werte["name"] != alt["name"]:
            for r in self.buch.treffer(alt["name"]):
                self.con.execute("UPDATE versicherer SET name = ? WHERE id = ?", (werte["name"], r["id"]))
        self.con.execute(f"UPDATE versicherungen SET {', '.join(f'{k} = ?' for k in werte)}, geaendert = ? "
                         f"WHERE id = ?", (*werte.values(), _jetzt(), vid))
        self.con.commit()
        return vid

    def email_hinzufuegen(self, vid: int, email: str) -> None:
        v = self.versicherung(vid)
        if v:
            self.buch.hinzufuegen(v["name"], email)

    def email_entfernen(self, vid: int, email: str) -> None:
        v = self.versicherung(vid)
        if not v:
            return
        for r in self.buch.treffer(v["name"]):
            if r["email"].lower() == email.lower():
                self.buch.loeschen(r["id"])

    # --- Akten -----------------------------------------------------------------
    def akte_anlegen(self, referenz: str, **werte) -> None:
        referenz = referenz.strip()
        if not referenz:
            raise ValueError("Bitte ein Aktenzeichen oder eine Versicherungsnummer eingeben.")
        self.con.execute("INSERT OR IGNORE INTO akten (referenz, angelegt) VALUES (?, ?)", (referenz, _jetzt()))
        self.con.commit()
        self.akte_setzen(referenz, **werte)

    def akte_setzen(self, referenz: str, **werte) -> None:
        erlaubt = {"aktenzeichen", "mandant_id", "versicherung_id", "versicherungsnummer", "schaden_nr",
                   "mandant_name", "mandant_email", "versicherer_email", "notiz", "ordner"}
        werte = {k: v for k, v in werte.items() if k in erlaubt}
        if not werte:
            return
        self.con.execute(f"UPDATE akten SET {', '.join(f'{k} = ?' for k in werte)} WHERE referenz = ?",
                         (*werte.values(), referenz))
        self.con.commit()

    def akte(self, referenz: str) -> dict | None:
        r = _zeilen(self.con.execute("SELECT * FROM akten WHERE referenz = ?", (referenz,)))
        if not r:
            return None
        a = r[0]
        # Alte Akten: Nummer stand nur in `referenz` (+ nummer_art) → in das passende Feld übernehmen
        if not a.get("versicherungsnummer") and not a.get("schaden_nr"):
            if a.get("nummer_art") == "Schaden-Nr.":
                a["schaden_nr"] = a["referenz"]
            elif a.get("nummer_art"):
                a["versicherungsnummer"] = a["referenz"]
        return a

    def akten_von_mandant(self, mid: int) -> list[dict]:
        return _zeilen(self.con.execute("SELECT * FROM akten WHERE mandant_id = ? ORDER BY angelegt DESC", (mid,)))

    def akten_von_versicherung(self, vid: int) -> list[dict]:
        return _zeilen(self.con.execute("SELECT * FROM akten WHERE versicherung_id = ? ORDER BY angelegt DESC",
                                        (vid,)))
