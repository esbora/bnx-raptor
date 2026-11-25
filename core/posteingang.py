"""Kanzlei-Eingang (0.5): gemeinsamer Posteingang mit Akte-Vorschlag und Aufgaben.

Saf Python + SQLite (aynı verlauf.sqlite). Sunucu modunda yalnızca sunucu açar; istemciler RPC ile çağırır.

- Eingang (`eingaenge`): ein Eingangsstück (E-Mail mit Text/Kopf und Anhängen, .eml/.msg-Datei oder einzelne
  Dateien). Die Dateien liegen im Dokumentenarchiv (`dokumente`) und sind über `eingang_dateien` verbunden.
  Quelldateien und Postfach werden nie verändert – gespeichert werden Kopien.
- Akte-Vorschlag: nur ein Vorschlag mit Begründung. Die Akte wird erst nach Bestätigung durch einen Menschen
  gesetzt; bei mehreren passenden Akten wird nichts still zugeordnet. Nicht zugeordnete Eingänge bleiben sichtbar.
- Aufgaben (`aufgaben`): aus den Schnellaktionen (Zur Kenntnis, Antwort vorbereiten, Unterlagen anfordern,
  Rückruf, Frist prüfen). „Frist prüfen“ ist ein Prüfauftrag – es wird KEINE Frist berechnet oder eingetragen.
- Doppelte vermeiden: `client_id` (vom anlegenden PC, macht Wiederholungen nach Verbindungsabbruch sicher),
  Message-ID und SHA-256 der Rohdatei. Nur gleiche Kennung/Prüfsumme gilt als doppelt – ähnliche Inhalte nie.
- Rechte (auf dem Server bei jedem Aufruf geprüft, da hier im Kern): Sekretariat erfasst, ordnet zu und bereitet
  vor; Aufgaben für andere verteilt nur Rechtsanwalt/Administrator.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime

from core import protokoll as pr

SCHEMA = """
CREATE TABLE IF NOT EXISTS eingaenge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    quelle TEXT DEFAULT 'datei',
    quelle_id TEXT DEFAULT '',
    sha256 TEXT DEFAULT '',
    eingang_am TEXT, dokument_datum TEXT DEFAULT '',
    absender TEXT DEFAULT '', absender_name TEXT DEFAULT '', betreff TEXT DEFAULT '',
    belegart TEXT DEFAULT '',
    akte TEXT DEFAULT '',
    vorschlag TEXT DEFAULT '[]',
    verantwortlich TEXT DEFAULT '',
    status TEXT DEFAULT 'neu',
    naechster_schritt TEXT DEFAULT '',
    text TEXT DEFAULT '',
    erstellt_von TEXT DEFAULT '', erstellt_am TEXT DEFAULT '',
    geaendert_von TEXT DEFAULT '', geaendert_am TEXT DEFAULT '',
    zugeordnet_von TEXT DEFAULT '', zugeordnet_am TEXT DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS ix_eingaenge_client ON eingaenge(client_id);
CREATE INDEX IF NOT EXISTS ix_eingaenge_quelle ON eingaenge(quelle_id);
CREATE INDEX IF NOT EXISTS ix_eingaenge_sha ON eingaenge(sha256);
CREATE INDEX IF NOT EXISTS ix_eingaenge_akte ON eingaenge(akte);
CREATE TABLE IF NOT EXISTS eingang_dateien (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eingang_id INTEGER NOT NULL, position INTEGER DEFAULT 0,
    rolle TEXT DEFAULT 'datei', dokument_id INTEGER,
    name TEXT DEFAULT '', pfad TEXT DEFAULT '', sha256 TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_eingang_dateien ON eingang_dateien(eingang_id);
CREATE TABLE IF NOT EXISTS aufgaben (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    eingang_id INTEGER, erwartung_id INTEGER,
    akte TEXT DEFAULT '',
    art TEXT DEFAULT 'sonstiges', titel TEXT DEFAULT '', beschreibung TEXT DEFAULT '',
    verantwortlich TEXT DEFAULT '', prioritaet TEXT DEFAULT 'normal', faellig TEXT DEFAULT '',
    status TEXT DEFAULT 'offen',
    erstellt_von TEXT DEFAULT '', erstellt_am TEXT DEFAULT '',
    geaendert_von TEXT DEFAULT '', geaendert_am TEXT DEFAULT '',
    erledigt_von TEXT DEFAULT '', erledigt_am TEXT DEFAULT '',
    wiedereroeffnet_von TEXT DEFAULT '', wiedereroeffnet_am TEXT DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS ix_aufgaben_client ON aufgaben(client_id);
CREATE INDEX IF NOT EXISTS ix_aufgaben_verantwortlich ON aufgaben(verantwortlich, status);
CREATE INDEX IF NOT EXISTS ix_aufgaben_eingang ON aufgaben(eingang_id);
"""

STATUS = {"neu": "Neu", "in_bearbeitung": "In Bearbeitung", "erledigt": "Erledigt"}
AUFGABE_STATUS = {"offen": "Offen", "in_bearbeitung": "In Bearbeitung", "erledigt": "Erledigt"}
PRIORITAETEN = {"niedrig": "Niedrig", "normal": "Normal", "hoch": "Hoch"}
# Schnellaktionen des Rechtsanwalts → Aufgabenart (Titel, Standardbeschreibung)
AKTIONEN = {
    "kenntnis": ("Zur Kenntnis", "Eingang zur Kenntnis nehmen und ablegen."),
    "antwort": ("Antwort vorbereiten", "Antwort auf diesen Eingang vorbereiten (Entwurf – nicht senden)."),
    "unterlagen": ("Unterlagen anfordern", "Fehlende Unterlagen anfordern."),
    "rueckruf": ("Rückruf", "Zurückrufen."),
    "frist": ("Frist prüfen", "Prüfauftrag: Ob und welche Frist läuft, bitte selbst prüfen und im Fristenkalender "
                              "eintragen. BnX-Raptor berechnet keine Fristen und trägt keine Frist ein."),
    "sonstiges": ("Aufgabe", ""),
}
BELEGARTEN = ["E-Mail", "Schreiben Versicherung", "Vollmacht", "Gutachten", "Rechnung", "Kostenvoranschlag",
              "Gerichtspost", "Mandantenunterlagen", "Sonstiges"]
EINGANG_FELDER = ("belegart", "verantwortlich", "status", "naechster_schritt", "dokument_datum", "betreff",
                  "absender", "absender_name")
AUFGABE_FELDER = ("titel", "beschreibung", "verantwortlich", "prioritaet", "faellig", "status")
TEXT_MAX = 20000                                   # gespeicherter Text (für Vorschlag/Suche), nicht der ganze Inhalt
VERTEILEN = {"admin", "anwalt"}                    # Rollen, die Aufgaben an andere vergeben dürfen


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _heute() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------- reine Regeln (ohne Datenbank)
def _norm(s: str) -> str:
    return re.sub(r"[\s\-/.]", "", s or "").upper()


def nummer_im_text(text: str, nummer: str, min_laenge: int = 5) -> bool:
    """Nummer (Versicherungsnummer, Schaden-Nr., Aktenzeichen …) im Text – Trennzeichen egal, keine Teiltreffer
    mitten in längeren Zahlen/Wörtern."""
    n = _norm(nummer)
    if len(n) < min_laenge or not any(c.isdigit() for c in n):
        return False
    zeichen = [(c.upper(), i) for i, c in enumerate(text or "") if c not in " \t\r\n-/."]
    flach = "".join(c for c, _ in zeichen)
    start = 0
    while (pos := flach.find(n, start)) != -1:
        vor = text[zeichen[pos][1] - 1] if zeichen[pos][1] > 0 else " "
        ende = zeichen[pos + len(n) - 1][1]
        nach = text[ende + 1] if ende + 1 < len(text) else " "
        if not vor.isalnum() and not nach.isalnum():
            return True
        start = pos + 1
    return False


ALLGEMEINE_DOMAINS = {"gmail.com", "googlemail.com", "gmx.de", "gmx.net", "web.de", "t-online.de", "outlook.com",
                      "outlook.de", "hotmail.com", "hotmail.de", "live.com", "yahoo.com", "yahoo.de", "icloud.com",
                      "me.com", "aol.com", "freenet.de", "posteo.de", "mailbox.org", "example.com"}


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower().strip() if "@" in (email or "") else ""


@dataclass
class AktenInfo:
    """Was zu einer Akte bekannt ist (für den Vorschlag)."""
    referenz: str
    nummern: list[tuple[str, str]] = field(default_factory=list)      # (Bezeichnung, Wert)
    emails: list[tuple[str, str]] = field(default_factory=list)       # (Rolle, Adresse)
    namen: list[tuple[str, str]] = field(default_factory=list)        # (Rolle, Name)


def akte_vorschlaege(text: str, absender: str, akten: list[AktenInfo]) -> list[dict]:
    """Vorschläge mit Begründung, beste zuerst. → [{referenz, punkte, gruende, art}]

    art: "nummer" (Nummer der Akte steht im Eingang), "absender" (Absender gehört zur Akte), "name".
    Es wird nie automatisch zugeordnet – siehe `eindeutig()`.
    """
    absender = (absender or "").strip().lower()
    dom = _domain(absender)
    out = []
    for a in akten:
        gruende, punkte, art = [], 0, ""
        for bez, wert in a.nummern:
            if wert and nummer_im_text(text, wert):
                gruende.append(f"{bez} {wert} steht im Eingang")
                punkte += 100
                art = art or "nummer"
        gesehen: set[str] = set()
        for rolle, mail in a.emails:
            m = (mail or "").strip().lower()
            if (rolle, m) in gesehen:
                continue
            gesehen.add((rolle, m))
            if m and absender and m == absender:
                gruende.append(f"Absender {mail} = E-Mail {rolle} dieser Akte")
                punkte += 50
                art = art or "absender"
            elif m and dom and dom not in ALLGEMEINE_DOMAINS and _domain(m) == dom and \
                    not any(g.startswith("Absender-Domain") for g in gruende):
                gruende.append(f"Absender-Domain @{dom} wie {rolle} dieser Akte")
                punkte += 20
                art = art or "absender"
        for rolle, name in a.namen:
            n = (name or "").strip()
            if len(n) >= 5 and re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text or "", re.I):
                gruende.append(f"Name {rolle} „{n}“ steht im Eingang")
                punkte += 15
                art = art or "name"
        if punkte:
            out.append({"referenz": a.referenz, "punkte": punkte, "gruende": gruende, "art": art})
    return sorted(out, key=lambda v: (-v["punkte"], v["referenz"]))


def eindeutig(vorschlaege: list[dict]) -> bool:
    """Genau EIN Vorschlag mit Nummerntreffer und keine zweite Akte mit gleich starkem Grund → „sicherer“
    Vorschlag (wird trotzdem nur vorgeschlagen, nie automatisch bestätigt)."""
    return sum(1 for v in vorschlaege if v["art"] == "nummer") == 1 and vorschlaege[0]["art"] == "nummer"


BELEG_REGELN = [
    ("Vollmacht", r"\bvollmacht"),
    ("Gutachten", r"\bgutachten|sachverständig"),
    ("Kostenvoranschlag", r"kostenvoranschlag"),
    ("Rechnung", r"\brechnung|\binvoice"),
    ("Gerichtspost", r"\b(amtsgericht|landgericht|oberlandesgericht|gericht)\b"),
    ("Schreiben Versicherung", r"versicherung|schadennummer|schaden-nr|versicherungsnummer|regulierung"),
]


def belegart_vorschlag(betreff: str, dateinamen: list[str], text: str = "") -> str:
    """Belegart aus Betreff/Dateinamen (zuerst) und Text – nur ein Vorschlag („erkannt – bitte prüfen“)."""
    for quelle in (" ".join([betreff or ""] + list(dateinamen or [])), (text or "")[:3000]):
        for art, muster in BELEG_REGELN:
            if re.search(muster, quelle, re.I):
                return art
    return ""


_DATUM = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


def datum_vorschlag(text: str) -> str:
    """Erstes gültiges Datum (TT.MM.JJJJ) im Anfang des Textes → ISO; sonst ''. Nur ein Vorschlag."""
    for m in _DATUM.finditer((text or "")[:2000]):
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            continue
    return ""


def ueberfaellig(aufgabe: dict, heute: str | None = None) -> bool:
    return bool(aufgabe.get("faellig")) and aufgabe.get("status") != "erledigt" and \
        aufgabe["faellig"] < (heute or _heute())


# --------------------------------------------------------------------------- Datenbank
def _zeilen(cur) -> list[dict]:
    namen = [c[0] for c in cur.description]
    return [dict(zip(namen, r)) for r in cur.fetchall()]


class Posteingang:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.executescript(SCHEMA)
        self.prot = pr.Protokoll(con)
        self.con.commit()

    # --- Hilfen -------------------------------------------------------------------
    @staticmethod
    def _ich() -> pr.Benutzer:
        return pr.aktuell()

    def _darf_verteilen(self) -> bool:
        return self._ich().rolle in VERTEILEN

    def personen(self) -> list[dict]:
        """Aktive Benutzer (für „Verantwortlich“). Einzelplatz: nur der aktuelle Benutzer."""
        try:
            z = _zeilen(self.con.execute("SELECT name, anzeigename, rolle FROM benutzer WHERE aktiv = 1 "
                                         "ORDER BY name COLLATE NOCASE"))
        except sqlite3.Error:
            z = []
        if not z:
            b = self._ich()
            z = [{"name": b.name, "anzeigename": b.anzeigename, "rolle": b.rolle}]
        for p in z:
            p["anzeige"] = p.get("anzeigename") or p["name"]
        return z

    def _anzeige(self) -> dict[str, str]:
        return {p["name"].lower(): p["anzeige"] for p in self.personen()}

    def _person_pruefen(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return ""
        for p in self.personen():
            if p["name"].lower() == name.lower():
                return p["name"]
        raise ValueError(f"Den Benutzer „{name}“ gibt es nicht (mehr) oder er ist deaktiviert.")

    def _akte_gibt_es(self, ref: str) -> bool:
        return self.con.execute("SELECT 1 FROM akten WHERE referenz = ?", (ref,)).fetchone() is not None

    # --- Akte-Vorschlag --------------------------------------------------------------
    def akten_infos(self) -> list[AktenInfo]:
        spalten = {r[1] for r in self.con.execute("PRAGMA table_info(akten)")}
        sp = lambda s: s if s in spalten else "''"                       # noqa: E731 – ältere Datenbanken
        akten = _zeilen(self.con.execute(
            f"SELECT referenz, {sp('aktenzeichen')} AS aktenzeichen, {sp('versicherungsnummer')} AS vnr, "
            f"{sp('schaden_nr')} AS snr, {sp('nummer_art')} AS nummer_art, mandant_email, versicherer_email, "
            f"mandant_name, {sp('mandant_id')} AS mandant_id, {sp('versicherung_id')} AS versicherung_id FROM akten"))
        mand, vers, buch = {}, {}, {}
        try:
            mand = {r["id"]: r for r in _zeilen(self.con.execute("SELECT id, name, email FROM mandanten"))}
            vers = {r["id"]: r for r in _zeilen(self.con.execute("SELECT id, name FROM versicherungen"))}
        except sqlite3.Error:
            pass
        try:
            for r in _zeilen(self.con.execute("SELECT name, email FROM versicherer")):
                buch.setdefault(r["name"].strip().lower(), []).append(r["email"])
        except sqlite3.Error:
            pass
        out = []
        for a in akten:
            info = AktenInfo(a["referenz"])
            art = a.get("nummer_art") or ""
            info.nummern.append((art or "Akte", a["referenz"]))
            for bez, k in (("Aktenzeichen", "aktenzeichen"), ("Versicherungsnummer", "vnr"), ("Schaden-Nr.", "snr")):
                if a.get(k) and a[k] != a["referenz"]:
                    info.nummern.append((bez, a[k]))
            if a.get("mandant_email"):
                info.emails.append(("Mandant", a["mandant_email"]))
            if a.get("versicherer_email"):
                info.emails.append(("Versicherung", a["versicherer_email"]))
            m = mand.get(a.get("mandant_id"))
            if m:
                if m.get("email"):
                    info.emails.append(("Mandant", m["email"]))
                info.namen.append(("Mandant", m["name"]))
            elif a.get("mandant_name"):
                info.namen.append(("Mandant", a["mandant_name"]))
            v = vers.get(a.get("versicherung_id"))
            if v:
                for e in buch.get(v["name"].strip().lower(), []):
                    info.emails.append(("Versicherung", e))
            info.emails = list(dict.fromkeys((r, e.strip()) for r, e in info.emails if e and e.strip()))
            info.namen = list(dict.fromkeys(info.namen))
            out.append(info)
        return out

    def vorschlagen(self, text: str, absender: str) -> list[dict]:
        return akte_vorschlaege(text, absender, self.akten_infos())

    # --- Eingänge ---------------------------------------------------------------------
    def vorhanden(self, quelle_id: str = "", sha256: str = "") -> dict | None:
        """Bereits erfasster Eingang mit gleicher Message-ID oder gleicher Rohdatei (SHA-256)?"""
        if quelle_id:
            r = _zeilen(self.con.execute("SELECT id, betreff, akte, eingang_am FROM eingaenge WHERE quelle_id = ? "
                                         "ORDER BY id LIMIT 1", (quelle_id,)))
            if r:
                return r[0]
        if sha256:
            r = _zeilen(self.con.execute("SELECT id, betreff, akte, eingang_am FROM eingaenge WHERE sha256 = ? "
                                         "ORDER BY id LIMIT 1", (sha256,)))
            if r:
                return r[0]
            r = _zeilen(self.con.execute(
                "SELECT e.id, e.betreff, e.akte, e.eingang_am FROM eingang_dateien d JOIN eingaenge e "
                "ON e.id = d.eingang_id WHERE d.sha256 = ? AND d.rolle IN ('mail', 'datei') ORDER BY e.id LIMIT 1",
                (sha256,)))
            if r:
                return r[0]
        return None

    def anlegen(self, client_id: str, quelle: str, dateien: list[dict], quelle_id: str = "", sha256: str = "",
                absender: str = "", absender_name: str = "", betreff: str = "", text: str = "",
                eingang_am: str = "", dokument_datum: str = "", belegart: str = "", verantwortlich: str = "") -> dict:
        """Eingang anlegen. dateien: [{rolle: mail|anhang|datei, dokument_id, name, pfad, sha256}] (bereits im
        Archiv erfasst). Wiederholung mit gleicher client_id → derselbe Eingang (doppelt=False);
        gleiche Message-ID/Rohdatei → vorhandener Eingang (doppelt=True), nichts Neues."""
        if not client_id:
            raise ValueError("Interner Fehler: Eingangs-Kennung fehlt.")
        r = self.con.execute("SELECT id FROM eingaenge WHERE client_id = ?", (client_id,)).fetchone()
        if r:
            return {"id": int(r[0]), "doppelt": False, "wiederholt": True}
        alt = self.vorhanden(quelle_id, sha256)
        if alt:
            return {"id": int(alt["id"]), "doppelt": True, "wiederholt": False}
        wer = self._ich().name
        verantwortlich = self._person_pruefen(verantwortlich) if verantwortlich else ""
        text = (text or "")[:TEXT_MAX]
        vorschlag = akte_vorschlaege(f"{betreff}\n{text}", absender, self.akten_infos())
        jetzt = _jetzt()
        cur = self.con.execute(
            "INSERT INTO eingaenge (client_id, quelle, quelle_id, sha256, eingang_am, dokument_datum, absender, "
            "absender_name, betreff, belegart, vorschlag, verantwortlich, status, text, erstellt_von, erstellt_am, "
            "geaendert_von, geaendert_am) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (client_id, quelle, quelle_id or "", sha256 or "", eingang_am or jetzt, dokument_datum or "",
             absender or "", absender_name or "", betreff or "", belegart or "",
             json.dumps(vorschlag[:8], ensure_ascii=False), verantwortlich, "neu", text, wer, jetzt, wer, jetzt))
        eid = int(cur.lastrowid)
        for i, d in enumerate(dateien or []):
            self.con.execute("INSERT INTO eingang_dateien (eingang_id, position, rolle, dokument_id, name, pfad, sha256)"
                             " VALUES (?,?,?,?,?,?,?)", (eid, i, d.get("rolle", "datei"), d.get("dokument_id"),
                                                         d.get("name", ""), str(d.get("pfad", "")),
                                                         d.get("sha256", "")))
        self.prot.eintragen("eingang", eid, "erstellt", [], betreff or (dateien[0]["name"] if dateien else ""),
                            commit=False)
        self.con.commit()
        return {"id": eid, "doppelt": False, "wiederholt": False}

    def eingang(self, eid: int) -> dict | None:
        r = _zeilen(self.con.execute("SELECT * FROM eingaenge WHERE id = ?", (eid,)))
        if not r:
            return None
        e = self._aufbereiten(r[0])
        e["dateien"] = _zeilen(self.con.execute("SELECT * FROM eingang_dateien WHERE eingang_id = ? ORDER BY position",
                                                (eid,)))
        e["aufgaben"] = self.aufgaben(eingang_id=eid, alle=True)
        return e

    def _aufbereiten(self, e: dict, anzeige: dict | None = None) -> dict:
        anzeige = anzeige if anzeige is not None else self._anzeige()
        e = dict(e)
        try:
            e["vorschlag"] = json.loads(e.get("vorschlag") or "[]")
        except ValueError:
            e["vorschlag"] = []
        e["eindeutig"] = eindeutig(e["vorschlag"])
        e["status_text"] = STATUS.get(e.get("status"), e.get("status"))
        for k in ("verantwortlich", "erstellt_von", "geaendert_von", "zugeordnet_von"):
            e[k + "_anzeige"] = anzeige.get((e.get(k) or "").lower(), e.get(k) or "")
        return e

    def liste(self, ansicht: str = "offen", verantwortlich: str = "", akte: str = "", suche: str = "",
              limit: int = 500) -> list[dict]:
        """ansicht: alle | offen | nicht_zugeordnet | neu | in_bearbeitung | erledigt."""
        sql, w = "SELECT * FROM eingaenge WHERE 1=1", []
        if ansicht == "offen":
            sql += " AND status != 'erledigt'"
        elif ansicht == "nicht_zugeordnet":
            sql += " AND akte = ''"
        elif ansicht in STATUS:
            sql += " AND status = ?"
            w.append(ansicht)
        if verantwortlich:
            sql += " AND lower(verantwortlich) = ?"
            w.append(verantwortlich.lower())
        if akte:
            sql += " AND akte = ?"
            w.append(akte)
        if suche:
            sql += " AND (betreff LIKE ? OR absender LIKE ? OR absender_name LIKE ? OR akte LIKE ? OR text LIKE ?)"
            w += [f"%{suche}%"] * 5
        sql += " ORDER BY eingang_am DESC, id DESC LIMIT ?"
        w.append(limit)
        anzeige = self._anzeige()
        out = []
        offen = {r[0]: r[1] for r in self.con.execute(
            "SELECT eingang_id, COUNT(*) FROM aufgaben WHERE status != 'erledigt' AND eingang_id IS NOT NULL "
            "GROUP BY eingang_id")}
        for e in _zeilen(self.con.execute(sql, w)):
            e.pop("text", None)
            e = self._aufbereiten(e, anzeige)
            e["offene_aufgaben"] = offen.get(e["id"], 0)
            out.append(e)
        return out

    def aendern(self, eid: int, _basis: dict | None = None, **werte) -> dict:
        """Belegart, Verantwortlich, Status, nächster Schritt … ändern (Konfliktprüfung gegen _basis)."""
        werte = {k: str(v or "").strip() for k, v in werte.items() if k in EINGANG_FELDER}
        if "status" in werte and werte["status"] not in STATUS:
            raise ValueError("Unbekannter Status.")
        if werte.get("verantwortlich"):
            werte["verantwortlich"] = self._person_pruefen(werte["verantwortlich"])
        alt = _zeilen(self.con.execute("SELECT * FROM eingaenge WHERE id = ?", (eid,)))
        if not alt:
            raise ValueError("Diesen Eingang gibt es nicht (mehr).")
        alt = alt[0]
        k = pr.konflikte(alt, werte, _basis)
        if k:
            raise pr.Konflikt("eingang", eid, k, alt)
        werte = pr.geaendert(alt, werte)
        if werte:
            self.con.execute(f"UPDATE eingaenge SET {', '.join(f'{x} = ?' for x in werte)}, geaendert_von = ?, "
                             "geaendert_am = ? WHERE id = ?", (*werte.values(), self._ich().name, _jetzt(), eid))
            self.prot.eintragen("eingang", eid, "geaendert", list(werte), alt.get("betreff") or "", commit=False)
            self.con.commit()
        return self.eingang(eid)

    def zuordnen(self, eid: int, akte: str, _basis_akte: str | None = None) -> dict:
        """Akte bestätigen (Mensch). Dokumente werden der Akte zugeordnet und erscheinen in ihrem Verlauf.
        _basis_akte: beim Laden gesehene Akte – hat jemand anderes inzwischen anders zugeordnet → Konflikt."""
        akte = (akte or "").strip()
        alt = _zeilen(self.con.execute("SELECT * FROM eingaenge WHERE id = ?", (eid,)))
        if not alt:
            raise ValueError("Diesen Eingang gibt es nicht (mehr).")
        alt = alt[0]
        if _basis_akte is not None and not pr.gleich(alt["akte"], _basis_akte) and not pr.gleich(alt["akte"], akte):
            raise pr.Konflikt("eingang", eid, ["akte"], {**alt, "geaendert_am": alt.get("zugeordnet_am")})
        if akte and not self._akte_gibt_es(akte):
            raise ValueError(f"Die Akte „{akte}“ gibt es nicht (mehr).")
        if pr.gleich(alt["akte"], akte):
            return self.eingang(eid)
        wer, jetzt = self._ich().name, _jetzt()
        self.con.execute("UPDATE eingaenge SET akte = ?, zugeordnet_von = ?, zugeordnet_am = ?, geaendert_von = ?, "
                         "geaendert_am = ? WHERE id = ?", (akte, wer, jetzt, wer, jetzt, eid))
        dateien = _zeilen(self.con.execute("SELECT * FROM eingang_dateien WHERE eingang_id = ? ORDER BY position",
                                           (eid,)))
        for d in dateien:
            if d.get("dokument_id"):
                self.con.execute("UPDATE dokumente SET akte = ? WHERE id = ?", (akte, d["dokument_id"]))
        self.con.execute("UPDATE aufgaben SET akte = ? WHERE eingang_id = ? AND akte = ''", (akte, eid))
        if akte:
            qid = f"posteingang:{eid}"
            if not self.con.execute("SELECT 1 FROM vorgaenge WHERE quelle_id = ? AND referenz = ?",
                                    (qid, akte)).fetchone():
                haupt = next((d for d in dateien if d["rolle"] in ("mail", "datei")), dateien[0] if dateien else None)
                anl = sum(1 for d in dateien if d["rolle"] == "anhang")
                self.con.execute(
                    "INSERT INTO vorgaenge (zeit, workflow, dokument, ergebnis, empfaenger, referenz, status, meldung,"
                    " art, quelle_id, benutzer) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (jetzt, "posteingang", (haupt or {}).get("pfad", ""), (haupt or {}).get("pfad", ""),
                     alt.get("absender") or "", akte, "ok",
                     (alt.get("betreff") or "Eingang") + (f" ({anl} Anlage(n))" if anl else ""),
                     "eingang", qid, self._ich().text))
        self.prot.eintragen("eingang", eid, "zugeordnet" if akte else "zuordnung_geloest", ["akte"],
                            alt.get("betreff") or "", commit=False)
        if akte:
            self.prot.eintragen("akte", akte, "dokument_zugeordnet", [], alt.get("betreff") or "Eingang", commit=False)
        self.con.commit()
        return self.eingang(eid)

    def vorschlag_neu(self, eid: int) -> list[dict]:
        """Vorschlag neu berechnen (z. B. nach neuer Akte oder Texterkennung)."""
        e = _zeilen(self.con.execute("SELECT betreff, text, absender FROM eingaenge WHERE id = ?", (eid,)))
        if not e:
            raise ValueError("Diesen Eingang gibt es nicht (mehr).")
        v = akte_vorschlaege(f"{e[0]['betreff']}\n{e[0]['text']}", e[0]["absender"], self.akten_infos())
        self.con.execute("UPDATE eingaenge SET vorschlag = ? WHERE id = ?", (json.dumps(v[:8], ensure_ascii=False), eid))
        self.con.commit()
        return v

    def text_ergaenzen(self, eid: int, text: str) -> list[dict]:
        """Zusätzlicher Text (z. B. Texterkennung eines Scans) → Vorschlag neu."""
        alt = self.con.execute("SELECT text FROM eingaenge WHERE id = ?", (eid,)).fetchone()
        if alt is None:
            raise ValueError("Diesen Eingang gibt es nicht (mehr).")
        neu = ((alt[0] or "") + "\n" + (text or ""))[:TEXT_MAX]
        self.con.execute("UPDATE eingaenge SET text = ? WHERE id = ?", (neu, eid))
        self.con.commit()
        return self.vorschlag_neu(eid)

    # --- Aufgaben ------------------------------------------------------------------------
    def aufgabe_anlegen(self, client_id: str, art: str, verantwortlich: str, beschreibung: str = "",
                        prioritaet: str = "normal", faellig: str = "", eingang_id: int | None = None,
                        akte: str = "", titel: str = "", erwartung_id: int | None = None) -> dict:
        """Aufgabe aus einer Schnellaktion. Wiederholung mit gleicher client_id → dieselbe Aufgabe."""
        from core.benutzer import Berechtigung
        if not client_id:
            raise ValueError("Interner Fehler: Aufgaben-Kennung fehlt.")
        r = self.con.execute("SELECT id FROM aufgaben WHERE client_id = ?", (client_id,)).fetchone()
        if r:
            return self.aufgabe(int(r[0]))
        if art not in AKTIONEN:
            raise ValueError("Unbekannte Aufgabenart.")
        if prioritaet not in PRIORITAETEN:
            raise ValueError("Unbekannte Priorität.")
        faellig = _datum_pruefen(faellig)
        ich = self._ich()
        verantwortlich = self._person_pruefen(verantwortlich) or ich.name
        if not self._darf_verteilen() and verantwortlich.lower() != ich.name.lower():
            raise Berechtigung("Keine Berechtigung: Aufgaben für andere vergibt die Rechtsanwältin / der "
                               "Rechtsanwalt. Sie können sich selbst eine Aufgabe anlegen.")
        if eingang_id is not None:
            e = self.con.execute("SELECT akte FROM eingaenge WHERE id = ?", (eingang_id,)).fetchone()
            if e is None:
                raise ValueError("Diesen Eingang gibt es nicht (mehr).")
            akte = akte or e[0] or ""
        if akte and not self._akte_gibt_es(akte):
            raise ValueError(f"Die Akte „{akte}“ gibt es nicht (mehr).")
        titel = (titel or AKTIONEN[art][0]).strip()
        beschreibung = (beschreibung or "").strip() or AKTIONEN[art][1]
        jetzt = _jetzt()
        cur = self.con.execute(
            "INSERT INTO aufgaben (client_id, eingang_id, erwartung_id, akte, art, titel, beschreibung, verantwortlich,"
            " prioritaet, faellig, status, erstellt_von, erstellt_am, geaendert_von, geaendert_am)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (client_id, eingang_id, erwartung_id, akte, art, titel, beschreibung, verantwortlich, prioritaet, faellig,
             "offen", ich.name, jetzt, ich.name, jetzt))
        aid = int(cur.lastrowid)
        if eingang_id is not None:
            self.con.execute("UPDATE eingaenge SET status = 'in_bearbeitung', geaendert_von = ?, geaendert_am = ? "
                             "WHERE id = ? AND status = 'neu'", (ich.name, jetzt, eingang_id))
        self.prot.eintragen("aufgabe", aid, "erstellt", ["verantwortlich"], titel, commit=False)
        self.con.commit()
        return self.aufgabe(aid)

    def aufgabe(self, aid: int) -> dict | None:
        r = _zeilen(self.con.execute("SELECT a.*, e.betreff AS eingang_betreff FROM aufgaben a LEFT JOIN eingaenge e "
                                     "ON e.id = a.eingang_id WHERE a.id = ?", (aid,)))
        return self._aufgabe_aufbereiten(r[0]) if r else None

    def _aufgabe_aufbereiten(self, a: dict, anzeige: dict | None = None) -> dict:
        anzeige = anzeige if anzeige is not None else self._anzeige()
        a = dict(a)
        a["status_text"] = AUFGABE_STATUS.get(a["status"], a["status"])
        a["prioritaet_text"] = PRIORITAETEN.get(a["prioritaet"], a["prioritaet"])
        a["ueberfaellig"] = ueberfaellig(a)
        for k in ("verantwortlich", "erstellt_von", "erledigt_von", "wiedereroeffnet_von", "geaendert_von"):
            a[k + "_anzeige"] = anzeige.get((a.get(k) or "").lower(), a.get(k) or "")
        return a

    def aufgaben(self, ansicht: str = "offen", verantwortlich: str = "", akte: str = "", eingang_id: int | None = None,
                 alle: bool = False) -> list[dict]:
        """ansicht: offen | ueberfaellig | erledigt | alle. verantwortlich="ich" → aktueller Benutzer."""
        if verantwortlich == "ich":
            verantwortlich = self._ich().name
        sql, w = ("SELECT a.*, e.betreff AS eingang_betreff FROM aufgaben a LEFT JOIN eingaenge e "
                  "ON e.id = a.eingang_id WHERE 1=1"), []
        if not alle:
            if ansicht in ("offen", "ueberfaellig"):
                sql += " AND a.status != 'erledigt'"
            elif ansicht == "erledigt":
                sql += " AND a.status = 'erledigt'"
            if ansicht == "ueberfaellig":
                sql += " AND a.faellig != '' AND a.faellig < ?"
                w.append(_heute())
        if verantwortlich:
            sql += " AND lower(a.verantwortlich) = ?"
            w.append(verantwortlich.lower())
        if akte:
            sql += " AND a.akte = ?"
            w.append(akte)
        if eingang_id is not None:
            sql += " AND a.eingang_id = ?"
            w.append(eingang_id)
        sql += (" ORDER BY CASE a.status WHEN 'erledigt' THEN 1 ELSE 0 END, CASE a.faellig WHEN '' THEN 1 ELSE 0 END,"
                " a.faellig, CASE a.prioritaet WHEN 'hoch' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, a.id DESC")
        anzeige = self._anzeige()
        return [self._aufgabe_aufbereiten(a, anzeige) for a in _zeilen(self.con.execute(sql, w))]

    def _aufgabe_roh(self, aid: int) -> dict:
        r = _zeilen(self.con.execute("SELECT * FROM aufgaben WHERE id = ?", (aid,)))
        if not r:
            raise ValueError("Diese Aufgabe gibt es nicht (mehr).")
        return r[0]

    def _darf_aufgabe(self, a: dict) -> bool:
        ich = self._ich().name.lower()
        return self._darf_verteilen() or ich in ((a.get("verantwortlich") or "").lower(),
                                                 (a.get("erstellt_von") or "").lower())

    def aufgabe_aendern(self, aid: int, _basis: dict | None = None, **werte) -> dict:
        from core.benutzer import Berechtigung
        werte = {k: str(v or "").strip() for k, v in werte.items() if k in AUFGABE_FELDER}
        alt = self._aufgabe_roh(aid)
        if "status" in werte:
            if werte["status"] not in AUFGABE_STATUS:
                raise ValueError("Unbekannter Status.")
            if werte["status"] == "erledigt" or alt["status"] == "erledigt":
                werte.pop("status")                       # erledigen/wieder öffnen nur über die eigenen Aktionen
        if "prioritaet" in werte and werte["prioritaet"] not in PRIORITAETEN:
            raise ValueError("Unbekannte Priorität.")
        if "faellig" in werte:
            werte["faellig"] = _datum_pruefen(werte["faellig"])
        if "verantwortlich" in werte:
            werte["verantwortlich"] = self._person_pruefen(werte["verantwortlich"]) or alt["verantwortlich"]
            if not pr.gleich(werte["verantwortlich"], alt["verantwortlich"]) and not self._darf_verteilen():
                raise Berechtigung("Keine Berechtigung: Aufgaben neu verteilen kann die Rechtsanwältin / der "
                                   "Rechtsanwalt.")
        if not self._darf_aufgabe(alt):
            raise Berechtigung("Keine Berechtigung: Diese Aufgabe gehört einer anderen Person.")
        k = pr.konflikte(alt, werte, _basis)
        if k:
            raise pr.Konflikt("aufgabe", aid, k, alt)
        werte = pr.geaendert(alt, werte)
        if werte:
            self.con.execute(f"UPDATE aufgaben SET {', '.join(f'{x} = ?' for x in werte)}, geaendert_von = ?, "
                             "geaendert_am = ? WHERE id = ?", (*werte.values(), self._ich().name, _jetzt(), aid))
            self.prot.eintragen("aufgabe", aid, "geaendert", list(werte), alt["titel"], commit=False)
            self.con.commit()
        return self.aufgabe(aid)

    def erledigen(self, aid: int) -> dict:
        """Mit Benutzer und Zeit. Schon erledigt → unverändert (Wiederholung nach Verbindungsabbruch)."""
        from core.benutzer import Berechtigung
        a = self._aufgabe_roh(aid)
        if not self._darf_aufgabe(a):
            raise Berechtigung("Keine Berechtigung: Diese Aufgabe gehört einer anderen Person.")
        if a["status"] != "erledigt":
            wer, jetzt = self._ich().name, _jetzt()
            self.con.execute("UPDATE aufgaben SET status = 'erledigt', erledigt_von = ?, erledigt_am = ?, "
                             "geaendert_von = ?, geaendert_am = ? WHERE id = ?", (wer, jetzt, wer, jetzt, aid))
            self.prot.eintragen("aufgabe", aid, "erledigt", [], a["titel"], commit=False)
            self.con.commit()
        return self.aufgabe(aid)

    def wieder_oeffnen(self, aid: int) -> dict:
        """Versehentlich erledigt → wieder offen (erledigt_von/_am bleiben im Änderungsverlauf sichtbar)."""
        from core.benutzer import Berechtigung
        a = self._aufgabe_roh(aid)
        if not self._darf_aufgabe(a):
            raise Berechtigung("Keine Berechtigung: Diese Aufgabe gehört einer anderen Person.")
        if a["status"] == "erledigt":
            wer, jetzt = self._ich().name, _jetzt()
            self.con.execute("UPDATE aufgaben SET status = 'offen', wiedereroeffnet_von = ?, wiedereroeffnet_am = ?, "
                             "geaendert_von = ?, geaendert_am = ? WHERE id = ?", (wer, jetzt, wer, jetzt, aid))
            self.prot.eintragen("aufgabe", aid, "wiedereroeffnet", [], a["titel"], commit=False)
            self.con.commit()
        return self.aufgabe(aid)

    # --- Übersicht für die Startseite -----------------------------------------------------
    def uebersicht(self) -> dict:
        ich = self._ich().name
        meine = self.aufgaben("offen", verantwortlich=ich)
        return {"meine": meine[:20], "meine_anzahl": len(meine),
                "ueberfaellig": [a for a in self.aufgaben("ueberfaellig")
                                 if self._darf_verteilen() or a["verantwortlich"].lower() == ich.lower()][:20],
                "nicht_zugeordnet": int(self.con.execute("SELECT COUNT(*) FROM eingaenge WHERE akte = '' AND "
                                                         "status != 'erledigt'").fetchone()[0]),
                "neu": int(self.con.execute("SELECT COUNT(*) FROM eingaenge WHERE status = 'neu'").fetchone()[0])}

    def aenderungsverlauf(self, art: str, objekt) -> list[dict]:
        return self.prot.fuer(art, objekt)


def _datum_pruefen(s: str) -> str:
    """'' oder ISO-Datum (JJJJ-MM-TT); TT.MM.JJJJ wird umgewandelt."""
    s = (s or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise ValueError(f"Ungültiges Datum: „{s}“ (bitte TT.MM.JJJJ).") from None
