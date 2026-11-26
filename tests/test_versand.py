"""0.5 Versandkontrolle: Prüfungen, Bereinigung in Kopie, Versandnachweis – fiktive Daten, kein Versand."""
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import protokoll as pr  # noqa: E402
from core.docx_schreiben import docx_absaetze  # noqa: E402
from core.journal import Journal  # noqa: E402
from core.unterlagen import Unterlagen  # noqa: E402
from core.versand import (Parteien, Versand, aenderungen_seit_entwurf, anlage_verweise, bereinigen,  # noqa: E402
                          bezeichnung_nummer, docx_eigenschaften, docx_volltext, feste_kopien, gesendet_passt,
                          pruefen)

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def docx(pfad: Path, absaetze: list[str], autor: str = "", kommentar: bool = False, aenderung: bool = False) -> Path:
    """Kleines Word-Dokument; optional mit Autor, Kommentar und nachverfolgter Änderung (fiktiv)."""
    docx_absaetze(pfad, absaetze)
    with zipfile.ZipFile(pfad) as z:
        teile = {n: z.read(n) for n in z.namelist()}
    doc = teile["word/document.xml"].decode("utf-8")
    if kommentar:
        doc = doc.replace("<w:body>", '<w:body><w:p><w:commentRangeStart w:id="0"/><w:r><w:t>kommentiert</w:t></w:r>'
                          '<w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r></w:p>', 1)
        teile["word/comments.xml"] = (f'<?xml version="1.0" encoding="UTF-8"?><w:comments {W_NS}><w:comment w:id="0"'
                                      f' w:author="RA Berger"><w:p><w:r><w:t>Bitte prüfen</w:t></w:r></w:p></w:comment>'
                                      f'</w:comments>').encode()
    if aenderung:
        doc = doc.replace("<w:body>", '<w:body><w:p><w:ins w:id="1" w:author="RA Berger"><w:r><w:t>neu</w:t></w:r>'
                          '</w:ins></w:p>', 1)
    teile["word/document.xml"] = doc.encode("utf-8")
    if autor:
        teile["docProps/core.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.'
            'openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:creator>{autor}</dc:creator><cp:lastModifiedBy>{autor}</cp:lastModifiedBy>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">2026-11-20T10:00:00Z</dcterms:created>'
            '</cp:coreProperties>').encode()
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in teile.items():
            z.writestr(n, d)
    return pfad


def pdf(pfad: Path, text: str) -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), text)
    d.save(pfad)
    return pfad


# ---------------------------------------------------------------- Anlagenverweise
def test_verweise_sicher_unsicher_bereiche():
    t = ("Wir überreichen die Rechnung als Anlage K1 und das Gutachten (Anlagen K2 bis K3).\n"
         "Siehe ferner Anlagen K5, K6 und K7. Der Gegner schreibt: „vgl. Anlage K9“.\n"
         "Fahrzeugklasse K4 ist hier unerheblich.")
    v = anlage_verweise(t)
    sicher = sorted((x.buchstabe, x.nummer) for x in v if x.sicher)
    unsicher = sorted((x.buchstabe, x.nummer) for x in v if not x.sicher)
    assert sicher == [("K", 1), ("K", 2), ("K", 3), ("K", 5), ("K", 6), ("K", 7)]
    assert ("K", 9) in unsicher and ("K", 4) in unsicher                     # Zitat bzw. bloßes „K4“
    assert bezeichnung_nummer("Anlage K12") == ("K", 12) and bezeichnung_nummer("Schriftsatz") is None


def test_k1_bis_k3_k2_fehlt_mit_beleg_und_empfaenger(tmp_path):
    schrift = docx(tmp_path / "Erwiderung.docx", ["In Sachen Erfunden ./. Fiktiva, Az. 0815/26",
                                                   "Die Reparatur ist belegt durch die Rechnung (Anlage K1).",
                                                   "Das Gutachten liegt als Anlage K2 bei, die Fotos als Anlage K3."])
    k1 = pdf(tmp_path / "Anlage_K1.pdf", "Rechnung")
    k3 = pdf(tmp_path / "Anlage_K3.pdf", "Fotos")
    p = Parteien(mandant=["erika@example.com"], versicherung=["schaden@fiktiva.example"], nummern=["0815/26"],
                 andere={"max@example.com": ["2026/0901"]}, andere_nummern={"0901/26": "2026/0901"})
    erg = pruefen("schaden@fiktiva.example", "2026/0815", p, schrift, [(k1, "Anlage K1"), (k3, "Anlage K3")])
    assert erg.rolle == "versicherung"
    fehlt = [b for b in erg.befunde if b.art == "anlage_fehlt" and b.stufe == "warnung"]
    assert len(fehlt) == 1 and "K2" in fehlt[0].text and "Anlage K2 bei" in fehlt[0].beleg and fehlt[0].bestaetigen
    assert any(b.art == "anlage_nummer" and "K2 fehlt" in b.text for b in erg.befunde)       # Lücke
    assert any(b.art == "hauptdokument" and b.stufe == "ok" for b in erg.befunde)
    # falscher Empfänger (Mandant einer anderen Akte) → Warnung zur Bestätigung
    erg2 = pruefen("max@example.com", "2026/0815", p, schrift, [(k1, "Anlage K1")])
    assert erg2.rolle == "andere_akte" and any(b.art == "empfaenger" and b.bestaetigen for b in erg2.befunde)
    # nach Ergänzung von K2: keine Warnung zu fehlenden Anlagen
    k2 = pdf(tmp_path / "Anlage_K2.pdf", "Gutachten")
    erg3 = pruefen("schaden@fiktiva.example", "2026/0815", p, schrift,
                   [(k1, "Anlage K1"), (k2, "Anlage K2"), (k3, "Anlage K3")])
    assert not erg3.zu_bestaetigen and erg3.schlimmste in ("ok", "hinweis")


def test_grenzen_scan_doppelt_fehlend_nicht_unterstuetzt(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    scan = tmp_path / "Scan.pdf"
    d = pymupdf.open()
    d.new_page()
    d.save(scan)                                                     # PDF ohne Text
    a = pdf(tmp_path / "A.pdf", "x")
    kopie = tmp_path / "A_kopie.pdf"
    kopie.write_bytes(a.read_bytes())
    weg = tmp_path / "weg.pdf"
    bild = tmp_path / "Foto.jpg"
    bild.write_bytes(b"\xff\xd8\xff fiktiv")
    erg = pruefen("schaden@fiktiva.example", "", None, scan, [(a, "Anlage K1"), (kopie, "Anlage K2"),
                                                              (weg, "Anlage K3"), (bild, "Anlage K4")])
    arten = {(b.art, b.stufe) for b in erg.befunde}
    assert ("anlage_fehlt", "nicht_geprueft") in arten          # Scan ≠ „keine Verweise“
    assert ("doppelt", "warnung") in arten and ("lesbar", "fehler") in arten
    assert ("metadaten", "nicht_geprueft") in arten              # JPG: Metadaten nicht geprüft
    assert ("empfaenger", "nicht_geprueft") in arten             # ohne Akte nicht abgeglichen
    assert not any(b.stufe == "ok" and b.art == "anlage_fehlt" for b in erg.befunde)


def test_word_kommentare_aenderungen_metadaten_bereinigen(tmp_path):
    orig = docx(tmp_path / "Brief.docx", ["Sehr geehrte Damen und Herren,", "anbei Anlage K1."], autor="Bora Test",
                kommentar=True)
    vorher = orig.read_bytes()
    e = docx_eigenschaften(orig)
    assert e["kommentare"] == 1 and e["aenderungen"] == 0 and e["metadaten"]["creator"] == "Bora Test"
    erg = pruefen("a@example.com", "", None, orig, [])
    assert any(b.art == "word_kommentar" for b in erg.befunde) and str(orig) in erg.metadaten
    ziel = tmp_path / "versand" / "Brief.docx"
    ziel.parent.mkdir()
    b = bereinigen(orig, ziel, kommentare_entfernen=True)
    assert b.ok and "creator" in b.entfernt and any("Kommentar" in x for x in b.entfernt)
    neu = docx_eigenschaften(ziel)
    assert neu["kommentare"] == 0 and "creator" not in neu["metadaten"]
    assert docx_volltext(ziel) == docx_volltext(orig)
    assert orig.read_bytes() == vorher                                         # Original unverändert
    # Änderungsnachverfolgung: nie still annehmen/ablehnen → keine Bereinigung
    mit = docx(tmp_path / "Mit_Aenderung.docx", ["Text"], aenderung=True)
    assert docx_eigenschaften(mit)["aenderungen"] == 1
    b2 = bereinigen(mit, tmp_path / "versand" / "Mit_Aenderung.docx")
    assert not b2.ok and b2.kopie is None and "in Word entscheiden" in b2.text
    assert not (tmp_path / "versand" / "Mit_Aenderung.docx").exists()


def test_pdf_metadaten_bereinigen_in_kopie(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    p = tmp_path / "Anlage.pdf"
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "Rechnung Nr. 1")
    d.set_metadata({"author": "Sachbearbeiter X", "title": "intern"})
    d.save(p)
    b = bereinigen(p, tmp_path / "Kopie.pdf")
    assert b.ok and "author" in b.entfernt
    with pymupdf.open(b.kopie) as k, pymupdf.open(p) as o:
        assert not k.metadata.get("author") and o.metadata["author"] == "Sachbearbeiter X"
        assert k[0].get_text() == o[0].get_text()


def test_versandnachweis_kopien_bestaetigung_und_aenderung(tmp_path):
    j = Journal(tmp_path / "verlauf.sqlite")
    j.akte_speichern("2026/0815", mandant_name="Erika Erfunden")
    un, vs = Unterlagen(j.con), Versand(j.con)
    tok = pr.setzen(pr.Benutzer("anna", "sekretariat", "Anna"))
    try:
        e = un.anlegen("e-1", "2026/0815", "Vollmacht")
        orig = tmp_path / "Anlage_K1.pdf"
        orig.write_bytes(b"%PDF v1")
        kopien = feste_kopien([orig], tmp_path / "Versand" / "1")
        datei = {"position": 0, "rolle": "anlage", "bezeichnung": "Anlage K1", "name": kopien[0].name,
                 "original_pfad": str(orig), "original_sha256": __import__("hashlib").sha256(b"%PDF v1").hexdigest(),
                 "sha256": __import__("hashlib").sha256(b"%PDF v1").hexdigest(), "kopie_pfad": str(kopien[0])}
        v = vs.anlegen("v-1", "2026/0815", "erika@example.com", "mandant", "Fehlende Unterlagen", [datei],
                       akzeptiert=[{"text": "K2 fehlt", "art": "anlage_fehlt", "begruendung": "wird nachgereicht"}],
                       erwartungen=[e["id"]])
        assert v["status"] == "entwurf_erstellt" and v["akzeptiert"][0]["benutzer"] == "anna"
        assert vs.anlegen("v-1", "2026/0815", "x@example.com", "", "anders", [])["id"] == v["id"]   # Wiederholung
        # Entwurf ≠ angefordert
        assert un.erwartung(e["id"])["status"] == "nicht_angefordert"
        # Original wird im Archiv geändert → Versandkopie bleibt, Änderung wird erkannt
        orig.write_bytes(b"%PDF v2")
        assert kopien[0].read_bytes() == b"%PDF v1"
        import hashlib
        aend = aenderungen_seit_entwurf(v, lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest())
        assert aend and "seit dem Entwurf geändert" in aend[0]
        # neuer Entwurf an denselben Empfänger → alter bleibt erhalten, gilt als ersetzt
        v2 = vs.anlegen("v-2", "2026/0815", "erika@example.com", "mandant", "Fehlende Unterlagen (neu)", [datei])
        alt = vs.eintrag(v["id"])
        assert alt["status"] == "entwurf_erstellt" and not alt["gueltig"] and alt["ersetzt_durch"] == v2["id"]
        # Outlook-Abgleich: falsche Anhänge → nicht bestätigt; passende → bestätigt mit Quelle
        k_falsch = {"betreff": "x", "empfaenger": ["erika@example.com"], "anhaenge": [("Anlage_K1.pdf", "abc")],
                    "gesendet_am": (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")}
        assert not gesendet_passt(v, k_falsch)[0]
        k_ok = dict(k_falsch, anhaenge=[("Anlage_K1.pdf", datei["sha256"])])
        ok, text = gesendet_passt(v, k_ok)
        assert ok and "Gesendete Elemente" in text and "Betreff im Gesendet-Ordner" in text
        b = vs.bestaetigen(v["id"], "outlook_gesendet", text)
        assert b["status"] == "versand_bestaetigt" and b["quelle_text"].startswith("Outlook")
        assert vs.bestaetigen(v["id"], "manuell")["bestaetigt_am"] == b["bestaetigt_am"]          # Wiederholung
        # bestätigter Versand → verknüpfte Unterlage gilt als angefordert (Quelle sichtbar)
        ee = un.erwartung(e["id"])
        assert ee["status"] == "angefordert" and ee["angefordert_quelle"] == "versand_bestaetigt"
        with pytest.raises(ValueError):
            vs.nicht_bestaetigt(v["id"])
        assert vs.nicht_bestaetigt(v2["id"], "verworfen")["status"] == "versand_nicht_bestaetigt"
        assert [x["id"] for x in vs.liste("2026/0815")] == [v2["id"], v["id"]]               # nichts überschrieben
    finally:
        pr.zuruecksetzen(tok)


def test_versandreihenfolge_akte_schriftsatz_dann_anlagen():
    pytest.importorskip("PySide6")
    from ui.versand_ui import versandreihenfolge
    ps = [Path(n) for n in ("Anlage_K2.pdf", "Anlage_K3.pdf", "Anlage_K1.pdf", "Erwiderung.docx", "Anlage_K10.pdf")]
    assert [p.name for p in versandreihenfolge(ps)] == ["Erwiderung.docx", "Anlage_K1.pdf", "Anlage_K2.pdf",
                                                         "Anlage_K3.pdf", "Anlage_K10.pdf"]
