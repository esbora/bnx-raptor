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
from core.protokoll import Konflikt, Protokoll, aktuell, geaendert, konflikte

SCHEMA = """
CREATE TABLE IF NOT EXISTS mandanten (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    art TEXT DEFAULT 'person', name TEXT NOT NULL,
    strasse TEXT DEFAULT '', plz TEXT DEFAULT '', ort TEXT DEFAULT '',
    telefon TEXT DEFAULT '', email TEXT DEFAULT '', notiz TEXT DEFAULT '',
    angelegt TEXT, geaendert TEXT);
CREATE TABLE IF NOT EXISTS zaehler (name TEXT PRIMARY KEY, wert INTEGER);
CREATE TABLE IF NOT EXISTS versicherungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    strasse TEXT DEFAULT '', plz TEXT DEFAULT '', ort TEXT DEFAULT '',
    telefon TEXT DEFAULT '', notiz TEXT DEFAULT '',
    angelegt TEXT, geaendert TEXT);
"""
AKTEN_SPALTEN = [("aktenzeichen", "TEXT DEFAULT ''"), ("mandant_id", "INTEGER"), ("versicherung_id", "INTEGER"),
                 ("versicherungsnummer", "TEXT DEFAULT ''"), ("schaden_nr", "TEXT DEFAULT ''"),
                 ("erstellt_von", "TEXT DEFAULT ''"), ("geaendert", "TEXT DEFAULT ''"),
                 ("geaendert_von", "TEXT DEFAULT ''"),                 # 0.4.2: wer/wann
                 ("akte_art", "TEXT DEFAULT ''")]                      # 0.5: Aktenart (Checklisten)
VERSICHERUNG_SPALTEN = [("standard_email", "TEXT DEFAULT ''"),       # 0.4.1: Standardadresse bei mehreren
                        ("erstellt_von", "TEXT DEFAULT ''"), ("geaendert_von", "TEXT DEFAULT ''")]
MANDANT_SPALTEN = [("nummer", "TEXT DEFAULT ''"),                     # 0.4.2: Mandats-Nr. M01, M02 … (fest)
                   ("erstellt_von", "TEXT DEFAULT ''"), ("geaendert_von", "TEXT DEFAULT ''")]
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
        self.prot = Protokoll(con)
        vorhanden = {r[1] for r in self.con.execute("PRAGMA table_info(akten)")}
        for spalte, typ in AKTEN_SPALTEN:
            if vorhanden and spalte not in vorhanden:
                self.con.execute(f"ALTER TABLE akten ADD COLUMN {spalte} {typ}")
        v_spalten = {r[1] for r in self.con.execute("PRAGMA table_info(versicherungen)")}
        for spalte, typ in VERSICHERUNG_SPALTEN:
            if spalte not in v_spalten:
                self.con.execute(f"ALTER TABLE versicherungen ADD COLUMN {spalte} {typ}")
        m_spalten = {r[1] for r in self.con.execute("PRAGMA table_info(mandanten)")}
        for spalte, typ in MANDANT_SPALTEN:
            if spalte not in m_spalten:
                self.con.execute(f"ALTER TABLE mandanten ADD COLUMN {spalte} {typ}")
        # Mandanten ohne Nummer (ältere Daten) in Anlagereihenfolge nummerieren
        for (mid,) in self.con.execute("SELECT id FROM mandanten WHERE COALESCE(nummer, '') = '' ORDER BY id")                .fetchall():
            self.con.execute("UPDATE mandanten SET nummer = ? WHERE id = ?", (self._naechste_nummer(), mid))
        self.con.commit()

    def _naechste_nummer(self) -> str:
        """Nächste Mandats-Nr. (M01 … M99, danach M100 …). Ein Zähler merkt sich die höchste je vergebene
        Nummer – Nummern gelöschter Mandanten werden nie neu vergeben."""
        hoechste = 0
        for (n,) in self.con.execute("SELECT nummer FROM mandanten WHERE nummer LIKE 'M%'"):
            ziffern = (n or "")[1:]
            if ziffern.isdigit():
                hoechste = max(hoechste, int(ziffern))
        r = self.con.execute("SELECT wert FROM zaehler WHERE name = 'mandat'").fetchone()
        neu = max(hoechste, r[0] if r else 0) + 1
        self.con.execute("INSERT OR REPLACE INTO zaehler (name, wert) VALUES ('mandat', ?)", (neu,))
        return f"M{neu:02d}"

    # --- Mandanten -------------------------------------------------------------
    def mandanten(self, suche: str = "") -> list[dict]:
        """Suche auch nach Mandats-Nr., Aktenzeichen, Versicherungsnummer und Schaden-Nr. der Akten."""
        like = f"%{suche}%"
        return _zeilen(self.con.execute(
            "SELECT m.*, (SELECT COUNT(*) FROM akten a WHERE a.mandant_id = m.id) AS akten FROM mandanten m"
            " WHERE m.name LIKE ? OR m.email LIKE ? OR m.ort LIKE ? OR m.nummer LIKE ?"
            " OR EXISTS (SELECT 1 FROM akten a WHERE a.mandant_id = m.id AND (a.referenz LIKE ?"
            "   OR COALESCE(a.aktenzeichen, '') LIKE ? OR COALESCE(a.versicherungsnummer, '') LIKE ?"
            "   OR COALESCE(a.schaden_nr, '') LIKE ?))"
            " ORDER BY m.name COLLATE NOCASE", (like,) * 8))

    def mandant(self, mid: int) -> dict | None:
        r = _zeilen(self.con.execute("SELECT * FROM mandanten WHERE id = ?", (mid,)))
        return r[0] if r else None

    def mandant_speichern(self, mid: int | None, _basis: dict | None = None, **werte) -> int:
        """Anlegen (mid None) oder ändern. Nur tatsächlich geänderte Felder werden geschrieben; mit `_basis`
        (Stand beim Laden) wird ein gleichzeitiges Ändern desselben Feldes als `Konflikt` gemeldet."""
        werte = {k: str(v or "").strip() for k, v in werte.items() if k in MANDANT_FELDER}
        if not werte.get("name", "x"):
            raise ValueError("Bitte einen Namen oder Firmennamen eingeben.")
        wer = aktuell().text
        if mid is None:
            werte.setdefault("art", "person")
            werte["nummer"] = self._naechste_nummer()
            cur = self.con.execute(
                f"INSERT INTO mandanten ({', '.join(werte)}, angelegt, geaendert, erstellt_von, geaendert_von) VALUES "
                f"({', '.join('?' * len(werte))}, ?, ?, ?, ?)", (*werte.values(), _jetzt(), _jetzt(), wer, wer))
            neu = int(cur.lastrowid)
            self.prot.eintragen("mandant", neu, "erstellt", [k for k, v in werte.items() if v and k != "nummer"],
                                werte.get("name", ""), commit=False)
            self.con.commit()
            return neu
        alt = self.mandant(mid)
        if alt is None:
            raise ValueError("Dieser Mandant wurde inzwischen von einem anderen Benutzer gelöscht.")
        k = konflikte(alt, werte, _basis)
        if k:
            raise Konflikt("mandant", mid, k, alt)
        werte = geaendert(alt, werte)
        if not werte:
            return mid
        self.con.execute(f"UPDATE mandanten SET {', '.join(f'{k} = ?' for k in werte)}, geaendert = ?, "
                         f"geaendert_von = ? WHERE id = ?", (*werte.values(), _jetzt(), wer, mid))
        self.prot.eintragen("mandant", mid, "geaendert", list(werte), werte.get("name") or alt["name"], commit=False)
        self.con.commit()
        return mid

    def mandant_loeschen(self, mid: int) -> None:
        """Akten bleiben erhalten (nur die Verknüpfung wird gelöst)."""
        alt = self.mandant(mid) or {}
        self.con.execute("UPDATE akten SET mandant_id = NULL WHERE mandant_id = ?", (mid,))
        self.con.execute("DELETE FROM mandanten WHERE id = ?", (mid,))
        self.prot.eintragen("mandant", mid, "geloescht", [],
                            f"{alt.get('nummer', '')} {alt.get('name', '')}".strip(), commit=False)
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
                                                  "telefon": "", "notiz": "", "emails": [], "quelle": "Adressbuch",
                                                  "standard_email": ""})
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

    def versicherung_speichern(self, vid: int | None, _basis: dict | None = None, **werte) -> int:
        """Anlegen/ändern. Bei Umbenennung werden die Adressbuch-Einträge mit umbenannt."""
        werte = {k: str(v or "").strip() for k, v in werte.items() if k in VERSICHERUNG_FELDER}
        wer = aktuell().text
        if "name" in werte and not werte["name"]:
            raise ValueError("Bitte den Namen der Versicherung eingeben.")
        if vid is None:
            vorhanden = next((v for v in self.versicherungen() if v["id"] is not None
                              and self.buch._key(v["name"]) == self.buch._key(werte.get("name", ""))), None)
            if vorhanden:
                vid = vorhanden["id"]
            else:
                cur = self.con.execute(
                    f"INSERT INTO versicherungen ({', '.join(werte)}, angelegt, geaendert, erstellt_von, geaendert_von)"
                    f" VALUES ({', '.join('?' * len(werte))}, ?, ?, ?, ?)",
                    (*werte.values(), _jetzt(), _jetzt(), wer, wer))
                neu = int(cur.lastrowid)
                self.prot.eintragen("versicherung", neu, "erstellt", [k for k, v in werte.items() if v],
                                    werte.get("name", ""), commit=False)
                self.con.commit()
                return neu
        alt = self.versicherung(vid)
        if alt is None:
            raise ValueError("Diese Versicherung wurde inzwischen von einem anderen Benutzer gelöscht.")
        k = konflikte(alt, werte, _basis)
        if k:
            raise Konflikt("versicherung", vid, k, alt)
        werte = geaendert(alt, werte)
        if not werte:
            return vid
        if alt and "name" in werte and werte["name"] != alt["name"]:
            for r in self.buch.treffer(alt["name"]):
                self.con.execute("UPDATE versicherer SET name = ? WHERE id = ?", (werte["name"], r["id"]))
        self.con.execute(f"UPDATE versicherungen SET {', '.join(f'{k} = ?' for k in werte)}, geaendert = ?, "
                         f"geaendert_von = ? WHERE id = ?", (*werte.values(), _jetzt(), wer, vid))
        self.prot.eintragen("versicherung", vid, "geaendert", list(werte), werte.get("name") or alt["name"],
                            commit=False)
        self.con.commit()
        return vid

    def email_hinzufuegen(self, vid: int, email: str) -> None:
        v = self.versicherung(vid)
        if v:
            self.buch.hinzufuegen(v["name"], email)
            self.prot.eintragen("versicherung", vid, "email_hinzugefuegt", [], email)

    def standard_email_setzen(self, vid: int, email: str) -> None:
        """Standardadresse bei mehreren E-Mail-Adressen (leer = keine)."""
        self.con.execute("UPDATE versicherungen SET standard_email = ?, geaendert = ?, geaendert_von = ? "
                         "WHERE id = ?", (email.strip(), _jetzt(), aktuell().text, vid))
        self.prot.eintragen("versicherung", vid, "geaendert", ["standard_email"], commit=False)
        self.con.commit()

    def email_entfernen(self, vid: int, email: str) -> None:
        v = self.versicherung(vid)
        if not v:
            return
        if (v.get("standard_email") or "").lower() == email.lower():
            self.standard_email_setzen(vid, "")
        for r in self.buch.treffer(v["name"]):
            if r["email"].lower() == email.lower():
                self.buch.loeschen(r["id"])
        self.prot.eintragen("versicherung", vid, "email_entfernt", [], email)

    # --- Akten -----------------------------------------------------------------
    def akte_anlegen(self, referenz: str, **werte) -> None:
        referenz = referenz.strip()
        if not referenz:
            raise ValueError("Bitte ein Aktenzeichen oder eine Versicherungsnummer eingeben.")
        wer = aktuell().text
        cur = self.con.execute("INSERT OR IGNORE INTO akten (referenz, angelegt, erstellt_von, geaendert, "
                               "geaendert_von) VALUES (?, ?, ?, ?, ?)", (referenz, _jetzt(), wer, _jetzt(), wer))
        if cur.rowcount:
            self.prot.eintragen("akte", referenz, "erstellt", [k for k, v in werte.items() if v], referenz,
                                commit=False)
        self.con.commit()
        self.akte_setzen(referenz, _protokoll=not cur.rowcount, **werte)

    def akte_setzen(self, referenz: str, _basis: dict | None = None, _protokoll: bool = True, **werte) -> None:
        erlaubt = {"aktenzeichen", "mandant_id", "versicherung_id", "versicherungsnummer", "schaden_nr",
                   "mandant_name", "mandant_email", "versicherer_email", "notiz", "ordner", "akte_art"}
        werte = {k: v for k, v in werte.items() if k in erlaubt}
        if not werte:
            return
        alt = self.akte(referenz)
        if alt is None:
            raise ValueError("Diese Akte gibt es nicht (mehr).")
        k = konflikte(alt, werte, _basis)
        if k:
            raise Konflikt("akte", referenz, k, alt)
        werte = geaendert(alt, werte)
        if not werte:
            return
        self.con.execute(f"UPDATE akten SET {', '.join(f'{k} = ?' for k in werte)}, geaendert = ?, geaendert_von = ?"
                         f" WHERE referenz = ?", (*werte.values(), _jetzt(), aktuell().text, referenz))
        if _protokoll:
            self.prot.eintragen("akte", referenz, "geaendert", [k for k in werte if k != "mandant_name"], referenz,
                                commit=False)
        self.con.commit()

    def aenderungsverlauf(self, art: str, objekt) -> list[dict]:
        return self.prot.fuer(art, objekt)

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
        """Akten des Mandanten (neueste zuerst) mit Aktenzeichen, Versicherungsnummer, Schaden-Nr. und
        Versicherungsname (`versicherung`); alte Akten wie in akte() aufbereitet."""
        out = []
        for (ref,) in self.con.execute("SELECT referenz FROM akten WHERE mandant_id = ? ORDER BY angelegt DESC",
                                       (mid,)).fetchall():
            a = self.akte(ref)
            v = self.versicherung(a["versicherung_id"]) if isinstance(a.get("versicherung_id"), int) else None
            a["versicherung"] = v["name"] if v else ""
            out.append(a)
        return out

    def akten_von_versicherung(self, vid: int) -> list[dict]:
        return _zeilen(self.con.execute("SELECT * FROM akten WHERE versicherung_id = ? ORDER BY angelegt DESC",
                                        (vid,)))

    # --- Dokumentenordner (0.4.1) ---------------------------------------------
    def dokumentordner(self, mandant_id: int | None = None, versicherung_id: int | None = None) -> list[tuple[str, str]]:
        """Ordner der Dokumente aller verknüpften Akten aus der Datenbank: Aktenordner, Dateien im Verlauf
        (gesendete/bearbeitete/eingegangene) und im Dokumentenarchiv. Rückgabe [(Ordner, Akte)], neueste zuerst,
        nur vorhandene Ordner, ohne Doppelte."""
        from pathlib import Path as _P
        if mandant_id is not None:
            akten = self.akten_von_mandant(mandant_id)
        elif versicherung_id is not None:
            akten = self.akten_von_versicherung(versicherung_id)
        else:
            return []
        kandidaten: list[tuple[str, str, str]] = []          # (zeit, ordner, akte)
        for a in akten:
            ref = a["referenz"]
            if a.get("ordner"):
                kandidaten.append((a.get("angelegt") or "", a["ordner"], ref))
            for zeit, ergebnis, dokument in self.con.execute(
                    "SELECT zeit, ergebnis, dokument FROM vorgaenge WHERE referenz = ? AND status != 'abgebrochen'",
                    (ref,)):
                for f in (ergebnis, dokument):
                    if f:
                        kandidaten.append((zeit or "", str(_P(f).parent), ref))
            try:
                for pfad, zeit in self.con.execute(
                        "SELECT pfad, COALESCE(NULLIF(bearbeitet, ''), hinzugefuegt) FROM dokumente WHERE akte = ?", (ref,)):
                    kandidaten.append((zeit or "", str(_P(pfad).parent), ref))
            except sqlite3.OperationalError:                   # Archiv noch nicht angelegt
                pass
        out: dict[str, tuple[str, str]] = {}
        for zeit, ordner, ref in sorted(kandidaten, reverse=True):
            k = ordner.lower()
            if k not in out and _P(ordner).is_dir():
                out[k] = (ordner, ref)
        return list(out.values())

