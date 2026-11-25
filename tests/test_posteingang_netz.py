"""0.5 Kabul-Szenario auf Kernebene: echter TLS-Server + zwei Arbeitsplätze (gleicher Rechner, getrennte Prozesse
werden NICHT als zwei physische PCs gewertet) – Posteingang, Aufgaben, Was fehlt?, Versandkontrolle, Sicherung.
Nur fiktive Daten; Entwürfe als .eml-Datei (nichts wird geöffnet oder gesendet)."""
import os
import sqlite3
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import netz  # noqa: E402
from core import posteingang_service as ps  # noqa: E402
from core import versand_service as vsrv  # noqa: E402
from core.benutzer import Berechtigung  # noqa: E402
from tests.test_netz import _client, server  # noqa: E402,F401
from workflows.base import AppContext  # noqa: E402

pymupdf = pytest.importorskip("pymupdf")


def _pdf(pfad: Path, text: str) -> Path:
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), text)
    d.save(pfad)
    return pfad


def _ctx(v, k, tmp, name):
    cfg = {"mail_modus": "eml", "daten_ordner": str(tmp / f"daten_{name}"), "signatur_quelle": "outlook"}
    ctx = AppContext(cfg, netz.FernKanzlei(v, k), netz.FernJournal(v, k), verbindung=v, kopien=k)
    return ctx


def _eml(pfad: Path, mid: str, betreff: str, absender: str, text: str, anhaenge: list[Path]) -> Path:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = absender, "kanzlei@example.com", betreff, mid
    m["Date"] = "Fri, 20 Nov 2026 09:15:00 +0100"
    m.set_content(text)
    for a in anhaenge:
        m.add_attachment(a.read_bytes(), maintype="application", subtype="pdf", filename=a.name)
    pfad.write_bytes(bytes(m))
    return pfad


def test_kabul_szenario_kernebene(server, tmp_path, monkeypatch):
    monkeypatch.delattr(os, "startfile", raising=False)            # .eml-Entwurf nicht öffnen
    d, adr, admin, tmp = server
    sek, sk = _client(adr, "anna", "Sekretariat-1", tmp, "pc_sek")
    ra, rk = _client(adr, "ra", "Anwalt-Passwort-1", tmp, "pc_ra")
    c_sek, c_ra = _ctx(sek, sk, tmp, "sek"), _ctx(ra, rk, tmp, "ra")
    st = c_sek.stammdaten
    m = st.mandant_speichern(None, name="Erika Erfunden", email="erika@example.com")
    m2 = st.mandant_speichern(None, name="Max Mustermann", email="max@example.com")
    v = st.versicherung_speichern(None, name="Fiktiva Versicherung AG")
    st.email_hinzufuegen(v, "schaden@fiktiva-versicherung.example")
    st.akte_anlegen("2026/0815", aktenzeichen="0815/26", mandant_id=m, versicherung_id=v,
                    versicherungsnummer="FV-4711-2026", schaden_nr="SCH 2026/99123", mandant_email="erika@example.com",
                    versicherer_email="schaden@fiktiva-versicherung.example")
    st.akte_anlegen("2026/0901", aktenzeichen="0901/26", mandant_id=m2, versicherung_id=v,
                    versicherer_email="schaden@fiktiva-versicherung.example")

    # 1. Sekretariat importiert die E-Mail der Versicherung mit Anhang
    quelle = tmp / "quelle"
    quelle.mkdir()
    anh = _pdf(quelle / "Regulierungsschreiben.pdf", "Schaden-Nr. SCH 2026/99123 - wir bitten um Vollmacht")
    eml = _eml(quelle / "antwort.eml", "<a1@fiktiva.example>", "Ihre Schaden-Nr. SCH 2026/99123",
               "schaden@fiktiva-versicherung.example", "Sehr geehrte Damen und Herren, bitte Vollmacht senden.", [anh])
    vorher = eml.read_bytes()
    s = ps.aus_eml(eml)
    erg = ps.ablegen(c_sek, s)
    assert not erg["doppelt"] and eml.read_bytes() == vorher                 # Quelle unverändert
    # 2. Vorschlag mit Begründung; Sekretariat bestätigt die richtige Akte
    e = c_sek.posteingang.eingang(erg["id"])
    assert e["akte"] == "" and e["vorschlag"][0]["referenz"] == "2026/0815" and e["eindeutig"]
    assert any("SCH 2026/99123" in g for g in e["vorschlag"][0]["gruende"])
    assert [x["rolle"] for x in e["dateien"]] == ["mail", "anhang"]
    c_sek.posteingang.zuordnen(erg["id"], "2026/0815", _basis_akte="")
    # erneuter Import derselben Mail (Message-ID) → nichts doppelt
    assert ps.ablegen(c_sek, ps.aus_eml(eml))["doppelt"]
    # 3. Anwalt sieht den Eingang und gibt „Unterlagen anfordern“ an das Sekretariat
    assert erg["id"] in [x["id"] for x in c_ra.posteingang.liste("offen")]
    auf = c_ra.posteingang.aufgabe_anlegen("auf-1", "unterlagen", "anna", "Vollmacht anfordern",
                                           eingang_id=erg["id"])
    assert auf["akte"] == "2026/0815"
    with pytest.raises(Berechtigung):                                          # 9. Sekretariat verteilt nicht
        c_sek.posteingang.aufgabe_anlegen("auf-x", "rueckruf", "ra", eingang_id=erg["id"])
    assert [a["id"] for a in c_sek.posteingang.aufgaben("offen", verantwortlich="ich")] == [auf["id"]]
    # 4. Erinnerung (Vollmacht) als Entwurf – nichts gesendet, Status nicht „angefordert“
    un = c_sek.unterlagen
    vorlage = un.vorlagen()[0]
    un.vorlage_anwenden("vl-1", "2026/0815", vorlage["id"], verantwortlich="anna")
    voll = next(x for x in un.liste("2026/0815") if x["titel"] == "Vollmacht")
    akte = c_sek.stammdaten.akte("2026/0815")
    betreff, html = __import__("core.unterlagen", fromlist=["x"]).erinnerung_text(akte, [voll], "mandant")
    pruef = vsrv.kontrolle(c_sek, "2026/0815", "erika@example.com", None, [])
    assert pruef.rolle == "mandant"
    ent = vsrv.entwurf_mit_nachweis(c_sek, "2026/0815", "erika@example.com", betreff, html, [], pruef,
                                    erwartungen=[voll["id"]])
    assert ent.eintrag["status"] == "entwurf_erstellt" and "Entwurf als" in ent.meldung
    assert un.erwartung(voll["id"])["status"] == "nicht_angefordert"
    # 5. Fiktive Vollmacht kommt an → Vorschlag → Mensch verknüpft → Anwalt prüft
    vdatei = _pdf(quelle / "Vollmacht_Erfunden.pdf", "Vollmacht Erika Erfunden 0815/26")
    e2 = ps.ablegen(c_sek, ps.aus_datei(vdatei))
    assert c_sek.posteingang.eingang(e2["id"])["vorschlag"][0]["referenz"] == "2026/0815"
    c_sek.posteingang.zuordnen(e2["id"], "2026/0815")
    vor = un.vorschlaege_fuer_eingang(e2["id"])
    assert vor and vor[0]["erwartung_id"] == voll["id"]
    assert un.eingang_verknuepfen(voll["id"], e2["id"])["status"] == "eingegangen"
    with pytest.raises(Berechtigung):
        un.aendern(voll["id"], status="geprueft")
    assert c_ra.unterlagen.aendern(voll["id"], status="geprueft")["status"] == "geprueft"
    with pytest.raises(Berechtigung):                                          # Vorlagen: nur Anwalt/Admin
        un.vorlage_speichern(None, "Eigene", "", "", [{"titel": "X"}])
    c_sek.posteingang.erledigen(auf["id"])

    # 6. Erwiderung nennt K1–K3, K2 fehlt
    arbeit = tmp / "pc_ra_arbeit"
    arbeit.mkdir()
    from tests.test_versand import docx
    schrift = docx(arbeit / "Erwiderung.docx", ["In Sachen Erfunden, Az. 0815/26",
                                                "Rechnung als Anlage K1, Gutachten als Anlage K2, Fotos als Anlage K3."])
    k1, k3 = _pdf(arbeit / "Anlage_K1.pdf", "Rechnung"), _pdf(arbeit / "Anlage_K3.pdf", "Fotos")
    erg6 = vsrv.kontrolle(c_ra, "2026/0815", "schaden@fiktiva-versicherung.example", schrift,
                          [(k1, "Anlage K1"), (k3, "Anlage K3")])
    fehlt = [b for b in erg6.befunde if b.art == "anlage_fehlt" and b.stufe == "warnung"]
    assert fehlt and "K2" in fehlt[0].text and "Anlage K2" in fehlt[0].beleg
    # 7. K2 ergänzt → Entwurf mit fester Kopie und Nachweis
    k2 = _pdf(arbeit / "Anlage_K2.pdf", "Gutachten")
    anl = [(k1, "Anlage K1"), (k2, "Anlage K2"), (k3, "Anlage K3")]
    erg7 = vsrv.kontrolle(c_ra, "2026/0815", "schaden@fiktiva-versicherung.example", schrift, anl)
    assert not erg7.zu_bestaetigen
    anh7 = [vsrv.Anhang(schrift, "hauptdokument", "Schriftsatz")] + [vsrv.Anhang(p, "anlage", b) for p, b in anl]
    ent7 = vsrv.entwurf_mit_nachweis(c_ra, "2026/0815", "schaden@fiktiva-versicherung.example",
                                     "Erwiderung nebst Anlagen K1 bis K3", "<p>anbei</p>", anh7, erg7)
    v7 = ent7.eintrag
    assert [x["name"] for x in v7["dateien"]] == ["Erwiderung.docx", "Anlage_K1.pdf", "Anlage_K2.pdf",
                                                  "Anlage_K3.pdf"]
    assert v7["empfaenger_rolle"] == "versicherung"
    # 8. Original (K2) wird später geändert → Versandkopie bleibt, Änderung wird angezeigt
    k2_kopie_server = Path(v7["dateien"][2]["kopie_pfad"])
    alt_kopie = k2_kopie_server.read_bytes()
    _pdf(k2, "Gutachten – zweite Fassung")
    aend = vsrv.gueltigkeit_pruefen(c_ra, v7)
    assert aend and "Anlage_K2.pdf" in aend[0] and k2_kopie_server.read_bytes() == alt_kopie
    assert not c_ra.versand.eintrag(v7["id"])["gueltig"]
    # 9. Andere Benutzerin sieht Aufgaben- und Aktenstand
    assert c_sek.versand.liste("2026/0815")[0]["id"] == v7["id"]
    assert c_ra.posteingang.aufgabe(auf["id"])["status"] == "erledigt"

    # 10. Verbindungsabbruch + Wiederholung: gleiche Kennung → nichts doppelt
    stueck = ps.aus_datei(_pdf(quelle / "Rechnung_Werkstatt.pdf", "Rechnung 0815/26"))
    erst = ps.ablegen(c_sek, stueck)
    nochmal = c_sek.posteingang.anlegen(stueck.client_id, "datei", [], sha256=stueck.sha256)
    assert nochmal["id"] == erst["id"] and nochmal["wiederholt"]
    t1 = c_ra.posteingang.aufgabe_anlegen("auf-retry", "rueckruf", "ra")
    assert c_ra.posteingang.aufgabe_anlegen("auf-retry", "rueckruf", "ra")["id"] == t1["id"]
    vorher_n = {t: _anzahl(d, t) for t in ("eingaenge", "aufgaben", "erwartungen", "versand")}
    #     Sicherung + Wiederherstellung: nichts verdoppelt, nichts verloren, Versandkopien dabei
    daten, info = admin.sicherung_erstellen()
    assert info["anzahl"]["Versandnachweise"] == vorher_n["versand"] and info["anzahl"]["Aufgaben"] == vorher_n["aufgaben"]
    p = admin.sicherung_pruefen(daten)
    admin.sicherung_wiederherstellen(p["token"])
    nachher = {t: _anzahl(d, t) for t in vorher_n}
    assert nachher == vorher_n
    kopie_pfade = [r[0] for r in sqlite3.connect(d.db).execute("SELECT kopie_pfad FROM versand_dateien")]
    assert kopie_pfade and all(Path(x).is_file() for x in kopie_pfade)


def _anzahl(d, tab: str) -> int:
    con = sqlite3.connect(d.db)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {tab}").fetchone()[0]
    finally:
        con.close()
