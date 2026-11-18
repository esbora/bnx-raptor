"""Word-Dokument im Programm bearbeiten (0.4.1, „Versicherungsschreiben vorbereiten“ und Akten-Verlauf).

Bearbeitet wird absatzweise über Word selbst (COM): nur der geänderte Teil eines Absatzes wird ersetzt,
Briefkopf, Formatierung, Kopf-/Fußzeilen und Inhaltssteuerelemente bleiben erhalten. Gespeichert wird
sicher: Kopie bearbeiten → prüfen → Original ersetzen (gesperrt/extern geändert → nichts überschrieben).

PDF → Word: Textebene (digital) bzw. OCR (Scan) → Absätze in ein neues Word-Dokument. Die Arbeitskopie liegt neben dem PDF und ist im
Dokumentenarchiv mit dem PDF verknüpft.
"""
from __future__ import annotations

import difflib
import hashlib
import shutil
import tempfile
from pathlib import Path

from core.word_service import WordError, WordService

def fingerabdruck(pfad: Path) -> str:
    try:
        return hashlib.sha256(Path(pfad).read_bytes()).hexdigest()
    except OSError:
        return "?"


def _rein(text: str) -> str:
    return text.rstrip("\r\x07").replace("\x0b", "\n").replace("\x07", "")


def absaetze_lesen(w: WordService, pfad: Path) -> list[str]:
    """Absätze des Haupttextes (Tabellenzellen eingeschlossen) – in einer offenen WordService-Sitzung."""
    with w._waechter(pfad):
        doc = w._open(pfad)
        try:
            return [_rein(p.Range.Text) for p in doc.Paragraphs]
        finally:
            if not w._abgelaufen:
                doc.Close(SaveChanges=0)


def _absatz_setzen(doc, par, alt: str, neu: str) -> None:
    """Nur den geänderten Mittelteil ersetzen (gemeinsamer Anfang/Ende bleiben samt Formatierung)."""
    vorne = 0
    while vorne < min(len(alt), len(neu)) and alt[vorne] == neu[vorne]:
        vorne += 1
    hinten = 0
    while hinten < min(len(alt), len(neu)) - vorne and alt[-1 - hinten] == neu[-1 - hinten]:
        hinten += 1
    r = par.Range
    start = r.Start + vorne
    ende = r.Start + len(alt) - hinten
    doc.Range(start, ende).Text = neu[vorne:len(neu) - hinten].replace("\n", "\x0b")
    if _rein(par.Range.Text) != neu:            # z. B. Felder: Zeichenpositionen weichen ab → ganzen Absatz setzen
        r = par.Range
        inhalt = doc.Range(r.Start, r.End - 1)
        inhalt.Text = neu.replace("\n", "\x0b")


def aenderungen_anwenden(doc, alt: list[str], neu: list[str]) -> None:
    """Absatzliste alt → neu in einem geöffneten Word-Dokument (von hinten nach vorne, Indizes bleiben gültig)."""
    sm = difflib.SequenceMatcher(a=alt, b=neu, autojunk=False)
    for tag, i1, i2, j1, j2 in reversed(sm.get_opcodes()):
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            for k in reversed(range(i2 - i1)):
                _absatz_setzen(doc, doc.Paragraphs(i1 + k + 1), alt[i1 + k], neu[j1 + k])
        elif tag in ("replace", "delete"):
            von = doc.Paragraphs(i1 + 1).Range.Start
            bis = doc.Paragraphs(i2).Range.End
            if tag == "delete":
                if i2 == len(alt) and i1 > 0:                  # letzter Absatz: Marke davor mitnehmen
                    von = doc.Paragraphs(i1).Range.End - 1
                    doc.Range(von, bis - 1).Delete()
                else:
                    doc.Range(von, bis).Delete()
            else:
                doc.Range(von, bis - 1).Text = "\r".join(x.replace("\n", "\x0b") for x in neu[j1:j2])
        elif tag == "insert":
            text = "\r".join(x.replace("\n", "\x0b") for x in neu[j1:j2])
            if i1 < len(alt):
                doc.Paragraphs(i1 + 1).Range.InsertBefore(text + "\r")
            else:
                doc.Content.InsertAfter("\r" + text)


def speichern(w: WordService, pfad: Path, alt: list[str], neu: list[str], basis: str) -> list[str]:
    """Änderungen sicher in `pfad` speichern. Gibt die tatsächlich gespeicherten Absätze zurück.

    basis = Fingerabdruck beim Öffnen; weicht die Datei inzwischen ab → WordError, nichts überschrieben.
    """
    pfad = Path(pfad)
    if fingerabdruck(pfad) != basis:
        raise WordError(f"{pfad.name} wurde während der Bearbeitung von einem anderen Programm geändert – "
                        "nicht überschrieben. Bitte neu laden.")
    from core import pdf_engine as pe
    td = Path(tempfile.mkdtemp(prefix="bnx-word-"))
    try:
        kopie = td / pfad.name
        shutil.copyfile(pfad, kopie)
        with w._waechter(kopie):
            doc = w.app.Documents.Open(str(kopie), ReadOnly=False, AddToRecentFiles=False, Visible=False)
            try:
                aenderungen_anwenden(doc, alt, neu)
                ergebnis = [_rein(p.Range.Text) for p in doc.Paragraphs]
                doc.Save()
            finally:
                if not w._abgelaufen:
                    doc.Close(SaveChanges=0)
        if ergebnis != neu:
            raise WordError("Word hat den Text nicht vollständig übernommen – nichts gespeichert. "
                            "Bitte die Datei direkt in Word bearbeiten.")
        if fingerabdruck(pfad) != basis:                 # während Word lief geändert?
            raise WordError(f"{pfad.name} wurde zwischenzeitlich geändert – nicht überschrieben.")
        tmp = pe.temp_neben(pfad)
        shutil.copyfile(kopie, tmp)
        try:
            pe.ersetzen(tmp, pfad)
        except pe.PdfFehler as e:
            raise WordError(str(e)) from e
        finally:
            if tmp.exists():
                tmp.unlink()
        return ergebnis
    finally:
        shutil.rmtree(td, ignore_errors=True)


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
