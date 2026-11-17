"""PDF motoru (0.4): PyMuPDF + yerel Tesseract.

Belgeler, sayfa görüntüleri ve OCR metni bilgisayardan çıkmaz: Tesseract programın yanındaki
`ocr\\` klasöründen yerel süreç olarak çalışır, ağ kullanılmaz.
Bu modül yalnızca PDF editörü / Anlagen-Assistent açılınca içe aktarılır (açılışı yavaşlatmaz).

Koordinatlar: PyMuPDF metin/arama koordinatları sayfanın DÖNDÜRÜLMEMİŞ hâline göredir.
Ekranda göstermek için `rect * page.rotation_matrix` kullanılır.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from core.config import app_dir

SPRACHEN = ("deu", "tur", "eng")
SPRACH_NAMEN = {"deu": "Deutsch", "tur": "Türkisch", "eng": "Englisch"}
SCHRAEGLAGE_VERFUEGBAR = False          # Schräglagenkorrektur (Deskew) ist noch nicht umgesetzt
FONT_ORDNER = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
               Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
ERSATZ_SCHRIFT = "Arial"
AUSRICHTUNGEN = ("links", "zentriert", "rechts", "blocksatz")
# Bu alanlar OCR'dan sonra asla kendiliğinden düzeltilmez – kullanıcı onayı gerekir
SCHUTZ_MUSTER = [
    re.compile(r"^[A-Z]{2}\d{2}$|^\d{4}$|^\d{2}$"),          # IBAN parçaları (DE89 3704 …)
    re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}"),             # E-Mail
    re.compile(r"\d.*[/\-.].*\d|[A-Z]{2,}\d{3,}"),            # Aktenzeichen, Schaden-Nr., Datum
]


class PdfFehler(Exception):
    """Almanca mesajla kullanıcıya gösterilir."""


def sha256(pfad: Path) -> str:
    return hashlib.sha256(Path(pfad).read_bytes()).hexdigest()


# ---------------------------------------------------------------- Öffnen / Speichern
def oeffnen(pfad: Path | None = None, daten: bytes | None = None) -> pymupdf.Document:
    """PDF (veya görsel → PDF) açar; bozuk/şifreli dosyada anlaşılır Almanca hata verir."""
    name = Path(pfad).name if pfad else "Dokument"
    if daten is None and pfad and Path(pfad).suffix.lower() == ".pdf":
        daten = Path(pfad).read_bytes()
    if daten is not None and b"%PDF" not in daten[:1024]:
        anfang = daten[:40].decode("latin-1", "replace").strip()
        art = "HTML-Seite" if "<html" in anfang.lower() or "<!doctype" in anfang.lower() else "kein PDF"
        raise PdfFehler(f"{name}: Datei ist beschädigt oder kein PDF ({art}) und kann nicht geöffnet werden.")
    try:
        if daten is not None:
            doc = pymupdf.open("pdf", daten)
        elif Path(pfad).suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"):
            return bild_zu_pdf(Path(pfad))
        else:
            doc = pymupdf.open(pfad, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise PdfFehler(f"{name}: Datei ist beschädigt oder kein PDF und kann nicht geöffnet werden.") from e
    if doc.needs_pass:
        raise PdfFehler(f"{name}: Datei ist kennwortgeschützt.")
    try:                                   # z. B. falsche /Count-Angabe im Seitenbaum
        seiten = doc.page_count
    except Exception as e:  # noqa: BLE001
        raise PdfFehler(f"{name}: Datei ist beschädigt (Seitenverzeichnis fehlerhaft).") from e
    if seiten == 0:
        raise PdfFehler(f"{name}: Datei enthält keine Seiten (beschädigt?).")
    try:                                   # Seiteninhalte tatsächlich lesbar? (kaputte Streams)
        for p in doc:
            p.get_text("text")
        leer = doc.is_repaired and not any(p.get_text().strip() or p.get_images() or p.get_drawings() for p in doc)
    except Exception as e:  # noqa: BLE001
        raise PdfFehler(f"{name}: Seite {p.number + 1} ist beschädigt und kann nicht gelesen werden.") from e
    if leer:
        raise PdfFehler(f"{name}: Datei ist beschädigt (repariert, aber ohne lesbaren Inhalt).")
    return doc


def sicher_speichern(doc: pymupdf.Document, ziel: Path) -> Path:
    """Önce geçici dosyaya yazar, yeniden açıp kontrol eder, sonra yerine koyar.

    Kayıt yarıda kalırsa mevcut dosya bozulmaz. Artımlı kayıt yok: eski sürümler dosyada kalmaz.
    """
    ziel = Path(ziel)
    tmp = ziel.with_name(ziel.stem + ".bnx-tmp.pdf")
    try:
        doc.subset_fonts()            # eklenen yazı tiplerinden yalnızca kullanılan karakterler kalır
    except Exception:  # noqa: BLE001 – alt küme oluşturulamazsa tam yazı tipiyle kaydet
        pass
    try:
        doc.save(tmp, garbage=4, deflate=True, clean=True, incremental=False)
        with pymupdf.open(tmp) as probe:
            if probe.page_count != doc.page_count:
                raise PdfFehler("Die gespeicherte Datei ist unvollständig.")
        os.replace(tmp, ziel)
    finally:
        if tmp.exists():
            tmp.unlink()
    return ziel


# ---------------------------------------------------------------- Seiten
def seiten_drehen(doc, nummern: list[int], grad: int) -> None:
    for n in nummern:
        doc[n].set_rotation((doc[n].rotation + grad) % 360)


def seiten_loeschen(doc, nummern: list[int]) -> None:
    if len(set(nummern)) >= doc.page_count:
        raise PdfFehler("Es muss mindestens eine Seite übrig bleiben.")
    doc.delete_pages(sorted(set(nummern)))


def seite_duplizieren(doc, nummer: int) -> None:
    doc.fullcopy_page(nummer, nummer + 1)


def seite_verschieben(doc, von: int, nach: int) -> None:
    """Seite `von` so verschieben, dass sie danach an Position `nach` steht."""
    if von == nach:
        return
    ziel = nach + 1 if nach > von else nach          # move_page: "vor dieser Seite einfügen"
    doc.move_page(von, -1 if ziel >= doc.page_count else ziel)


def reihenfolge_setzen(doc, neu: list[int]) -> None:
    doc.select(neu)


def seite_zuschneiden(page, rect: pymupdf.Rect) -> None:
    r = pymupdf.Rect(rect) & page.mediabox
    if r.is_empty or r.width < 20 or r.height < 20:
        raise PdfFehler("Zuschnittbereich ist zu klein.")
    page.set_cropbox(r)


def seiten_extrahieren(doc, nummern: list[int]) -> pymupdf.Document:
    neu = pymupdf.open()
    for n in sorted(nummern):
        neu.insert_pdf(doc, from_page=n, to_page=n)
    return neu


def pdf_einfuegen(doc, quelle: pymupdf.Document, nach: int) -> int:
    """Fügt alle Seiten von `quelle` nach Seite `nach` (-1 = am Anfang) ein; gibt Seitenzahl zurück."""
    doc.insert_pdf(quelle, start_at=nach + 1)
    return quelle.page_count


def aufteilen(doc, starts: list[int]) -> list[pymupdf.Document]:
    """Teilt an den angegebenen Startseiten (0-basiert) in mehrere Dokumente."""
    grenzen = sorted({0, *[s for s in starts if 0 < s < doc.page_count]}) + [doc.page_count]
    teile = []
    for a, b in zip(grenzen, grenzen[1:]):
        t = pymupdf.open()
        t.insert_pdf(doc, from_page=a, to_page=b - 1)
        teile.append(t)
    return teile


def bild_zu_pdf(pfad: Path) -> pymupdf.Document:
    """Foto/Scan als A4-Seite (Hoch- oder Querformat), proportional eingepasst."""
    try:
        bild = pymupdf.open(pfad)
        w, h = bild[0].rect.width, bild[0].rect.height
        bild.close()
    except Exception as e:  # noqa: BLE001
        raise PdfFehler(f"{Path(pfad).name}: Bild ist beschädigt und kann nicht geöffnet werden.") from e
    doc = pymupdf.open()
    breit, hoch = (842, 595) if w > h else (595, 842)
    page = doc.new_page(width=breit, height=hoch)
    page.insert_image(pymupdf.Rect(28, 28, breit - 28, hoch - 28), filename=str(pfad), keep_proportion=True)
    return doc


def ist_gescannt(page) -> bool:
    """Seite ohne Text, die überwiegend aus einem Bild besteht."""
    if page.get_text("text").strip():
        return False
    flaeche = page.rect.width * page.rect.height
    return any(pymupdf.Rect(i["bbox"]).get_area() > 0.5 * flaeche for i in page.get_image_info())


def seitenbild(page, breite: int = 160, gray: bool = False) -> pymupdf.Pixmap:
    zoom = breite / max(page.rect.width, 1)
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False,
                           colorspace=pymupdf.csGRAY if gray else pymupdf.csRGB)


# ---------------------------------------------------------------- Ähnlichkeit
def bildhash(page) -> int:
    """Durchschnitts-Hash 16×16 (256 Bit) des Seitenbilds – erkennt optisch gleiche Seiten."""
    pix = seitenbild(page, 128, gray=True)
    w, h, s = pix.width, pix.height, pix.samples
    werte = []
    for gy in range(16):
        for gx in range(16):
            x0, x1 = gx * w // 16, max(gx * w // 16 + 1, (gx + 1) * w // 16)
            y0, y1 = gy * h // 16, max(gy * h // 16 + 1, (gy + 1) * h // 16)
            summe = sum(s[y * w + x] for y in range(y0, y1) for x in range(x0, x1))
            werte.append(summe / ((x1 - x0) * (y1 - y0)))
    mittel = sum(werte) / len(werte)
    return sum(1 << i for i, v in enumerate(werte) if v < mittel)


def hash_abstand(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ---------------------------------------------------------------- Schriften
_systemschriften: dict[str, Path] | None = None


def systemschrift(name: str) -> Path | None:
    """Windows'ta aynı adlı yazı tipi dosyası (alt küme önekiyle: 'BCDEEE+Calibri' → Calibri)."""
    global _systemschriften
    if _systemschriften is None:
        _systemschriften = {}
        for ordner in FONT_ORDNER:
            for f in sorted(ordner.glob("*.tt[fc]")) + sorted(ordner.glob("*.otf")):
                try:
                    _systemschriften.setdefault(pymupdf.Font(fontfile=str(f)).name.lower(), f)
                except Exception:  # noqa: BLE001 – bozuk/okunamayan yazı tipi
                    pass
    basis = name.split("+")[-1].replace(",", " ").replace("-", " ").lower().strip()
    if basis.endswith("mt"):                               # ArialMT, TimesNewRomanPSMT
        basis = basis[:-2].removesuffix("ps").strip()
    for kandidat in (basis, basis + " regular", basis.replace(" ", ""), basis.replace(" ", "") + " regular"):
        if kandidat in _systemschriften:
            return _systemschriften[kandidat]
    kompakt = {k.replace(" ", ""): v for k, v in _systemschriften.items()}
    return kompakt.get(basis.replace(" ", "")) or kompakt.get(basis.replace(" ", "") + "regular")


@dataclass
class Schriftwahl:
    font: pymupdf.Font
    puffer: bytes
    quelle: str                       # "eingebettet" | "Windows" | "Ersatz"
    name: str
    fehlende: str = ""


def schrift_waehlen(doc: pymupdf.Document, xref: int, name: str, text: str) -> Schriftwahl:
    """Yeni metin için yazı tipi: belgedeki gömülü yazı tipi → Windows'taki aynı yazı tipi → Arial."""
    noetig = {c for c in text if not c.isspace()}
    fehlt = "?"
    if xref:
        try:
            puffer = doc.extract_font(xref)[3]
            if puffer:
                f = pymupdf.Font(fontbuffer=puffer)
                fehlt = "".join(sorted(c for c in noetig if not f.has_glyph(ord(c))))
                if not fehlt:
                    return Schriftwahl(f, puffer, "eingebettet", name)
        except Exception:  # noqa: BLE001
            fehlt = "?"
    datei = systemschrift(name)
    if datei:
        puffer = datei.read_bytes()
        return Schriftwahl(pymupdf.Font(fontbuffer=puffer), puffer, "Windows", name, fehlt)
    f = schrift_laden()
    return Schriftwahl(f, f.buffer, "Ersatz", f.name, fehlt)


def schrift_laden(name: str | None = None) -> pymupdf.Font:
    """Windows-Schrift `name` → Arial → in PyMuPDF eingebaute Helvetica (enthält ä ö ü ß ç ğ ı ş İ €).
    So funktioniert das Programm auch, wenn eine Windows-Schrift fehlt."""
    for n in ([name] if name else []) + [ERSATZ_SCHRIFT]:
        datei = systemschrift(n)
        if datei:
            return pymupdf.Font(fontfile=str(datei))
    return pymupdf.Font("helv")


def _rgb(farbe: int) -> tuple[float, float, float]:
    return ((farbe >> 16) & 255) / 255, ((farbe >> 8) & 255) / 255, (farbe & 255) / 255


def _umbrechen(text: str, font: pymupdf.Font, fs: float, breite: float) -> list[str]:
    zeilen = []
    for absatz in text.split("\n"):
        akt = ""
        for wort in absatz.split():
            probe = (akt + " " + wort).strip()
            if font.text_length(probe, fontsize=fs) <= breite + 0.5 or not akt:
                akt = probe
            else:
                zeilen.append(akt)
                akt = wort
        zeilen.append(akt)
    return zeilen


def _zeile_schreiben(tw: pymupdf.TextWriter, x: float, y: float, text: str, font: pymupdf.Font, fs: float,
                     ausrichtung: str = "links", breite: float = 0, letzte: bool = True) -> None:
    """Kelimeleri tek tek yerleştirir: bazı yazı tiplerinde (Arial) boşluk glifi metin çıkarmada
    bölünmez boşluk (U+00A0) olarak geri geliyordu ve arama bozuluyordu."""
    worte = [w for w in text.split(" ") if w]
    if not worte:
        return
    bosluk = font.text_length(" ", fontsize=fs)
    laengen = [font.text_length(w, fontsize=fs) for w in worte]
    gesamt = sum(laengen) + bosluk * (len(worte) - 1)
    if ausrichtung == "rechts":
        x += breite - gesamt
    elif ausrichtung == "zentriert":
        x += (breite - gesamt) / 2
    elif ausrichtung == "blocksatz" and not letzte and len(worte) > 1:
        bosluk = (breite - sum(laengen)) / (len(worte) - 1)
    for w, lg in zip(worte, laengen):
        tw.append((x, y), w, font=font, fontsize=fs)
        x += lg + bosluk


# ---------------------------------------------------------------- Textbearbeitung (digital)
@dataclass
class Aenderung:
    warnungen: list[str] = field(default_factory=list)
    schrift: str = ""
    rect: pymupdf.Rect | None = None


@dataclass
class Blockformat:
    text: str
    schrift: str
    groesse: float
    farbe: tuple[float, float, float]
    ausrichtung: str
    gemischt: bool
    rect: pymupdf.Rect


def _blocktext(b: dict) -> str:
    return " ".join("".join(s["text"] for s in ln["spans"]).strip() for ln in b["lines"]).strip()


def textbloecke(page) -> list[dict]:
    return [b for b in page.get_text("dict")["blocks"] if b["type"] == 0 and _blocktext(b)]


def block_an(page, punkt) -> dict | None:
    p = pymupdf.Point(punkt)
    for b in textbloecke(page):
        if (pymupdf.Rect(b["bbox"]) + (-2, -2, 2, 2)).contains(p):
            return b
    return None


def block_format(b: dict) -> Blockformat:
    spans = [s for ln in b["lines"] for s in ln["spans"] if s["text"].strip()]
    haupt = max(spans, key=lambda s: len(s["text"]))
    gemischt = len({(s["font"], round(s["size"], 1), s["color"]) for s in spans}) > 1
    ausrichtung = "links"
    if len(b["lines"]) > 1:
        lx = [ln["bbox"][0] for ln in b["lines"]]
        rx = [ln["bbox"][2] for ln in b["lines"]]
        mx = [(ln["bbox"][0] + ln["bbox"][2]) / 2 for ln in b["lines"]]
        if max(lx) - min(lx) > 3 and max(mx) - min(mx) < 2:
            ausrichtung = "zentriert"
        elif max(lx) - min(lx) > 3 and max(rx) - min(rx) < 2:
            ausrichtung = "rechts"
        elif max(rx[:-1]) - min(rx[:-1]) < 1.5 and len(b["lines"]) > 2:
            ausrichtung = "blocksatz"
    return Blockformat(_blocktext(b), haupt["font"].split("+")[-1], round(haupt["size"], 1),
                       _rgb(haupt["color"]), ausrichtung, gemischt, pymupdf.Rect(b["bbox"]))


def _block_entfernen(page, b: dict) -> None:
    """Zeichen des Blocks wirklich löschen (Zeilen leicht verkleinert → Nachbarzeilen bleiben)."""
    for ln in b["lines"]:
        r = pymupdf.Rect(ln["bbox"])
        h = r.height * 0.2
        page.add_redact_annot(pymupdf.Rect(r.x0, r.y0 + h, r.x1, r.y1 - h), fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)


def block_ersetzen(page, b: dict, neuer_text: str, groesse: float | None = None,
                   farbe: tuple | None = None, ausrichtung: str | None = None) -> Aenderung:
    """Paragrafı (blok) gerçekten siler ve yeni metinle aynı yere yeniden dizer.

    Beyaz kutu kullanılmaz: eski karakterler içerik akışından kaldırılır (görsel/çizgi korunur).
    `neuer_text` boşsa paragraf yalnızca silinir.
    """
    doc = page.parent
    fmt = block_format(b)
    ergebnis = Aenderung(rect=pymupdf.Rect(b["bbox"]))
    bloecke = textbloecke(page)
    if not neuer_text.strip():
        _block_entfernen(page, b)
        ergebnis.schrift = "–"
        return ergebnis
    fs = groesse or fmt.groesse
    farbe = farbe or fmt.farbe
    ausrichtung = ausrichtung or fmt.ausrichtung
    if fmt.gemischt:
        ergebnis.warnungen.append(f"Absatz enthält mehrere Formatierungen – wird vereinfacht auf "
                                  f"{fmt.schrift} {fs:.1f} pt")
    spans = [s for ln in b["lines"] for s in ln["spans"] if s["text"].strip()]
    haupt_font = max(spans, key=lambda s: len(s["text"]))["font"]
    font_xref = next((f[0] for f in page.get_fonts() if f[3].split("+")[-1] == haupt_font.split("+")[-1]), 0)
    wahl = schrift_waehlen(doc, font_xref, haupt_font, neuer_text)
    ergebnis.schrift = f"{wahl.name.split('+')[-1]} ({wahl.quelle})"
    if wahl.quelle == "Windows":
        ergebnis.warnungen.append(
            (f"Eingebettete Teilschrift ohne Zeichen „{wahl.fehlende}“" if wahl.fehlende != "?"
             else "Eingebettete Schrift nicht verwendbar") + " – gleiche Schrift aus Windows ergänzt")
    elif wahl.quelle == "Ersatz":
        ergebnis.warnungen.append(f"Schrift {fmt.schrift} nicht verfügbar – ersetzt durch {ERSATZ_SCHRIFT}")

    basislinien = [ln["spans"][0]["origin"][1] for ln in b["lines"]]
    abstand = ((basislinien[-1] - basislinien[0]) / (len(basislinien) - 1)
               if len(basislinien) > 1 else fmt.groesse * 1.2) * fs / fmt.groesse
    links = b["bbox"][0]
    rechts = b["bbox"][2] if len(b["lines"]) > 1 else max(b["bbox"][2], page.rect.width - 56)
    breite = rechts - links

    _block_entfernen(page, b)
    zeilen = _umbrechen(neuer_text, wahl.font, fs, breite)
    tw = pymupdf.TextWriter(page.rect, color=farbe)
    y = basislinien[0] + (fs - fmt.groesse) * 0.8
    for i, z in enumerate(zeilen):
        _zeile_schreiben(tw, links, y, z, wahl.font, fs, ausrichtung, breite, letzte=i == len(zeilen) - 1)
        y += abstand
    unten = y - abstand + fs * 0.3
    naechster = min((o["bbox"][1] for o in bloecke if o is not b and o["bbox"][1] > b["bbox"][3] - 1
                     and o["bbox"][0] < rechts and o["bbox"][2] > links), default=page.rect.height)
    if len(zeilen) > len(b["lines"]):
        ergebnis.warnungen.append(f"Absatz wird länger ({len(b['lines'])} → {len(zeilen)} Zeilen)")
    if unten > naechster:
        ergebnis.warnungen.append("Text passt nicht: läuft in den folgenden Absatz – bitte kürzen")
    if unten > page.rect.height - 20:
        ergebnis.warnungen.append("Text passt nicht: läuft über den unteren Seitenrand")
    if any(wahl.font.text_length(z, fontsize=fs) > breite + 1 for z in zeilen):
        ergebnis.warnungen.append("Ein Wort ist breiter als die Zeile")
    tw.write_text(page)
    return ergebnis


def text_ersetzen(page, alt: str, neu: str) -> Aenderung:
    """Bir cümleyi/kelimeyi içeren paragrafı bulur ve değiştirir (paragraf yeniden dizilir)."""
    for b in textbloecke(page):
        t = _blocktext(b)
        if alt in t:
            return block_ersetzen(page, b, t.replace(alt, neu))
    raise PdfFehler(f"Text nicht gefunden: „{alt}“")


def text_einfuegen(page, punkt, text: str, groesse: float = 11, farbe=(0, 0, 0),
                   schrift: str = ERSATZ_SCHRIFT, ausrichtung: str = "links") -> Aenderung:
    """Neuen Text ab `punkt` (linke obere Ecke) einfügen; Umbruch bis zum rechten Rand."""
    font = schrift_laden(schrift)
    x, y0 = punkt
    breite = page.rect.width - 56 - x
    if breite < 40:
        raise PdfFehler("Zu nah am rechten Rand.")
    zeilen = _umbrechen(text, font, groesse, breite)
    tw = pymupdf.TextWriter(page.rect, color=farbe)
    y = y0 + groesse
    for i, z in enumerate(zeilen):
        _zeile_schreiben(tw, x, y, z, font, groesse, ausrichtung, breite, letzte=i == len(zeilen) - 1)
        y += groesse * 1.2
    bereich = pymupdf.Rect(x, y0, x + breite, y - groesse * 0.9)
    erg = Aenderung(rect=bereich, schrift=f"{font.name} {groesse:.1f} pt")
    if any(pymupdf.Rect(b["bbox"]).intersects(bereich) for b in textbloecke(page)):
        erg.warnungen.append("Neuer Text überlappt vorhandenen Text")
    if bereich.y1 > page.rect.height - 20:
        erg.warnungen.append("Text passt nicht: läuft über den unteren Seitenrand")
    tw.write_text(page)
    return erg


# ---------------------------------------------------------------- OCR (Tesseract, lokal)
def tesseract_ordner() -> Path | None:
    for d in (os.environ.get("BNX_TESSERACT"), app_dir() / "ocr"):
        if d and (Path(d) / "tesseract.exe").exists():
            return Path(d)
    return None


def _tesseract(png: bytes, *args: str, timeout: int = 180) -> str:
    ordner = tesseract_ordner()
    if not ordner:
        raise PdfFehler("OCR-Komponente (Tesseract) nicht gefunden – Ordner „ocr“ neben BnX-Raptor.exe fehlt.")
    # Tesseract scheitert an Pfaden mit Umlauten (z. B. „C:\Users\Müller\…“, „Masaüstü“): „Cannot convert
    # character sequence“. Deshalb: Bild über stdin (keine Temp-Datei), Arbeitsordner = ocr\, Sprachdaten
    # über den relativen, reinen ASCII-Pfad „tessdata“.
    # OMP_THREAD_LIMIT=1: Tesseract 5.5.4 (MSYS2) nutzt OpenMP; BnX startet je Sprache einen eigenen Prozess
    # parallel – ohne Begrenzung überbuchen sich die Threads (gemessen 2–3× langsamer).
    env = dict(os.environ, TESSDATA_PREFIX="tessdata", OMP_THREAD_LIMIT="1")
    r = subprocess.run([str(ordner / "tesseract.exe"), "stdin", "stdout", *args],
                       input=png, capture_output=True, env=env, cwd=str(ordner), timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        raise PdfFehler("OCR fehlgeschlagen: " + r.stderr.decode("utf-8", "replace")[-300:])
    return r.stdout.decode("utf-8", "replace")


@dataclass
class OcrWort:
    text: str
    conf: float                       # 0–100 (Tesseract)
    rect: pymupdf.Rect                # Seitenkoordinaten (pt, ungedreht)
    zeile: tuple[int, int, int]       # block, absatz, zeile
    geschuetzt: bool = False          # Aktenzeichen/E-Mail/IBAN → nie automatisch korrigieren


def ocr_tsv(png: bytes, dpi: int, sprachen: str = "+".join(SPRACHEN)) -> list[tuple]:
    """Tesseract-TSV: (text, conf, left, top, width, height, block, par, line) in Pixeln."""
    roh = _tesseract(png, "-l", sprachen, "--dpi", str(dpi), "--psm", "3", "tsv")
    out = []
    for z in roh.splitlines()[1:]:
        f = z.split("\t")
        if len(f) == 12 and f[0] == "5" and f[11].strip():
            out.append((f[11], float(f[10]), *map(int, f[6:10]), *map(int, f[2:5])))
    return out


def ocr_erkennen(png: bytes, dpi: int, sprachen: tuple[str, ...] = SPRACHEN, vorsprung: float = 3.0) -> list[tuple]:
    """Her dili ayrı çalıştırır, her satır için ortalama güveni en yüksek sonucu alır.

    Ortak 'deu+tur+eng' modeli Almanca 'ü'yü 'ii' okuyordu; satır bazında seçim bunu çözüyor.
    İlk dil önceliklidir: diğer dil ancak `vorsprung` puan daha güvenliyse seçilir.
    Sadece alt süreç çalıştırır → iş parçacığında güvenle çağrılabilir.
    """
    if len(sprachen) == 1:
        return ocr_tsv(png, dpi, sprachen[0])
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(len(sprachen)) as ex:
        laeufe = list(ex.map(lambda s: ocr_tsv(png, dpi, s), sprachen))
    zeilen = []
    for lauf in laeufe:
        z: dict[tuple, list] = {}
        for w in lauf:
            z.setdefault(w[6:9], []).append(w)
        zeilen.append(z)
    if any(z.keys() != zeilen[0].keys() for z in zeilen):
        return ocr_tsv(png, dpi, "+".join(sprachen))        # Layout weicht ab → kombiniertes Modell
    out = []
    for key in zeilen[0]:
        def mittel(i):
            return sum(w[1] for w in zeilen[i][key]) / len(zeilen[i][key])
        wahl = 0
        for i in range(1, len(sprachen)):
            if mittel(i) > mittel(wahl) + (vorsprung if wahl == 0 else 0):
                wahl = i
        out += zeilen[wahl][key]
    return out


def ocr_bild(page, dpi: int = 300) -> tuple[bytes, pymupdf.Matrix]:
    """Seitenbild für OCR (Hauptthread) + Matrix Pixel → Seitenkoordinaten."""
    zoom = pymupdf.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=zoom, colorspace=pymupdf.csGRAY, alpha=False)
    return pix.tobytes("png"), ~zoom * page.derotation_matrix


def worte_bilden(tsv: list[tuple], rueck: pymupdf.Matrix) -> list[OcrWort]:
    worte = [OcrWort(t, c, pymupdf.Rect(x, y, x + w, y + h) * rueck, (b, p, ln))
             for t, c, x, y, w, h, b, p, ln in tsv]
    # Schutz: Wort selbst oder ganze Zeile mit IBAN/Zeichen/Nr./E-Mail
    zeilen: dict[tuple, list[OcrWort]] = {}
    for w in worte:
        zeilen.setdefault(w.zeile, []).append(w)
    for zw in zeilen.values():
        zeile = " ".join(w.text for w in zw)
        heikel = bool(re.search(r"IBAN|BIC|Zeichen|Az\.|-Nr|Nr\.|E-Mail|@", zeile))
        for w in zw:
            w.geschuetzt = any(m.search(w.text) for m in SCHUTZ_MUSTER[1:]) or (
                heikel and bool(re.search(r"\d|@", w.text)))
    return worte


def ocr_seite(page, dpi: int = 300, sprachen: tuple[str, ...] = SPRACHEN) -> list[OcrWort]:
    png, rueck = ocr_bild(page, dpi)
    return worte_bilden(ocr_erkennen(png, dpi, sprachen), rueck)


def ausrichtung_aus_png(png: bytes) -> tuple[int, float]:
    """Tesseract OSD: (im Uhrzeigersinn zu drehende Grad, Sicherheit). Zu wenig Text → (0, 0)."""
    try:
        roh = _tesseract(png, "--psm", "0", "-l", "osd")
    except PdfFehler:
        return 0, 0.0
    m1 = re.search(r"Rotate: (\d+)", roh)
    m2 = re.search(r"Orientation confidence: ([\d.]+)", roh)
    return (int(m1.group(1)), float(m2.group(1))) if m1 and m2 else (0, 0.0)


def ausrichtung_png(page) -> bytes:
    return page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY, alpha=False).tobytes("png")


def ausrichtung(page) -> tuple[int, float]:
    return ausrichtung_aus_png(ausrichtung_png(page))


def textebene_einfuegen(page, worte: list[OcrWort]) -> int:
    """Unsichtbare, durchsuchbare Textebene (render_mode 3) wortgenau über das Scanbild legen."""
    font = schrift_laden()
    tw = pymupdf.TextWriter(page.rect)
    for w in worte:
        laenge = font.text_length(w.text, fontsize=1)
        if not laenge:
            continue
        fs = w.rect.width / laenge
        tw.append((w.rect.x0, w.rect.y1 - abs(font.descender) * fs * 0.6), w.text, font=font, fontsize=fs)
    tw.write_text(page, render_mode=3)
    return len(worte)


def wort_an(page, punkt) -> tuple[str, pymupdf.Rect] | None:
    p = pymupdf.Point(punkt)
    for w in page.get_text("words"):
        r = pymupdf.Rect(w[:4])
        if (r + (-1, -1, 1, 1)).contains(p):
            return w[4], r
    return None


# ---------------------------------------------------------------- Scan: Wort korrigieren
def _bild_auf_seite(page, rect: pymupdf.Rect) -> tuple[int, pymupdf.Matrix]:
    for info in page.get_image_info(xrefs=True):
        if info["xref"] and pymupdf.Rect(info["bbox"]).contains(rect):
            return info["xref"], pymupdf.Matrix(info["transform"])
    raise PdfFehler("Kein Scanbild an dieser Stelle.")


def _pixelrechteck(pix: pymupdf.Pixmap, rect: pymupdf.Rect, trafo: pymupdf.Matrix, rand: int) -> pymupdf.IRect:
    inv = ~trafo
    ecken = [pymupdf.Point(p) * inv for p in (rect.tl, rect.br, rect.tr, rect.bl)]
    xs = [e.x * pix.width for e in ecken]
    ys = [e.y * pix.height for e in ecken]
    return pymupdf.IRect(int(min(xs)) - rand, int(min(ys)) - rand,
                         int(max(xs)) + 1 + rand, int(max(ys)) + 1 + rand) & pymupdf.IRect(0, 0, pix.width, pix.height)


def _median(werte: list[int]) -> int:
    werte = sorted(werte)
    return werte[len(werte) // 2] if werte else 255


def scan_wort_ersetzen(page, alt: str, neu: str, rect: pymupdf.Rect | None = None,
                       schrift: str = "Times New Roman") -> Aenderung:
    """Taranmış sayfada kelimeyi düzeltir: pikseller görüntüden silinir (arka plan rengiyle),
    eski OCR kelimesi metin katmanından kaldırılır, yeni kelime görünür ve aranabilir metin olarak yazılır."""
    doc = page.parent
    if rect is None:
        treffer = [pymupdf.Rect(w[:4]) for w in page.get_text("words") if w[4].strip(".,;:") == alt]
        if not treffer:
            raise PdfFehler(f"Wort nicht in der Textebene gefunden: „{alt}“ (zuerst OCR ausführen)")
        rect = treffer[0]
    rect = pymupdf.Rect(rect)
    xref, trafo = _bild_auf_seite(page, rect)
    pix = pymupdf.Pixmap(doc, xref)
    if pix.alpha or pix.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB if pix.n >= 3 else pymupdf.csGRAY, pix, 0)
    innen = _pixelrechteck(pix, rect, trafo, 2)
    aussen = _pixelrechteck(pix, rect, trafo, 8)
    n = pix.n
    hinter = [[] for _ in range(n)]
    dunkel = []
    for yy in range(aussen.y0, aussen.y1):
        for xx in range(aussen.x0, aussen.x1):
            px = pix.pixel(xx, yy)
            if innen.contains(pymupdf.Point(xx, yy)):
                dunkel.append(px)
            else:
                for i in range(n):
                    hinter[i].append(px[i])
    hg = tuple(_median(h) for h in hinter)
    # Grundlinie aus den Pixeln: letzte Zeile mit kräftiger Schwärzung (Unterlängen wie 'g' sind schwächer)
    grenze = (sum(hg) / n) * 0.6
    zeilen_schwarz: dict[int, int] = {}
    for yy in range(innen.y0, innen.y1):
        zeilen_schwarz[yy] = sum(1 for xx in range(innen.x0, innen.x1) if sum(pix.pixel(xx, yy)) / n < grenze)
    spitze = max(zeilen_schwarz.values() or [0])
    basis_px = max((y for y, c in zeilen_schwarz.items() if c >= spitze * 0.3), default=innen.y1)
    mitte_x = (innen.x0 + innen.x1) / 2
    basis_pt = (pymupdf.Point(mitte_x / pix.width, (basis_px + 1) / pix.height) * trafo).y
    dunkel.sort(key=sum)
    schrift_px = dunkel[: max(1, len(dunkel) // 15)]
    farbe = tuple(_median([p[i] for p in schrift_px]) / 255 for i in range(n))
    farbe = farbe * 3 if n == 1 else farbe
    pix.set_rect(innen, hg)
    if "DCTDecode" in doc.xref_get_key(xref, "Filter")[1]:   # Scan war JPEG → wieder JPEG (sonst ~3× größer)
        page.replace_image(xref, stream=pix.tobytes("jpeg", jpg_quality=90))
    else:
        page.replace_image(xref, pixmap=pix)

    # alte Wörter der OCR-Ebene an dieser Stelle entfernen (Bild bleibt wie eben ersetzt)
    page.add_redact_annot(rect, fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    font = schrift_laden(schrift)
    fs = rect.width / max(font.text_length(alt, fontsize=1), 0.1)
    tw = pymupdf.TextWriter(page.rect, color=farbe)
    tw.append((rect.x0, basis_pt), neu, font=font, fontsize=fs)
    tw.write_text(page)
    erg = Aenderung(rect=rect, schrift=f"{font.name} {fs:.1f} pt")
    if font.text_length(neu, fontsize=fs) > rect.width * 1.15:
        erg.warnungen.append("Neues Wort ist deutlich breiter als das alte – Überlappung prüfen")
    return erg


# ---------------------------------------------------------------- Schwärzen
@dataclass
class Schwaerzung:
    seite: int
    rect: tuple[float, float, float, float]
    text: str                          # was vorher darunter stand (für die Prüfung nach dem Speichern)


def schwaerzen(page, rect: pymupdf.Rect) -> Schwaerzung:
    """Kalıcı karartma: metin + OCR katmanı + görsel pikselleri + üstteki çizimler silinir."""
    doc = page.parent
    rect = pymupdf.Rect(rect)
    vorher = " ".join(w[4] for w in page.get_text("words", clip=rect))
    jpeg_vorher = any("DCTDecode" in doc.xref_get_key(i[0], "Filter")[1] for i in page.get_images())
    page.add_redact_annot(rect, fill=(0, 0, 0))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    if jpeg_vorher:                    # MuPDF speichert das geschwärzte Bild verlustfrei → wieder JPEG
        for info in page.get_images():
            if "DCTDecode" not in doc.xref_get_key(info[0], "Filter")[1] and info[2] * info[3] > 250_000:
                pix = pymupdf.Pixmap(doc, info[0])
                if not pix.alpha:
                    page.replace_image(info[0], stream=pix.tobytes("jpeg", jpg_quality=90))
    return Schwaerzung(page.number, tuple(rect), vorher)


def nach_schwaerzung_bereinigen(doc) -> list[str]:
    """Gömülü dosyalar, dosya ekleri, meta veriler, küçük resimler ve JavaScript karartılmış içeriği
    taşıyabilir → kaydetmeden önce kaldırılır. OCR katmanı (gizli metin) korunur."""
    entfernt = []
    if doc.embfile_count():
        entfernt.append(f"{doc.embfile_count()} eingebettete Datei(en)")
    anhaenge = sum(1 for p in doc for a in (p.annots() or []) if a.type[0] == pymupdf.PDF_ANNOT_FILE_ATTACHMENT)
    if anhaenge:
        entfernt.append(f"{anhaenge} Dateianhang/-anhänge in Kommentaren")
    if any(v for v in (doc.metadata or {}).values()):
        entfernt.append("Dokumenteigenschaften (Metadaten)")
    doc.scrub(attached_files=True, clean_pages=True, embedded_files=True, hidden_text=False,
              javascript=True, metadata=True, redactions=True, remove_links=False, reset_fields=False,
              reset_responses=False, thumbnails=True, xml_metadata=True)
    return entfernt


def _rohmuster(text: str) -> list[str]:
    worte = [w.strip(".,;:()") for w in text.split() if w.strip(".,;:()")]
    muster = [" ".join(worte)] if len(" ".join(worte)) >= 6 else []
    muster += [f"{a} {b}" for a, b in zip(worte, worte[1:])]
    muster += [w for w in worte if len(w) >= 3 and not (re.fullmatch(r"[0-9A-Fa-f]+", w) and len(w) < 8)]
    return list(dict.fromkeys(muster))


def schwaerzung_pruefen(pfad: Path, schwaerzungen: list[Schwaerzung], ocr: bool = True) -> dict:
    """Gespeicherte Datei neu öffnen und prüfen, ob geschwärzte Inhalte wiederherstellbar sind:
    Text, OCR-Ebene, herausgezogene Bilder, eingebettete Dateien und Rohdaten."""
    roh_datei = Path(pfad).read_bytes()
    d = pymupdf.open(pfad)
    roh = roh_datei + b"".join(d.xref_stream(x) or b"" for x in range(1, d.xref_length()) if d.xref_is_stream(x))
    ganztext = " ".join(" ".join(p.get_text().split()) for p in d)
    erg: dict = {"text": [], "ocr_ebene": [], "bilder": [], "eingebettet": [], "rohdaten": [], "bild_ocr": []}
    for s in schwaerzungen:
        page = d[s.seite]
        rect = pymupdf.Rect(s.rect)
        geheim = [w.strip(".,;:()") for w in s.text.split() if len(w.strip(".,;:()")) >= 3]
        # a) sichtbarer Text + b) OCR-Ebene: beide sind Text der Seite; im Feld darf nichts mehr stehen
        im_feld = [w[4] for w in page.get_text("words", clip=rect)]
        erg["ocr_ebene"] += im_feld
        satz = " ".join(s.text.split())
        if len(satz) >= 4 and satz in ganztext:
            erg["text"].append(satz)
        erg["text"] += [g for g in geheim if page.search_for(g) and
                        any(r.intersects(rect) for r in page.search_for(g))]
        # c) Bilder im Feld: herausziehen, Pixel im Feld müssen einfarbig sein, OCR darf nichts finden
        for info in page.get_image_info(xrefs=True):
            if not info["xref"] or not pymupdf.Rect(info["bbox"]).intersects(rect):
                continue
            pix = pymupdf.Pixmap(d, info["xref"])
            if pix.alpha or pix.n not in (1, 3):
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix, 0)
            ir = _pixelrechteck(pix, rect & pymupdf.Rect(info["bbox"]), pymupdf.Matrix(info["transform"]), -3)
            if ir.is_empty:
                continue
            kanal = [pix.pixel(x, y)[0] for y in range(ir.y0, ir.y1, 2) for x in range(ir.x0, ir.x1, 2)]
            if kanal and max(kanal) - min(kanal) > 16:
                erg["bilder"].append(f"Seite {s.seite + 1}: Bildpixel im Feld nicht einheitlich")
            if ocr and geheim and tesseract_ordner():
                gelesen = " ".join(t[0] for t in ocr_tsv(pix.tobytes("png"), 300, "deu+eng"))
                erg["bild_ocr"] += [g for g in geheim if g in gelesen]
        # d) Rohdaten (alle entpackten Streams + Datei): Wortfolgen und eindeutige Einzelwörter.
        # Kurze reine Hex-Ziffern (z. B. „0044“) kommen in Schrift-Tabellen als <0044> vor → nur als Folge prüfen.
        for g in _rohmuster(s.text):
            if g in ganztext:                  # steht an anderer Stelle sichtbar (nicht geschwärzt) → kein Rest
                continue
            if g.encode("utf-8") in roh or g.encode("utf-16-be") in roh:
                erg["rohdaten"].append(g)
    for i in range(d.embfile_count()):
        inhalt = d.embfile_get(i)
        erg["eingebettet"].append(d.embfile_info(i)["filename"])
        for s in schwaerzungen:
            erg["rohdaten"] += [g for g in _rohmuster(s.text) if g.encode() in inhalt]
    erg["eof_marken"] = roh_datei.count(b"%%EOF")
    erg["bestanden"] = (not any(erg[k] for k in ("text", "ocr_ebene", "bilder", "eingebettet", "rohdaten", "bild_ocr"))
                        and erg["eof_marken"] == 1)
    d.close()
    return erg


# ---------------------------------------------------------------- Signaturen
def signaturen(doc) -> list[str]:
    """Mevcut dijital imza alanları (imzalı belge düzenlenince ayrı kopyaya kaydedilir)."""
    namen = []
    for page in doc:
        for w in page.widgets() or []:
            if w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                namen.append(w.field_name or f"Seite {page.number + 1}")
    if doc.get_sigflags() > 0 and not namen:
        namen.append("(signiert)")
    return namen
