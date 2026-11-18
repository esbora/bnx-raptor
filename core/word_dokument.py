"""Word-Dokumente bearbeiten (0.4.1): im echten, sichtbaren Word – nie per Textersetzung.

Bis 0.4.0 wurde der Text im Programm bearbeitet und absatzweise per COM zurückgeschrieben. Das scheiterte an
gesperrten Bereichen („Bereich kann nicht gelöscht werden“) und konnte Formatierung verlieren → entfernt.
Jetzt: „In Word bearbeiten“ legt eine datierte KOPIE an (11_Vollmacht_2026-11-18.docx), öffnet sie im
sichtbaren Word und beobachtet nur diese eine Datei; nach dem Schließen wird die Vorschau neu erzeugt.
Vorher wird geprüft, ob das Dokument geschützt ist oder gesperrte Inhaltssteuerelemente hat.

PDF → Word: Textebene (digital) bzw. OCR (Scan) → Absätze in ein neues Word-Dokument.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

from core.word_service import WordError, WordService

# Word-Konstanten
WD_KEIN_SCHUTZ = -1
SCHUTZARTEN = {0: "nur Überarbeitungen (Änderungen nachverfolgen)", 1: "nur Kommentare",
               2: "nur Formularfelder ausfüllen", 3: "nur Lesen"}


def fingerabdruck(pfad: Path) -> str:
    try:
        return hashlib.sha256(Path(pfad).read_bytes()).hexdigest()
    except OSError:
        return "?"


# ---------------------------------------------------------------- Kopie statt Original
_KOPIE = re.compile(r"_\d{4}-\d{2}-\d{2}(_\d+)?$")


def ist_bnx_kopie(pfad: Path) -> bool:
    """Von BnX-Raptor angelegte Bearbeitungskopie (…_JJJJ-MM-TT[_n].docx) oder Word-Arbeitskopie eines PDF
    („… (Word).docx“) – diese werden direkt bearbeitet, alle anderen Dateien nur als Kopie."""
    stamm = Path(pfad).stem
    return bool(_KOPIE.search(stamm)) or bool(re.search(r" \(Word( \d+)?\)$", stamm))


def kopie_name(original: Path, heute: date | None = None) -> Path:
    """11_Vollmacht.docx → 11_Vollmacht_2026-11-18.docx (vorhanden → _2, _3 …). Nie das Original."""
    original = Path(original)
    tag = (heute or date.today()).isoformat()
    ziel = original.with_name(f"{original.stem}_{tag}{original.suffix}")
    i = 2
    while ziel.exists():
        ziel = original.with_name(f"{original.stem}_{tag}_{i}{original.suffix}")
        i += 1
    return ziel


def bearbeitungskopie(original: Path, heute: date | None = None) -> Path:
    ziel = kopie_name(original, heute)
    shutil.copy2(original, ziel)
    return ziel


def wird_bearbeitet(pfad: Path) -> bool:
    """Ist die Datei gerade in Word geöffnet? Nur diese eine Datei wird geprüft (Sperre bzw. „~$“-Besitzerdatei)
    – andere Word-Dokumente werden nicht angefasst."""
    pfad = Path(pfad)
    besitzer = pfad.with_name("~$" + pfad.name[2:]) if len(pfad.name) > 2 else None
    if besitzer is not None and besitzer.exists():
        return True
    try:
        with open(pfad, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- Schutz prüfen (vor dem Bearbeiten)
def schutz_texte(schutzart: int, steuerelemente: list[tuple[str, bool, bool]], schreibgeschuetzt: bool = False) -> list[str]:
    """Verständliche Hinweise. steuerelemente: (Name, Inhalt gesperrt, Steuerelement nicht löschbar)."""
    out = []
    if schreibgeschuetzt:
        out.append("Die Datei ist schreibgeschützt (Dateieigenschaft „Schreibgeschützt“).")
    if schutzart != WD_KEIN_SCHUTZ:
        out.append(f"Das Dokument hat eine Bearbeitungseinschränkung: {SCHUTZARTEN.get(schutzart, 'eingeschränkt')}. "
                   "Aufheben in Word unter „Überprüfen → Bearbeitung einschränken → Schutz aufheben“.")
    gesperrt = [n or "ohne Namen" for n, inhalt, _ in steuerelemente if inhalt]
    nicht_loeschbar = [n or "ohne Namen" for n, inhalt, element in steuerelemente if element and not inhalt]
    if gesperrt:
        out.append(f"{len(gesperrt)} Inhaltssteuerelement(e) sind gegen Änderungen gesperrt ({', '.join(gesperrt[:4])}"
                   f"{' …' if len(gesperrt) > 4 else ''}). Deren Text lässt sich nicht ändern.")
    if nicht_loeschbar:
        out.append(f"{len(nicht_loeschbar)} Inhaltssteuerelement(e) können nicht gelöscht werden "
                   f"({', '.join(nicht_loeschbar[:4])}{' …' if len(nicht_loeschbar) > 4 else ''}).")
    return out


def schutz_pruefen(w: WordService, pfad: Path) -> list[str]:
    """Liest Schutzart und Inhaltssteuerelemente im eigenen, unsichtbaren Word (nur lesend)."""
    import os
    import stat
    schreibgeschuetzt = not os.stat(pfad).st_mode & stat.S_IWRITE
    with w._waechter(pfad):
        doc = w._open(pfad)
        try:
            art = int(doc.ProtectionType)
            ccs = []
            for cc in doc.ContentControls:
                ccs.append(((cc.Title or cc.Tag or "").strip(), bool(cc.LockContents), bool(cc.LockContentControl)))
        finally:
            if not w._abgelaufen:
                doc.Close(SaveChanges=0)
    return schutz_texte(art, ccs, schreibgeschuetzt)


def vorschau_pdf(w: WordService, pfad: Path, ziel: Path) -> Path:
    w.export_pdf(pfad, ziel, pdfa=False)
    return ziel


def arbeitskopie_name(pdf: Path) -> Path:
    basis = pdf.with_name(f"{pdf.stem} (Word).docx")
    ziel, i = basis, 2
    while ziel.exists():
        ziel = pdf.with_name(f"{pdf.stem} (Word {i}).docx")
        i += 1
    return ziel


def pdf_zu_word(pdf: Path, ziel: Path, ocr=None) -> tuple[Path, str]:
    """PDF → bearbeitbares Word-Dokument (Absätze). Rückgabe (Pfad, Art): 'text' (Textebene genutzt)
    oder 'ocr' (mindestens eine Scan-Seite per Texterkennung).

    Bewusst ohne Word-„PDF-Reflow“: der zeigt im unsichtbaren Word eine Rückfrage und hängt; abschalten
    ließe er sich nur über eine Office-Einstellung, die BnX-Raptor nicht verändert. Das Layout wird daher
    vereinfacht – Original und Word-Fassung stehen in der Vorschau nebeneinander.
    ocr(page) -> list[str]: Absätze einer Seite ohne Text.
    """
    from core import pdf_engine as pe
    from core.docx_schreiben import docx_absaetze
    pdf, ziel = Path(pdf), Path(ziel)
    doc = pe.oeffnen(pdf)
    absaetze: list[str] = []
    art = "text"
    for p in doc:
        if pe.ist_gescannt(p):
            if ocr is None:
                raise WordError(f"Seite {p.number + 1} ist ein Scan ohne Text – Texterkennung nicht verfügbar.")
            absaetze += ocr(p)
            art = "ocr"
        else:
            absaetze += [pe._blocktext(b) for b in pe.textbloecke(p)]
        absaetze.append("")                          # Seitenwechsel als Leerabsatz
    doc.close()
    docx_absaetze(ziel, absaetze[:-1], titel=pdf.stem)
    return ziel, art


def ocr_absaetze(page, sprachen=None) -> list[str]:
    """OCR einer Seite → Absätze (Tesseract-Block/Absatz-Gruppierung)."""
    from core import pdf_engine as pe
    worte = pe.ocr_seite(page, sprachen=tuple(sprachen or pe.SPRACHEN))
    absaetze: dict[tuple, list[str]] = {}
    for w in worte:
        absaetze.setdefault(w.zeile[:2], []).append(w.text)
    return [" ".join(x) for x in absaetze.values()]
