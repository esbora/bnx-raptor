"""Was fehlt? (0.5): erwartete Unterlagen und Antworten je Akte.

Saf Python + SQLite (aynı verlauf.sqlite).

- Erwartung (`erwartungen`): was, von wem, wer kümmert sich, angefordert am, Nachfassen am, Notiz, Status.
  „Eingegangen – zu prüfen“ und „Geprüft / vollständig“ sind getrennt: ein Teil- oder falscher Eingang bleibt
  offen. BnX-Raptor setzt NIE selbst „Geprüft / vollständig“.
- „Angefordert am“ entsteht nur durch eine bestätigte Versendung (Versand bestätigt) oder eine ausdrückliche
  Eintragung durch einen Menschen – ein bloß erstellter Entwurf zählt nicht.
- Checklisten-Vorlagen je Aktenart sind Vorschläge (keine rechtlichen Pflichten). Beim Anwenden werden die Punkte in
  die Akte KOPIERT – spätere Änderungen an der Vorlage ändern bestehende Akten nicht.
- Verknüpfungen (`erwartung_links`): Anforderung (Entwurf/Versand), Eingang, Dokument.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime

from core import protokoll as pr
from core.posteingang import _datum_pruefen

SCHEMA = """
CREATE TABLE IF NOT EXISTS erwartungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    akte TEXT NOT NULL,
    titel TEXT NOT NULL,
    von_rolle TEXT DEFAULT 'mandant', von_name TEXT DEFAULT '',
    verantwortlich TEXT DEFAULT '',
    angefordert_am TEXT DEFAULT '', angefordert_quelle TEXT DEFAULT '', angefordert_von TEXT DEFAULT '',
    nachfassen TEXT DEFAULT '',
    beschreibung TEXT DEFAULT '',
    status TEXT DEFAULT 'nicht_angefordert',
    vorlage TEXT DEFAULT '',
    geprueft_von TEXT DEFAULT '', geprueft_am TEXT DEFAULT '',
    erstellt_von TEXT DEFAULT '', erstellt_am TEXT DEFAULT '',
    geaendert_von TEXT DEFAULT '', geaendert_am TEXT DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS ix_erwartungen_client ON erwartungen(client_id);
CREATE INDEX IF NOT EXISTS ix_erwartungen_akte ON erwartungen(akte, status);
CREATE TABLE IF NOT EXISTS erwartung_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    erwartung_id INTEGER NOT NULL, art TEXT NOT NULL, ziel_id INTEGER, text TEXT DEFAULT '',
    zeit TEXT, benutzer TEXT DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS ix_erwartung_links ON erwartung_links(erwartung_id, art, ziel_id);
CREATE TABLE IF NOT EXISTS checklisten (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, akte_art TEXT DEFAULT '', beschreibung TEXT DEFAULT '', aktiv INTEGER DEFAULT 1,
    geaendert_von TEXT DEFAULT '', geaendert_am TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS checklisten_punkte (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkliste_id INTEGER NOT NULL, position INTEGER DEFAULT 0,
    titel TEXT NOT NULL, von_rolle TEXT DEFAULT 'mandant', beschreibung TEXT DEFAULT '');
"""

STATUS = {"nicht_angefordert": "Noch nicht angefordert", "angefordert": "Angefordert",
          "eingegangen": "Eingegangen – zu prüfen", "geprueft": "Geprüft / vollständig",
          "nicht_erforderlich": "Nicht erforderlich"}
OFFEN = ("nicht_angefordert", "angefordert", "eingegangen")
VON_ROLLEN = {"mandant": "Mandant", "versicherung": "Versicherung", "gegner": "Gegenseite", "gericht": "Gericht",
              "sachverstaendiger": "Sachverständiger", "sonstige": "Sonstige"}
ERWARTUNG_FELDER = ("titel", "von_rolle", "von_name", "verantwortlich", "nachfassen", "beschreibung", "status")
NUR_ANWALT_STATUS = {"geprueft", "nicht_erforderlich"}     # Entscheidung: Rechtsanwalt/Administrator
BEISPIEL = ("Verkehrsunfall / Versicherung (Beispiel)", "Verkehrsunfall",
            "Beispiel-Vorlage – keine rechtliche Pflichtliste. Bitte für die eigene Kanzlei anpassen.",
            [("Vollmacht", "mandant"), ("Gutachten", "sachverstaendiger"), ("Rechnung", "mandant"),
             ("Antwort der Versicherung", "versicherung")])
# Schlüsselwörter für den Abgleich Eingang → erwartete Unterlage (nur Vorschlag)
STICHWOERTER = {"vollmacht": ["vollmacht"], "gutachten": ["gutachten", "sachverständig"],
                "rechnung": ["rechnung", "invoice"], "kostenvoranschlag": ["kostenvoranschlag", "kva"],
                "antwort": ["antwort", "stellungnahme", "regulierung", "schreiben", "ihr schreiben", "re:", "aw:"],
                "fotos": ["foto", "bild", "lichtbild"], "polizei": ["polizei", "unfallbericht", "ermittlungsakte"]}


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _zeilen(cur) -> list[dict]:
    namen = [c[0] for c in cur.description]
    return [dict(zip(namen, r)) for r in cur.fetchall()]


def _woerter(s: str) -> set[str]:
    return set(re.findall(r"\w{3,}", (s or "").lower()))


def passende_erwartungen(betreff: str, dateinamen: list[str], belegart: str, absender_rolle: str,
                         offene: list[dict]) -> list[dict]:
    """Offene Erwartungen, zu denen ein Eingang passen könnte – mit Begründung. Nur Vorschlag; verknüpft und
    geprüft wird erst durch einen Menschen. → [{erwartung_id, titel, gruende, punkte}]"""
    quelle = " ".join([betreff or "", belegart or "", *(dateinamen or [])]).lower()
    out = []
    for e in offene:
        if e.get("status") not in OFFEN:
            continue
        gruende, punkte = [], 0
        titel = (e.get("titel") or "").lower()
        for schluessel, woerter in STICHWOERTER.items():
            if schluessel in titel or any(w in titel for w in woerter):
                treffer = [w for w in woerter if w in quelle]
                if treffer:
                    gruende.append(f"„{treffer[0]}“ im Betreff/Dateinamen")
                    punkte += 60
                    break
        gemeinsam = _woerter(titel) & _woerter(quelle)
        if gemeinsam and not gruende:
            gruende.append("gleiches Wort: " + ", ".join(sorted(gemeinsam)[:3]))
            punkte += 30
        if punkte and absender_rolle and e.get("von_rolle") == absender_rolle:
            gruende.append(f"kommt von {VON_ROLLEN.get(absender_rolle, absender_rolle)} (wie erwartet)")
            punkte += 20
        if punkte:
            out.append({"erwartung_id": e["id"], "titel": e["titel"], "gruende": gruende, "punkte": punkte})
    return sorted(out, key=lambda x: -x["punkte"])


def erinnerung_text(akte: dict, offene: list[dict], empfaenger_rolle: str) -> tuple[str, str]:
    """(Betreff, HTML-Text) für „Erinnerung vorbereiten“ – nur fehlende Punkte dieser Empfängergruppe."""
    from html import escape
    punkte = [e for e in offene if e.get("status") in ("nicht_angefordert", "angefordert")
              and (not empfaenger_rolle or e.get("von_rolle") == empfaenger_rolle)]
    nummern = [x for x in (akte.get("aktenzeichen"), akte.get("versicherungsnummer"), akte.get("schaden_nr")) if x]
    zeichen = " / ".join(dict.fromkeys(nummern)) or akte.get("referenz", "")
    betreff = f"Fehlende Unterlagen – {zeichen}" if zeichen else "Fehlende Unterlagen"
    liste = "".join(f"<li>{escape(e['titel'])}" + (f" – {escape(e['beschreibung'])}" if e.get("beschreibung") else "")
                    + "</li>" for e in punkte)
    text = ("<p>Sehr geehrte Damen und Herren,</p>"
            f"<p>in der oben genannten Angelegenheit ({escape(zeichen)}) fehlen uns noch folgende Unterlagen:</p>"
            f"<ul>{liste}</ul><p>Wir bitten um Übersendung.</p><p>Mit freundlichen Grüßen</p>")
    return betreff, text


class Unterlagen:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.executescript(SCHEMA)
        self.prot = pr.Protokoll(con)
        akten_spalten = {r[1] for r in self.con.execute("PRAGMA table_info(akten)")}
        if akten_spalten and "akte_art" not in akten_spalten:          # wie Stammdaten.AKTEN_SPALTEN (nur Ergänzung)
            self.con.execute("ALTER TABLE akten ADD COLUMN akte_art TEXT DEFAULT ''")
        if not self.con.execute("SELECT 1 FROM checklisten LIMIT 1").fetchone():
            self._vorlage_schreiben(None, BEISPIEL[0], BEISPIEL[1], BEISPIEL[2],
                                    [{"titel": t, "von_rolle": r} for t, r in BEISPIEL[3]], protokoll=False)
        self.con.commit()

    @staticmethod
    def _ich() -> pr.Benutzer:
        return pr.aktuell()

    def _anzeige(self) -> dict[str, str]:
        ich = pr.aktuell()
        out = {ich.name.lower(): ich.anzeigename or ich.name}          # Einzelplatz: keine Benutzertabelle
        try:
            out.update({r[0].lower(): (r[1] or r[0]) for r in
                        self.con.execute("SELECT name, anzeigename FROM benutzer")})
        except sqlite3.Error:
            pass
        return out

    def _akte_gibt_es(self, ref: str) -> bool:
        return self.con.execute("SELECT 1 FROM akten WHERE referenz = ?", (ref,)).fetchone() is not None

    def _aufbereiten(self, e: dict, anzeige: dict | None = None) -> dict:
        anzeige = anzeige if anzeige is not None else self._anzeige()
        e = dict(e)
        e["status_text"] = STATUS.get(e["status"], e["status"])
        e["von_text"] = VON_ROLLEN.get(e["von_rolle"], e["von_rolle"]) + (f" ({e['von_name']})" if e.get("von_name")
                                                                          else "")
        heute = date.today().isoformat()
        e["nachfassen_faellig"] = bool(e.get("nachfassen")) and e["status"] in OFFEN and e["nachfassen"] < heute
        for k in ("verantwortlich", "erstellt_von", "geaendert_von", "geprueft_von", "angefordert_von"):
            e[k + "_anzeige"] = anzeige.get((e.get(k) or "").lower(), e.get(k) or "")
        e["links"] = _zeilen(self.con.execute("SELECT * FROM erwartung_links WHERE erwartung_id = ? ORDER BY id",
                                              (e["id"],)))
        return e

    # --- Erwartungen -----------------------------------------------------------------
    def liste(self, akte: str) -> list[dict]:
        anzeige = self._anzeige()
        return [self._aufbereiten(e, anzeige) for e in _zeilen(self.con.execute(
            "SELECT * FROM erwartungen WHERE akte = ? ORDER BY CASE status WHEN 'geprueft' THEN 2 WHEN "
            "'nicht_erforderlich' THEN 3 ELSE 0 END, id", (akte,)))]

    def erwartung(self, eid: int) -> dict | None:
        r = _zeilen(self.con.execute("SELECT * FROM erwartungen WHERE id = ?", (eid,)))
        return self._aufbereiten(r[0]) if r else None

    def anlegen(self, client_id: str, akte: str, titel: str, von_rolle: str = "mandant", von_name: str = "",
                verantwortlich: str = "", nachfassen: str = "", beschreibung: str = "", vorlage: str = "") -> dict:
        if not client_id:
            raise ValueError("Interner Fehler: Kennung fehlt.")
        r = self.con.execute("SELECT id FROM erwartungen WHERE client_id = ?", (client_id,)).fetchone()
        if r:
            return self.erwartung(int(r[0]))
        titel = (titel or "").strip()
        if not titel:
            raise ValueError("Bitte angeben, welche Unterlage oder Antwort erwartet wird.")
        if not self._akte_gibt_es(akte):
            raise ValueError(f"Die Akte „{akte}“ gibt es nicht (mehr).")
        if von_rolle not in VON_ROLLEN:
            raise ValueError("Unbekannte Herkunft.")
        wer, jetzt = self._ich().name, _jetzt()
        cur = self.con.execute(
            "INSERT INTO erwartungen (client_id, akte, titel, von_rolle, von_name, verantwortlich, nachfassen, "
            "beschreibung, status, vorlage, erstellt_von, erstellt_am, geaendert_von, geaendert_am)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (client_id, akte, titel, von_rolle, (von_name or "").strip(), (verantwortlich or "").strip(),
             _datum_pruefen(nachfassen), (beschreibung or "").strip(), "nicht_angefordert", vorlage, wer, jetzt,
             wer, jetzt))
        eid = int(cur.lastrowid)
        self.prot.eintragen("erwartung", eid, "erstellt", [], f"{akte}: {titel}", commit=False)
        self.prot.eintragen("akte", akte, "erwartung_angelegt", [], titel, commit=False)
        self.con.commit()
        return self.erwartung(eid)

    def aendern(self, eid: int, _basis: dict | None = None, **werte) -> dict:
        from core.benutzer import Berechtigung
        werte = {k: str(v or "").strip() for k, v in werte.items() if k in ERWARTUNG_FELDER}
        alt = _zeilen(self.con.execute("SELECT * FROM erwartungen WHERE id = ?", (eid,)))
        if not alt:
            raise ValueError("Diesen Eintrag gibt es nicht (mehr).")
        alt = alt[0]
        if "status" in werte:
            s = werte["status"]
            if s not in STATUS:
                raise ValueError("Unbekannter Status.")
            if s == "angefordert" and alt["status"] != "angefordert":
                werte.pop("status")                       # nur über angefordert_eintragen() (mit Datum + Quelle)
            elif s in NUR_ANWALT_STATUS and s != alt["status"] and self._ich().rolle not in ("admin", "anwalt"):
                raise Berechtigung("Keine Berechtigung: „Geprüft / vollständig“ und „Nicht erforderlich“ setzt die "
                                   "Rechtsanwältin / der Rechtsanwalt.")
        if "von_rolle" in werte and werte["von_rolle"] not in VON_ROLLEN:
            raise ValueError("Unbekannte Herkunft.")
        if "nachfassen" in werte:
            werte["nachfassen"] = _datum_pruefen(werte["nachfassen"])
        if "titel" in werte and not werte["titel"]:
            raise ValueError("Bitte angeben, welche Unterlage oder Antwort erwartet wird.")
        k = pr.konflikte(alt, werte, _basis)
        if k:
            raise pr.Konflikt("erwartung", eid, k, alt)
        werte = pr.geaendert(alt, werte)
        if not werte:
            return self.erwartung(eid)
        wer, jetzt = self._ich().name, _jetzt()
        extra, ew = "", []
        if werte.get("status") == "geprueft":
            extra, ew = ", geprueft_von = ?, geprueft_am = ?", [wer, jetzt]
        self.con.execute(f"UPDATE erwartungen SET {', '.join(f'{x} = ?' for x in werte)}{extra}, geaendert_von = ?, "
                         "geaendert_am = ? WHERE id = ?", (*werte.values(), *ew, wer, jetzt, eid))
        self.prot.eintragen("erwartung", eid, "geaendert", list(werte), f"{alt['akte']}: {alt['titel']}", commit=False)
        self.con.commit()
        return self.erwartung(eid)

    def angefordert_eintragen(self, eid: int, datum: str = "", quelle: str = "manuell", versand_id: int | None = None,
                              notiz: str = "") -> dict:
        """„Angefordert am“ setzen – nur durch ausdrückliche Eintragung eines Menschen (quelle=manuell) oder eine
        bestätigte Versendung (quelle=versand_bestaetigt, versand_id). Ein erstellter Entwurf genügt nicht."""
        if quelle not in ("manuell", "versand_bestaetigt"):
            raise ValueError("Angefordert kann nur nach bestätigter Versendung oder durch ausdrückliche Eintragung "
                             "gesetzt werden – ein Entwurf allein genügt nicht.")
        if quelle == "versand_bestaetigt":
            try:
                v = self.con.execute("SELECT status, bestaetigt_am FROM versand WHERE id = ?",
                                     (versand_id,)).fetchone() if versand_id else None
            except sqlite3.OperationalError:
                v = None
            if not v or v[0] != "versand_bestaetigt":
                raise ValueError("Diese Versendung ist nicht als gesendet bestätigt.")
            datum = datum or (v[1] or "")[:10]
        alt = _zeilen(self.con.execute("SELECT * FROM erwartungen WHERE id = ?", (eid,)))
        if not alt:
            raise ValueError("Diesen Eintrag gibt es nicht (mehr).")
        alt = alt[0]
        datum = _datum_pruefen(datum) or date.today().isoformat()
        wer, jetzt = self._ich().name, _jetzt()
        neuer_status = "angefordert" if alt["status"] == "nicht_angefordert" else alt["status"]
        self.con.execute("UPDATE erwartungen SET angefordert_am = ?, angefordert_quelle = ?, angefordert_von = ?, "
                         "status = ?, geaendert_von = ?, geaendert_am = ? WHERE id = ?",
                         (datum, quelle, wer, neuer_status, wer, jetzt, eid))
        if versand_id:
            self._link(eid, "versand", versand_id, notiz or "Anforderung versendet")
        elif notiz:
            self._link(eid, "anforderung", None, notiz)
        self.prot.eintragen("erwartung", eid, "angefordert", ["angefordert_am"], f"{alt['akte']}: {alt['titel']}",
                            commit=False)
        self.con.commit()
        return self.erwartung(eid)

    def _link(self, eid: int, art: str, ziel_id: int | None, text: str = "") -> None:
        self.con.execute("INSERT OR IGNORE INTO erwartung_links (erwartung_id, art, ziel_id, text, zeit, benutzer) "
                         "VALUES (?,?,?,?,?,?)", (eid, art, ziel_id, text, _jetzt(), self._ich().name))

    def entwurf_vermerken(self, eid: int, versand_id: int | None = None, text: str = "") -> dict:
        """Erinnerungs-Entwurf erstellt → nur vermerken (Status/„angefordert am“ bleiben unverändert)."""
        if self.con.execute("SELECT 1 FROM erwartungen WHERE id = ?", (eid,)).fetchone() is None:
            raise ValueError("Diesen Eintrag gibt es nicht (mehr).")
        self._link(eid, "entwurf", versand_id, text or "Erinnerungs-Entwurf erstellt (nicht gesendet)")
        self.con.commit()
        return self.erwartung(eid)

    def eingang_verknuepfen(self, eid: int, eingang_id: int, dokument_id: int | None = None) -> dict:
        """Nach Bestätigung durch einen Menschen: Eingang gehört zu dieser Erwartung. Status höchstens
        „Eingegangen – zu prüfen“ – nie automatisch „Geprüft / vollständig“."""
        alt = _zeilen(self.con.execute("SELECT * FROM erwartungen WHERE id = ?", (eid,)))
        if not alt:
            raise ValueError("Diesen Eintrag gibt es nicht (mehr).")
        alt = alt[0]
        e = self.con.execute("SELECT akte, betreff FROM eingaenge WHERE id = ?", (eingang_id,)).fetchone()
        if e is None:
            raise ValueError("Diesen Eingang gibt es nicht (mehr).")
        if e[0] and e[0] != alt["akte"]:
            raise ValueError(f"Der Eingang gehört zur Akte „{e[0]}“, nicht zu „{alt['akte']}“.")
        self._link(eid, "eingang", eingang_id, e[1] or "Eingang")
        if dokument_id:
            self._link(eid, "dokument", dokument_id, "")
        if alt["status"] in ("nicht_angefordert", "angefordert"):
            wer, jetzt = self._ich().name, _jetzt()
            self.con.execute("UPDATE erwartungen SET status = 'eingegangen', geaendert_von = ?, geaendert_am = ? "
                             "WHERE id = ?", (wer, jetzt, eid))
        self.prot.eintragen("erwartung", eid, "eingang_verknuepft", ["status"], f"{alt['akte']}: {alt['titel']}",
                            commit=False)
        self.con.commit()
        return self.erwartung(eid)

    def vorschlaege_fuer_eingang(self, eingang_id: int) -> list[dict]:
        e = _zeilen(self.con.execute("SELECT * FROM eingaenge WHERE id = ?", (eingang_id,)))
        if not e or not e[0]["akte"]:
            return []
        e = e[0]
        namen = [r[0] for r in self.con.execute("SELECT name FROM eingang_dateien WHERE eingang_id = ?", (eingang_id,))]
        rolle = ""
        a = self.con.execute("SELECT mandant_email, versicherer_email FROM akten WHERE referenz = ?",
                             (e["akte"],)).fetchone()
        absender = (e.get("absender") or "").lower()
        if a and absender:
            if absender == (a[0] or "").lower():
                rolle = "mandant"
            elif absender == (a[1] or "").lower():
                rolle = "versicherung"
        bereits = {r[0] for r in self.con.execute("SELECT erwartung_id FROM erwartung_links WHERE art = 'eingang' "
                                                  "AND ziel_id = ?", (eingang_id,))}
        offene = [x for x in _zeilen(self.con.execute("SELECT * FROM erwartungen WHERE akte = ?", (e["akte"],)))
                  if x["id"] not in bereits]
        return passende_erwartungen(e["betreff"], namen, e.get("belegart") or "", rolle, offene)

    # --- Übersicht ------------------------------------------------------------------------
    def uebersicht(self) -> dict:
        """Startseite: was ich erwarte/zu prüfen habe, was überfällig ist."""
        ich = self._ich().name.lower()
        anzeige = self._anzeige()
        alle = [self._aufbereiten(e, anzeige) for e in _zeilen(self.con.execute(
            "SELECT * FROM erwartungen WHERE status IN ('nicht_angefordert', 'angefordert', 'eingegangen') "
            "ORDER BY CASE nachfassen WHEN '' THEN 1 ELSE 0 END, nachfassen, id"))]
        meine = [e for e in alle if (e.get("verantwortlich") or "").lower() == ich]
        return {"zu_pruefen": [e for e in alle if e["status"] == "eingegangen"][:20],
                "erwartet": [e for e in alle if e["status"] in ("nicht_angefordert", "angefordert")][:20],
                "erwartet_anzahl": sum(1 for e in alle if e["status"] in ("nicht_angefordert", "angefordert")),
                "nachfassen_faellig": [e for e in alle if e["nachfassen_faellig"]][:20],
                "meine": meine[:20]}

    # --- Checklisten-Vorlagen ----------------------------------------------------------------
    def vorlagen(self, akte_art: str = "") -> list[dict]:
        out = _zeilen(self.con.execute("SELECT * FROM checklisten WHERE aktiv = 1 ORDER BY "
                                       "CASE WHEN akte_art = ? THEN 0 ELSE 1 END, name", (akte_art or "",)))
        for v in out:
            v["punkte"] = _zeilen(self.con.execute("SELECT * FROM checklisten_punkte WHERE checkliste_id = ? "
                                                   "ORDER BY position, id", (v["id"],)))
        return out

    def _vorlage_schreiben(self, vid, name, akte_art, beschreibung, punkte, protokoll=True) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Bitte einen Namen für die Checkliste eingeben.")
        wer, jetzt = self._ich().name, _jetzt()
        if vid is None:
            if self.con.execute("SELECT 1 FROM checklisten WHERE name = ?", (name,)).fetchone():
                raise ValueError(f"Eine Checkliste „{name}“ gibt es schon.")
            vid = int(self.con.execute("INSERT INTO checklisten (name, akte_art, beschreibung, geaendert_von, "
                                       "geaendert_am) VALUES (?,?,?,?,?)",
                                       (name, (akte_art or "").strip(), (beschreibung or "").strip(), wer, jetzt))
                      .lastrowid)
        else:
            self.con.execute("UPDATE checklisten SET name = ?, akte_art = ?, beschreibung = ?, geaendert_von = ?, "
                             "geaendert_am = ? WHERE id = ?", (name, (akte_art or "").strip(),
                                                                (beschreibung or "").strip(), wer, jetzt, vid))
            self.con.execute("DELETE FROM checklisten_punkte WHERE checkliste_id = ?", (vid,))
        for i, p in enumerate(punkte):
            titel = (p.get("titel") or "").strip()
            if not titel:
                continue
            rolle = p.get("von_rolle") or "mandant"
            if rolle not in VON_ROLLEN:
                raise ValueError("Unbekannte Herkunft.")
            self.con.execute("INSERT INTO checklisten_punkte (checkliste_id, position, titel, von_rolle, beschreibung)"
                             " VALUES (?,?,?,?,?)", (vid, i, titel, rolle, (p.get("beschreibung") or "").strip()))
        if protokoll:
            self.prot.eintragen("checkliste", vid, "geaendert", [], name, commit=False)
        return vid

    def vorlage_speichern(self, vid: int | None, name: str, akte_art: str, beschreibung: str,
                          punkte: list[dict]) -> int:
        """Vorlage anlegen/ändern (Rechtsanwalt/Administrator). Bestehende Akten bleiben unverändert."""
        self._nur_anwalt()
        vid = self._vorlage_schreiben(vid, name, akte_art, beschreibung, punkte)
        self.con.commit()
        return vid

    def vorlage_loeschen(self, vid: int) -> None:
        self._nur_anwalt()
        self.con.execute("UPDATE checklisten SET aktiv = 0, name = name || ' (gelöscht ' || ? || ')' WHERE id = ?",
                         (_jetzt(), vid))
        self.prot.eintragen("checkliste", vid, "geloescht", [], "", commit=False)
        self.con.commit()

    def _nur_anwalt(self) -> None:
        from core.benutzer import Berechtigung
        if self._ich().rolle not in ("admin", "anwalt"):
            raise Berechtigung("Keine Berechtigung: Checklisten-Vorlagen pflegt die Rechtsanwältin / der Rechtsanwalt.")

    def vorlage_anwenden(self, client_id: str, akte: str, vid: int, verantwortlich: str = "") -> list[dict]:
        """Punkte der Vorlage als Erwartungen in die Akte KOPIEREN (vorhandene gleichnamige Punkte werden nicht
        doppelt angelegt). Wiederholung mit gleicher client_id → nichts Neues."""
        v = next((x for x in self.vorlagen() if x["id"] == vid), None)
        if v is None:
            raise ValueError("Diese Checkliste gibt es nicht (mehr).")
        vorhanden = {r[0].strip().lower() for r in self.con.execute(
            "SELECT titel FROM erwartungen WHERE akte = ? AND status != 'nicht_erforderlich'", (akte,))}
        neu = []
        for p in v["punkte"]:
            if p["titel"].strip().lower() in vorhanden:
                continue
            neu.append(self.anlegen(f"{client_id}:{p['id']}", akte, p["titel"], p["von_rolle"],
                                    verantwortlich=verantwortlich, beschreibung=p.get("beschreibung") or "",
                                    vorlage=v["name"]))
        return neu

    def akte_art_setzen(self, akte: str, art: str) -> None:
        if not self._akte_gibt_es(akte):
            raise ValueError(f"Die Akte „{akte}“ gibt es nicht (mehr).")
        self.con.execute("UPDATE akten SET akte_art = ? WHERE referenz = ?", ((art or "").strip(), akte))
        self.prot.eintragen("akte", akte, "geaendert", ["akte_art"], akte, commit=False)
        self.con.commit()

    def aenderungsverlauf(self, art: str, objekt) -> list[dict]:
        return self.prot.fuer(art, objekt)
