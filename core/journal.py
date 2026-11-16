"""Veritabanı (SQLite): işlem günlüğü ve dosyalar (Akten).

- vorgaenge : her olay – giden yazı, müvekkile e-posta, gelen cevap …  (art sütunu)
- akten     : sigorta numarası başına bir kayıt – klasör, sigorta ve müvekkil e-postası
"""
from __future__ import annotations

import getpass
import sqlite3
from datetime import datetime
from pathlib import Path

# art (olay türü) – arayüzde gösterilen Almanca adlar
ARTEN = {
    "ausgang": "Schreiben an Versicherung",
    "mandant": "E-Mail an Mandant",
    "eingang": "Antwort eingegangen",
    "entwurf": "E-Mail-Entwurf",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS vorgaenge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT, workflow TEXT, dokument TEXT, ergebnis TEXT,
    empfaenger TEXT, referenz TEXT, status TEXT, meldung TEXT);
CREATE TABLE IF NOT EXISTS akten (
    referenz TEXT PRIMARY KEY,
    ordner TEXT DEFAULT '', versicherer_email TEXT DEFAULT '',
    mandant_name TEXT DEFAULT '', mandant_email TEXT DEFAULT '',
    notiz TEXT DEFAULT '', angelegt TEXT);
"""

# Sonradan eklenen sütunlar: eski veritabanları otomatik güncellenir
MIGRATIONEN = [
    ("vorgaenge", "art", "TEXT DEFAULT 'ausgang'"),
    ("vorgaenge", "quelle_id", "TEXT DEFAULT ''"),
    ("vorgaenge", "benutzer", "TEXT DEFAULT ''"),
]

AKTEN_FELDER = ("ordner", "versicherer_email", "mandant_name", "mandant_email", "notiz")


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _benutzer() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return ""


class Journal:
    def __init__(self, db_path: Path):
        self.con = sqlite3.connect(db_path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        for tabelle, spalte, typ in MIGRATIONEN:
            vorhanden = {r["name"] for r in self.con.execute(f"PRAGMA table_info({tabelle})")}
            if spalte not in vorhanden:
                self.con.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")
        self.con.commit()

    # --- Olaylar --------------------------------------------------------------
    def add(self, workflow: str, dokument: str, ergebnis: str = "", empfaenger: str = "",
            referenz: str = "", status: str = "ok", meldung: str = "",
            art: str = "ausgang", quelle_id: str = "") -> None:
        self.con.execute(
            "INSERT INTO vorgaenge (zeit, workflow, dokument, ergebnis, empfaenger, referenz,"
            " status, meldung, art, quelle_id, benutzer) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_jetzt(), workflow, dokument, ergebnis, empfaenger, referenz, status, meldung,
             art, quelle_id, _benutzer()),
        )
        self.con.commit()

    def recent(self, limit: int = 300) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT zeit, art, referenz, dokument, ergebnis, empfaenger, status, meldung, benutzer"
            " FROM vorgaenge ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def verlauf(self, referenz: str) -> list[sqlite3.Row]:
        """Bir dosyanın tüm olayları, en yenisi üstte."""
        return self.con.execute(
            "SELECT zeit, art, dokument, ergebnis, empfaenger, status, meldung, benutzer"
            " FROM vorgaenge WHERE referenz = ? AND status != 'abgebrochen' ORDER BY id DESC",
            (referenz,)).fetchall()

    def bereits_importiert(self, quelle_id: str) -> bool:
        return bool(quelle_id) and self.con.execute(
            "SELECT 1 FROM vorgaenge WHERE quelle_id = ? AND status = 'ok' LIMIT 1",
            (quelle_id,)).fetchone() is not None

    # --- Dosyalar (Akten) -----------------------------------------------------
    def akte_speichern(self, referenz: str, **werte: str) -> None:
        """Dosyayı oluşturur/günceller. Boş değerler mevcut bilgiyi silmez."""
        if not referenz:
            return
        self.con.execute("INSERT OR IGNORE INTO akten (referenz, angelegt) VALUES (?, ?)",
                         (referenz, _jetzt()))
        for feld, wert in werte.items():
            if feld in AKTEN_FELDER and wert:
                self.con.execute(f"UPDATE akten SET {feld} = ? WHERE referenz = ?",
                                 (str(wert), referenz))
        self.con.commit()

    def akte(self, referenz: str) -> dict | None:
        r = self.con.execute("SELECT * FROM akten WHERE referenz = ?", (referenz,)).fetchone()
        return dict(r) if r else None

    def akten(self, suche: str = "") -> list[dict]:
        like = f"%{suche}%"
        rows = self.con.execute(
            """SELECT a.*, MAX(v.zeit) AS letzte, COUNT(v.id) AS anzahl,
                      SUM(CASE WHEN v.art = 'eingang' THEN 1 ELSE 0 END) AS eingaenge
               FROM akten a LEFT JOIN vorgaenge v
                    ON v.referenz = a.referenz AND v.status != 'abgebrochen'
               WHERE a.referenz LIKE ? OR a.mandant_name LIKE ? OR a.versicherer_email LIKE ?
                     OR a.mandant_email LIKE ?
               GROUP BY a.referenz ORDER BY letzte DESC""",
            (like, like, like, like)).fetchall()
        return [dict(r) for r in rows]

    def referenzen(self) -> list[str]:
        return [r[0] for r in self.con.execute("SELECT referenz FROM akten")]
