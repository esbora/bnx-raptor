"""Versandkontrolle (0.5): gemeinsame Prüfung vor dem Outlook-Entwurf + Versandnachweis.

Saf Python (PyMuPDF nur bei PDF-Dateien, erst bei Bedarf geladen). Es wird NIE etwas gesendet.

Prüfungen (Ergebnis = Befunde mit Stufe ok | hinweis | warnung | nicht_geprueft | fehler):
- Empfänger ↔ Akte: Mandant, Versicherung oder unbekannt (z. B. Gegenseite); Adresse einer ANDEREN Akte → Warnung.
- Hauptdokument: nennt es die Nummern der gewählten Akte – oder die einer anderen Akte?
- Anlagenverweise im Text (Anlage K1, Anlagen K1 bis K3, K1–K3 …) ↔ gewählte Anlagen: fehlende → Warnung mit
  Belegstelle; unsichere Fundstellen (bloßes „K2“, Zitate) → nur Hinweis.
- Nummern der gewählten Anlagen: Lücken, doppelte Nummern, Reihenfolge.
- Dieselbe Datei mehrfach (SHA-256), Datei vorhanden/lesbar.
- Word: Kommentare und Änderungsnachverfolgung; Metadaten (Autor …) in Word und PDF.
Grenzen werden ausdrücklich gezeigt: nicht unterstützte/nicht lesbare Datei → „Nicht geprüft“; ein PDF ohne Text
heißt NICHT „keine Verweise“; ein technischer Fehler gilt nie als bestanden. PDF/A und Schwärzung werden hier
nicht neu bewertet (dafür gelten die bestehenden Prüfungen beim Erstellen/Speichern).

Metadaten entfernen: nur auf Wunsch, nur in einer getrennten Versandkopie, mit Prüfung der Kopie. Änderungs-
nachverfolgung wird nie still angenommen oder abgelehnt.

Versandnachweis (`versand`, `versand_dateien`): Empfänger, Betreff, Reihenfolge, Dokumentversionen, SHA-256 und
eine feste Kopie jeder angehängten Datei. Status: Entwurf erstellt → Versand bestätigt (Outlook „Gesendete
Elemente“ mit identischen Anhängen oder ausdrückliche Bestätigung eines Menschen, Quelle sichtbar) / Versand nicht
bestätigt. Öffnen/Schließen des Entwurfs zählt nie als Versand. Frühere Einträge werden nie überschrieben.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from core import protokoll as pr

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
STUFEN = ("fehler", "warnung", "nicht_geprueft", "hinweis", "ok")
STUFE_TEXT = {"ok": "OK", "hinweis": "Hinweis", "warnung": "Warnung", "nicht_geprueft": "Nicht geprüft",
              "fehler": "Fehler"}
ROLLE_TEXT = {"mandant": "Mandant", "versicherung": "Versicherung", "unbekannt": "nicht in dieser Akte hinterlegt",
              "andere_akte": "Beteiligter einer anderen Akte", "": "–"}
WORD_ENDUNGEN = {".docx", ".docm"}
PDF_ENDUNGEN = {".pdf"}


@dataclass
class Befund:
    stufe: str
    art: str
    text: str
    beleg: str = ""
    datei: str = ""
    bestaetigen: bool = False          # gehört zur EINEN Bestätigung vor dem Entwurf

    def als_dict(self) -> dict:
        return asdict(self)


@dataclass
class Ergebnis:
    befunde: list[Befund] = field(default_factory=list)
    rolle: str = ""
    metadaten: dict[str, list[str]] = field(default_factory=dict)      # Datei → Felder
    kommentare: list[str] = field(default_factory=list)                # Dateien mit Kommentaren
    aenderungen: list[str] = field(default_factory=list)               # Dateien mit Änderungsnachverfolgung

    def add(self, *a, **k) -> Befund:
        b = Befund(*a, **k)
        self.befunde.append(b)
        return b

    @property
    def zu_bestaetigen(self) -> list[Befund]:
        return [b for b in self.befunde if b.bestaetigen]

    @property
    def schlimmste(self) -> str:
        for s in STUFEN:
            if any(b.stufe == s for b in self.befunde):
                return s
        return "ok"

    def zusammenfassung(self) -> str:
        n = {s: sum(1 for b in self.befunde if b.stufe == s) for s in STUFEN}
        teile = [f"Empfänger: {ROLLE_TEXT.get(self.rolle, self.rolle)}"]
        for s, wort in (("fehler", "Fehler"), ("warnung", "Warnung(en)"), ("nicht_geprueft", "nicht geprüft"),
                        ("hinweis", "Hinweis(e)")):
            if n[s]:
                teile.append(f"{n[s]} {wort}")
        if not any(n[s] for s in ("fehler", "warnung", "nicht_geprueft", "hinweis")):
            teile.append("keine Auffälligkeiten")
        return " · ".join(teile)


# =========================================================================== Text lesen
def _xml(z: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None


def docx_volltext(pfad: Path) -> str:
    """Sichtbarer Text eines Word-Dokuments (Hauptteil, Fußnoten, Endnoten; ohne gelöschten Text)."""
    with zipfile.ZipFile(pfad) as z:
        teile = []
        for name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
            root = _xml(z, name)
            if root is None:
                continue
            for p in root.iter(W + "p"):
                teile.append("".join(t.text or "" for t in p.iter(W + "t")))
        return "\n".join(teile)


def pdf_text(pfad: Path) -> tuple[str, int, int]:
    """(Text, Seiten, Seiten ohne Text)."""
    import pymupdf
    with pymupdf.open(pfad) as d:
        texte = [p.get_text() for p in d]
    return "\n".join(texte), len(texte), sum(1 for t in texte if not t.strip())


def text_lesen(pfad: Path) -> tuple[str | None, str]:
    """(Text oder None, Grund wenn None)."""
    p = Path(pfad)
    endung = p.suffix.lower()
    try:
        if endung in WORD_ENDUNGEN:
            return docx_volltext(p), ""
        if endung in PDF_ENDUNGEN:
            text, seiten, leer = pdf_text(p)
            if seiten and leer == seiten:
                return None, "PDF ohne Textebene (Scan) – Verweise konnten nicht gelesen werden"
            return text, (f"{leer} von {seiten} Seiten ohne Text – dort nicht geprüft" if leer else "")
        if endung in (".txt",):
            return p.read_text(encoding="utf-8", errors="replace"), ""
    except Exception as e:  # noqa: BLE001 – technischer Fehler: nie als „bestanden“ werten
        return None, f"Text konnte nicht gelesen werden ({type(e).__name__})"
    return None, f"Dateityp {endung or '?'} wird für die Textprüfung nicht unterstützt"


# =========================================================================== Anlagenverweise
@dataclass
class Verweis:
    buchstabe: str
    nummer: int
    sicher: bool
    beleg: str


_BEZ = re.compile(r"([A-Za-z]{1,2})\s*(\d{1,3})\s*$")


def bezeichnung_nummer(bez: str) -> tuple[str, int] | None:
    """'Anlage K3' → ('K', 3); sonst None."""
    m = _BEZ.search((bez or "").strip())
    return (m.group(1).upper(), int(m.group(2))) if m else None


def _beleg(text: str, a: int, b: int) -> str:
    s = max(0, a - 50)
    e = min(len(text), b + 50)
    return (("…" if s else "") + re.sub(r"\s+", " ", text[s:e]).strip() + ("…" if e < len(text) else ""))


def _in_zitat(text: str, pos: int) -> bool:
    """Steht die Fundstelle in Anführungszeichen (innerhalb derselben Zeile) oder in einer zitierten Zeile?"""
    zs = text.rfind("\n", 0, pos) + 1
    ze = text.find("\n", pos)
    zeile = text[zs: ze if ze != -1 else len(text)]
    if zeile.lstrip().startswith(">"):
        return True
    links = text[zs:pos]
    for auf, zu in (("„", "“"), ("»", "«"), ('"', '"'), ("“", "”")):
        if auf == zu:
            if links.count(auf) % 2 == 1:
                return True
        elif links.count(auf) > links.count(zu):
            return True
    return False


def anlage_verweise(text: str, buchstaben: set[str] | None = None) -> list[Verweis]:
    """Anlagenverweise im Text. „Anlage K1“, „Anlagen K1 bis K3“, „Anlagen K1, K2 und K4“, „K 1 – K 3“ (nach
    „Anlage“) gelten als sicher; ein bloßes „K2“ ohne „Anlage“ oder ein Verweis im Zitat nur als unsicher."""
    buchstaben = {b.upper() for b in (buchstaben or {"K"})}
    bset = "".join(sorted(buchstaben))
    num = rf"([{bset}{bset.lower()}])\s?(\d{{1,3}})"
    out: list[Verweis] = []
    belegt: set[tuple[int, int]] = set()
    # sichere Verweise: „Anlage(n)“ + Folge von Nummern/Bereichen
    for m in re.finditer(rf"\bAnlagen?\s+(?:(?:als|wie|in)\s+)?{num}((?:\s*(?:,|und|sowie|bis|–|-|—)\s*(?:[{bset}"
                         rf"{bset.lower()}])?\s?\d{{1,3}})*)", text):
        sicher = not _in_zitat(text, m.start())
        beleg = _beleg(text, m.start(), m.end())
        b0, n0 = m.group(1).upper(), int(m.group(2))
        folge = [(b0, n0)]
        rest = m.group(3) or ""
        letzt = n0
        for t in re.finditer(rf"(,|und|sowie|bis|–|-|—)\s*([{bset}{bset.lower()}])?\s?(\d{{1,3}})", rest):
            n = int(t.group(3))
            b = (t.group(2) or b0).upper()
            if t.group(1) in ("bis", "–", "-", "—") and b == b0 and letzt < n <= letzt + 50:
                folge += [(b, k) for k in range(letzt + 1, n + 1)]
            else:
                folge.append((b, n))
            letzt = n
        for b, n in folge:
            out.append(Verweis(b, n, sicher, beleg))
        belegt.add((m.start(), m.end()))
    # unsichere: bloßes K2 außerhalb der obigen Fundstellen
    for m in re.finditer(rf"(?<![\w/]){num}(?![\w/])", text):
        if any(a <= m.start() < b for a, b in belegt):
            continue
        out.append(Verweis(m.group(1).upper(), int(m.group(2)), False, _beleg(text, m.start(), m.end())))
    return out


# =========================================================================== Word / PDF Eigenschaften
def docx_eigenschaften(pfad: Path) -> dict:
    """{'kommentare': n, 'aenderungen': n, 'metadaten': {Feld: Wert}} – liest nur, ändert nichts."""
    with zipfile.ZipFile(pfad) as z:
        namen = set(z.namelist())
        n_komm = 0
        for name in namen:
            if re.fullmatch(r"word/comments(Extended|Ids|Extensible)?\.xml", name) and name == "word/comments.xml":
                root = _xml(z, name)
                n_komm = sum(1 for _ in root.iter(W + "comment")) if root is not None else 0
        n_aend = 0
        for name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml", "word/styles.xml"):
            root = _xml(z, name)
            if root is None:
                continue
            for tag in ("ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "sectPrChange", "tblPrChange"):
                n_aend += sum(1 for _ in root.iter(W + tag))
        meta = {}
        core = _xml(z, "docProps/core.xml")
        if core is not None:
            for el in core:
                tag = el.tag.split("}")[-1]
                if tag in ("creator", "lastModifiedBy", "title", "subject", "keywords", "description") and \
                        (el.text or "").strip():
                    meta[tag] = el.text.strip()
        app = _xml(z, "docProps/app.xml")
        if app is not None:
            for el in app:
                tag = el.tag.split("}")[-1]
                if tag in ("Company", "Manager") and (el.text or "").strip():
                    meta[tag] = el.text.strip()
        if "docProps/custom.xml" in namen:
            meta["Benutzerdefinierte Eigenschaften"] = "vorhanden"
    return {"kommentare": n_komm, "aenderungen": n_aend, "metadaten": meta}


PDF_META_FELDER = ("author", "creator", "producer", "title", "subject", "keywords")


def pdf_eigenschaften(pfad: Path) -> dict:
    import pymupdf
    from core.pdf_engine import signaturen
    with pymupdf.open(pfad) as d:
        meta = {k: v for k, v in (d.metadata or {}).items() if k in PDF_META_FELDER and (v or "").strip()}
        xmp = d.get_xml_metadata() or ""
        sig = signaturen(d)
    return {"metadaten": meta, "pdfa": bool(re.search(r"pdfaid:part", xmp)), "xmp": bool(xmp.strip()),
            "signiert": bool(sig)}


# =========================================================================== Prüfen
@dataclass
class Parteien:
    """Bekannte Adressen der gewählten Akte und – für die Gegenprobe – anderer Akten."""
    mandant: list[str] = field(default_factory=list)
    versicherung: list[str] = field(default_factory=list)
    nummern: list[str] = field(default_factory=list)              # Nummern der gewählten Akte
    andere: dict[str, list[str]] = field(default_factory=dict)    # E-Mail → [Akten]
    andere_nummern: dict[str, str] = field(default_factory=dict)  # Nummer → Akte


def _adressen(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"[;,]", text or "") if a.strip()]


def empfaenger_pruefen(erg: Ergebnis, empfaenger: str, akte: str, parteien: Parteien | None) -> None:
    from core.extractor import is_valid_email
    adressen = _adressen(empfaenger)
    if not adressen:
        erg.rolle = ""
        erg.add("warnung", "empfaenger", "Kein Empfänger eingetragen – bitte im Entwurf ergänzen.", bestaetigen=True)
        return
    for a in adressen:
        if not is_valid_email(a):
            erg.add("fehler", "empfaenger", f"„{a}“ ist keine gültige E-Mail-Adresse.", bestaetigen=True)
    if not akte or parteien is None:
        erg.rolle = "unbekannt"
        erg.add("nicht_geprueft", "empfaenger", "Keine Akte gewählt – Empfänger nicht mit Beteiligten abgeglichen.")
        return
    rollen = []
    for a in adressen:
        k = a.lower()
        if k in {x.lower() for x in parteien.mandant}:
            rollen.append("mandant")
        elif k in {x.lower() for x in parteien.versicherung}:
            rollen.append("versicherung")
        elif k in {x.lower() for x in parteien.andere}:
            rollen.append("andere_akte")
            akten = ", ".join(parteien.andere[next(x for x in parteien.andere if x.lower() == k)][:3])
            erg.add("warnung", "empfaenger", f"{a} ist in einer anderen Akte hinterlegt ({akten}), nicht in Akte "
                                             f"{akte}.", bestaetigen=True)
        else:
            rollen.append("unbekannt")
            erg.add("warnung", "empfaenger", f"{a} ist in Akte {akte} weder als Mandant noch als Versicherung "
                                             "hinterlegt (z. B. Gegenseite?). Bitte Empfänger prüfen.",
                    bestaetigen=True)
    erg.rolle = rollen[0] if len(set(rollen)) == 1 else "unbekannt"
    if erg.rolle in ("mandant", "versicherung"):
        erg.add("ok", "empfaenger", f"Empfänger ist {ROLLE_TEXT[erg.rolle]} der Akte {akte}.")


def pruefen(empfaenger: str, akte: str, parteien: Parteien | None, hauptdokument: Path | None,
            anlagen: list[tuple[Path, str]], weitere: list[Path] | None = None) -> Ergebnis:
    """Alle Prüfungen. anlagen: [(Datei, Bezeichnung „Anlage K1“ oder '')] in Versandreihenfolge;
    weitere: sonstige Anhänge (z. B. Anlagenverzeichnis)."""
    erg = Ergebnis()
    empfaenger_pruefen(erg, empfaenger, akte, parteien)
    alle: list[tuple[Path, str]] = ([(Path(hauptdokument), "Hauptdokument")] if hauptdokument else []) + \
        [(Path(p), b) for p, b in anlagen] + [(Path(p), "") for p in (weitere or [])]
    # --- Dateien vorhanden/lesbar, doppelt -------------------------------------------------
    shas: dict[str, str] = {}
    lesbar: dict[str, bool] = {}
    for p, _b in alle:
        try:
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            lesbar[str(p)] = True
        except OSError as e:
            lesbar[str(p)] = False
            erg.add("fehler", "lesbar", f"{p.name}: Datei fehlt oder ist nicht lesbar ({e.strerror or e}). Sie kann "
                                        "nicht angehängt werden.", datei=str(p), bestaetigen=True)
            continue
        if h in shas:
            erg.add("warnung", "doppelt", f"{p.name} ist inhaltsgleich mit {Path(shas[h]).name} – dieselbe Datei "
                                          "wäre zweimal angehängt.", datei=str(p))
        shas.setdefault(h, str(p))
    # --- PDF lesbar? Word/PDF-Eigenschaften -------------------------------------------------
    for p, _b in alle:
        if not lesbar.get(str(p)):
            continue
        endung = p.suffix.lower()
        try:
            if endung in WORD_ENDUNGEN:
                e = docx_eigenschaften(p)
                if e["kommentare"]:
                    erg.kommentare.append(str(p))
                    erg.add("warnung", "word_kommentar", f"{p.name}: enthält {e['kommentare']} Kommentar(e).",
                            datei=str(p))
                if e["aenderungen"]:
                    erg.aenderungen.append(str(p))
                    erg.add("warnung", "word_aenderungen", f"{p.name}: enthält nachverfolgte Änderungen "
                                                           f"({e['aenderungen']} Stellen) – bitte in Word annehmen "
                                                           "oder ablehnen.", datei=str(p))
                if e["metadaten"]:
                    erg.metadaten[str(p)] = sorted(e["metadaten"])
                    erg.add("hinweis", "metadaten", f"{p.name}: Dokumenteigenschaften "
                                                    + ", ".join(f"{k}: {v}" for k, v in e["metadaten"].items()),
                            datei=str(p))
            elif endung in (".doc", ".rtf"):
                erg.add("nicht_geprueft", "word_kommentar", f"{p.name}: Kommentare, Änderungen und Metadaten "
                                                            "bei .doc/.rtf nicht geprüft.", datei=str(p))
            elif endung in PDF_ENDUNGEN:
                e = pdf_eigenschaften(p)
                if e["metadaten"]:
                    erg.metadaten[str(p)] = sorted(e["metadaten"])
                    erg.add("hinweis", "metadaten", f"{p.name}: PDF-Eigenschaften "
                                                    + ", ".join(f"{k}: {v}" for k, v in e["metadaten"].items()),
                            datei=str(p))
            else:
                erg.add("nicht_geprueft", "metadaten", f"{p.name}: Metadaten dieses Dateityps nicht geprüft.",
                        datei=str(p))
        except Exception as ex:  # noqa: BLE001
            erg.add("warnung", "lesbar", f"{p.name}: Datei konnte nicht geöffnet werden ({type(ex).__name__}) – "
                                         "wird nur als Originaldatei angehängt, Inhalt nicht geprüft.",
                    datei=str(p), bestaetigen=True)
    # --- gewählte Nummern -------------------------------------------------------------------
    gewaehlt: list[tuple[str, int, str]] = []
    for p, b in anlagen:
        bn = bezeichnung_nummer(b)
        if bn:
            gewaehlt.append((*bn, Path(p).name))
    nummern = [(b, n) for b, n, _ in gewaehlt]
    for (b, n) in sorted(set(nummern)):
        if nummern.count((b, n)) > 1:
            erg.add("warnung", "anlage_nummer", f"Anlage {b}{n} ist mehrfach vergeben.")
    for b in sorted({b for b, _ in nummern}):
        ns = sorted({n for bb, n in nummern if bb == b})
        luecken = [n for n in range(ns[0], ns[-1] + 1) if n not in ns]
        if luecken:
            erg.add("warnung", "anlage_nummer", "Lücke in der Nummerierung: " +
                    ", ".join(f"{b}{n}" for n in luecken) + " fehlt zwischen den gewählten Anlagen.")
        if [n for bb, n in nummern if bb == b] != sorted(n for bb, n in nummern if bb == b):
            erg.add("hinweis", "anlage_nummer", f"Die Anlagen {b} sind nicht in aufsteigender Reihenfolge angehängt.")
    # --- Hauptdokument: Text, Aktennummer, Anlagenverweise ------------------------------------
    if hauptdokument is None:
        erg.add("hinweis", "hauptdokument", "Kein Hauptdokument gewählt – Anlagenverweise nicht geprüft.")
        return erg
    if not lesbar.get(str(hauptdokument)):
        erg.add("nicht_geprueft", "anlage_fehlt", "Anlagenverweise nicht geprüft (Hauptdokument nicht lesbar).")
        return erg
    text, grund = text_lesen(Path(hauptdokument))
    if text is None:
        erg.add("nicht_geprueft", "anlage_fehlt", f"{Path(hauptdokument).name}: {grund}. Fehlende Anlagen bitte "
                                                  "selbst prüfen.", datei=str(hauptdokument))
        return erg
    if grund:
        erg.add("nicht_geprueft", "text", f"{Path(hauptdokument).name}: {grund}.", datei=str(hauptdokument))
    if parteien is not None and akte:
        eigene = [n for n in parteien.nummern if n and _nummer_drin(text, n)]
        fremd = [(n, a) for n, a in parteien.andere_nummern.items() if a != akte and _nummer_drin(text, n)]
        if fremd:
            n, a = fremd[0]
            erg.add("warnung", "hauptdokument", f"Das Hauptdokument nennt {n} – das ist eine Nummer der Akte {a}, "
                                                f"nicht der gewählten Akte {akte}.", beleg=_fundstelle(text, n),
                    bestaetigen=True)
        if parteien.nummern and not eigene:
            erg.add("hinweis", "hauptdokument", f"Keine Nummer der Akte {akte} im Hauptdokument gefunden "
                                                "(Aktenzeichen, Versicherungsnummer, Schaden-Nr.).")
        elif eigene:
            erg.add("ok", "hauptdokument", f"Hauptdokument nennt {eigene[0]} (Akte {akte}).")
    buchstaben = {b for b, _ in nummern} or {"K"}
    verweise = anlage_verweise(text, buchstaben)
    sicher = {(v.buchstabe, v.nummer): v for v in verweise if v.sicher}
    unsicher = {(v.buchstabe, v.nummer): v for v in verweise if not v.sicher and (v.buchstabe, v.nummer) not in sicher}
    gewaehlt_set = set(nummern)
    for k in sorted(sicher):
        if k not in gewaehlt_set:
            erg.add("warnung", "anlage_fehlt", f"Im Text wird Anlage {k[0]}{k[1]} genannt, sie ist aber nicht "
                                               "angehängt.", beleg=sicher[k].beleg, bestaetigen=True)
    for k in sorted(unsicher):
        if k not in gewaehlt_set:
            erg.add("hinweis", "anlage_fehlt", f"„{k[0]}{k[1]}“ steht im Text (vermutlich kein Anlagenverweis oder "
                                               "Zitat) – nicht angehängt.", beleg=unsicher[k].beleg)
    if sicher:
        for k in sorted(gewaehlt_set - set(sicher) - set(unsicher)):
            erg.add("hinweis", "anlage_nummer", f"Anlage {k[0]}{k[1]} ist angehängt, wird im Text aber nicht genannt.")
        if all(k in gewaehlt_set for k in sicher):
            erg.add("ok", "anlage_fehlt", "Alle im Text genannten Anlagen sind angehängt: "
                    + ", ".join(f"{b}{n}" for b, n in sorted(sicher)) + ".")
    elif anlagen:
        erg.add("hinweis", "anlage_fehlt", "Im Hauptdokument wurden keine Anlagenverweise (z. B. „Anlage K1“) "
                                           "gefunden.")
    return erg


def _nummer_drin(text: str, nummer: str) -> bool:
    from core.posteingang import nummer_im_text
    return nummer_im_text(text, nummer, min_laenge=4)


def _fundstelle(text: str, nummer: str) -> str:
    kern = re.escape(nummer[:4])
    m = re.search(kern, text, re.I)
    return _beleg(text, m.start(), m.end()) if m else ""


# =========================================================================== Metadaten-Bereinigung (Kopie)
@dataclass
class Bereinigung:
    ok: bool
    kopie: Path | None
    entfernt: list[str]
    text: str


def _docx_text_ohne_kommentare(pfad: Path) -> str:
    return docx_volltext(pfad)


def bereinigen(quelle: Path, ziel: Path, kommentare_entfernen: bool = False) -> Bereinigung:
    """Metadaten (und auf Wunsch Kommentare) in einer KOPIE entfernen; das Original bleibt unverändert.
    Die Kopie wird danach geöffnet und mit dem Original verglichen. Fehler → ok=False, nichts gilt als bereinigt."""
    quelle, ziel = Path(quelle), Path(ziel)
    endung = quelle.suffix.lower()
    try:
        if endung in WORD_ENDUNGEN:
            return _docx_bereinigen(quelle, ziel, kommentare_entfernen)
        if endung in PDF_ENDUNGEN:
            return _pdf_bereinigen(quelle, ziel)
    except Exception as e:  # noqa: BLE001
        if ziel.exists() and ziel != quelle:
            ziel.unlink(missing_ok=True)
        return Bereinigung(False, None, [], f"{quelle.name}: Bereinigung fehlgeschlagen ({type(e).__name__}) – "
                                            "die Datei wird NICHT als bereinigt angehängt.")
    return Bereinigung(False, None, [], f"{quelle.name}: Für diesen Dateityp ist keine Bereinigung möglich.")


def _leer_setzen(xml: bytes, felder: set[str]) -> tuple[bytes, list[str]]:
    root = ET.fromstring(xml)
    entfernt = []
    for el in list(root):
        tag = el.tag.split("}")[-1]
        if tag in felder and (el.text or "").strip():
            el.text = ""
            entfernt.append(tag)
    for prefix, uri in re.findall(rb'xmlns:(\w+)="([^"]+)"', xml):
        ET.register_namespace(prefix.decode(), uri.decode())
    return ET.tostring(root, xml_declaration=True, encoding="UTF-8", short_empty_elements=True), entfernt


def _docx_bereinigen(quelle: Path, ziel: Path, kommentare_entfernen: bool) -> Bereinigung:
    eig = docx_eigenschaften(quelle)
    if eig["aenderungen"]:
        return Bereinigung(False, None, [], f"{quelle.name}: enthält nachverfolgte Änderungen. Diese werden nicht "
                                            "automatisch angenommen oder abgelehnt – bitte in Word entscheiden und "
                                            "speichern, dann erneut prüfen.")
    entfernt: list[str] = []
    tmp = ziel.with_name(ziel.name + ".bnx-tmp")
    with zipfile.ZipFile(quelle) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        komm_teile = {n for n in zin.namelist() if re.fullmatch(r"word/comments(Extended|Ids|Extensible)?\.xml", n)}
        for info in zin.infolist():
            daten = zin.read(info.filename)
            n = info.filename
            if n == "docProps/core.xml":
                daten, e = _leer_setzen(daten, {"creator", "lastModifiedBy", "description", "keywords"})
                entfernt += e
            elif n == "docProps/app.xml":
                daten, e = _leer_setzen(daten, {"Company", "Manager"})
                entfernt += e
            elif n == "docProps/custom.xml":
                entfernt.append("Benutzerdefinierte Eigenschaften")
                daten = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"'
                         b' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>')
            elif kommentare_entfernen and n in komm_teile:
                if n == "word/comments.xml" and eig["kommentare"]:
                    entfernt.append(f"{eig['kommentare']} Kommentar(e)")
                daten = _leere_kommentare(daten)
            elif kommentare_entfernen and n == "word/document.xml":
                daten = re.sub(rb"<w:commentRangeStart[^>]*/>|<w:commentRangeEnd[^>]*/>", b"", daten)
                daten = re.sub(rb"<w:r>(?:(?!</w:r>).)*?<w:commentReference[^>]*/>(?:(?!</w:r>).)*?</w:r>", b"", daten,
                               flags=re.S)
                daten = re.sub(rb"<w:r [^>]*>(?:(?!</w:r>).)*?<w:commentReference[^>]*/>(?:(?!</w:r>).)*?</w:r>", b"",
                               daten, flags=re.S)
            zout.writestr(info, daten)
    # Kopie prüfen: öffnet sich, Text unverändert, Metadaten leer, (Kommentare weg)
    try:
        neu = docx_eigenschaften(tmp)
        gleich = docx_volltext(tmp) == docx_volltext(quelle)
        rest = [k for k in ("creator", "lastModifiedBy", "Company", "Manager") if k in neu["metadaten"]]
        if not gleich or rest or (kommentare_entfernen and neu["kommentare"]):
            raise ValueError("Prüfung der Kopie fehlgeschlagen")
    except Exception:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        return Bereinigung(False, None, [], f"{quelle.name}: Die bereinigte Kopie ließ sich nicht fehlerfrei prüfen – "
                                            "sie wird NICHT verwendet.")
    tmp.replace(ziel)
    return Bereinigung(True, ziel, entfernt, f"{quelle.name}: bereinigte Kopie geprüft"
                       + (f" (entfernt: {', '.join(entfernt)})" if entfernt else " (nichts zu entfernen)"))


def _leere_kommentare(xml: bytes) -> bytes:
    root = ET.fromstring(xml)
    for prefix, uri in re.findall(rb'xmlns:(\w+)="([^"]+)"', xml):
        ET.register_namespace(prefix.decode(), uri.decode())
    for el in list(root):
        root.remove(el)
    return ET.tostring(root, xml_declaration=True, encoding="UTF-8")


def _pdf_bereinigen(quelle: Path, ziel: Path) -> Bereinigung:
    import pymupdf
    eig = pdf_eigenschaften(quelle)
    if eig["signiert"]:
        return Bereinigung(False, None, [], f"{quelle.name}: digital signiert – Änderungen würden die Signatur "
                                            "ungültig machen. Nicht bereinigt.")
    if eig["pdfa"]:
        return Bereinigung(False, None, [], f"{quelle.name}: PDF/A – die Metadaten gehören zur PDF/A-Kennzeichnung. "
                                            "Nicht bereinigt (Original wird angehängt).")
    tmp = ziel.with_name(ziel.name + ".bnx-tmp")
    with pymupdf.open(quelle) as d:
        entfernt = [k for k in PDF_META_FELDER if (d.metadata or {}).get(k)]
        d.set_metadata({})
        if eig["xmp"]:
            d.del_xml_metadata()
            entfernt.append("XMP")
        d.save(tmp, garbage=3, deflate=True)
    try:
        with pymupdf.open(quelle) as a, pymupdf.open(tmp) as b:
            if a.page_count != b.page_count or any(pa.get_text() != pb.get_text() for pa, pb in zip(a, b)):
                raise ValueError("Inhalt weicht ab")
            if any((b.metadata or {}).get(k) for k in PDF_META_FELDER) or (b.get_xml_metadata() or "").strip():
                raise ValueError("Metadaten noch vorhanden")
    except Exception:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        return Bereinigung(False, None, [], f"{quelle.name}: Die bereinigte Kopie ließ sich nicht fehlerfrei prüfen – "
                                            "sie wird NICHT verwendet.")
    tmp.replace(ziel)
    return Bereinigung(True, ziel, entfernt, f"{quelle.name}: bereinigte Kopie geprüft"
                       + (f" (entfernt: {', '.join(entfernt)})" if entfernt else " (nichts zu entfernen)"))


# =========================================================================== feste Versandkopien
def feste_kopien(dateien: list[Path], ordner: Path) -> list[Path]:
    """Jede Datei als unveränderliche Versandkopie in einen eigenen, neuen Ordner kopieren (gleicher Dateiname,
    damit der Empfänger dieselben Namen sieht). Prüfsumme wird nach dem Kopieren verglichen."""
    ordner.mkdir(parents=True, exist_ok=False)
    out = []
    namen: set[str] = set()
    for p in dateien:
        p = Path(p)
        name = p.name
        i = 2
        while name.lower() in namen:
            name = f"{p.stem}_{i}{p.suffix}"
            i += 1
        namen.add(name.lower())
        z = ordner / name
        shutil.copyfile(p, z)
        if _sha(z) != _sha(p):
            raise OSError(f"{p.name}: Kopie weicht vom Original ab")
        out.append(z)
    return out


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# =========================================================================== Outlook „Gesendete Elemente“
def gesendet_passt(eintrag: dict, kandidat: dict) -> tuple[bool, str]:
    """Passt eine gesendete Mail zuverlässig zu diesem Versandeintrag?
    Verlangt: gesendet NACH dem Entwurf, Empfänger enthalten, Anhänge in gleicher Reihenfolge mit gleicher
    Prüfsumme. Der Betreff darf abweichen (wird im Nachweis genannt). → (passt, Begründung)"""
    try:
        erstellt = datetime.strptime(eintrag["erstellt_am"], "%Y-%m-%d %H:%M:%S")
        gesendet = datetime.strptime(kandidat["gesendet_am"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        return False, "Zeitpunkt unbekannt"
    if gesendet < erstellt - timedelta(minutes=1):
        return False, "vor dem Entwurf gesendet"
    soll_empf = {a.lower() for a in _adressen(eintrag.get("empfaenger") or "")}
    ist_empf = {a.lower() for a in kandidat.get("empfaenger") or []}
    if soll_empf and not soll_empf <= ist_empf:
        return False, "Empfänger weicht ab"
    soll = [(d["name"], d["sha256"]) for d in sorted(eintrag.get("dateien") or [], key=lambda d: d["position"])]
    ist = [(n, s) for n, s in kandidat.get("anhaenge") or []]
    if [s for _, s in soll] != [s for _, s in ist]:
        return False, "Anhänge weichen ab"
    text = (f"Outlook „Gesendete Elemente“: gesendet am {gesendet:%d.%m.%Y %H:%M} an "
            f"{', '.join(sorted(ist_empf))}; {len(ist)} Anhänge identisch (SHA-256)")
    if (kandidat.get("betreff") or "").strip() != (eintrag.get("betreff") or "").strip():
        text += f"; Betreff im Gesendet-Ordner: „{kandidat.get('betreff', '')}“"
    return True, text


# =========================================================================== Datenbank
SCHEMA = """
CREATE TABLE IF NOT EXISTS versand (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    akte TEXT DEFAULT '',
    empfaenger TEXT DEFAULT '', empfaenger_rolle TEXT DEFAULT '',
    betreff TEXT DEFAULT '',
    status TEXT DEFAULT 'entwurf_erstellt',
    pruefung TEXT DEFAULT '',
    akzeptiert TEXT DEFAULT '[]',
    erstellt_von TEXT DEFAULT '', erstellt_am TEXT DEFAULT '',
    bestaetigt_von TEXT DEFAULT '', bestaetigt_am TEXT DEFAULT '',
    bestaetigung_quelle TEXT DEFAULT '', bestaetigung_text TEXT DEFAULT '',
    gueltig INTEGER DEFAULT 1, ungueltig_grund TEXT DEFAULT '', ersetzt_durch INTEGER,
    erwartungen TEXT DEFAULT '[]');
CREATE UNIQUE INDEX IF NOT EXISTS ix_versand_client ON versand(client_id);
CREATE INDEX IF NOT EXISTS ix_versand_akte ON versand(akte);
CREATE TABLE IF NOT EXISTS versand_dateien (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    versand_id INTEGER NOT NULL, position INTEGER DEFAULT 0,
    rolle TEXT DEFAULT 'anlage', bezeichnung TEXT DEFAULT '', name TEXT DEFAULT '',
    original_pfad TEXT DEFAULT '', original_dokument_id INTEGER, original_sha256 TEXT DEFAULT '',
    sha256 TEXT DEFAULT '', kopie_pfad TEXT DEFAULT '', groesse INTEGER DEFAULT 0, bereinigt INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_versand_dateien ON versand_dateien(versand_id);
"""
STATUS = {"entwurf_erstellt": "Entwurf erstellt", "versand_bestaetigt": "Versand bestätigt",
          "versand_nicht_bestaetigt": "Versand nicht bestätigt"}
QUELLEN = {"outlook_gesendet": "Outlook „Gesendete Elemente“", "manuell": "Bestätigung durch Benutzer"}


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _zeilen(cur) -> list[dict]:
    namen = [c[0] for c in cur.description]
    return [dict(zip(namen, r)) for r in cur.fetchall()]


class Versand:
    def __init__(self, con: sqlite3.Connection):
        from core.unterlagen import SCHEMA as UNTERLAGEN_SCHEMA
        self.con = con
        self.con.executescript(SCHEMA)
        self.con.executescript(UNTERLAGEN_SCHEMA)          # erwartung_links (Verknüpfung Erinnerung ↔ Versand)
        self.prot = pr.Protokoll(con)
        self.con.commit()

    def _anzeige(self) -> dict[str, str]:
        ich = pr.aktuell()
        out = {ich.name.lower(): ich.anzeigename or ich.name}          # Einzelplatz: keine Benutzertabelle
        try:
            out.update({r[0].lower(): (r[1] or r[0]) for r in
                        self.con.execute("SELECT name, anzeigename FROM benutzer")})
        except sqlite3.Error:
            pass
        return out

    def anlegen(self, client_id: str, akte: str, empfaenger: str, empfaenger_rolle: str, betreff: str,
                dateien: list[dict], pruefung: str = "", akzeptiert: list[dict] | None = None,
                erwartungen: list[int] | None = None) -> dict:
        """Versandnachweis „Entwurf erstellt“. dateien: [{position, rolle, bezeichnung, name, original_pfad,
        original_dokument_id, original_sha256, sha256, kopie_pfad, groesse, bereinigt}]. Gleiche client_id →
        derselbe Eintrag. Frühere offene Entwürfe derselben Akte an denselben Empfänger werden als „ersetzt“
        markiert, nie gelöscht oder überschrieben."""
        if not client_id:
            raise ValueError("Interner Fehler: Versand-Kennung fehlt.")
        r = self.con.execute("SELECT id FROM versand WHERE client_id = ?", (client_id,)).fetchone()
        if r:
            return self.eintrag(int(r[0]))
        wer, jetzt = pr.aktuell().name, _jetzt()
        akz = []
        for a in akzeptiert or []:
            akz.append({"text": a.get("text", ""), "art": a.get("art", ""), "begruendung": a.get("begruendung", ""),
                        "benutzer": wer, "zeit": jetzt})
        cur = self.con.execute(
            "INSERT INTO versand (client_id, akte, empfaenger, empfaenger_rolle, betreff, status, pruefung, akzeptiert,"
            " erstellt_von, erstellt_am, erwartungen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (client_id, akte or "", empfaenger or "", empfaenger_rolle or "", betreff or "", "entwurf_erstellt",
             pruefung or "", json.dumps(akz, ensure_ascii=False), wer, jetzt,
             json.dumps([int(x) for x in erwartungen or []])))
        vid = int(cur.lastrowid)
        for d in dateien:
            self.con.execute(
                "INSERT INTO versand_dateien (versand_id, position, rolle, bezeichnung, name, original_pfad, "
                "original_dokument_id, original_sha256, sha256, kopie_pfad, groesse, bereinigt) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (vid, int(d.get("position", 0)), d.get("rolle", "anlage"), d.get("bezeichnung", ""),
                 d.get("name", ""), str(d.get("original_pfad", "")), d.get("original_dokument_id"),
                 d.get("original_sha256", ""), d.get("sha256", ""), str(d.get("kopie_pfad", "")),
                 int(d.get("groesse", 0)), 1 if d.get("bereinigt") else 0))
        if akte:
            self.con.execute("UPDATE versand SET gueltig = 0, ungueltig_grund = ?, ersetzt_durch = ? WHERE akte = ? "
                             "AND lower(empfaenger) = lower(?) AND status = 'entwurf_erstellt' AND id != ? "
                             "AND gueltig = 1", (f"durch neueren Entwurf Nr. {vid} ersetzt", vid, akte, empfaenger,
                                                 vid))
            self.con.execute(
                "INSERT INTO vorgaenge (zeit, workflow, dokument, ergebnis, empfaenger, referenz, status, meldung, art,"
                " quelle_id, benutzer) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (jetzt, "versand", (dateien[0].get("kopie_pfad") if dateien else "") or "",
                 (dateien[0].get("kopie_pfad") if dateien else "") or "", empfaenger or "", akte, "ok",
                 f"Entwurf erstellt (nicht gesendet): {betreff} – {len(dateien)} Anhänge, Versandnachweis Nr. {vid}",
                 "entwurf", f"versand:{vid}", pr.aktuell().text))
        for eid in erwartungen or []:
            self.con.execute("INSERT OR IGNORE INTO erwartung_links (erwartung_id, art, ziel_id, text, zeit, benutzer)"
                             " VALUES (?,?,?,?,?,?)", (eid, "entwurf", vid, "Erinnerungs-Entwurf erstellt (nicht "
                                                                             "gesendet)", jetzt, wer))
        self.prot.eintragen("versand", vid, "entwurf_erstellt", [], betreff, commit=False)
        if akte:
            self.prot.eintragen("akte", akte, "versand_entwurf", [], betreff, commit=False)
        self.con.commit()
        return self.eintrag(vid)

    def eintrag(self, vid: int) -> dict | None:
        r = _zeilen(self.con.execute("SELECT * FROM versand WHERE id = ?", (vid,)))
        if not r:
            return None
        return self._aufbereiten(r[0])

    def _aufbereiten(self, v: dict, anzeige: dict | None = None) -> dict:
        anzeige = anzeige if anzeige is not None else self._anzeige()
        v = dict(v)
        v["dateien"] = _zeilen(self.con.execute("SELECT * FROM versand_dateien WHERE versand_id = ? ORDER BY position",
                                                (v["id"],)))
        for k in ("akzeptiert", "erwartungen"):
            try:
                v[k] = json.loads(v.get(k) or "[]")
            except ValueError:
                v[k] = []
        v["status_text"] = STATUS.get(v["status"], v["status"])
        v["quelle_text"] = QUELLEN.get(v.get("bestaetigung_quelle") or "", "")
        v["rolle_text"] = ROLLE_TEXT.get(v.get("empfaenger_rolle") or "", v.get("empfaenger_rolle") or "")
        for k in ("erstellt_von", "bestaetigt_von"):
            v[k + "_anzeige"] = anzeige.get((v.get(k) or "").lower(), v.get(k) or "")
        return v

    def liste(self, akte: str = "", status: str = "", limit: int = 200) -> list[dict]:
        sql, w = "SELECT * FROM versand WHERE 1=1", []
        if akte:
            sql += " AND akte = ?"
            w.append(akte)
        if status:
            sql += " AND status = ?"
            w.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        w.append(limit)
        anzeige = self._anzeige()
        return [self._aufbereiten(v, anzeige) for v in _zeilen(self.con.execute(sql, w))]

    def bestaetigen(self, vid: int, quelle: str, text: str = "") -> dict:
        """Versand bestätigt – Quelle: outlook_gesendet (passender Eintrag in „Gesendete Elemente“) oder manuell
        (ausdrückliche Bestätigung eines Menschen). Verknüpfte erwartete Unterlagen gelten dann als angefordert."""
        if quelle not in QUELLEN:
            raise ValueError("Unbekannte Bestätigungsquelle.")
        v = self.eintrag(vid)
        if v is None:
            raise ValueError("Diesen Versandeintrag gibt es nicht (mehr).")
        if v["status"] == "versand_bestaetigt":
            return v
        wer, jetzt = pr.aktuell().name, _jetzt()
        if quelle == "manuell" and not (text or "").strip():
            text = f"Bestätigt von {pr.aktuell().text}"
        self.con.execute("UPDATE versand SET status = 'versand_bestaetigt', bestaetigt_von = ?, bestaetigt_am = ?, "
                         "bestaetigung_quelle = ?, bestaetigung_text = ? WHERE id = ?",
                         (wer, jetzt, quelle, (text or "").strip(), vid))
        if v.get("akte"):
            self.con.execute(
                "INSERT INTO vorgaenge (zeit, workflow, dokument, ergebnis, empfaenger, referenz, status, meldung, art,"
                " quelle_id, benutzer) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (jetzt, "versand", "", "", v["empfaenger"], v["akte"], "ok",
                 f"Versand bestätigt ({QUELLEN[quelle]}): {v['betreff']} – Nachweis Nr. {vid}", "versand",
                 f"versand-bestaetigt:{vid}", pr.aktuell().text))
        self.prot.eintragen("versand", vid, "versand_bestaetigt", [], v["betreff"], commit=False)
        self.con.commit()
        if v.get("erwartungen"):
            from core.unterlagen import Unterlagen
            u = Unterlagen(self.con)
            for eid in v["erwartungen"]:
                try:
                    u.angefordert_eintragen(int(eid), quelle="versand_bestaetigt", versand_id=vid)
                except ValueError:
                    pass
        return self.eintrag(vid)

    def nicht_bestaetigt(self, vid: int, grund: str = "") -> dict:
        v = self.eintrag(vid)
        if v is None:
            raise ValueError("Diesen Versandeintrag gibt es nicht (mehr).")
        if v["status"] == "versand_bestaetigt":
            raise ValueError("Dieser Versand ist bereits bestätigt.")
        self.con.execute("UPDATE versand SET status = 'versand_nicht_bestaetigt', bestaetigt_von = ?, bestaetigt_am = ?,"
                         " bestaetigung_quelle = 'manuell', bestaetigung_text = ? WHERE id = ?",
                         (pr.aktuell().name, _jetzt(), (grund or "").strip() or "Als nicht gesendet markiert", vid))
        self.prot.eintragen("versand", vid, "versand_nicht_bestaetigt", [], v["betreff"], commit=False)
        self.con.commit()
        return self.eintrag(vid)

    def veraltet(self, vid: int, grund: str) -> dict:
        """Prüfung nicht mehr gültig (z. B. Original nach dem Entwurf geändert) – Eintrag bleibt erhalten."""
        self.con.execute("UPDATE versand SET gueltig = 0, ungueltig_grund = ? WHERE id = ? AND gueltig = 1",
                         ((grund or "").strip(), vid))
        self.con.commit()
        return self.eintrag(vid)

    def aenderungsverlauf(self, art: str, objekt) -> list[dict]:
        return self.prot.fuer(art, objekt)


def aenderungen_seit_entwurf(eintrag: dict, sha_jetzt) -> list[str]:
    """Originale, die sich seit dem Entwurf verändert haben (die feste Versandkopie bleibt unverändert).
    sha_jetzt(original_pfad) → aktuelle Prüfsumme oder None (nicht erreichbar)."""
    out = []
    for d in eintrag.get("dateien") or []:
        if not d.get("original_pfad") or not d.get("original_sha256"):
            continue
        jetzt = sha_jetzt(d["original_pfad"])
        if jetzt is None:
            out.append(f"{d['name']}: Original auf diesem Rechner nicht erreichbar – Änderung nicht geprüft")
        elif jetzt != d["original_sha256"]:
            out.append(f"{d['name']}: Original seit dem Entwurf geändert (Versandkopie unverändert)")
    return out
