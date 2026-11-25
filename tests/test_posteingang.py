"""0.5 Kanzlei-Eingang + Was fehlt?: Kernlogik (ohne Netz, ohne Outlook) – nur fiktive Daten."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import protokoll as pr  # noqa: E402
from core.adressbuch import Adressbuch  # noqa: E402
from core.archiv import Archiv  # noqa: E402
from core.benutzer import Benutzerverwaltung, Berechtigung  # noqa: E402
from core.journal import Journal  # noqa: E402
from core.posteingang import (AktenInfo, Posteingang, akte_vorschlaege, belegart_vorschlag,  # noqa: E402
                              datum_vorschlag, eindeutig, nummer_im_text)
from core.stammdaten import Stammdaten  # noqa: E402
from core.unterlagen import Unterlagen, passende_erwartungen  # noqa: E402
from core.versand import Versand  # noqa: E402


@pytest.fixture
def welt(tmp_path):
    j = Journal(tmp_path / "verlauf.sqlite")
    con = j.con
    st = Stammdaten(con, Adressbuch(con))
    bv = Benutzerverwaltung(con)
    tok = pr.setzen(pr.Benutzer("chef", "admin", "Chefin"))
    bv.anlegen("chef", "Admin-Passwort-1", "admin", "Chefin")
    bv.anlegen("anna", "Sekretariat-1", "sekretariat", "Anna (Sekretariat)")
    bv.anlegen("ra", "Anwalt-Passwort-1", "anwalt", "RA Berger")
    m = st.mandant_speichern(None, name="Erika Erfunden", email="erika@example.com")
    m2 = st.mandant_speichern(None, name="Max Mustermann", email="max@example.com")
    v = st.versicherung_speichern(None, name="Fiktiva Versicherung AG")
    st.email_hinzufuegen(v, "schaden@fiktiva-versicherung.example")
    st.akte_anlegen("2026/0815", aktenzeichen="0815/26", mandant_id=m, versicherung_id=v,
                    versicherungsnummer="FV-4711-2026", schaden_nr="SCH 2026/99123",
                    mandant_email="erika@example.com", versicherer_email="schaden@fiktiva-versicherung.example")
    st.akte_anlegen("2026/0901", aktenzeichen="0901/26", mandant_id=m2, versicherung_id=v,
                    versicherungsnummer="FV-5522-2026", mandant_email="max@example.com",
                    versicherer_email="schaden@fiktiva-versicherung.example")
    pe, un, vs, ar = Posteingang(con), Unterlagen(con), Versand(con), Archiv(con)
    yield {"j": j, "con": con, "st": st, "pe": pe, "un": un, "vs": vs, "ar": ar, "tmp": tmp_path}
    pr.zuruecksetzen(tok)


def als(name, rolle):
    return pr.setzen(pr.Benutzer(name, rolle, name))


# ---------------------------------------------------------------- reine Regeln
def test_nummer_im_text_trennzeichen_und_keine_teiltreffer():
    assert nummer_im_text("Ihre Schaden-Nr.: SCH 2026/99123 vom", "SCH 2026/99123")
    assert nummer_im_text("Versicherungsnummer FV47112026", "FV-4711-2026")
    assert not nummer_im_text("Kontonummer 1FV-4711-20261", "FV-4711-2026")
    assert not nummer_im_text("abc", "12")


def test_vorschlag_nummer_eindeutig_absender_mehrdeutig():
    a1 = AktenInfo("A1", nummern=[("Versicherungsnummer", "FV-4711-2026")],
                   emails=[("Versicherung", "schaden@fiktiva.example")], namen=[("Mandant", "Erika Erfunden")])
    a2 = AktenInfo("A2", nummern=[("Versicherungsnummer", "FV-5522-2026")],
                   emails=[("Versicherung", "schaden@fiktiva.example")], namen=[("Mandant", "Max Mustermann")])
    v = akte_vorschlaege("Re: Versicherungsnummer FV-4711-2026", "schaden@fiktiva.example", [a1, a2])
    assert v[0]["referenz"] == "A1" and "FV-4711-2026" in v[0]["gruende"][0] and eindeutig(v)
    # nur Absender: zwei Akten derselben Versicherung → mehrdeutig, kein „sicherer“ Vorschlag
    v2 = akte_vorschlaege("Allgemeine Mitteilung", "schaden@fiktiva.example", [a1, a2])
    assert {x["referenz"] for x in v2} == {"A1", "A2"} and not eindeutig(v2)
    assert all("Absender" in x["gruende"][0] for x in v2)


def test_belegart_und_datum_sind_nur_vorschlaege():
    assert belegart_vorschlag("Unterlagen", ["Vollmacht_Erfunden.pdf"]) == "Vollmacht"
    assert belegart_vorschlag("Ihr Schreiben", [], "Sehr geehrte … Regulierung") == "Schreiben Versicherung"
    assert datum_vorschlag("Musterstadt, 31.02.2026 – nein; Schreiben vom 14.11.2026") == "2026-11-14"


# ---------------------------------------------------------------- Posteingang
def test_eingang_vorschlag_bestaetigen_und_doppelt(welt):
    pe, ar, tmp = welt["pe"], welt["ar"], welt["tmp"]
    f = tmp / "Antwort.pdf"
    f.write_bytes(b"%PDF-1.4 fiktiv")
    did = ar.erfassen(f, rolle="eingang")
    tok = als("anna", "sekretariat")
    try:
        erg = pe.anlegen("c-1", "eml", [{"rolle": "mail", "dokument_id": did, "name": f.name, "pfad": str(f),
                                         "sha256": "x1"}], quelle_id="<m1@fiktiva>", sha256="raw1",
                         absender="schaden@fiktiva-versicherung.example", betreff="Ihre Schaden-Nr. SCH 2026/99123",
                         text="Wir regulieren.")
        e = pe.eingang(erg["id"])
        assert e["akte"] == "" and e["vorschlag"][0]["referenz"] == "2026/0815" and e["eindeutig"]
        assert e["status"] == "neu" and e["erstellt_von"] == "anna"
        assert [x["id"] for x in pe.liste("nicht_zugeordnet")] == [erg["id"]]
        # Wiederholung (gleiche client_id) und Doppelimport (gleiche Message-ID) → nichts Neues
        assert pe.anlegen("c-1", "eml", [], quelle_id="<m1@fiktiva>")["wiederholt"]
        assert pe.anlegen("c-2", "eml", [], quelle_id="<m1@fiktiva>")["doppelt"]
        assert pe.anlegen("c-3", "datei", [], sha256="raw1")["doppelt"]
        assert len(pe.liste("alle")) == 1
        # Sekretariat bestätigt die Akte → Dokument + Verlauf der Akte
        pe.zuordnen(erg["id"], "2026/0815", _basis_akte="")
        pe.zuordnen(erg["id"], "2026/0815")                     # Wiederholung: keine zweite Verlaufszeile
    finally:
        pr.zuruecksetzen(tok)
    assert ar.dokument(did)["akte"] == "2026/0815"
    verlauf = welt["j"].verlauf("2026/0815")
    assert sum(1 for v in verlauf if v["art"] == "eingang") == 1
    assert pe.liste("nicht_zugeordnet") == []
    # gleichzeitig anders zugeordnet → Konflikt statt Überschreiben
    with pytest.raises(pr.Konflikt):
        pe.zuordnen(erg["id"], "2026/0901", _basis_akte="")


def test_aufgaben_rechte_erledigen_wiederoeffnen_ueberfaellig(welt):
    pe = welt["pe"]
    tok = als("anna", "sekretariat")
    try:
        e = pe.anlegen("c-a", "datei", [], betreff="Gutachten", sha256="g1")
        with pytest.raises(Berechtigung):                     # Sekretariat verteilt keine Arbeit an andere
            pe.aufgabe_anlegen("t-0", "rueckruf", "ra", eingang_id=e["id"])
        eigene = pe.aufgabe_anlegen("t-1", "rueckruf", "anna", eingang_id=e["id"])
        assert eigene["verantwortlich"] == "anna"
    finally:
        pr.zuruecksetzen(tok)
    tok = als("ra", "anwalt")
    try:
        gestern = (date.today() - timedelta(days=1)).isoformat()
        a = pe.aufgabe_anlegen("t-2", "unterlagen", "anna", "Vollmacht fehlt", "hoch", gestern, eingang_id=e["id"])
        assert a["titel"] == "Unterlagen anfordern" and a["ueberfaellig"] and a["status"] == "offen"
        assert pe.aufgabe_anlegen("t-2", "unterlagen", "anna")["id"] == a["id"]        # Wiederholung
        f = pe.aufgabe_anlegen("t-3", "frist", "ra", eingang_id=e["id"])
        assert "berechnet keine Fristen" in f["beschreibung"] and not f["faellig"]       # Prüfauftrag, keine Frist
        assert pe.eingang(e["id"])["status"] == "in_bearbeitung"
    finally:
        pr.zuruecksetzen(tok)
    tok = als("anna", "sekretariat")
    try:
        assert [x["id"] for x in pe.aufgaben("offen", verantwortlich="ich")] == [a["id"], eigene["id"]]
        assert [x["id"] for x in pe.aufgaben("ueberfaellig")] == [a["id"]]
        with pytest.raises(Berechtigung):
            pe.erledigen(f["id"])                             # fremde Aufgabe
        with pytest.raises(Berechtigung):
            pe.aufgabe_aendern(a["id"], verantwortlich="chef")
        done = pe.erledigen(a["id"])
        assert done["status"] == "erledigt" and done["erledigt_von"] == "anna" and done["erledigt_am"]
        assert pe.erledigen(a["id"])["erledigt_am"] == done["erledigt_am"]      # Wiederholung: unverändert
        offen = pe.wieder_oeffnen(a["id"])
        assert offen["status"] == "offen" and offen["wiedereroeffnet_von"] == "anna"
        # gleichzeitige Änderung desselben Feldes → Konflikt
        basis = {"beschreibung": offen["beschreibung"]}
        pe.aufgabe_aendern(a["id"], beschreibung="Vollmacht + Rechnung fehlen")
        with pytest.raises(pr.Konflikt):
            pe.aufgabe_aendern(a["id"], _basis=basis, beschreibung="anders")
    finally:
        pr.zuruecksetzen(tok)


# ---------------------------------------------------------------- Was fehlt?
def test_erwartungen_status_angefordert_und_vorlage_kopie(welt):
    un, pe = welt["un"], welt["pe"]
    vorlage = un.vorlagen()[0]
    assert "Beispiel" in vorlage["name"] and [p["titel"] for p in vorlage["punkte"]] == \
        ["Vollmacht", "Gutachten", "Rechnung", "Antwort der Versicherung"]
    neu = un.vorlage_anwenden("v-1", "2026/0815", vorlage["id"], verantwortlich="anna")
    assert len(neu) == 4 and all(e["status"] == "nicht_angefordert" for e in neu)
    assert un.vorlage_anwenden("v-1", "2026/0815", vorlage["id"]) == []        # Wiederholung: nichts doppelt
    # Vorlage ändern → bestehende Akte bleibt, wie sie ist
    un.vorlage_speichern(vorlage["id"], vorlage["name"], "Verkehrsunfall", "", [{"titel": "Fotos"}])
    assert [e["titel"] for e in un.liste("2026/0815")] == ["Vollmacht", "Gutachten", "Rechnung",
                                                            "Antwort der Versicherung"]
    voll = next(e for e in un.liste("2026/0815") if e["titel"] == "Vollmacht")
    # „angefordert“ nur mit Quelle: nicht über aendern(), nicht durch einen Entwurf
    assert un.aendern(voll["id"], status="angefordert")["status"] == "nicht_angefordert"
    un.entwurf_vermerken(voll["id"])
    assert un.erwartung(voll["id"])["angefordert_am"] == ""
    with pytest.raises(ValueError):
        un.angefordert_eintragen(voll["id"], quelle="entwurf")
    tok = als("anna", "sekretariat")
    try:
        e = un.angefordert_eintragen(voll["id"], "20.11.2026", quelle="manuell", notiz="telefonisch angefordert")
        assert (e["status"], e["angefordert_am"], e["angefordert_quelle"], e["angefordert_von"]) == \
            ("angefordert", "2026-11-20", "manuell", "anna")
        # Eingang (fiktive Vollmacht) zuordnen → Vorschlag → Mensch verknüpft → nur „Eingegangen – zu prüfen“
        eg = pe.anlegen("c-v", "datei", [{"rolle": "datei", "name": "Vollmacht_Erfunden.pdf", "sha256": "v"}],
                        betreff="Vollmacht Erfunden", sha256="voll1", absender="erika@example.com")
        pe.zuordnen(eg["id"], "2026/0815")
        vorschlag = un.vorschlaege_fuer_eingang(eg["id"])
        assert vorschlag[0]["erwartung_id"] == voll["id"] and "vollmacht" in vorschlag[0]["gruende"][0].lower()
        e = un.eingang_verknuepfen(voll["id"], eg["id"])
        assert e["status"] == "eingegangen" and any(l["art"] == "eingang" for l in e["links"])
        with pytest.raises(Berechtigung):                        # „geprüft“ entscheidet der Rechtsanwalt
            un.aendern(voll["id"], status="geprueft")
    finally:
        pr.zuruecksetzen(tok)
    tok = als("ra", "anwalt")
    try:
        e = un.aendern(voll["id"], status="geprueft")
        assert e["status_text"] == "Geprüft / vollständig" and e["geprueft_von"] == "ra"
    finally:
        pr.zuruecksetzen(tok)
    ueb = un.uebersicht()
    assert voll["id"] not in [x["id"] for x in ueb["erwartet"]] and ueb["erwartet_anzahl"] == 3


def test_teilweise_eingang_bleibt_offen_und_vorschlag_nur_passend():
    offene = [{"id": 1, "titel": "Vollmacht", "status": "angefordert", "von_rolle": "mandant"},
              {"id": 2, "titel": "Gutachten", "status": "nicht_angefordert", "von_rolle": "sachverstaendiger"}]
    v = passende_erwartungen("Ihre Unterlagen", ["Gutachten_Seite1.pdf"], "Gutachten", "", offene)
    assert [x["erwartung_id"] for x in v] == [2]
    assert passende_erwartungen("Hallo", ["Brief.pdf"], "", "", offene) == []
