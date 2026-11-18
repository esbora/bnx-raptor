"""Anlagen-Assistent: Schriftsatz + Anlagen → einzelne PDFs + Anlagenverzeichnis.docx.

Arayüzden bağımsız mantık (testlerde doğrudan kullanılır). Orijinal dosyalar yalnızca okunur;
her ekin bellekte bir PDF çalışma kopyası vardır. Paket önce YEREL geçici klasörde (%TEMP%) oluşturulur,
her dosya yeniden açılıp kontrol edilir, sonra hedefe kopyalanıp hemen adlandırılır (OneDrive/virüs
tarayıcısı kısa süre kilitlerse tekrar denenir). 0.4.1: Hauptdokument isteğe bağlı; açılamayan veya
dönüştürülemeyen ekler orijinal adı/uzantısı/içeriğiyle pakete alınır, kullanıcı seçmedikçe hiçbir ek çıkarılmaz.
"""
from __future__ import annotations

import hashlib
import itertools
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import pymupdf

from core import pdf_engine as pe
from core.docx_schreiben import docx_schreiben
from core.fehlertexte import meldung

WORD = {".docx", ".doc", ".docm", ".rtf"}
PDF = {".pdf"}
BILD = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
UNTERSTUETZT = WORD | PDF | BILD
AEHNLICH_SCHWELLE = 30            # von 256 Bit; darunter gelten erste Seiten als optisch ähnlich
VERZEICHNIS = "Anlagenverzeichnis.docx"
GESAMT = "Gesamt_zur_internen_Pruefung.pdf"
_ids = itertools.count(1)


@dataclass
class Eintrag:
    quelle: Path
    titel: str
    art: str = "pdf"                       # pdf | bild | word
    sha256: str = ""
    daten: bytes | None = None             # PDF-Arbeitskopie (Word: erst beim Erstellen)
    seiten: int = 0
    fehler: str = ""
    bildhash: int | None = None
    worte: frozenset[str] = frozenset()        # Wortprobe des Textes (für "ähnlich")
    scan_seiten: list[int] = field(default_factory=list)
    drehvorschlag: dict[int, int] = field(default_factory=dict)   # Seite → Grad im Uhrzeigersinn
    ocr_fehler: list[str] = field(default_factory=list)
    bearbeitet: list[str] = field(default_factory=list)
    id: int = field(default_factory=lambda: next(_ids))

    @property
    def ok(self) -> bool:
        return not self.fehler

    def dokument(self) -> pymupdf.Document:
        return pymupdf.open("pdf", self.daten)

    def aktualisieren(self, doc: pymupdf.Document, beschreibung: str) -> None:
        """Arbeitskopie nach einer Bearbeitung übernehmen (Original bleibt unberührt)."""
        self.daten = doc.tobytes(garbage=3, deflate=True)
        _analysieren(self, doc)
        self.bearbeitet.append(beschreibung)


def _analysieren(e: "Eintrag", doc: pymupdf.Document) -> None:
    e.seiten = doc.page_count
    e.bildhash = pe.bildhash(doc[0])
    e.scan_seiten = [p.number for p in doc if pe.ist_gescannt(p)]
    e.worte = _wortprobe(" ".join(p.get_text() for p in doc[:10]))


def _wortprobe(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"\w{3,}", text.lower())[:5000])


def aehnlich(a: "Eintrag", b: "Eintrag") -> bool:
    """Inhaltlich gleiches Dokument in anderer Datei (z. B. PDF und Scan derselben Rechnung).

    Mit Text auf beiden Seiten (digital oder per OCR-Probe): Wortschatz überschneidet sich stark.
    Ohne Text (Fotos): erste Seite optisch fast gleich. Immer: gleiche Seitenzahl.
    """
    if a.seiten != b.seiten or a.bildhash is None or b.bildhash is None:
        return False
    if len(a.worte) >= 5 and len(b.worte) >= 5:
        return len(a.worte & b.worte) / len(a.worte | b.worte) >= 0.5
    if a.worte or b.worte:
        return False                      # eine Seite hat Text, die andere (noch) nicht → nicht vergleichbar
    return pe.hash_abstand(a.bildhash, b.bildhash) <= AEHNLICH_SCHWELLE


def textprobe_ergaenzen(e: "Eintrag", erkenner: Callable[[bytes, int], list[tuple]]) -> None:
    """Für Scans ohne Text: kurze OCR-Probe der ersten Seite (nur für den Doppelt-Vergleich)."""
    if e.worte or not e.daten or 0 not in e.scan_seiten:
        return
    with e.dokument() as doc:
        png, _ = pe.ocr_bild(doc[0], 150)
    try:
        e.worte = _wortprobe(" ".join(t[0] for t in erkenner(png, 150)))
    except Exception:  # noqa: BLE001 – Probe ist nur eine Hilfe für den Vergleich
        pass


def titel_vorschlag(pfad: Path) -> str:
    t = re.sub(r"^[\d\s._-]+", "", Path(pfad).stem)          # führende Nummern weg ("03_Rechnung")
    t = re.sub(r"[_]+", " ", t).strip(" -")
    return t[:1].upper() + t[1:] if t else Path(pfad).stem


def einlesen(pfad: Path) -> Eintrag:
    pfad = Path(pfad)
    e = Eintrag(pfad, titel_vorschlag(pfad))
    endung = pfad.suffix.lower()
    try:
        e.sha256 = hashlib.sha256(pfad.read_bytes()).hexdigest()
    except OSError as ex:
        e.fehler = f"Datei kann nicht gelesen werden ({ex.strerror})"
        return e
    if endung not in UNTERSTUETZT:
        e.fehler = "Dateityp wird nicht unterstützt (PDF, JPG, PNG, TIFF, Word)"
        return e
    if endung in WORD:
        e.art = "word"
        return e
    e.art = "bild" if endung in BILD else "pdf"
    try:
        doc = pe.oeffnen(pfad, pfad.read_bytes() if endung in PDF else None)
        e.daten = doc.tobytes(garbage=3, deflate=True)
        _analysieren(e, doc)
        doc.close()
    except pe.PdfFehler as ex:
        e.fehler = str(ex).split(": ", 1)[-1]
    return e


# ---------------------------------------------------------------- Seiten einer Anlage
def seiten_drehen(e: Eintrag, seiten: list[int], grad: int) -> None:
    doc = e.dokument()
    pe.seiten_drehen(doc, seiten, grad)
    for s in seiten:
        e.drehvorschlag.pop(s, None)
    e.aktualisieren(doc, f"Seite(n) {', '.join(str(s + 1) for s in seiten)} gedreht")


def seiten_loeschen(e: Eintrag, seiten: list[int]) -> None:
    doc = e.dokument()
    pe.seiten_loeschen(doc, seiten)
    e.drehvorschlag = {}
    e.aktualisieren(doc, f"Seite(n) {', '.join(str(s + 1) for s in seiten)} gelöscht")


def als_eigene_anlage(e: Eintrag, seiten: list[int]) -> Eintrag:
    """Seiten herauslösen → neue Anlage (direkt dahinter einzusortieren); in `e` werden sie entfernt."""
    doc = e.dokument()
    teil = pe.seiten_extrahieren(doc, seiten)
    neu = Eintrag(e.quelle, f"{e.titel} (Seite {', '.join(str(s + 1) for s in seiten)})", art="pdf")
    neu.daten = teil.tobytes(garbage=3, deflate=True)
    _analysieren(neu, teil)
    neu.bearbeitet.append(f"aus {e.quelle.name} herausgelöst")
    pe.seiten_loeschen(doc, seiten)
    e.drehvorschlag = {}
    e.aktualisieren(doc, f"Seite(n) {', '.join(str(s + 1) for s in seiten)} als eigene Anlage herausgelöst")
    return neu


def ausrichtung_pruefen(e: Eintrag, osd: Callable[[bytes], tuple[int, float]], mindest: float = 2.0) -> dict:
    """OSD für Scan-Seiten; Vorschläge (Seite → Grad) werden nur vorgemerkt, nicht angewendet."""
    if not e.daten:
        return {}
    doc = e.dokument()
    vorschlag = {}
    for s in e.scan_seiten or [p.number for p in doc if p.get_images()]:
        grad, sicher = osd(pe.ausrichtung_png(doc[s]))
        if grad and sicher >= mindest:
            vorschlag[s] = grad
    e.drehvorschlag = vorschlag
    return vorschlag


def ausrichtung_korrigieren(e: Eintrag) -> int:
    if not e.drehvorschlag:
        return 0
    doc = e.dokument()
    n = len(e.drehvorschlag)
    for s, g in e.drehvorschlag.items():
        doc[s].set_rotation((doc[s].rotation + g) % 360)
    e.drehvorschlag = {}
    e.aktualisieren(doc, f"Ausrichtung von {n} Seite(n) korrigiert")
    return n


def ocr_ausfuehren(e: Eintrag, erkenner: Callable[[bytes, int], list[tuple]], dpi: int = 300) -> int:
    """Scan-Seiten durchsuchbar machen. Fehler je Seite werden in e.ocr_fehler gemeldet (Datei + Seite)."""
    if not e.daten:
        return 0
    doc = e.dokument()
    e.ocr_fehler = []
    fertig = 0
    for s in list(e.scan_seiten):
        try:
            png, rueck = pe.ocr_bild(doc[s], dpi)
            worte = pe.worte_bilden(erkenner(png, dpi), rueck)
        except Exception as ex:  # noqa: BLE001
            e.ocr_fehler.append(f"Seite {s + 1}: Texterkennung fehlgeschlagen ({meldung(ex)[:160]})")
            continue
        if not worte:
            e.ocr_fehler.append(f"Seite {s + 1}: kein Text erkannt")
            continue
        pe.textebene_einfuegen(doc[s], worte)
        fertig += 1
    if fertig:
        fehler = e.ocr_fehler
        e.aktualisieren(doc, f"Texterkennung ({fertig} Seite(n))")
        e.ocr_fehler = fehler
    return fertig


def word_umwandeln(e: Eintrag, word_zu_pdf: Callable[[Path, Path], None]) -> bool:
    """Word-Anlage sofort in PDF umwandeln (für Vorschau, Seitenzahl, Doppelt-Prüfung).
    Fehler werden am Eintrag gemeldet (Datei bleibt in der Liste, Paket ist dann blockiert)."""
    if e.art != "word" or e.daten is not None or e.fehler:
        return False
    import tempfile
    with tempfile.TemporaryDirectory(prefix="bnx-word-") as td:
        ziel = Path(td) / (e.quelle.stem + ".pdf")
        try:
            word_zu_pdf(e.quelle, ziel)
            doc = pe.oeffnen(ziel, ziel.read_bytes())
        except Exception as ex:  # noqa: BLE001
            e.fehler = f"Word-Umwandlung fehlgeschlagen: {meldung(ex).splitlines()[0][:200]}"
            return False
        e.daten = doc.tobytes(garbage=3, deflate=True)
        _analysieren(e, doc)
        doc.close()
    return True


SCHRIFTSATZ_WOERTER = re.compile(r"klage|schriftsatz|antrag|erwiderung|berufung|replik|duplik|beschwerde|"
                                 r"einspruch|widerspruch|stellungnahme", re.I)


def schriftsatz_vorschlag(eintraege: list[Eintrag]) -> Eintrag | None:
    """Welche Word-Datei ist der Schriftsatz? Name mit „Klage/Schriftsatz/Antrag…“ zuerst, sonst die erste."""
    word = [e for e in eintraege if e.art == "word"]
    return next((e for e in word if SCHRIFTSATZ_WOERTER.search(e.quelle.stem)), word[0] if word else None)


def bezeichnungen(anzahl: int, praefix: str = "Anlage K", start: int = 1) -> list[str]:
    return [f"{praefix}{start + i}" for i in range(anzahl)]


def dateiname(bezeichnung: str) -> str:
    return re.sub(r"[^\w\-]+", "_", bezeichnung, flags=re.UNICODE).strip("_") + ".pdf"


@dataclass
class Hinweis:
    stufe: str                 # "fehler" | "warnung" | "info" – seit 0.4.1 blockiert nichts mehr das Paket
    art: str                   # original | fehlt | identisch | aehnlich | ausrichtung | ocr | leer
    text: str
    ids: list[int] = field(default_factory=list)


ORIGINAL_TEXT = "Original übernommen – Vorschau nicht verfügbar"


def lesbar(e: Eintrag) -> bool:
    """Quelldatei konnte gelesen werden (Prüfsumme vorhanden) – dann kann sie als Original ins Paket."""
    return bool(e.sha256)


def pruefen(schriftsatz: Eintrag | None, anlagen: list[Eintrag]) -> list[Hinweis]:
    """Nur Hinweise – das Paket wird trotzdem erstellt. Nichts wird automatisch entfernt."""
    h: list[Hinweis] = []
    alle = ([schriftsatz] if schriftsatz else []) + anlagen
    for e in alle:
        if e.fehler and lesbar(e):
            h.append(Hinweis("warnung", "original", f"{e.quelle.name}: {ORIGINAL_TEXT} ({e.fehler})", [e.id]))
        elif e.fehler:
            h.append(Hinweis("fehler", "fehlt", f"{e.quelle.name}: wird NICHT kopiert – {e.fehler}", [e.id]))
    for e in anlagen:
        if not e.titel.strip():
            h.append(Hinweis("warnung", "leer", f"{e.quelle.name}: Bezeichnung fehlt – Dateiname wird verwendet.",
                             [e.id]))
    if not anlagen and not schriftsatz:
        h.append(Hinweis("warnung", "leer", "Keine Dateien in der Liste."))
    for a, b in itertools.combinations(alle, 2):
        if a.sha256 and a.sha256 == b.sha256:
            h.append(Hinweis("info", "identisch",
                             f"Hinweis: identische Dateien (Byte für Byte gleich): {a.quelle.name} und {b.quelle.name}",
                             [a.id, b.id]))
        elif aehnlich(a, b):
            h.append(Hinweis("info", "aehnlich",
                             f"Hinweis: ähnlicher Inhalt: {a.quelle.name} und {b.quelle.name}", [a.id, b.id]))
    for e in alle:
        for s, g in sorted(e.drehvorschlag.items()):
            text = "steht vermutlich auf dem Kopf" if g == 180 else f"ist vermutlich um {g}° gedreht"
            h.append(Hinweis("warnung", "ausrichtung", f"{e.quelle.name}, Seite {s + 1} {text}", [e.id]))
        for f in e.ocr_fehler:
            h.append(Hinweis("warnung", "ocr", f"{e.quelle.name}: {f}", [e.id]))
    return h


def blockiert(hinweise: list[Hinweis]) -> bool:
    """Seit 0.4.1 blockiert kein Hinweis das Paket (Dateien werden notfalls als Original übernommen)."""
    return False


# ---------------------------------------------------------------- Paket erstellen
@dataclass
class Paketdatei:
    rolle: str                 # schriftsatz | anlage | original | fehlt | verzeichnis | gesamt
    bezeichnung: str
    titel: str
    pfad: Path
    seiten: int
    sha256: str


@dataclass
class Paket:
    ordner: Path
    dateien: list[Paketdatei]
    hinweise: list[str] = field(default_factory=list)      # z. B. nicht kopiert / nicht im Gesamt-PDF

    def fuer_versand(self, verzeichnis: bool = False, gesamt: bool = False) -> list[Paketdatei]:
        return [d for d in self.dateien if d.rolle in ("schriftsatz", "anlage", "original")
                or (verzeichnis and d.rolle == "verzeichnis") or (gesamt and d.rolle == "gesamt")]


class Namenskonflikt(Exception):
    def __init__(self, vorhanden: list[Path], vorschlag: list[Path]):
        super().__init__("Dateien existieren bereits")
        self.vorhanden, self.vorschlag = vorhanden, vorschlag


class AblageFehler(pe.PdfFehler):
    """Eine Paketdatei konnte nicht im Zielordner abgelegt werden (Datei wird genannt)."""

    def __init__(self, datei: Path, grund: str):
        super().__init__(f"{Path(datei).name}: {grund}")
        self.datei, self.grund = Path(datei), grund


ABLAGE_VERSUCHE = 8              # vorübergehende Sperren (OneDrive, Virenscanner, Vorschau) abwarten
ABLAGE_PAUSE = 0.25              # Sekunden, wächst je Versuch (gesamt ≈ 9 s)


def _ziel_name(e: Eintrag, bezeichnung: str) -> str:
    """Original übernommen → Originalname mit Endung; sonst Anlage_K1.pdf."""
    return e.quelle.name if (e.fehler and lesbar(e)) else dateiname(bezeichnung)


def geplante_namen(schriftsatz_name: str | None, bez: list[str], gesamt: bool,
                   anlagen: list[Eintrag] | None = None, schriftsatz: Eintrag | None = None) -> list[str]:
    """Dateinamen in Ablagereihenfolge (nicht kopierbare Anlagen erscheinen nicht)."""
    namen = []
    if schriftsatz_name:
        if schriftsatz is not None and schriftsatz.fehler:
            if lesbar(schriftsatz):
                namen.append(schriftsatz.quelle.name)
        else:
            namen.append(schriftsatz_name)
    if anlagen is None:
        namen += [dateiname(b) for b in bez]
    else:
        namen += [_ziel_name(e, b) for e, b in zip(anlagen, bez) if lesbar(e) or not e.fehler]
    return namen + [VERZEICHNIS] + ([GESAMT] if gesamt else [])


def freie_namen(ordner: Path, namen: list[str]) -> list[Path]:
    """Var olan dosyanın üzerine yazılmaz: aynı ad varsa _2, _3 … (CLAUDE.md kural 5)."""
    vergeben: set[str] = set()
    out = []
    for n in namen:
        p = ordner / n
        i = 2
        while p.exists() or p.name.lower() in vergeben:
            p = ordner / f"{Path(n).stem}_{i}{Path(n).suffix}"
            i += 1
        vergeben.add(p.name.lower())
        out.append(p)
    return out


def _pruefen_und_zaehlen(pfad: Path) -> int:
    with pymupdf.open(pfad) as d:
        if d.page_count == 0:
            raise pe.PdfFehler(f"{pfad.name}: keine Seiten")
        return d.page_count


def _schreibrecht(ordner: Path) -> None:
    probe = ordner / f".bnx-schreibprobe-{uuid.uuid4().hex[:6]}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except PermissionError as ex:
        raise AblageFehler(ordner, "Keine Schreibrechte im Zielordner (Zugriff verweigert). "
                                   "Bitte einen anderen Ordner wählen oder die Ordnerrechte prüfen.") from ex


def ablegen(quelle: Path, ziel: Path, warte: Callable[[float], None] | None = None) -> None:
    """Fertige Datei in den Zielordner legen – nie überschreiben.

    Erst als versteckte Teildatei kopieren, dann sofort umbenennen. Ist die Datei kurz gesperrt (z. B. weil
    OneDrive oder der Virenscanner sie gerade liest), wird mehrmals mit wachsender Pause erneut versucht.
    """
    import time
    warte = warte or time.sleep
    teil = ziel.with_name(f".~{ziel.name}.bnx-teil")
    letzter: OSError | None = None
    for versuch in range(ABLAGE_VERSUCHE):
        if ziel.exists():
            raise AblageFehler(ziel, "wurde inzwischen von einem anderen Programm angelegt – nicht überschrieben.")
        try:
            with open(quelle, "rb") as q, open(teil, "xb") as z:
                shutil.copyfileobj(q, z, 1 << 20)
                z.flush()
                os.fsync(z.fileno())
            os.rename(teil, ziel)                     # os.rename überschreibt unter Windows nie
            return
        except FileExistsError as ex:
            letzter = ex
            try:
                teil.unlink()                         # Rest eines früheren Versuchs
            except OSError:
                pass
        except PermissionError as ex:
            letzter = ex
            try:
                if teil.exists():
                    teil.unlink()
            except OSError:
                pass
        warte(ABLAGE_PAUSE * (versuch + 1))
    raise AblageFehler(ziel, "Zugriff verweigert – die Datei ist gesperrt (z. B. durch OneDrive-Synchronisierung, "
                             "Virenscanner oder ein geöffnetes Programm) oder der Ordner ist schreibgeschützt."
                       + (f" [{letzter}]" if letzter else ""))


def paket_erstellen(ordner: Path, schriftsatz: Eintrag | None, anlagen: list[Eintrag], bez: list[str],
                    word_zu_pdf: Callable[[Path, Path], None], gesamt_pdf: bool = False,
                    schriftsatz_name: str = "Schriftsatz.pdf", umbenennen_erlaubt: bool = False,
                    fortschritt: Callable[[str], None] = lambda t: None,
                    warte: Callable[[float], None] | None = None) -> Paket:
    """Paketi oluşturur. Bir dosya hedefe konamazsa bu çalıştırmada konan dosyalar geri alınır;
    önceden var olan dosyalara hiç dokunulmaz.

    - Hauptdokument (Schriftsatz) ist optional.
    - Nicht lesbare/umwandelbare Anlagen werden als Original (Name, Endung, Inhalt) übernommen.
    - Quelle selbst nicht lesbar → nicht kopiert, im Ergebnis (paket.hinweise) genannt.
    - Gebaut wird in einem lokalen Temp-Ordner (nicht im OneDrive-/Zielordner), abgelegt wird erst am Ende.
    """
    import tempfile
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    _schreibrecht(ordner)
    namen = geplante_namen(schriftsatz_name if schriftsatz else None, bez, gesamt_pdf, anlagen, schriftsatz)
    ziele = freie_namen(ordner, namen)
    vorhanden = [ordner / n for n, z in zip(namen, ziele) if z.name != n]
    if vorhanden and not umbenennen_erlaubt:
        raise Namenskonflikt(vorhanden, ziele)

    tmp = Path(tempfile.mkdtemp(prefix="bnx-paket-"))
    verschoben: list[Path] = []
    hinweise: list[str] = []
    dateien: list[Paketdatei] = []

    def tmp_name() -> Path:
        return tmp / f"{len(dateien):03d}.bin"

    def original(e: Eintrag, b: str, t: str) -> None:
        z = tmp_name()
        shutil.copyfile(e.quelle, z)
        dateien.append(Paketdatei("original", b, t, z, 0, ""))
        hinweise.append(f"{b}: {e.quelle.name} – {ORIGINAL_TEXT}; nicht im Gesamt-PDF.")

    try:
        if schriftsatz is not None:
            fortschritt("Hauptdokument wird in PDF umgewandelt …")
            if schriftsatz.fehler and lesbar(schriftsatz):
                original(schriftsatz, "Schriftsatz", schriftsatz.titel)
            elif schriftsatz.fehler:
                hinweise.append(f"Hauptdokument {schriftsatz.quelle.name} wurde NICHT kopiert: {schriftsatz.fehler}")
            else:
                s_tmp = tmp / "schriftsatz.pdf"
                try:
                    if schriftsatz.art == "word" and not schriftsatz.bearbeitet:
                        word_zu_pdf(schriftsatz.quelle, s_tmp)        # frisch aus Word → PDF/A bleibt erhalten
                    else:
                        s_tmp.write_bytes(schriftsatz.daten)
                    dateien.append(Paketdatei("schriftsatz", "Schriftsatz", schriftsatz.titel, s_tmp,
                                              _pruefen_und_zaehlen(s_tmp), ""))
                except Exception as ex:  # noqa: BLE001 – Umwandlung fehlgeschlagen → Original übernehmen
                    schriftsatz.fehler = f"Umwandlung fehlgeschlagen: {meldung(ex).splitlines()[0][:200]}"
                    s_tmp.unlink(missing_ok=True)
                    original(schriftsatz, "Schriftsatz", schriftsatz.titel)
        for i, (e, b) in enumerate(zip(anlagen, bez)):
            fortschritt(f"{b} wird geschrieben ({i + 1}/{len(anlagen)}) …")
            t_ = e.titel.strip() or e.quelle.stem
            if e.fehler and not lesbar(e):
                hinweise.append(f"{b} ({e.quelle.name}) wurde NICHT kopiert: {e.fehler}")
                dateien.append(Paketdatei("fehlt", b, t_, e.quelle, 0, ""))
                continue
            if e.fehler:
                original(e, b, t_)
                continue
            t = tmp_name().with_suffix(".pdf")
            try:
                if e.art == "word" and e.daten is None:
                    word_zu_pdf(e.quelle, t)
                else:                                        # auch Word-Anlagen: bereits umgewandelt (Vorschau)
                    with pymupdf.open("pdf", e.daten) as d:
                        d.save(t, garbage=4, deflate=True)
                dateien.append(Paketdatei("anlage", b, t_, t, _pruefen_und_zaehlen(t), ""))
            except Exception as ex:  # noqa: BLE001
                e.fehler = f"Umwandlung fehlgeschlagen: {meldung(ex).splitlines()[0][:200]}"
                t.unlink(missing_ok=True)
                original(e, b, t_)
        fortschritt("Anlagenverzeichnis wird erstellt …")
        v_tmp = tmp / VERZEICHNIS
        kopf = ([f"zum Schriftsatz: {schriftsatz.titel}"] if schriftsatz is not None else []) \
            + [f"Stand: {date.today():%d.%m.%Y}"]
        zeilen = []
        for d in dateien:
            if d.rolle == "anlage":
                zeilen.append([d.bezeichnung, d.titel, str(d.seiten)])
            elif d.rolle == "original" and d.bezeichnung != "Schriftsatz":
                zeilen.append([d.bezeichnung, f"{d.titel} (Originaldatei)", "–"])
            elif d.rolle == "fehlt":
                zeilen.append([d.bezeichnung, f"{d.titel} (nicht kopiert – Datei nicht lesbar)", "–"])
        docx_schreiben(v_tmp, "Anlagenverzeichnis", kopf, ["Anlage", "Bezeichnung", "Seiten"], zeilen,
                       [1700, 6000, 1100], rechts_spalten={2})
        dateien.append(Paketdatei("verzeichnis", "Anlagenverzeichnis", "Anlagenverzeichnis", v_tmp, 0, ""))
        if gesamt_pdf:
            fortschritt("Gesamt-PDF zur internen Prüfung …")
            g = pymupdf.open()
            toc = []
            for d in dateien:
                if d.rolle in ("schriftsatz", "anlage"):
                    toc.append([1, f"{d.bezeichnung} – {d.titel}" if d.rolle == "anlage" else "Schriftsatz",
                                g.page_count + 1])
                    with pymupdf.open(d.pfad) as q:
                        g.insert_pdf(q)
            if g.page_count:
                g.set_toc(toc)
                g_tmp = tmp / GESAMT
                g.save(g_tmp, garbage=4, deflate=True)
                dateien.append(Paketdatei("gesamt", "Gesamt-PDF", "zur internen Prüfung", g_tmp,
                                          _pruefen_und_zaehlen(g_tmp), ""))
            else:
                hinweise.append("Gesamt-PDF nicht erstellt: keine PDF-Dateien im Paket.")
        # Zielnamen neu bestimmen (Originale behalten ihren Namen) – nie überschreiben
        abzulegen = [d for d in dateien if d.rolle != "fehlt"]
        endnamen = []
        for d in abzulegen:
            if d.rolle == "schriftsatz":
                endnamen.append(schriftsatz_name)
            elif d.rolle == "anlage":
                endnamen.append(dateiname(d.bezeichnung))
            elif d.rolle == "original":
                q = schriftsatz if d.bezeichnung == "Schriftsatz" and schriftsatz is not None else \
                    next(e for e, b in zip(anlagen, bez) if b == d.bezeichnung)
                endnamen.append(q.quelle.name)
            else:
                endnamen.append(VERZEICHNIS if d.rolle == "verzeichnis" else GESAMT)
        if endnamen != namen:                      # erst beim Erstellen fehlgeschlagene Umwandlung
            ziele = freie_namen(ordner, endnamen)
            vorhanden = [ordner / n for n, z in zip(endnamen, ziele) if z.name != n]
            if vorhanden and not umbenennen_erlaubt:
                raise Namenskonflikt(vorhanden, ziele)
        fortschritt("Dateien werden im Zielordner abgelegt …")
        for d, ziel in zip(abzulegen, ziele):
            ablegen(d.pfad, ziel, warte)
            verschoben.append(ziel)
            d.pfad = ziel
            d.sha256 = hashlib.sha256(ziel.read_bytes()).hexdigest()
        return Paket(ordner, dateien, hinweise)
    except BaseException:
        for p in verschoben:                      # halbfertiges Paket wieder entfernen (nur eigene neue Dateien)
            try:
                p.unlink()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def mail_betreff(schriftsatz_titel: str, bez: list[str]) -> str:
    if not bez:
        return schriftsatz_titel
    spanne = bez[0] if len(bez) == 1 else f"{bez[0]} bis {bez[-1].split()[-1]}"
    return f"{schriftsatz_titel} nebst {spanne}"


def mail_text(dateien: list[Paketdatei]) -> str:
    from html import escape
    liste = "".join(f"<li>{escape(d.bezeichnung)}: {escape(d.titel)}</li>" if d.rolle in ("anlage", "original")
                    and d.bezeichnung != "Schriftsatz" else f"<li>{escape(d.pfad.name)}</li>"
                    for d in dateien if d.rolle != "fehlt")
    return ("<p>Sehr geehrte Damen und Herren,</p><p>anbei übersenden wir den Schriftsatz nebst "
            f"Anlagen:</p><ul>{liste}</ul><p>Mit freundlichen Grüßen</p>")
