"""PDF düzenleme oturumu: bellekteki çalışma kopyası, geri al / yinele, önizleme, „Speichern unter…“.

Belge belleğe okunur. 0.4.1: „Speichern“ aynı dosyaya yazar (geçici dosya → kontrol → güvenli değiştirme);
dosya bu arada dışarıdan değiştiyse veya kilitliyse üzerine yazılmaz. „Speichern unter…“ ayrı kalır.
Arayüzden bağımsızdır (testlerde doğrudan kullanılır).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from core import pdf_engine as pe

MAX_SCHRITTE = 40


@dataclass
class Schritt:
    beschreibung: str
    daten: bytes
    schwaerzungen: list


@dataclass
class Speicherergebnis:
    pfad: Path
    entfernt: list[str] = field(default_factory=list)
    pruefung: dict | None = None


class PdfSitzung:
    def __init__(self, pfad: Path | None = None, daten: bytes | None = None, name: str = ""):
        self.original = Path(pfad) if pfad else None
        self._basis = ""                     # Fingerabdruck der Datei beim Öffnen (nur bei PDF-Dateien)
        if daten is None and pfad and Path(pfad).suffix.lower() == ".pdf":
            daten = Path(pfad).read_bytes()          # ganz in den Speicher: Datei bleibt während der Arbeit frei
            self._basis = hashlib.sha256(daten).hexdigest()
        self.doc = pe.oeffnen(pfad, daten)
        self.name = name or (self.original.name if self.original else "Dokument.pdf")
        self.signaturen = pe.signaturen(self.doc)
        self._undo: list[Schritt] = []
        self._redo: list[Schritt] = []
        self.geaendert = False
        self.schwaerzungen: list[pe.Schwaerzung] = []
        self.protokoll: list[str] = []        # was wurde geändert (für Vorschau/Speichern)
        self.warnungen: list[str] = []

    # --- Änderungen -------------------------------------------------------------
    def _schnappschuss(self, beschreibung: str) -> Schritt:
        return Schritt(beschreibung, self.doc.tobytes(), list(self.schwaerzungen))

    def aendern(self, beschreibung: str, fn):
        """fn(doc) ausführen; bei Fehler bleibt das Dokument unverändert."""
        vorher = self._schnappschuss(beschreibung)
        try:
            ergebnis = fn(self.doc)
        except Exception:
            self._laden(vorher)
            raise
        self._undo.append(vorher)
        del self._undo[:-MAX_SCHRITTE]
        self._redo.clear()
        self.geaendert = True
        self.protokoll.append(beschreibung)
        warn = getattr(ergebnis, "warnungen", None)
        if warn:
            self.warnungen += [f"{beschreibung}: {w}" for w in warn]
        for e in ergebnis if isinstance(ergebnis, list) else [ergebnis]:
            if isinstance(e, pe.Schwaerzung):
                self.schwaerzungen.append(e)
        return ergebnis

    def vorschau(self, fn, seite: int, breite: int = 700):
        """fn auf einer KOPIE ausführen → (Seitenbild, Ergebnis). Das Dokument bleibt unverändert."""
        kopie = pymupdf.open("pdf", self.doc.tobytes())
        ergebnis = fn(kopie)
        pix = pe.seitenbild(kopie[min(seite, kopie.page_count - 1)], breite)
        kopie.close()
        return pix, ergebnis

    def _laden(self, s: Schritt) -> None:
        self.doc.close()
        self.doc = pymupdf.open("pdf", s.daten)
        self.schwaerzungen = list(s.schwaerzungen)

    @property
    def kann_rueckgaengig(self) -> bool:
        return bool(self._undo)

    @property
    def kann_wiederholen(self) -> bool:
        return bool(self._redo)

    def rueckgaengig(self) -> str:
        if not self._undo:
            return ""
        s = self._undo.pop()
        self._redo.append(self._schnappschuss(s.beschreibung))
        self._laden(s)
        self.geaendert = True
        if self.protokoll:
            self.protokoll.pop()
        return s.beschreibung

    def wiederholen(self) -> str:
        if not self._redo:
            return ""
        s = self._redo.pop()
        self._undo.append(self._schnappschuss(s.beschreibung))
        self._laden(s)
        self.geaendert = True
        self.protokoll.append(s.beschreibung)
        return s.beschreibung

    # --- Speichern --------------------------------------------------------------
    def vorschlag(self) -> Path:
        basis = self.original or Path.home() / self.name
        ziel = basis.with_name(basis.stem + "_bearbeitet.pdf")
        i = 2
        while ziel.exists():
            ziel = basis.with_name(f"{basis.stem}_bearbeitet_{i}.pdf")
            i += 1
        return ziel

    @property
    def kann_speichern(self) -> bool:
        """„Speichern“ in dieselbe Datei möglich (PDF-Datei geöffnet, nicht nur Bytes im Speicher)."""
        return bool(self._basis)

    def extern_geaendert(self) -> bool:
        return bool(self._basis) and _fingerabdruck(self.original) != self._basis

    def speichern(self, pruefen_ocr: bool = True) -> Speicherergebnis:
        """In dieselbe Datei speichern (Strg+S). Erst Temp-Datei, prüfen (auch Schwärzung), dann ersetzen.
        Wurde die Datei inzwischen von außen geändert oder ist sie gesperrt → Fehler, nichts überschrieben."""
        if not self.kann_speichern:
            raise pe.PdfFehler("Diese Datei kann nur über „Speichern unter…“ gespeichert werden.")
        if not self.original.exists():
            raise pe.PdfFehler(f"{self.original.name} existiert nicht mehr – bitte „Speichern unter…“ verwenden.")
        if self.extern_geaendert():
            raise ExternGeaendert(f"{self.original.name} wurde während der Bearbeitung von einem anderen Programm "
                                  "geändert. Nicht überschrieben – bitte „Speichern unter…“ verwenden.")
        erg = self._schreiben(self.original, pruefen_ocr)
        self._basis = _fingerabdruck(self.original)
        return erg

    def _schreiben(self, ziel: Path, pruefen_ocr: bool) -> Speicherergebnis:
        erg = Speicherergebnis(ziel)
        if self.schwaerzungen:
            erg.entfernt = pe.nach_schwaerzung_bereinigen(self.doc)
        tmp = pe.temp_neben(ziel)
        try:
            pe.sicher_speichern(self.doc, tmp)
            if self.schwaerzungen:                   # Prüfung VOR dem Ersetzen: schlechte Datei kommt nie ans Ziel
                erg.pruefung = pe.schwaerzung_pruefen(tmp, self.schwaerzungen, ocr=pruefen_ocr)
                if not erg.pruefung["bestanden"]:
                    raise pe.PdfFehler("Schwärzungsprüfung fehlgeschlagen – nicht gespeichert:\n"
                                       + _pruefung_text(erg.pruefung))
            pe.ersetzen(tmp, ziel)
        finally:
            if tmp.exists():
                tmp.unlink()
        self.geaendert = False
        return erg

    def speichern_unter(self, ziel: Path, pruefen_ocr: bool = True) -> Speicherergebnis:
        ziel = Path(ziel)
        if ziel.suffix.lower() != ".pdf":
            ziel = ziel.with_suffix(".pdf")
        if self.original and ziel.exists() and ziel.resolve() == self.original.resolve() and self.kann_speichern:
            return self.speichern(pruefen_ocr)
        erg = self._schreiben(ziel, pruefen_ocr)
        self.original, self.name = ziel, ziel.name          # weitere „Speichern“ gehen in die neue Datei
        self._basis = _fingerabdruck(ziel)
        return erg

    def als_bytes(self) -> bytes:
        return self.doc.tobytes(garbage=4, deflate=True)


class ExternGeaendert(pe.PdfFehler):
    """Datei wurde während der Bearbeitung extern geändert – nicht überschrieben."""


def _fingerabdruck(pfad: Path) -> str:
    try:
        return hashlib.sha256(Path(pfad).read_bytes()).hexdigest()
    except OSError:
        return "?"


def _pruefung_text(p: dict) -> str:
    namen = {"text": "Text", "ocr_ebene": "OCR-Ebene", "bilder": "Bilder", "bild_ocr": "Bild-Texterkennung",
             "eingebettet": "eingebettete Dateien", "rohdaten": "Rohdaten"}
    return "\n".join(f"{namen[k]}: {', '.join(map(str, p[k]))}" for k in namen if p.get(k))
