"""Anlagen-Assistent: Einlesen, Nummerierung, Hinweise, Paket (ohne Word/Outlook)."""
import email
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pymupdf = pytest.importorskip("pymupdf")
from core import anlagen as an  # noqa: E402
from core import pdf_engine as pe  # noqa: E402
from core.docx_schreiben import docx_tabelle_lesen  # noqa: E402
from core.mail_service import EmlDrafter, MailDraft, anhaenge_vergleichen, eml_anhaenge  # noqa: E402


def _pdf(pfad: Path, text: str, seiten: int = 1) -> Path:
    d = pymupdf.open()
    for i in range(seiten):
        fuell = " ".join(f"{text.split()[0].lower()}wort{k}" for k in range(6))
        d.new_page().insert_text((72, 100 + 20 * i), f"{text} – Seite {i + 1} {fuell}", fontsize=12)
    d.save(pfad)
    return pfad


def _bild(pfad: Path) -> Path:
    d = pymupdf.open()
    p = d.new_page(width=400, height=300)
    p.draw_rect(pymupdf.Rect(20, 20, 380, 280), color=(0, 0, 1), fill=(0.8, 0.9, 1))
    p.get_pixmap(dpi=72).save(pfad)
    return pfad


@pytest.fixture
def dateien(tmp_path):
    q = tmp_path / "quelle"
    q.mkdir()
    s = _pdf(q / "Klageschrift.pdf", "Klageschrift", 2)
    a = [_pdf(q / "01_Vertrag_Mustermann.pdf", "Vertrag", 3), _bild(q / "Schadenfoto.png"),
         _pdf(q / "Rechnung.pdf", "Rechnung Werkstatt")]
    dup = q / "Vertrag_Kopie.pdf"
    dup.write_bytes(a[0].read_bytes())
    kaputt = q / "kaputt.pdf"
    kaputt.write_bytes(b"%PDF-1.4\nnicht lesbar")
    return s, a, dup, kaputt


def test_einlesen_und_titel(dateien):
    s, a, dup, kaputt = dateien
    e = an.einlesen(a[0])
    assert (e.titel, e.seiten, e.art, e.ok) == ("Vertrag Mustermann", 3, "pdf", True)
    b = an.einlesen(a[1])
    assert b.art == "bild" and b.seiten == 1 and b.ok
    k = an.einlesen(kaputt)
    assert not k.ok and "beschädigt" in k.fehler


def test_nummern_und_dateinamen():
    bez = an.bezeichnungen(3, "Anlage K", 4)
    assert bez == ["Anlage K4", "Anlage K5", "Anlage K6"]
    assert an.dateiname("Anlage K4") == "Anlage_K4.pdf"
    assert an.dateiname("Anlage B 2") == "Anlage_B_2.pdf"
    assert an.mail_betreff("Klageschrift", bez) == "Klageschrift nebst Anlage K4 bis K6"


def test_hinweise_identisch_aehnlich_fehler(dateien):
    s, a, dup, kaputt = dateien
    anl = [an.einlesen(p) for p in [*a, dup, kaputt]]
    h = an.pruefen(an.einlesen(s), anl)
    arten = [x.art for x in h]
    assert arten.count("identisch") == 1 and not an.blockiert(h)       # 0.4.1: nur Hinweis, kein Stopp
    assert any("kaputt.pdf" in x.text and an.ORIGINAL_TEXT in x.text for x in h)
    # optisch ähnlich: gleiche Seite als Scan (andere Bytes)
    scan = pymupdf.open()
    for seite in pymupdf.open(a[0]):
        sp = scan.new_page()
        sp.insert_image(sp.rect, pixmap=seite.get_pixmap(dpi=90))
    sp_pfad = a[0].with_name("Vertrag_Scan.pdf")
    scan.save(sp_pfad)
    scan_e = an.einlesen(sp_pfad)
    assert not scan_e.worte                                 # Scan ohne Text
    probe = [(w, 90.0, 0, 0, 1, 1, 1, 1, 1) for w in pymupdf.open(a[0])[0].get_text().split()]
    an.textprobe_ergaenzen(scan_e, lambda png, dpi: probe)  # OCR-Probe (hier simuliert)
    h2 = an.pruefen(an.einlesen(s), [an.einlesen(a[0]), scan_e])
    assert [x.art for x in h2] == ["aehnlich"] and not an.blockiert(h2)


def _word_stub(quelle, ziel):
    _pdf(ziel, "aus Word")


def test_paket_reihenfolge_namen_verzeichnis(dateien, tmp_path):
    s, a, dup, kaputt = dateien
    anl = [an.einlesen(p) for p in a]
    anl = [anl[2], anl[0], anl[1]]                     # Nutzer hat umsortiert
    anl[0].titel = "Werkstattrechnung"
    bez = an.bezeichnungen(len(anl))
    vorher = {p: p.read_bytes() for p in [s, *a]}
    paket = an.paket_erstellen(tmp_path / "aus", an.einlesen(s), anl, bez, _word_stub, gesamt_pdf=True)
    namen = [d.pfad.name for d in paket.dateien]
    assert namen == ["Schriftsatz.pdf", "Anlage_K1.pdf", "Anlage_K2.pdf", "Anlage_K3.pdf",
                     "Anlagenverzeichnis.docx", "Gesamt_zur_internen_Pruefung.pdf"]
    assert "Rechnung Werkstatt" in pymupdf.open(paket.dateien[1].pfad)[0].get_text()
    zeilen = docx_tabelle_lesen(paket.ordner / "Anlagenverzeichnis.docx")
    assert zeilen == [["Anlage", "Bezeichnung", "Seiten"], ["Anlage K1", "Werkstattrechnung", "1"],
                      ["Anlage K2", "Vertrag Mustermann", "3"], ["Anlage K3", "Schadenfoto", "1"]]
    g = pymupdf.open(paket.ordner / an.GESAMT)
    assert g.page_count == 2 + 1 + 3 + 1 and g.get_toc()[1][1] == "Anlage K1 – Werkstattrechnung"
    assert all(p.read_bytes() == b for p, b in vorher.items())          # Originale unverändert
    assert not list(paket.ordner.glob(".bnx-paket-*"))
    # zweiter Lauf: nichts wird überschrieben
    with pytest.raises(an.Namenskonflikt) as k:
        an.paket_erstellen(paket.ordner, an.einlesen(s), anl, bez, _word_stub)
    assert k.value.vorschlag[1].name == "Anlage_K1_2.pdf"
    p2 = an.paket_erstellen(paket.ordner, an.einlesen(s), anl, bez, _word_stub, umbenennen_erlaubt=True)
    assert p2.dateien[0].pfad.name == "Schriftsatz_2.pdf"


def test_paket_word_fehler_original_uebernommen(dateien, tmp_path):
    """Hauptdokument nicht umwandelbar → Original (Name, Endung, Inhalt) im Paket, nichts bricht ab."""
    s, a, dup, kaputt = dateien
    word = tmp_path / "Schriftsatz.docx"
    word.write_bytes(b"PK fake")
    se = an.einlesen(word)

    def word_fehler(q, z):
        raise RuntimeError("Word hängt")
    ziel = tmp_path / "aus2"
    p = an.paket_erstellen(ziel, se, [an.einlesen(a[0]), an.einlesen(kaputt)], ["Anlage K1", "Anlage K2"],
                           word_fehler)
    namen = sorted(x.name for x in ziel.iterdir())
    assert namen == ["Anlage_K1.pdf", "Anlagenverzeichnis.docx", "Schriftsatz.docx", "kaputt.pdf"]
    assert (ziel / "kaputt.pdf").read_bytes() == kaputt.read_bytes()
    assert (ziel / "Schriftsatz.docx").read_bytes() == b"PK fake"
    assert any("kaputt.pdf" in h and "Gesamt-PDF" in h for h in p.hinweise)
    assert docx_tabelle_lesen(ziel / "Anlagenverzeichnis.docx")[2] == ["Anlage K2", "Kaputt (Originaldatei)", "–"]
    assert not list(ziel.glob(".~*")) and not list(ziel.glob(".bnx-*"))


def test_paket_ohne_hauptdokument_und_unlesbare_quelle(dateien, tmp_path):
    s, a, dup, kaputt = dateien
    weg = an.einlesen(a[2])
    weg.fehler, weg.sha256 = "Datei kann nicht gelesen werden (Zugriff verweigert)", ""
    p = an.paket_erstellen(tmp_path / "aus", None, [an.einlesen(a[0]), weg, an.einlesen(dup)],
                           an.bezeichnungen(3), _word_stub, gesamt_pdf=True)
    namen = [d.pfad.name for d in p.dateien if d.rolle != "fehlt"]
    assert namen == ["Anlage_K1.pdf", "Anlage_K3.pdf", "Anlagenverzeichnis.docx", an.GESAMT]
    assert any("Anlage K2" in h and "NICHT kopiert" in h for h in p.hinweise)
    zeilen = docx_tabelle_lesen(p.ordner / "Anlagenverzeichnis.docx")
    assert zeilen[2][0] == "Anlage K2" and "nicht kopiert" in zeilen[2][1]
    assert pymupdf.open(p.ordner / an.GESAMT).page_count == 6              # identische Datei bleibt drin


def test_ablegen_wartet_auf_vorübergehende_sperre(tmp_path, monkeypatch):
    """Wie OneDrive: Umbenennen scheitert zweimal mit „Zugriff verweigert“, danach klappt es."""
    q = tmp_path / "q.pdf"
    q.write_bytes(b"%PDF-1.4 x")
    ziel = tmp_path / "ziel" / "Schriftsatz.pdf"
    ziel.parent.mkdir()
    echt = an.os.rename
    fehl = {"n": 0}

    def rename(a_, b_):
        if fehl["n"] < 2:
            fehl["n"] += 1
            raise PermissionError(5, "Zugriff verweigert")
        echt(a_, b_)
    monkeypatch.setattr(an.os, "rename", rename)
    pausen = []
    an.ablegen(q, ziel, warte=pausen.append)
    assert ziel.read_bytes() == b"%PDF-1.4 x" and len(pausen) == 2
    assert not list(ziel.parent.glob(".~*"))


def test_ablegen_dauerhafte_sperre_nennt_datei_und_raeumt_auf(dateien, tmp_path, monkeypatch):
    s, a, dup, kaputt = dateien
    ziel = tmp_path / "aus"
    ziel.mkdir()
    alt = ziel / "Notiz.txt"
    alt.write_text("bleibt")
    echt = an.os.rename

    def rename(a_, b_):
        if str(b_).endswith("Anlage_K2.pdf"):
            raise PermissionError(5, "Zugriff verweigert")
        echt(a_, b_)
    monkeypatch.setattr(an.os, "rename", rename)
    with pytest.raises(an.AblageFehler) as f:
        an.paket_erstellen(ziel, an.einlesen(s), [an.einlesen(a[0]), an.einlesen(a[2])], an.bezeichnungen(2),
                           _word_stub, warte=lambda s_: None)
    assert f.value.datei.name == "Anlage_K2.pdf" and "Zugriff verweigert" in str(f.value)
    assert sorted(x.name for x in ziel.iterdir()) == ["Notiz.txt"]       # nichts halb Fertiges, Altes unverändert
    assert alt.read_text() == "bleibt"


def test_anhaenge_vergleich_und_eml(tmp_path):
    a = _pdf(tmp_path / "Anlage_K1.pdf", "A")
    b = _pdf(tmp_path / "Anlage_K2.pdf", "B")
    msg = EmlDrafter().build(MailDraft("x@example.com", "S", "<p>x</p>", [a, b]))
    eml = tmp_path / "e.eml"
    eml.write_bytes(bytes(msg))
    assert anhaenge_vergleichen(eml_anhaenge(eml), [a, b]) == []
    assert anhaenge_vergleichen(eml_anhaenge(eml), [b, a])          # falsche Reihenfolge erkannt
    assert email.message_from_bytes(eml.read_bytes())["X-Unsent"] == "1"


def test_word_anlage_wird_sofort_umgewandelt(dateien, tmp_path):
    s, a, dup, kaputt = dateien
    klage = tmp_path / "Klageschrift_Muster.docx"
    vollmacht = tmp_path / "Vollmacht.docx"
    for f in (klage, vollmacht):
        f.write_bytes(b"PK fake docx " + f.name.encode())
    aufrufe = []

    def word(q, z):
        aufrufe.append(q.name)
        _pdf(z, f"Word {q.stem}", 2)
    eintraege = [an.einlesen(vollmacht), an.einlesen(klage)]
    assert an.schriftsatz_vorschlag(eintraege).quelle == klage        # Name entscheidet, nicht Reihenfolge
    v = eintraege[0]
    assert an.word_umwandeln(v, word) and v.seiten == 2 and v.daten
    assert "Word Vollmacht" in v.dokument()[0].get_text()
    paket = an.paket_erstellen(tmp_path / "aus", eintraege[1], [an.einlesen(a[0]), v],
                               ["Anlage K1", "Anlage K2"], word)
    assert aufrufe == ["Vollmacht.docx", "Klageschrift_Muster.docx"]     # Anlage nicht doppelt umgewandelt
    k2 = [d for d in paket.dateien if d.bezeichnung == "Anlage K2"][0]
    assert k2.pfad.name == "Anlage_K2.pdf" and k2.seiten == 2
    assert docx_tabelle_lesen(paket.ordner / "Anlagenverzeichnis.docx")[2] == ["Anlage K2", "Vollmacht", "2"]


def test_word_umwandlung_fehler_wird_original(tmp_path):
    f = tmp_path / "Vollmacht.docx"
    f.write_bytes(b"PK")
    e = an.einlesen(f)

    def kaputt(q, z):
        raise RuntimeError("Word konnte nicht gestartet werden")
    assert not an.word_umwandeln(e, kaputt)
    assert "Word-Umwandlung fehlgeschlagen" in e.fehler
    h = an.pruefen(None, [e])
    assert not an.blockiert(h) and h[0].art == "original"


def test_drehen_volle_runde_und_paket(dateien, tmp_path):
    """4× rechts = volle Runde; mehrere Seiten je aus eigenem Winkel; Paket + Gesamt-PDF wie die Vorschau."""
    s, a, dup, kaputt = dateien
    e = an.einlesen(a[0])                                  # 3 Seiten
    vorher = a[0].read_bytes()
    winkel = []
    for _ in range(4):
        winkel.append(an.seiten_drehen_schritte(e, {0: 1})[0])
    assert winkel == [90, 180, 270, 0]
    an.seiten_drehen_schritte(e, {1: 1})                  # Seite 2 steht jetzt auf 90°
    neu = an.seiten_drehen_schritte(e, {0: 3, 1: 1, 2: -1})
    assert neu == {0: 270, 1: 180, 2: 270}
    p = an.paket_erstellen(tmp_path / "aus", None, [e], ["Anlage K1"], _word_stub, gesamt_pdf=True)
    assert [x.rotation for x in pymupdf.open(p.ordner / "Anlage_K1.pdf")] == [270, 180, 270]
    assert [x.rotation for x in pymupdf.open(p.ordner / an.GESAMT)] == [270, 180, 270]
    assert a[0].read_bytes() == vorher                     # Original unverändert
