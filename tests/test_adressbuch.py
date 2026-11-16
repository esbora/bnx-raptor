"""Versicherer-Adressbuch (0.3.0) – saf Python testleri, Word/Outlook gerekmez."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import adressbuch as ab  # noqa: E402
from core.adressbuch import (Adressbuch, email_vorschlag, passt, schluessel,  # noqa: E402
                             versicherer_aus_text, versicherer_erkennen)
from core.config import DEFAULTS  # noqa: E402
from core.extractor import extract, find_number  # noqa: E402
from core.journal import Journal  # noqa: E402
from core.kanzlei import Kanzlei, KanzleiStore  # noqa: E402
from workflows import versicherung_brief as vb  # noqa: E402
from workflows.base import AppContext  # noqa: E402

ABK = DEFAULTS["versicherer_abkuerzungen"]
STICH = DEFAULTS["versicherer_stichwoerter"]


def gleich(a: str, b: str) -> bool:
    return passt(schluessel(a, ABK), schluessel(b, ABK))


# --- Ad eşleştirme -----------------------------------------------------------
@pytest.mark.parametrize("variante", [
    "Fiktiva Versicherung AG", "FIKTIVA VERSICHERUNG AG", "Fiktiva Versicherungs-AG",
    "Fiktiva Vers. AG", "Fiktiva Versich. AG", "Fiktiva Versicherung Aktiengesellschaft",
    "Fiktiva  Versicherung   AG", "Firma Fiktiva Versicherung AG", "Fiktiva Versicherung",
])
def test_schreibvarianten_und_abkuerzungen_passen(variante):
    assert gleich("Fiktiva Versicherung AG", variante)


def test_umlaute_passen():
    assert gleich("Württembergische Versicherung AG", "Wuerttembergische Versicherung AG")
    assert gleich("Rheinische Allg. Versicherung AG", "Rheinische Allgemeine Versicherung AG")


@pytest.mark.parametrize("a,b", [
    ("Allianz Versicherungs-AG", "Allianz Lebensversicherungs-AG"),
    ("HUK-COBURG Allgemeine Versicherung AG", "HUK-COBURG-Rechtsschutzversicherung AG"),
    ("Fiktiva Versicherung AG", "Fiktiva Versicherung SE"),
    ("Fiktiva Versicherung AG", "Fiktiva Versicherung a.G."),
    ("Fiktiva Versicherung AG", "Fiktiva Direkt Versicherung AG"),
    ("Fiktiva Versicherung AG", "Fiktivia Versicherung AG"),        # tek harf farkı = başka şirket
])
def test_aehnliche_firmen_werden_nicht_zusammengefuehrt(a, b):
    assert not gleich(a, b)


# --- Adres bloğundan ad bulma -------------------------------------------------
BRIEF_A = "\r".join([
    "TESTKANZLEI Fiktiv & Partner (Testprofil)", "Erfundene Straße 1 · 12345 Musterstadt",
    "Tel. 0000 000000 · E-Mail: test@kanzlei-muster.example.net", "",
    "Fiktiva Versicherung AG (fiktiv)", "Schadenabteilung", "Ausgedachter Weg 99", "54321 Nirgendwo", "",
    "Per E-Mail: schaden.fiktiva@example.com", "", "Musterstadt, 16.11.2026", "",
    "Unser Zeichen: 0815/26 TB", "Ihr Versicherungsnehmer: Erika Erfunden (fiktiv)",
    "Versicherungsnummer: FV-4711-2026-0815", "Schaden-Nr.: SCH 2026/99123", "",
    "Sehr geehrte Damen und Herren,",
])


def test_name_aus_adressblock():
    assert versicherer_aus_text(BRIEF_A, STICH) == "Fiktiva Versicherung AG (fiktiv)"


def test_eigene_kanzleianschrift_wird_uebersprungen():
    text = "\r".join(["Kanzlei für Versicherungsrecht Muster", "Hauptstr. 1", "12345 Musterstadt", "",
                      "Beispiel Assekuranz AG", "Postfach 10 20 30", "50667 Köln"])
    assert versicherer_aus_text(text, STICH, kanzlei_name="Kanzlei für Versicherungsrecht Muster",
                                kanzlei_plz="12345") == "Beispiel Assekuranz AG"


def test_ihr_zeichen_wird_nicht_ausgewertet():
    # Adres bloğu yok; "Ihr Zeichen" satırındaki şirket adından tahmin yapılmaz
    text = "\r".join(["Ihr Zeichen: Allianz Versicherungs-AG 4711", "Versicherungsnummer: 123-456"])
    assert versicherer_aus_text(text, STICH) == ""


def test_adressblock_ohne_versicherer_ergibt_nichts():
    text = "\r".join(["Herrn", "Max Gegner", "Feldweg 3", "54321 Nirgendwo"])
    assert versicherer_aus_text(text, STICH) == ""


def test_zusatzzeilen_und_weicher_zeilenumbruch():
    text = "Per E-Mail vorab\x0bz. Hd. Frau Schmidt\x0bHDI Global SE\x0bHDI-Platz 1\x0b30659 Hannover"
    assert versicherer_aus_text(text, STICH) == "HDI Global SE"


def test_abgekuerzter_name_im_adressblock_wird_erkannt():
    # Windows-Test 0.3.0, Brief C: "FIKTIVA Vers. AG" wurde nicht als Versicherer erkannt
    text = "\r".join(["FIKTIVA Vers. AG", "Kfz-Schaden", "Ausgedachter Weg 99", "54321 Nirgendwo", "",
                      "Schaden-Nr.: SCH 2026/77777"])
    abk = DEFAULTS["versicherer_abkuerzungen"]
    assert versicherer_aus_text(text, STICH, abkuerzungen=abk) == "FIKTIVA Vers. AG"
    assert versicherer_erkennen(text, {}, DEFAULTS)[0] == "FIKTIVA Vers. AG"
    assert passt(schluessel("FIKTIVA Vers. AG", abk), schluessel("Fiktiva Versicherung AG (fiktiv)", abk))


def test_kurzes_stichwort_nur_als_ganzes_wort():
    # "axa" "Saxana" kelimesinin içinde -> sigorta sayılmaz
    text = "\r".join(["Saxana Handels GmbH", "Weg 1", "54321 Nirgendwo"])
    assert versicherer_aus_text(text, STICH) == ""


def test_inhaltssteuerelement_hat_vorrang_und_quelle():
    name, hint = versicherer_erkennen(BRIEF_A, {"Versicherer": "Beispiel Assekuranz AG"}, DEFAULTS)
    assert (name, hint) == ("Beispiel Assekuranz AG", "aus Vorlage")
    name, hint = versicherer_erkennen(BRIEF_A, {}, DEFAULTS)
    assert hint == "erkannt – bitte prüfen"
    assert versicherer_erkennen("kein Adressblock", {}, DEFAULTS)[0] == ""


# --- E-posta önerisi ---------------------------------------------------------
def test_brief_ohne_adressbuch():
    v = email_vorschlag("a@ex.com", "erkannt – bitte prüfen", ["a@ex.com"], [])
    assert (v.wert, v.muss_waehlen) == ("a@ex.com", False)


def test_brief_adresse_steht_auch_im_adressbuch():
    v = email_vorschlag("a@ex.com", "aus Vorlage", ["a@ex.com"], [("b@ex.com", "X AG"), ("A@ex.com", "X AG")])
    assert (v.wert, v.hint, v.muss_waehlen) == ("a@ex.com", "aus Vorlage", False)


def test_keine_adresse_im_brief_ein_eintrag():
    v = email_vorschlag("", "", [], [("b@ex.com", "X AG")])
    assert (v.wert, v.hint, v.muss_waehlen) == ("b@ex.com", "aus Adressbuch – bitte prüfen", False)


def test_keine_adresse_im_brief_mehrere_eintraege_muss_waehlen():
    v = email_vorschlag("", "", [], [("b@ex.com", "X AG"), ("c@ex.com", "X AG")])
    assert v.wert == "" and v.muss_waehlen
    assert [a for a, _ in v.auswahl] == ["b@ex.com", "c@ex.com"]


def test_abweichung_brief_und_adressbuch_beide_mit_quelle():
    v = email_vorschlag("neu@ex.com", "erkannt – bitte prüfen", ["neu@ex.com"], [("alt@ex.com", "X AG")])
    assert v.wert == "" and v.muss_waehlen
    assert v.auswahl == [("neu@ex.com", "aus Brief – bitte prüfen"),
                         ("alt@ex.com", "aus Adressbuch – bitte prüfen (X AG)")]


def test_nichts_gefunden():
    v = email_vorschlag("", "", [], [])
    assert (v.wert, v.hint, v.muss_waehlen) == ("", "nicht gefunden", False)


# --- Kayıt ------------------------------------------------------------------
@pytest.fixture
def buch(tmp_path):
    return Adressbuch(Journal(tmp_path / "v.sqlite").con, ABK)


def test_lernen_ohne_doppelte_zeilen(buch):
    assert buch.lernen("Fiktiva Versicherung AG", "schaden@ex.com") == "neu"
    assert buch.lernen("FIKTIVA Vers. AG", "Schaden@ex.com") == "aktualisiert"
    assert len(buch.alle()) == 1 and buch.alle()[0]["anzahl"] == 2
    assert buch.alle()[0]["name"] == "Fiktiva Versicherung AG"      # ilk yazım korunur


def test_mehrere_adressen_je_versicherer(buch, monkeypatch):
    zeiten = iter(["2026-01-01 10:00:00", "2026-02-01 10:00:00"])
    monkeypatch.setattr(ab, "_jetzt", lambda: next(zeiten))
    buch.lernen("Fiktiva Versicherung AG", "kfz@ex.com")
    buch.lernen("Fiktiva Versicherung AG", "leben@ex.com")
    assert [a for a, _ in buch.emails("Fiktiva Vers. AG")] == ["leben@ex.com", "kfz@ex.com"]


def test_aehnliche_firma_bekommt_eigenen_eintrag(buch):
    buch.lernen("Allianz Versicherungs-AG", "sach@ex.com")
    buch.lernen("Allianz Lebensversicherungs-AG", "leben@ex.com")
    assert len(buch.alle()) == 2
    assert buch.emails("Allianz Versicherungs-AG") == [("sach@ex.com", "Allianz Versicherungs-AG")]


def test_leere_werte_werden_nicht_gelernt(buch):
    assert buch.lernen("", "a@ex.com") == "" and buch.lernen("X AG", "") == ""
    assert buch.alle() == []


def test_aendern_hinzufuegen_loeschen(buch):
    eid = buch.hinzufuegen("Beispiel Assekuranz AG", "a@ex.com")
    with pytest.raises(ValueError):
        buch.hinzufuegen("Beispiel Assekuranz AG", "A@ex.com")
    eid2 = buch.hinzufuegen("Beispiel Assekuranz AG", "b@ex.com")
    with pytest.raises(ValueError):
        buch.aendern(eid2, "Beispiel Assekuranz AG", "a@ex.com")   # ikinci satır birinciyle aynı olamaz
    buch.aendern(eid, "Beispiel Assekuranz AG", "neu@ex.com")
    buch.loeschen(eid2)
    assert [(e["name"], e["email"]) for e in buch.alle()] == [("Beispiel Assekuranz AG", "neu@ex.com")]


def test_tabelle_kommt_zu_alter_datenbank_hinzu(tmp_path):
    j = Journal(tmp_path / "v.sqlite")
    j.akte_speichern("AS-1", versicherer_email="x@ex.com")
    Adressbuch(j.con).lernen("X AG", "x@ex.com")
    assert j.akte("AS-1")["versicherer_email"] == "x@ex.com"       # mevcut veriler etkilenmez


# --- İş akışı: alanlar ve öğrenme zamanı --------------------------------------
@pytest.fixture
def ctx(tmp_path):
    store = KanzleiStore(tmp_path / "d")
    store.speichern(Kanzlei(name="TESTKANZLEI Fiktiv & Partner", plz="12345",
                            email="test@kanzlei-muster.example.net"))
    return AppContext(dict(DEFAULTS), store, Journal(tmp_path / "v.sqlite"))


def felder(ctx, text, controls=None):
    return {f.key: f for f in vb.VersicherungBrief(ctx).felder(text, controls or {})}


def test_felder_mit_versicherer_und_quelle(ctx):
    f = felder(ctx, BRIEF_A)
    assert f["versicherer"].value == "Fiktiva Versicherung AG (fiktiv)"
    assert f["versicherer"].hint == "erkannt – bitte prüfen"
    assert f["empfaenger"].value == "schaden.fiktiva@example.com"
    assert f["nummer"].value == "FV-4711-2026-0815"


def test_felder_brief_ohne_email_nutzt_adressbuch(ctx):
    ctx.adressbuch.lernen("Fiktiva Versicherung AG", "gelernt@example.com")
    text = BRIEF_A.replace("Per E-Mail: schaden.fiktiva@example.com", "")
    e = felder(ctx, text)["empfaenger"]
    assert (e.value, e.hint, e.must_choose) == ("gelernt@example.com", "aus Adressbuch – bitte prüfen", False)


def test_felder_abweichung_muss_gewaehlt_werden(ctx):
    ctx.adressbuch.lernen("Fiktiva Versicherung AG", "alt@example.com")
    e = felder(ctx, BRIEF_A)["empfaenger"]
    assert e.value == "" and e.must_choose
    assert e.choice_hints["schaden.fiktiva@example.com"].startswith("aus Brief")
    assert e.choice_hints["alt@example.com"].startswith("aus Adressbuch")


def test_name_korrigiert_aktualisiert_vorschlag(ctx):
    ctx.adressbuch.lernen("Beispiel Assekuranz AG", "b@example.com")
    text = BRIEF_A.replace("Per E-Mail: schaden.fiktiva@example.com", "")
    f = felder(ctx, text)
    assert f["empfaenger"].value == ""
    neu = f["versicherer"].on_change("Beispiel Assekuranz AG")[0]
    assert (neu.key, neu.value) == ("empfaenger", "b@example.com")


class _WordDummy:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def export_pdf(self, path, pdf, pdfa=True):
        pdf.write_bytes(b"%PDF-1.7")


def _ausfuehren(ctx, tmp_path, monkeypatch, entwurf):
    monkeypatch.setattr(vb, "WordService", _WordDummy)
    monkeypatch.setattr(vb, "entwurf_erstellen", entwurf)
    doc = tmp_path / "Brief.docx"
    doc.write_bytes(b"x")
    return vb.VersicherungBrief(ctx).execute(doc, {
        "versicherer": "Fiktiva Versicherung AG", "empfaenger": "schaden.fiktiva@example.com",
        "nummer": "FV-4711-2026-0815", "mandant_email": ""})


def test_lernt_erst_nach_erfolgreichem_entwurf(ctx, tmp_path, monkeypatch):
    res = _ausfuehren(ctx, tmp_path, monkeypatch, lambda c, d, o: "Outlook-Entwurf geöffnet")
    assert res.ok and "Adressbuch: neuer Eintrag" in res.message
    assert ctx.adressbuch.emails("Fiktiva Versicherung AG") == [
        ("schaden.fiktiva@example.com", "Fiktiva Versicherung AG")]


def test_kein_lernen_bei_entwurfsfehler(ctx, tmp_path, monkeypatch):
    def fehler(c, d, o):
        raise RuntimeError("Outlook nicht erreichbar")
    with pytest.raises(RuntimeError):
        _ausfuehren(ctx, tmp_path, monkeypatch, fehler)
    assert ctx.adressbuch.alle() == []


# --- Madde 5: sigorta numarası ile hasar numarası aynı mektupta ----------------
@pytest.mark.parametrize("text", [
    "Versicherungsnummer: FV-4711-2026-0815\rSchaden-Nr.: SCH 2026/99123",
    "Schaden-Nr.: SCH 2026/99123\rVersicherungsnummer: FV-4711-2026-0815",   # hasar no. önce
    "Schadennummer SCH 2026/99123, Versicherungsschein-Nr. FV-4711-2026-0815",
    "Schaden-Nr.: SCH 2026/99123\rVS-Nr.: FV-4711-2026-0815",
])
def test_versicherungsnummer_hat_vorrang_vor_schadennummer(text):
    # CLAUDE.md / config: aranan alan "Versicherungsnummer"; Schaden-Nr. sadece yedek
    assert find_number(text, DEFAULTS["nummer_bezeichnungen"]) == "FV-4711-2026-0815"
    assert extract(text, {}, DEFAULTS).nummer == "FV-4711-2026-0815"


def test_schadennummer_nur_als_fallback():
    assert find_number("Schaden-Nr.: SCH 2026/99123", DEFAULTS["nummer_bezeichnungen"]) == "SCH 2026/99123"
