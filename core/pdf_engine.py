"""PDF motoru (0.4 Faz 0 prototipi): PyMuPDF + yerel Tesseract.

Belgeler, sayfa görüntüleri ve OCR metni bilgisayardan çıkmaz: Tesseract programın yanındaki
`ocr\\` klasöründen yerel süreç olarak çalışır, ağ kullanılmaz.
Bu modül yalnızca PDF editörü açılınca içe aktarılır (program açılışını yavaşlatmaz).
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from core.config import app_dir

SPRACHEN = "deu+tur+eng"
FONT_ORDNER = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
               Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
ERSATZ_SCHRIFT = "Arial"
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


# ---------------------------------------------------------------- Speichern
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
    doc.save(tmp, garbage=4, deflate=True, clean=True, incremental=False)
    try:
        with pymupdf.open(tmp) as probe:
            if probe.page_count != doc.page_count:
                raise PdfFehler("Die gespeicherte Datei ist unvollständig.")
        os.replace(tmp, ziel)
    finally:
        if tmp.exists():
            tmp.unlink()
    return ziel


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
        else:
            fehlt = fehlt if puffer else "?"
    else:
        fehlt = "?"
    datei = systemschrift(name)
    if datei:
        puffer = datei.read_bytes()
        return Schriftwahl(pymupdf.Font(fontbuffer=puffer), puffer, "Windows", name, fehlt)
    datei = systemschrift(ERSATZ_SCHRIFT)
    puffer = datei.read_bytes()
    return Schriftwahl(pymupdf.Font(fontbuffer=puffer), puffer, "Ersatz", ERSATZ_SCHRIFT, fehlt)


def _rgb(farbe: int) -> tuple[float, float, float]:
    return ((farbe >> 16) & 255) / 255, ((farbe >> 8) & 255) / 255, (farbe & 255) / 255


def _zeile_schreiben(tw: pymupdf.TextWriter, x: float, y: float, text: str, font: pymupdf.Font, fs: float) -> None:
    """Kelimeleri tek tek yerleştirir: bazı yazı tiplerinde (Arial) boşluk glifi metin çıkarmada
    bölünmez boşluk (U+00A0) olarak geri geliyordu ve arama bozuluyordu."""
    bosluk = font.text_length(" ", fontsize=fs)
    for wort in text.split(" "):
        if wort:
            tw.append((x, y), wort, font=font, fontsize=fs)
        x += font.text_length(wort, fontsize=fs) + bosluk


# ---------------------------------------------------------------- Textbearbeitung (digital)
@dataclass
class Aenderung:
    warnungen: list[str] = field(default_factory=list)
    schrift: str = ""
    rect: pymupdf.Rect | None = None


def text_ersetzen(page: pymupdf.Page, alt: str, neu: str) -> Aenderung:
    """Değiştirilen metni içeren paragrafı (blok) gerçekten siler ve yeni metinle aynı yere yeniden dizer.

    Beyaz kutu kullanılmaz: eski karakterler içerik akışından kaldırılır (redaksiyon, görsel/çizgi korunur).
    """
    doc = page.parent
    bloecke = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
    ziel = None
    for b in bloecke:
        zeilen = ["".join(s["text"] for s in ln["spans"]) for ln in b["lines"]]
        if alt in " ".join(z.strip() for z in zeilen):
            ziel, blocktext = b, " ".join(z.strip() for z in zeilen)
            break
    if ziel is None:
        raise PdfFehler(f"Text nicht gefunden: „{alt}“")
    neuer_text = blocktext.replace(alt, neu)
    ergebnis = Aenderung(rect=pymupdf.Rect(ziel["bbox"]))

    spans = [s for ln in ziel["lines"] for s in ln["spans"] if s["text"].strip()]
    haupt = max(spans, key=lambda s: len(s["text"]))
    if len({(s["font"], round(s["size"], 1), s["color"]) for s in spans}) > 1:
        ergebnis.warnungen.append("Absatz enthält mehrere Formatierungen – vereinfacht auf "
                                  f"{haupt['font'].split('+')[-1]} {haupt['size']:.1f} pt")
    font_xref = next((f[0] for f in page.get_fonts() if f[3].split("+")[-1] == haupt["font"].split("+")[-1]), 0)
    wahl = schrift_waehlen(doc, font_xref, haupt["font"], neuer_text)
    ergebnis.schrift = f"{wahl.name.split('+')[-1]} ({wahl.quelle})"
    if wahl.quelle == "Windows":
        ergebnis.warnungen.append(
            (f"Eingebettete Teilschrift ohne Zeichen „{wahl.fehlende}“" if wahl.fehlende != "?"
             else "Eingebettete Schrift nicht verwendbar") + " – gleiche Schrift aus Windows ergänzt")
    elif wahl.quelle == "Ersatz":
        ergebnis.warnungen.append(f"Schrift {haupt['font'].split('+')[-1]} nicht verfügbar – "
                                  f"ersetzt durch {ERSATZ_SCHRIFT}")

    # Zeilenabstand des Originals
    basislinien = [ln["spans"][0]["origin"][1] for ln in ziel["lines"]]
    abstand = ((basislinien[-1] - basislinien[0]) / (len(basislinien) - 1)
               if len(basislinien) > 1 else haupt["size"] * 1.2)

    # 1) alte Zeichen entfernen (Zeilen leicht verkleinert, damit Nachbarzeilen unberührt bleiben)
    for ln in ziel["lines"]:
        r = pymupdf.Rect(ln["bbox"])
        h = r.height * 0.2
        page.add_redact_annot(pymupdf.Rect(r.x0, r.y0 + h, r.x1, r.y1 - h), fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    # 2) neu setzen: gleiche linke Kante/Breite/erste Grundlinie, Umbruch wie Word (linksbündig)
    links, rechts = ziel["bbox"][0], max(ziel["bbox"][2], page.rect.width - 72)
    rechts = ziel["bbox"][2] if len(ziel["lines"]) > 1 else rechts
    fs = haupt["size"]
    zeilen, akt = [], ""
    for wort in neuer_text.split():
        probe = (akt + " " + wort).strip()
        if wahl.font.text_length(probe, fontsize=fs) <= (rechts - links) + 0.5 or not akt:
            akt = probe
        else:
            zeilen.append(akt)
            akt = wort
    zeilen.append(akt)
    tw = pymupdf.TextWriter(page.rect, color=_rgb(haupt["color"]))
    y = basislinien[0]
    for z in zeilen:
        _zeile_schreiben(tw, links, y, z, wahl.font, fs)
        y += abstand
    # Überlauf: kollidiert der Absatz mit dem nächsten Textblock?
    unten = y - abstand + fs * 0.3
    naechster = min((b["bbox"][1] for b in bloecke if b["bbox"][1] > ziel["bbox"][3] - 1
                     and b["bbox"][0] < rechts and b["bbox"][2] > links), default=page.rect.height)
    if len(zeilen) > len(ziel["lines"]):
        ergebnis.warnungen.append(f"Absatz wird länger ({len(ziel['lines'])} → {len(zeilen)} Zeilen)")
    if unten > naechster:
        ergebnis.warnungen.append("Text läuft in den folgenden Absatz – bitte kürzen")
    tw.write_text(page)
    return ergebnis


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
    with tempfile.TemporaryDirectory(prefix="bnx-ocr-") as td:
        bild = Path(td) / "seite.png"
        bild.write_bytes(png)
        env = dict(os.environ, TESSDATA_PREFIX=str(ordner / "tessdata"))
        r = subprocess.run([str(ordner / "tesseract.exe"), str(bild), "stdout", *args],
                           capture_output=True, env=env, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        raise PdfFehler("OCR fehlgeschlagen: " + r.stderr.decode("utf-8", "replace")[-300:])
    return r.stdout.decode("utf-8", "replace")


@dataclass
class OcrWort:
    text: str
    conf: float                       # 0–100 (Tesseract)
    rect: pymupdf.Rect                # Seitenkoordinaten (pt)
    zeile: tuple[int, int, int]       # block, absatz, zeile
    geschuetzt: bool = False          # Aktenzeichen/E-Mail/IBAN → nie automatisch korrigieren


def ocr_tsv(png: bytes, dpi: int, sprachen: str = SPRACHEN) -> list[tuple]:
    """Tesseract-TSV: (text, conf, left, top, width, height, block, par, line) in Pixeln."""
    roh = _tesseract(png, "-l", sprachen, "--dpi", str(dpi), "--psm", "3", "tsv")
    out = []
    for z in roh.splitlines()[1:]:
        f = z.split("\t")
        if len(f) == 12 and f[0] == "5" and f[11].strip():
            out.append((f[11], float(f[10]), *map(int, f[6:10]), *map(int, f[2:5])))
    return out


def _zeilenweise(png: bytes, dpi: int, sprachen: tuple[str, ...], vorsprung: float = 3.0) -> list[tuple]:
    """Her dili ayrı çalıştırır, her satır için ortalama güveni en yüksek sonucu alır.

    Ortak 'deu+tur+eng' modeli Almanca 'ü'yü 'ii' okuyordu; satır bazında seçim bunu çözüyor.
    İlk dil önceliklidir: diğer dil ancak `vorsprung` puan daha güvenliyse seçilir.
    """
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


def ocr_seite(page: pymupdf.Page, dpi: int = 300, sprachen: tuple[str, ...] = ("deu", "tur", "eng")) -> list[OcrWort]:
    zoom = pymupdf.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=zoom, colorspace=pymupdf.csGRAY, alpha=False)
    rueck = ~zoom * page.derotation_matrix
    worte = []
    for text, conf, x, y, w, h, b, p, ln in _zeilenweise(pix.tobytes("png"), dpi, sprachen):
        worte.append(OcrWort(text, conf, pymupdf.Rect(x, y, x + w, y + h) * rueck, (b, p, ln)))
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


def ausrichtung(page: pymupdf.Page) -> tuple[int, float]:
    """Tesseract OSD: (zu drehende Grad, Sicherheit)."""
    pix = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY, alpha=False)
    roh = _tesseract(pix.tobytes("png"), "--psm", "0", "-l", "osd")
    grad = int(re.search(r"Rotate: (\d+)", roh).group(1))
    sicher = float(re.search(r"Orientation confidence: ([\d.]+)", roh).group(1))
    return grad, sicher


def textebene_einfuegen(page: pymupdf.Page, worte: list[OcrWort]) -> int:
    """Unsichtbare, durchsuchbare Textebene (render_mode 3) wortgenau über das Scanbild legen."""
    datei = systemschrift(ERSATZ_SCHRIFT)
    font = pymupdf.Font(fontfile=str(datei))
    tw = pymupdf.TextWriter(page.rect)
    for w in worte:
        laenge = font.text_length(w.text, fontsize=1)
        if not laenge:
            continue
        fs = w.rect.width / laenge
        tw.append((w.rect.x0, w.rect.y1 - abs(font.descender) * fs * 0.6), w.text, font=font, fontsize=fs)
    tw.write_text(page, render_mode=3)
    return len(worte)


# ---------------------------------------------------------------- Scan: Wort korrigieren
def _bild_auf_seite(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[int, pymupdf.Matrix]:
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


def scan_wort_ersetzen(page: pymupdf.Page, alt: str, neu: str, schrift: str = "Times New Roman") -> Aenderung:
    """Taranmış sayfada kelimeyi düzeltir: pikseller görüntüden silinir (arka plan rengiyle),
    eski OCR kelimesi metin katmanından kaldırılır, yeni kelime görünür ve aranabilir metin olarak yazılır."""
    doc = page.parent
    treffer = [pymupdf.Rect(w[:4]) for w in page.get_text("words") if w[4].strip(".,;:") == alt]
    if not treffer:
        raise PdfFehler(f"Wort nicht in der Textebene gefunden: „{alt}“ (zuerst OCR ausführen)")
    rect = treffer[0]
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
    war_jpeg = "DCTDecode" in doc.xref_get_key(xref, "Filter")[1]
    if war_jpeg:                       # Scan war JPEG → wieder JPEG (sonst wird die Datei ~3× größer)
        page.replace_image(xref, stream=pix.tobytes("jpeg", jpg_quality=90))
    else:
        page.replace_image(xref, pixmap=pix)

    # alte Wörter der OCR-Ebene an dieser Stelle entfernen (Bild bleibt wie eben ersetzt)
    page.add_redact_annot(rect, fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    datei = systemschrift(schrift) or systemschrift(ERSATZ_SCHRIFT)
    font = pymupdf.Font(fontfile=str(datei))
    fs = rect.width / font.text_length(alt, fontsize=1)
    tw = pymupdf.TextWriter(page.rect, color=farbe)
    tw.append((rect.x0, basis_pt), neu, font=font, fontsize=fs)
    tw.write_text(page)
    erg = Aenderung(rect=rect, schrift=f"{font.name} {fs:.1f} pt")
    breite = font.text_length(neu, fontsize=fs)
    if breite > rect.width * 1.15:
        erg.warnungen.append("Neues Wort ist deutlich breiter als das alte – Überlappung prüfen")
    return erg


# ---------------------------------------------------------------- Schwärzen
def schwaerzen(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    """Kalıcı karartma: metin + OCR katmanı + görsel pikselleri + üstteki çizimler silinir."""
    doc = page.parent
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


# ---------------------------------------------------------------- Signaturen
def signaturen(doc: pymupdf.Document) -> list[str]:
    """Mevcut dijital imza alanları (imzalı belge düzenlenince ayrı kopyaya kaydedilir)."""
    namen = []
    for page in doc:
        for w in page.widgets() or []:
            if w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                namen.append(w.field_name or f"Seite {page.number + 1}")
    if doc.get_sigflags() > 0 and not namen:
        namen.append("(signiert)")
    return namen
