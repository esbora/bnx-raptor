"""Büro-Nachrichten (0.4.2): Eins-zu-eins-Nachrichten zwischen Benutzern, zentral in der Datenbank des Servers.

- Jede Abfrage ist an den angemeldeten Benutzer gebunden (protokoll.aktuell()): man sieht nur Gespräche, an denen
  man beteiligt ist – auf dem Server erzwungen, nicht nur in der Oberfläche.
- `client_id` (vom absendenden PC erzeugt) macht das Senden wiederholbar: derselbe Text wird bei erneutem Versuch
  nie doppelt angelegt.
- „Gelesen“ setzt nur der Empfänger, wenn er das Gespräch geöffnet und die Nachricht gesehen hat.
- Optional verknüpft: Akte (Referenz) und Mandant (Id).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from core import protokoll as pr

SCHEMA = """
CREATE TABLE IF NOT EXISTS nachrichten (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    absender TEXT NOT NULL, empfaenger TEXT NOT NULL,
    text TEXT NOT NULL, zeit TEXT NOT NULL,
    akte TEXT DEFAULT '', mandant_id INTEGER,
    client_id TEXT NOT NULL, gelesen TEXT DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS ix_nachrichten_client ON nachrichten(absender, client_id);
CREATE INDEX IF NOT EXISTS ix_nachrichten_paar ON nachrichten(absender, empfaenger);
"""
SPALTEN = [("aufgabe_id", "INTEGER")]                 # 0.5: Nachricht verweist auf eine Aufgabe
MAX_LAENGE = 8000


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Nachrichten:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.executescript(SCHEMA)
        vorhanden = {r[1] for r in self.con.execute("PRAGMA table_info(nachrichten)")}
        for spalte, typ in SPALTEN:
            if spalte not in vorhanden:
                self.con.execute(f"ALTER TABLE nachrichten ADD COLUMN {spalte} {typ}")
        self.con.commit()

    # --- Hilfen -----------------------------------------------------------------
    @staticmethod
    def _ich() -> str:
        return pr.aktuell().name

    def _zeilen(self, sql: str, werte=()) -> list[dict]:
        cur = self.con.execute(sql, werte)
        namen = [c[0] for c in cur.description]
        return [dict(zip(namen, r)) for r in cur.fetchall()]

    def _benutzer(self) -> dict[str, dict]:
        try:
            z = self._zeilen("SELECT name, anzeigename, rolle, aktiv FROM benutzer")
        except sqlite3.Error:
            z = []
        return {b["name"].lower(): b for b in z}

    def _anzeige(self, name: str, benutzer: dict | None = None) -> str:
        b = (benutzer or self._benutzer()).get(name.lower())
        return (b or {}).get("anzeigename") or name

    # --- öffentlich ---------------------------------------------------------------
    def kontakte(self) -> list[dict]:
        """Alle aktiven Benutzer außer mir – mit Rolle, letzter Nachricht und Zahl ungelesener Nachrichten."""
        from core.benutzer import ROLLEN
        ich = self._ich().lower()
        benutzer = self._benutzer()
        letzte = {}
        for r in self._zeilen(
                "SELECT CASE WHEN lower(absender) = ? THEN lower(empfaenger) ELSE lower(absender) END AS partner,"
                " MAX(id) AS letzte_id, MAX(zeit) AS letzte_zeit FROM nachrichten"
                " WHERE lower(absender) = ? OR lower(empfaenger) = ? GROUP BY partner", (ich, ich, ich)):
            letzte[r["partner"]] = r
        ungelesen = {r["a"]: r["n"] for r in self._zeilen(
            "SELECT lower(absender) AS a, COUNT(*) AS n FROM nachrichten WHERE lower(empfaenger) = ? AND gelesen = ''"
            " GROUP BY a", (ich,))}
        out = []
        for k, b in benutzer.items():
            if k == ich or (not b["aktiv"] and k not in letzte):
                continue
            l = letzte.get(k, {})
            text = ""
            if l:
                text = self.con.execute("SELECT text FROM nachrichten WHERE id = ?", (l["letzte_id"],)).fetchone()[0]
            out.append({"name": b["name"], "anzeigename": b["anzeigename"] or b["name"], "rolle": b["rolle"],
                        "rolle_text": ROLLEN.get(b["rolle"], b["rolle"]), "aktiv": bool(b["aktiv"]),
                        "letzte_zeit": l.get("letzte_zeit", ""), "letzter_text": text[:80],
                        "ungelesen": ungelesen.get(k, 0)})
        return sorted(out, key=lambda x: (x["letzte_zeit"] == "", "" if not x["letzte_zeit"] else
                                          "".join(chr(255 - ord(c)) for c in x["letzte_zeit"]), x["anzeigename"].lower()))

    def senden(self, empfaenger: str, text: str, client_id: str, akte: str = "", mandant_id: int | None = None,
               aufgabe_id: int | None = None) -> dict:
        ich = self._ich()
        text = (text or "").strip()
        if not text:
            raise ValueError("Bitte eine Nachricht eingeben.")
        if len(text) > MAX_LAENGE:
            raise ValueError("Die Nachricht ist zu lang.")
        if not client_id:
            raise ValueError("Interner Fehler: Nachrichten-Kennung fehlt.")
        b = self._benutzer().get((empfaenger or "").lower())
        if not b or not b["aktiv"]:
            raise ValueError("Diesen Empfänger gibt es nicht (mehr).")
        if b["name"].lower() == ich.lower():
            raise ValueError("Nachrichten an sich selbst sind nicht möglich.")
        vorhanden = self._zeilen("SELECT * FROM nachrichten WHERE absender = ? AND client_id = ?", (ich, client_id))
        if vorhanden:                                       # erneuter Sendeversuch → keine Doppelung
            return self._aufbereiten(vorhanden[0])
        cur = self.con.execute(
            "INSERT INTO nachrichten (absender, empfaenger, text, zeit, akte, mandant_id, client_id, aufgabe_id) "
            "VALUES (?,?,?,?,?,?,?,?)", (ich, b["name"], text, _jetzt(), akte or "", mandant_id, client_id,
                                        aufgabe_id))
        self.con.commit()
        return self.nachricht(int(cur.lastrowid))

    def verlauf(self, partner: str, seit_id: int = 0) -> list[dict]:
        """Nachrichten zwischen mir und `partner` (älteste zuerst)."""
        ich = self._ich().lower()
        p = (partner or "").lower()
        z = self._zeilen("SELECT * FROM nachrichten WHERE id > ? AND ((lower(absender) = ? AND lower(empfaenger) = ?)"
                         " OR (lower(absender) = ? AND lower(empfaenger) = ?)) ORDER BY id",
                         (seit_id, ich, p, p, ich))
        benutzer = self._benutzer()
        return [self._aufbereiten(n, benutzer) for n in z]

    def nachricht(self, nid: int) -> dict:
        from core.benutzer import Berechtigung
        z = self._zeilen("SELECT * FROM nachrichten WHERE id = ?", (nid,))
        ich = self._ich().lower()
        if not z or ich not in (z[0]["absender"].lower(), z[0]["empfaenger"].lower()):
            raise Berechtigung("Keine Berechtigung: Diese Nachricht gehört zu einem Gespräch anderer Benutzer.")
        return self._aufbereiten(z[0])

    def gelesen(self, partner: str, bis_id: int) -> int:
        """Vom Empfänger aufgerufen, wenn er das Gespräch geöffnet und die Nachrichten gesehen hat."""
        ich = self._ich().lower()
        cur = self.con.execute("UPDATE nachrichten SET gelesen = ? WHERE lower(empfaenger) = ? AND lower(absender) = ?"
                               " AND id <= ? AND gelesen = ''", (_jetzt(), ich, (partner or "").lower(), bis_id))
        self.con.commit()
        return cur.rowcount

    def status(self, seit_id: int = 0) -> dict:
        """Für die Benachrichtigung: ungelesen gesamt, neue eingegangene Nachrichten seit `seit_id`, höchste Id."""
        ich = self._ich().lower()
        ungelesen = self.con.execute("SELECT COUNT(*) FROM nachrichten WHERE lower(empfaenger) = ? AND gelesen = ''",
                                     (ich,)).fetchone()[0]
        neu = self._zeilen("SELECT id, absender FROM nachrichten WHERE lower(empfaenger) = ? AND id > ? ORDER BY id",
                           (ich, seit_id))
        benutzer = self._benutzer()
        hoechste = self.con.execute("SELECT COALESCE(MAX(id), 0) FROM nachrichten WHERE lower(absender) = ? OR "
                                    "lower(empfaenger) = ?", (ich, ich)).fetchone()[0]
        return {"ungelesen": ungelesen, "hoechste_id": hoechste,
                "neu": [{"id": n["id"], "absender": n["absender"], "absender_anzeige": self._anzeige(n["absender"],
                                                                                                    benutzer)}
                        for n in neu]}

    def _aufbereiten(self, n: dict, benutzer: dict | None = None) -> dict:
        benutzer = benutzer if benutzer is not None else self._benutzer()
        n = dict(n)
        n["absender_anzeige"] = self._anzeige(n["absender"], benutzer)
        n["empfaenger_anzeige"] = self._anzeige(n["empfaenger"], benutzer)
        n["von_mir"] = n["absender"].lower() == self._ich().lower()
        n.pop("client_id", None) if not n["von_mir"] else None
        return n
