"""Dokumentenarchiv (0.4.1): bearbeitete und hinzugefügte Dokumente – in derselben SQLite-Datenbank wie
Verlauf und Akten (verlauf.sqlite).

Die Dateien bleiben, wo sie sind (Aktenordner, OneDrive …); das Archiv merkt sich Pfad, Akte, Dateityp,
Zeitpunkt des Hinzufügens und der letzten Bearbeitung sowie die Herkunft (z. B. Word-Arbeitskopie ← PDF).
Dokumente ohne Akte können später einer Akte zugeordnet werden. Programm schließen/öffnen: alles bleibt.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS dokumente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    akte TEXT DEFAULT '',
    pfad TEXT NOT NULL,
    schluessel TEXT NOT NULL,
    name TEXT DEFAULT '', typ TEXT DEFAULT '',
    rolle TEXT DEFAULT 'original',
    quelle_id INTEGER,
    hinzugefuegt TEXT, bearbeitet TEXT DEFAULT '',
    sha256 TEXT DEFAULT '', notiz TEXT DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS ix_dokumente_schluessel ON dokumente(schluessel);
CREATE INDEX IF NOT EXISTS ix_dokumente_akte ON dokumente(akte);
"""

TYPEN = {".pdf": "PDF", ".docx": "Word", ".doc": "Word", ".docm": "Word", ".rtf": "Word",
         ".jpg": "Bild", ".jpeg": "Bild", ".png": "Bild", ".tif": "Bild", ".tiff": "Bild",
         ".eml": "E-Mail", ".msg": "E-Mail", ".xlsx": "Excel", ".txt": "Text"}
ROLLEN = {"original": "Original", "bearbeitet": "bearbeitet", "umgewandelt": "umgewandelt",
          "paket": "Anlagenpaket", "ausgang": "Ausgang", "eingang": "Eingang"}


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def typ(pfad: Path) -> str:
    return TYPEN.get(Path(pfad).suffix.lower(), Path(pfad).suffix.upper().lstrip(".") or "Datei")


def _schluessel(pfad: Path) -> str:
    try:
        return str(Path(pfad).resolve()).lower()
    except OSError:
        return str(Path(pfad)).lower()


def _sha(pfad: Path) -> str:
    try:
        return hashlib.sha256(Path(pfad).read_bytes()).hexdigest()
    except OSError:
        return ""


class Archiv:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.executescript(SCHEMA)
        self.con.commit()

    def erfassen(self, pfad: Path, akte: str = "", rolle: str = "original", quelle: Path | None = None,
                 notiz: str = "") -> int:
        """Dokument aufnehmen oder (bei gleichem Pfad) aktualisieren. Eine vorhandene Akte-Zuordnung wird
        nur gesetzt, nie durch „keine Akte“ gelöscht."""
        pfad = Path(pfad)
        k = _schluessel(pfad)
        quelle_id = self.id_von(quelle) if quelle else None
        if quelle and quelle_id is None:
            quelle_id = self.erfassen(quelle, akte=akte)
        r = self.con.execute("SELECT id, akte FROM dokumente WHERE schluessel = ?", (k,)).fetchone()
        jetzt = _jetzt()
        if r:
            self.con.execute(
                "UPDATE dokumente SET pfad = ?, name = ?, typ = ?, sha256 = ?, akte = CASE WHEN ? != '' THEN ?"
                " ELSE akte END, quelle_id = COALESCE(?, quelle_id), notiz = CASE WHEN ? != '' THEN ? ELSE notiz END,"
                " bearbeitet = CASE WHEN ? IN ('bearbeitet', 'umgewandelt') THEN ? ELSE bearbeitet END,"
                " rolle = CASE WHEN rolle = 'original' AND ? != 'original' THEN ? ELSE rolle END WHERE id = ?",
                (str(pfad), pfad.name, typ(pfad), _sha(pfad), akte, akte, quelle_id, notiz, notiz,
                 rolle, jetzt, rolle, rolle, r[0]))
            self.con.commit()
            return int(r[0])
        cur = self.con.execute(
            "INSERT INTO dokumente (akte, pfad, schluessel, name, typ, rolle, quelle_id, hinzugefuegt, bearbeitet,"
            " sha256, notiz) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (akte, str(pfad), k, pfad.name, typ(pfad), rolle, quelle_id, jetzt,
             jetzt if rolle in ("bearbeitet", "umgewandelt") else "", _sha(pfad), notiz))
        self.con.commit()
        return int(cur.lastrowid)

    def id_von(self, pfad: Path) -> int | None:
        r = self.con.execute("SELECT id FROM dokumente WHERE schluessel = ?", (_schluessel(pfad),)).fetchone()
        return int(r[0]) if r else None

    def bearbeitet(self, pfad: Path) -> None:
        """Nach dem Speichern: Zeitpunkt + Prüfsumme aktualisieren (Dokument wird bei Bedarf aufgenommen)."""
        if self.id_von(pfad) is None:
            self.erfassen(pfad, rolle="bearbeitet")
            return
        self.con.execute("UPDATE dokumente SET bearbeitet = ?, sha256 = ? WHERE schluessel = ?",
                         (_jetzt(), _sha(pfad), _schluessel(pfad)))
        self.con.commit()

    def zuordnen(self, dok_id: int, akte: str) -> None:
        self.con.execute("UPDATE dokumente SET akte = ? WHERE id = ?", (akte, dok_id))
        self.con.commit()

    def dokument(self, dok_id: int) -> dict | None:
        r = self.con.execute("SELECT * FROM dokumente WHERE id = ?", (dok_id,)).fetchone()
        return dict(zip([c[0] for c in self.con.execute("SELECT * FROM dokumente LIMIT 0").description], r)) \
            if r else None

    def liste(self, akte: str | None = None, ohne_akte: bool = False, suche: str = "") -> list[dict]:
        sql = "SELECT d.*, q.name AS quelle_name, q.typ AS quelle_typ FROM dokumente d " \
              "LEFT JOIN dokumente q ON q.id = d.quelle_id WHERE 1=1"
        werte: list = []
        if ohne_akte:
            sql += " AND d.akte = ''"
        elif akte is not None:
            sql += " AND d.akte = ?"
            werte.append(akte)
        if suche:
            sql += " AND (d.name LIKE ? OR d.akte LIKE ? OR d.pfad LIKE ?)"
            werte += [f"%{suche}%"] * 3
        sql += " ORDER BY COALESCE(NULLIF(d.bearbeitet, ''), d.hinzugefuegt) DESC, d.id DESC"
        cur = self.con.execute(sql, werte)
        namen = [c[0] for c in cur.description]
        return [dict(zip(namen, r)) for r in cur.fetchall()]

    def abgeleitet(self, dok_id: int) -> list[dict]:
        """Dokumente, die aus diesem entstanden sind (z. B. Word-Arbeitskopie eines PDF)."""
        cur = self.con.execute("SELECT * FROM dokumente WHERE quelle_id = ? ORDER BY id", (dok_id,))
        namen = [c[0] for c in cur.description]
        return [dict(zip(namen, r)) for r in cur.fetchall()]

    def arbeitskopie(self, quelle: Path) -> Path | None:
        """Neueste vorhandene Word-Arbeitskopie zu einem Quelldokument."""
        qid = self.id_von(quelle)
        if qid is None:
            return None
        for d in reversed(self.abgeleitet(qid)):
            if d["typ"] == "Word" and Path(d["pfad"]).exists():
                return Path(d["pfad"])
        return None
