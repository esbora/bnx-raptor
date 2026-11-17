"""PDF motoru: metin değiştirme, karartma, güvenli kayıt (Tesseract gerektirmez)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pymupdf = pytest.importorskip("pymupdf")
from core import pdf_engine as pe  # noqa: E402

ALT = "Wir bitten um Regulierung bis zum 30.11.2026."
NEU = "Wir bitten um Zahlung bis zum 15.12.2026."


def _brief(tmp_path):
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 100), "Sehr geehrte Damen und Herren,", fontname="helv", fontsize=11)
    p.insert_text((72, 130), ALT, fontname="helv", fontsize=11)
    p.insert_text((72, 160), "IBAN DE89 3704 0044 0532 0130 00", fontname="helv", fontsize=11)
    f = tmp_path / "brief.pdf"
    doc.save(f)
    return f


def test_satz_ersetzen_entfernt_alten_text(tmp_path):
    quelle = _brief(tmp_path)
    doc = pymupdf.open(quelle)
    pe.text_ersetzen(doc[0], ALT, NEU)
    ziel = pe.sicher_speichern(doc, tmp_path / "neu.pdf")
    d = pymupdf.open(ziel)
    text = d[0].get_text()
    assert ALT not in text and not d[0].search_for(ALT)
    assert NEU in text and d[0].search_for(NEU)
    assert "Sehr geehrte Damen und Herren," in text
    assert not (tmp_path / "neu.bnx-tmp.pdf").exists()


def test_schwaerzen_ist_endgueltig(tmp_path):
    doc = pymupdf.open(_brief(tmp_path))
    r = doc[0].search_for("DE89 3704 0044 0532 0130 00")[0]
    pe.schwaerzen(doc[0], r)
    ziel = pe.sicher_speichern(doc, tmp_path / "geschwaerzt.pdf")
    roh = ziel.read_bytes()
    d = pymupdf.open(ziel)
    assert "3704" not in d[0].get_text() and b"3704" not in roh
    assert roh.count(b"%%EOF") == 1 and not list(d[0].annots())


def test_text_nicht_gefunden(tmp_path):
    doc = pymupdf.open(_brief(tmp_path))
    with pytest.raises(pe.PdfFehler):
        pe.text_ersetzen(doc[0], "gibt es nicht", "x")
