"""Faz 0 prototipi: `BnX-Raptor.exe --pdf-prototyp <ordner>`

<ordner>\\eingang\\digital_brief.pdf ve scan_brief.pdf (hayali) üzerinde dört işlemi yapar,
her çıktıyı yeniden açıp doğrular ve <ordner>\\bericht.json yazar. 4. adımda gerçek bir
önizleme penceresi açılır; kullanıcı onaylarsa PDF klasik Outlook taslağına eklenir (gönderilmez).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import traceback
from pathlib import Path

import pymupdf
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel, QVBoxLayout)

from core import pdf_engine as pe

SATZ_ALT = "Wir bitten um Regulierung des Schadens bis zum 30.11.2026."
SATZ_NEU = "Wir bitten um Zahlung des Gesamtbetrags bis zum 15.12.2026."
WORT_ALT, WORT_NEU = "Versicherumgsnehmer", "Versicherungsnehmer"
WAHRHEIT = {
    "deu": "Die Reparaturkosten für das Fahrzeug betragen laut Gutachten 4.250,00 € zuzüglich "
           "Nutzungsausfall für zwölf Tage.",
    "tur": "Müvekkilimiz kazadan sonra iş göremez durumdaydı; tıbbi raporlar ekte sunulmuştur. "
           "İstanbul şubenizin ödeme çağrımızı yanıtlamasını rica ediyoruz.",
    "eng": "Please confirm receipt of this letter and provide the claim handler's direct contact details.",
}


def _texte(doc) -> str:
    return " ".join(p.get_text() for p in doc)


def _rohdaten(doc) -> bytes:
    return b"".join(doc.xref_stream(x) or b"" for x in range(1, doc.xref_length()) if doc.xref_is_stream(x))


def _normal(s: str) -> str:
    return " ".join(s.split())


# ------------------------------------------------------------------ 1
def schritt1(ein: Path, aus: Path) -> dict:
    doc = pymupdf.open(ein / "digital_brief.pdf")
    vorher = _normal(_texte(doc))
    aend = pe.text_ersetzen(doc[0], SATZ_ALT, SATZ_NEU)
    ziel = pe.sicher_speichern(doc, aus / "1_digital_geaendert.pdf")
    doc.close()
    d = pymupdf.open(ziel)
    text = _normal(_texte(d))
    roh = _rohdaten(d)
    nachbar_ok = all(w in text for w in ("Sehr geehrte Damen und Herren,", "Müvekkilimiz", "Please confirm"))
    d[0].get_pixmap(dpi=110).save(aus / "1_digital_geaendert.png")
    erg = {
        "alter_satz_vorher_vorhanden": SATZ_ALT in vorher,
        "alter_satz_im_text": SATZ_ALT in text,
        "alter_satz_suchbar": bool(d[0].search_for(SATZ_ALT)),
        "alter_satz_teil_im_text": "Regulierung des Schadens" in text,
        "neuer_satz_im_text": SATZ_NEU in text,
        "neuer_satz_suchbar": bool(d[0].search_for(SATZ_NEU)),
        "nachbarabsaetze_unveraendert": nachbar_ok,
        "anzahl_bilder_annotationen": [len(d[0].get_images()), len(list(d[0].annots()))],
        "schrift": aend.schrift, "warnungen": aend.warnungen,
        "rohdaten_klartext_regulierung": b"Regulierung" in roh,
    }
    erg["bestanden"] = (erg["alter_satz_vorher_vorhanden"] and not erg["alter_satz_im_text"]
                        and not erg["alter_satz_suchbar"] and not erg["alter_satz_teil_im_text"]
                        and erg["neuer_satz_im_text"] and erg["neuer_satz_suchbar"] and nachbar_ok)
    return erg


# ------------------------------------------------------------------ 2
def _trefferquote(worte: list[str], wahr: str) -> tuple[float, list[str]]:
    vorrat = [w.strip(".,;:€") for w in worte]
    soll = [w.strip(".,;:€") for w in wahr.split() if w.strip(".,;:€")]
    fehlt = [w for w in soll if w not in vorrat]
    return round(1 - len(fehlt) / len(soll), 3), fehlt


def schritt2(ein: Path, aus: Path) -> dict:
    doc = pymupdf.open(ein / "scan_brief.pdf")
    page = doc[0]
    erg: dict = {"text_vor_ocr": bool(page.get_text().strip())}
    t0 = time.time()
    grad, sicher = pe.ausrichtung(page)
    erg["osd_aufrecht"] = {"drehen_grad": grad, "sicherheit": sicher}
    # OSD auch an einer auf den Kopf gestellten Kopie prüfen
    kopf = pymupdf.open(); kopf.insert_pdf(doc); kopf[0].set_rotation(180)
    erg["osd_kopfstehend"] = dict(zip(("drehen_grad", "sicherheit"), pe.ausrichtung(kopf[0])))
    worte = pe.ocr_seite(page)
    erg["ocr_sekunden"] = round(time.time() - t0, 1)
    erg["woerter"] = len(worte)
    confs = [w.conf for w in worte]
    erg["konfidenz_min_mittel"] = [min(confs), round(sum(confs) / len(confs), 1)]
    erg["unsichere_woerter_unter_80"] = [(w.text, round(w.conf)) for w in worte if w.conf < 80][:15]
    erg["geschuetzte_woerter"] = [w.text for w in worte if w.geschuetzt]
    beispiel = next(w for w in worte if w.text == WORT_ALT)
    erg["beispielwort"] = {"text": beispiel.text, "conf": beispiel.conf,
                           "rect_pt": [round(v, 1) for v in beispiel.rect]}
    # Koordinaten echt? Ausschnitt an der gemeldeten Stelle getrennt erkennen
    clip = page.get_pixmap(dpi=300, clip=beispiel.rect + (-4, -4, 4, 4), colorspace=pymupdf.csGRAY)
    erg["koordinaten_ausschnitt_ocr"] = pe._tesseract(clip.tobytes("png"), "-l", "deu", "--psm", "6").strip()
    texte = [w.text for w in worte]
    erg["sprachen"] = {}
    for sprache, wahr in WAHRHEIT.items():
        quote, fehlt = _trefferquote(texte, wahr)
        erg["sprachen"][sprache] = {"wortquote": quote, "fehlende_woerter": fehlt}
    pe.textebene_einfuegen(page, worte)
    pe.sicher_speichern(doc, aus / "2a_scan_ocr.pdf")
    doc.close()

    d = pymupdf.open(aus / "2a_scan_ocr.pdf")
    erg["nach_ocr_suchbar_altwort"] = bool(d[0].search_for(WORT_ALT))
    erg["nach_ocr_suchbar_tuerkisch"] = bool(d[0].search_for("çağrımızı"))
    aend = pe.scan_wort_ersetzen(d[0], WORT_ALT, WORT_NEU)
    erg["korrektur_schrift"], erg["korrektur_warnungen"] = aend.schrift, aend.warnungen
    pe.sicher_speichern(d, aus / "2b_scan_korrigiert.pdf")
    d.close()

    k = pymupdf.open(aus / "2b_scan_korrigiert.pdf")
    p = k[0]
    text = _normal(p.get_text())
    erg["textebene_altwort"] = WORT_ALT in text or bool(p.search_for(WORT_ALT))
    erg["textebene_neuwort"] = WORT_NEU in text and bool(p.search_for(WORT_NEU))
    # Sichtbar: Seite rendern und unabhängig neu erkennen (ohne vorhandene Textebene)
    r = aend.rect + (-30, -6, 60, 6)
    bild = p.get_pixmap(dpi=300, clip=r, colorspace=pymupdf.csGRAY)
    bild.save(aus / "2b_korrektur_ausschnitt.png")
    sichtbar = pe._tesseract(bild.tobytes("png"), "-l", "deu", "--psm", "6").strip()
    voll = " ".join(t[0] for t in pe.ocr_tsv(p.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY).tobytes("png"), 300))
    erg["sichtbar_ausschnitt_ocr"] = sichtbar
    erg["sichtbar_neuwort"] = WORT_NEU in voll
    erg["sichtbar_altwort"] = WORT_ALT in voll
    erg["bilder_im_dokument"] = len([x for x in range(1, k.xref_length()) if k.xref_get_key(x, "Subtype")[1] == "/Image"])
    p.get_pixmap(dpi=110).save(aus / "2b_scan_korrigiert.png")
    erg["bestanden"] = (not erg["text_vor_ocr"] and erg["woerter"] > 50 and erg["nach_ocr_suchbar_altwort"]
                        and not erg["textebene_altwort"] and erg["textebene_neuwort"]
                        and erg["sichtbar_neuwort"] and not erg["sichtbar_altwort"]
                        and WORT_ALT in erg["koordinaten_ausschnitt_ocr"])
    return erg


# ------------------------------------------------------------------ 3
GEHEIM = ["3704", "0044", "0532", "0130"]


def schritt3(aus: Path) -> dict:
    quelle = aus / "2b_scan_korrigiert.pdf"
    doc = pymupdf.open(quelle)
    page = doc[0]
    altbild_xref = page.get_images()[0][0]
    altbild_hash = pe.hashlib.sha256(doc.xref_stream_raw(altbild_xref)).hexdigest()
    worte = page.get_text("words")
    zeile = next(w for w in worte if w[4] == "IBAN")
    teile = [pymupdf.Rect(w[:4]) for w in worte if w[4] in ("DE89", *GEHEIM, "00")
             and abs(w[1] - zeile[1]) < 4]
    rect = teile[0]
    for t in teile[1:]:
        rect |= t
    rect += (-2, -2, 2, 2)
    vorher_im_text = all(g in page.get_text() for g in GEHEIM)
    pe.schwaerzen(page, rect)
    ziel = pe.sicher_speichern(doc, aus / "3_geschwaerzt.pdf")
    doc.close()

    d = pymupdf.open(ziel)
    p = d[0]
    erg: dict = {"geschwaerztes_rechteck_pt": [round(v, 1) for v in rect], "vorher_im_text": vorher_im_text}
    text = p.get_text()
    erg["a_text_enthaelt_iban"] = [g for g in GEHEIM if g in text]
    erg["a_suchbar"] = [g for g in GEHEIM if p.search_for(g)]
    erg["b_ocr_ebene_woerter_im_feld"] = [w[4] for w in p.get_text("words") if pymupdf.Rect(w[:4]).intersects(rect)]
    # Rohdaten: entpackte Streams + Datei, als ASCII und UTF-16 (Ziffernfolgen der IBAN mit Leerzeichen)
    roh = _rohdaten(d) + ziel.read_bytes()
    muster = ["DE89 3704", "3704 0044", "0044 0532", "0532 0130", "DE893704", "37040044"]
    erg["b_rohdaten_klartext"] = [m for m in muster
                                  if m.encode() in roh or m.encode("utf-16-be") in roh]
    erg["b_ocr_ebene_sonst_intakt"] = bool(p.search_for("Beispielbank")) and bool(p.search_for("çağrımızı"))
    # c) eingebettetes Bild herausziehen und unabhängig prüfen
    bilder = [x for x in range(1, d.xref_length()) if d.xref_get_key(x, "Subtype")[1] == "/Image"]
    xref = bilder[0]
    pix = pymupdf.Pixmap(d, xref)
    pix.save(aus / "3_extrahiertes_bild.png")
    info = p.get_image_info(xrefs=True)[0]
    ir = pe._pixelrechteck(pix, rect, pymupdf.Matrix(info["transform"]), -3)
    werte = {pix.pixel(x, y) for y in range(ir.y0, ir.y1) for x in range(ir.x0, ir.x1)}
    kanal = [w[0] for w in werte]
    erg["c_bild_pixel_min_max_im_feld"] = [min(kanal), max(kanal)]
    erg["c_bild_filter"] = d.xref_get_key(xref, "Filter")[1]
    # einfarbig (JPEG darf ±16 Rauschen haben; Schrift wäre < 128)
    erg["c_bild_feld_einfarbig"] = max(kanal) - min(kanal) <= 16
    bild_ocr = " ".join(t[0] for t in pe.ocr_tsv(pix.tobytes("png"), 300))
    erg["c_ocr_des_extrahierten_bildes_findet"] = [g for g in GEHEIM if g in bild_ocr]
    erg["c_ocr_bild_findet_umgebung"] = "Beispielbank" in bild_ocr
    erg["c_anzahl_bildobjekte"] = len(bilder)
    erg["c_altes_bild_noch_in_datei"] = any(
        pe.hashlib.sha256(d.xref_stream_raw(x)).hexdigest() == altbild_hash for x in bilder)
    roh_datei = ziel.read_bytes()
    erg["d_eof_marken_inkrementell"] = roh_datei.count(b"%%EOF")
    erg["d_annotationen"] = len(list(p.annots()))
    erg["bestanden"] = (vorher_im_text and not erg["a_text_enthaelt_iban"] and not erg["a_suchbar"]
                        and not erg["b_ocr_ebene_woerter_im_feld"] and not erg["b_rohdaten_klartext"]
                        and erg["b_ocr_ebene_sonst_intakt"]
                        and erg["c_bild_feld_einfarbig"] and not erg["c_ocr_des_extrahierten_bildes_findet"]
                        and erg["c_ocr_bild_findet_umgebung"] and not erg["c_altes_bild_noch_in_datei"]
                        and erg["d_eof_marken_inkrementell"] == 1 and erg["d_annotationen"] == 0)
    return erg


# ------------------------------------------------------------------ 4
class Vorschau(QDialog):
    """Önizleme: kullanıcı hangi dosyanın ekleneceğini görür ve onaylar."""

    def __init__(self, pdf: Path, digest: str):
        super().__init__()
        self.setWindowTitle("Anhang prüfen – BnX-Raptor")
        lay = QVBoxLayout(self)
        d = pymupdf.open(pdf)
        pix = d[0].get_pixmap(dpi=60)
        bild = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        lbl = QLabel(); lbl.setPixmap(QPixmap.fromImage(bild)); lay.addWidget(lbl, alignment=Qt.AlignCenter)
        lay.addWidget(QLabel(f"<b>{pdf.name}</b><br>{d.page_count} Seite(n) · {pdf.stat().st_size / 1024:.0f} KB<br>"
                             f"Prüfsumme (SHA-256): {digest[:16]}…<br>Diese Datei wird dem Entwurf angehängt. "
                             "Die E-Mail wird nicht gesendet."))
        d.close()
        bb = QDialogButtonBox()
        self.ok = bb.addButton("In Outlook-Entwurf übernehmen", QDialogButtonBox.AcceptRole)
        bb.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        self.ok.setDefault(True)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def schritt4(aus: Path) -> dict:
    pdf = aus / "3_geschwaerzt.pdf"
    digest = pe.sha256(pdf)
    if Vorschau(pdf, digest).exec() != QDialog.Accepted:
        return {"bestanden": False, "abgebrochen": True}
    import pythoncom
    import win32com.client as win32
    pythoncom.CoInitialize()
    ol = win32.Dispatch("Outlook.Application")
    betreff = f"BnX Faz0 Test {time.strftime('%H%M%S')}"
    mail = ol.CreateItem(0)
    mail.To = "test@example.com"
    mail.Subject = betreff
    mail.Display()
    mail.Attachments.Add(str(pdf))
    # Rückprüfung: Anhang aus dem Entwurf speichern und vergleichen
    with tempfile.TemporaryDirectory() as td:
        att = mail.Attachments.Item(mail.Attachments.Count)
        kopie = Path(td) / att.FileName
        att.SaveAsFile(str(kopie))
        anhang_hash = pe.sha256(kopie)
    erg = {"betreff": betreff, "vorschau_sha256": digest, "anhang_sha256": anhang_hash,
           "anhang_name": att.FileName, "anzahl_anhaenge": mail.Attachments.Count,
           "gesendet": bool(mail.Sent)}
    erg["bestanden"] = digest == anhang_hash and not erg["gesendet"]
    return erg


def main(ordner: Path) -> int:
    app = QApplication.instance() or QApplication([])  # noqa: F841
    ein, aus = ordner / "eingang", ordner / "ausgabe"
    aus.mkdir(parents=True, exist_ok=True)
    bericht = {"pymupdf": pymupdf.VersionBind, "mupdf": pymupdf.VersionFitz,
               "tesseract": str(pe.tesseract_ordner()), "eingang_sha256": {
                   f.name: pe.sha256(f) for f in sorted(ein.glob("*.pdf"))}}
    nur = os.environ.get("BNX_SCHRITTE", "1234")
    for nr, fn in (("1", lambda: schritt1(ein, aus)), ("2", lambda: schritt2(ein, aus)),
                   ("3", lambda: schritt3(aus)), ("4", lambda: schritt4(aus))):
        if nr not in nur:
            continue
        t0 = time.time()
        try:
            bericht[f"schritt{nr}"] = fn()
        except Exception:  # noqa: BLE001
            bericht[f"schritt{nr}"] = {"bestanden": False, "fehler": traceback.format_exc()}
        bericht[f"schritt{nr}"]["sekunden"] = round(time.time() - t0, 1)
    bericht["eingang_unveraendert"] = all(pe.sha256(ein / n) == h for n, h in bericht["eingang_sha256"].items())
    (ordner / "bericht.json").write_text(json.dumps(bericht, ensure_ascii=False, indent=1, default=str),
                                         encoding="utf-8")
    return 0
