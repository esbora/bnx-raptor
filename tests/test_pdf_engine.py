"""PDF motoru ve düzenleme oturumu (Tesseract gerektirmeyen testler)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pymupdf = pytest.importorskip("pymupdf")
from core import pdf_engine as pe  # noqa: E402
from core.pdf_sitzung import PdfSitzung  # noqa: E402

ALT = "Wir bitten um Regulierung bis zum 30.11.2026."
NEU = "Wir bitten um Zahlung bis zum 15.12.2026."
IBAN = "DE89 3704 0044 0532 0130 00"


def _brief(tmp_path, name="brief.pdf", seiten=1, anhang=False, bild=False):
    doc = pymupdf.open()
    for i in range(seiten):
        p = doc.new_page()
        p.insert_text((72, 100), f"Sehr geehrte Damen und Herren, Seite {i + 1}", fontname="helv", fontsize=11)
        p.insert_text((72, 130), ALT, fontname="helv", fontsize=11)
        p.insert_text((72, 160), "IBAN " + IBAN, fontname="helv", fontsize=11)
        if bild:
            q = pymupdf.open()
            qp = q.new_page(width=300, height=60)
            qp.insert_text((10, 35), "GEHEIM 3704 0044", fontsize=20)
            p.insert_image(pymupdf.Rect(72, 200, 372, 260), pixmap=qp.get_pixmap(dpi=150))
    if anhang:
        doc.embfile_add("notiz.txt", ("Kontodaten " + IBAN).encode())
    doc.set_metadata({"title": "Geheim " + IBAN})
    f = tmp_path / name
    doc.save(f)
    return f


def test_satz_ersetzen_entfernt_alten_text(tmp_path):
    doc = pymupdf.open(_brief(tmp_path))
    pe.text_ersetzen(doc[0], ALT, NEU)
    ziel = pe.sicher_speichern(doc, tmp_path / "neu.pdf")
    d = pymupdf.open(ziel)
    text = d[0].get_text()
    assert ALT not in text and not d[0].search_for(ALT)
    assert NEU in text and d[0].search_for(NEU)
    assert "Sehr geehrte Damen und Herren" in text
    assert not (tmp_path / "neu.bnx-tmp.pdf").exists()


def test_block_ausrichtung_groesse_und_ueberlauf():
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 100), "Kurzer Absatz", fontname="helv", fontsize=11)
    p.insert_text((72, 200), "Folgeabsatz weiter unten", fontname="helv", fontsize=11)
    b = pe.block_an(p, (80, 97))
    assert b and pe.block_format(b).text.startswith("Kurzer Absatz")
    erg = pe.block_ersetzen(p, b, "Rechtsbündig", ausrichtung="rechts", groesse=11)
    r = p.search_for("Rechtsbündig")[0]
    assert r.x1 > p.rect.width - 60                 # rechter Rand
    b2 = pe.block_an(p, ((r.x0 + r.x1) / 2, r.y0 + 2))
    erg = pe.block_ersetzen(p, b2, "sehr langer Text " * 40, groesse=14)
    assert any("passt nicht" in w for w in erg.warnungen)


def test_absatz_loeschen_und_text_einfuegen():
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 100), "Weg damit", fontname="helv", fontsize=11)
    pe.block_ersetzen(p, pe.block_an(p, (75, 97)), "")
    assert "Weg damit" not in p.get_text()
    erg = pe.text_einfuegen(p, (72, 300), "Neuer Hinweis für Müller: Frist beachtet.", 12)
    assert p.search_for("Neuer Hinweis für Müller") and not erg.warnungen


def test_seitenoperationen(tmp_path):
    doc = pymupdf.open(_brief(tmp_path, seiten=4))
    pe.seite_verschieben(doc, 0, 3)
    assert "Seite 1" in doc[3].get_text() and "Seite 2" in doc[0].get_text()
    pe.seite_verschieben(doc, 3, 0)
    assert "Seite 1" in doc[0].get_text()
    pe.seite_duplizieren(doc, 1)
    assert doc.page_count == 5 and "Seite 2" in doc[2].get_text()
    pe.seiten_drehen(doc, [0], 90)
    assert doc[0].rotation == 90
    pe.seiten_loeschen(doc, [1, 2])
    assert doc.page_count == 3
    with pytest.raises(pe.PdfFehler):
        pe.seiten_loeschen(doc, [0, 1, 2])
    teile = pe.aufteilen(doc, [1, 2])
    assert [t.page_count for t in teile] == [1, 1, 1]
    assert pe.seiten_extrahieren(doc, [2, 0]).page_count == 2
    pe.seite_zuschneiden(doc[1], pymupdf.Rect(50, 50, 400, 400))
    assert doc[1].cropbox.width == 350


def test_sitzung_rueckgaengig_vorschau_und_original_bleibt(tmp_path):
    quelle = _brief(tmp_path)
    vorher = quelle.read_bytes()
    s = PdfSitzung(quelle)
    pix, erg = s.vorschau(lambda d: pe.text_ersetzen(d[0], ALT, NEU), 0)
    assert pix.width > 100 and ALT in s.doc[0].get_text()      # Vorschau ändert nichts
    s.aendern("Drehen", lambda d: pe.seiten_drehen(d, [0], 90))
    s.aendern("Text ändern", lambda d: pe.text_ersetzen(d[0], ALT, NEU))
    assert s.doc[0].rotation == 90 and NEU in s.doc[0].get_text()
    s.rueckgaengig()
    assert ALT in s.doc[0].get_text()
    s.wiederholen()
    assert NEU in s.doc[0].get_text()
    with pytest.raises(pe.PdfFehler, match="Original"):
        s.speichern_unter(quelle)
    erg = s.speichern_unter(s.vorschlag())
    assert erg.pfad.name == "brief_bearbeitet.pdf" and not s.geaendert
    assert quelle.read_bytes() == vorher


def test_schwaerzung_mit_bild_und_eingebetteter_datei(tmp_path):
    s = PdfSitzung(_brief(tmp_path, anhang=True, bild=True))
    assert s.doc.embfile_count() == 1
    r = s.doc[0].search_for(IBAN)[0]
    s.aendern("Schwärzen", lambda d: pe.schwaerzen(d[0], r + (-1, -1, 1, 1)))
    s.aendern("Schwärzen", lambda d: pe.schwaerzen(d[0], pymupdf.Rect(72, 200, 372, 260)))
    erg = s.speichern_unter(tmp_path / "geschwaerzt.pdf", pruefen_ocr=False)
    assert erg.pruefung["bestanden"], erg.pruefung
    assert any("eingebettete" in e for e in erg.entfernt)
    d = pymupdf.open(erg.pfad)
    assert d.embfile_count() == 0 and "3704" not in d[0].get_text()
    assert not d.metadata.get("title")
    assert erg.pfad.read_bytes().count(b"%%EOF") == 1


def test_bildhash_erkennt_aehnliche_seite(tmp_path):
    a = pymupdf.open(_brief(tmp_path))
    scan = pymupdf.open()
    sp = scan.new_page()
    sp.insert_image(sp.rect, pixmap=a[0].get_pixmap(dpi=100))
    anders = pymupdf.open()
    ap = anders.new_page()
    ap.insert_text((300, 600), "Ganz anderer Inhalt", fontsize=30)
    ha, hs, hx = pe.bildhash(a[0]), pe.bildhash(scan[0]), pe.bildhash(ap)
    assert pe.hash_abstand(ha, hs) <= 30 < pe.hash_abstand(ha, hx)


def test_kaputte_datei_klare_meldung(tmp_path):
    f = tmp_path / "kaputt.pdf"
    f.write_bytes(b"%PDF-1.7\n1 0 obj << /Type /Catalog >>\nKAPUTT")
    with pytest.raises(pe.PdfFehler, match="kaputt.pdf"):
        pe.oeffnen(f)


def test_text_nicht_gefunden(tmp_path):
    doc = pymupdf.open(_brief(tmp_path))
    with pytest.raises(pe.PdfFehler):
        pe.text_ersetzen(doc[0], "gibt es nicht", "x")


def test_ohne_windows_schriften(monkeypatch):
    # Programm darf nicht von installierten Windows-Schriften abhängen
    monkeypatch.setattr(pe, "systemschrift", lambda name: None)
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 100), "Alter Absatz", fontname="helv", fontsize=11)
    erg = pe.block_ersetzen(p, pe.block_an(p, (75, 97)), "Çağrı für Müller – İstanbul")
    assert "Çağrı für Müller – İstanbul" in p.get_text() and "Ersatz" in erg.schrift
    pe.text_einfuegen(p, (72, 300), "Ğüşö")
    assert "Ğüşö" in p.get_text()
