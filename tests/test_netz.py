"""Mehrbenutzerbetrieb: echter HTTP-Dienst + zwei Clients (Sekretariat, Rechtsanwalt) mit fiktiven Daten."""
import base64
import json
import sqlite3
from pathlib import Path

import pytest

from core import netz
from core import protokoll as pr
from core.benutzer import Berechtigung
from core.sicherung import SicherungFehler


@pytest.fixture()
def server(tmp_path):
    daten = tmp_path / "Server-Daten"
    daten.mkdir()
    d = netz.Dienst(daten, tmp_path, port=0, host="127.0.0.1", version="0.4.2").starten()
    adr = f"http://127.0.0.1:{d.port}"
    admin = netz.Verbindung(adr)
    assert admin.ping()["benutzer_vorhanden"] is False
    admin.erster_admin("chef", "Admin-Passwort-1", "Chefin")
    admin.anmelden("chef", "Admin-Passwort-1")
    admin.aufrufen("benutzer", "anlegen", ["anna", "Sekretariat-1", "sekretariat", "Anna (Sekretariat)"])
    admin.aufrufen("benutzer", "anlegen", ["ra", "Anwalt-Passwort-1", "anwalt", "RA Berger"])
    yield d, adr, admin, tmp_path
    d.beenden()


def _client(adr, name, pw, tmp, unter):
    v = netz.Verbindung(adr)
    v.anmelden(name, pw)
    k = netz.Arbeitskopien(v, tmp / unter)
    k.direkt = False                                   # Test: wie ein anderer Rechner (keine Direktpfade)
    return v, k


def test_ablauf_sekretariat_anwalt_mit_verlauf(server):
    d, adr, admin, tmp = server
    sek, sk = _client(adr, "anna", "Sekretariat-1", tmp, "pc_sek")
    ra, rk = _client(adr, "ra", "Anwalt-Passwort-1", tmp, "pc_ra")
    st_s = netz._Fern(sek, "stammdaten")
    m = st_s.mandant_speichern(None, name="Max Mustermann", email="max@example.com", telefon="0000")
    v = st_s.versicherung_speichern(None, name="Fiktiva Versicherung AG")
    st_s.email_hinzufuegen(v, "schaden@example.com")
    st_s.akte_anlegen("2026/0815", aktenzeichen="0815/26", mandant_id=m, versicherung_id=v,
                      mandant_email="max@example.com", versicherer_email="schaden@example.com")
    st_s.akte_anlegen("2026/0901", aktenzeichen="0901/26", mandant_id=m)          # zweite Akte, gleicher Mandant
    # Sekretariat fügt ein Dokument hinzu (Upload in die zentrale Ablage)
    lokal = tmp / "pc_sek_eingang" / "Vollmacht.docx"
    lokal.parent.mkdir()
    lokal.write_bytes(b"Vollmacht v1")
    netz.FernArchiv(sek, sk).erfassen(lokal, akte="2026/0815")
    netz.FernJournal(sek, sk).add("akte", str(lokal), "", "", "2026/0815", meldung="hinzugefügt", art="dokument")
    # Anwalt sieht alles
    st_r = netz._Fern(ra, "stammdaten")
    assert [x["name"] for x in st_r.mandanten()] == ["Max Mustermann"]
    assert len(st_r.akten_von_mandant(m)) == 2
    akte = st_r.akte("2026/0815")
    assert akte["mandant_email"] == "max@example.com" and akte["versicherer_email"] == "schaden@example.com"
    assert st_r.versicherung(v)["emails"] == ["schaden@example.com"]
    assert akte["erstellt_von"] == "Anna (Sekretariat)"
    doks = netz._Fern(ra, "archiv").liste(akte="2026/0815")
    assert len(doks) == 1 and Path(doks[0]["pfad"]).is_relative_to(d.daten / netz.DOKUMENTE)
    # Anwalt öffnet, bearbeitet und speichert das Dokument
    arbeit = rk.lokal(doks[0]["pfad"], "2026/0815")
    assert arbeit.read_bytes() == b"Vollmacht v1" and str(arbeit).startswith(str(tmp / "pc_ra"))
    arbeit.write_bytes(b"Vollmacht v2 vom Anwalt")
    netz.FernArchiv(ra, rk).bearbeitet(arbeit)
    assert Path(doks[0]["pfad"]).read_bytes() == b"Vollmacht v2 vom Anwalt"
    # Verlauf mit den richtigen Benutzern
    verlauf = st_r.aenderungsverlauf("akte", "2026/0815")
    texte = [(e["benutzer"], e["text"]) for e in verlauf]
    assert ("RA Berger", "Dokument gespeichert: Vollmacht.docx") in texte
    assert ("Anna (Sekretariat)", "Dokument hinzugefügt: Vollmacht.docx") in texte
    assert ("Anna (Sekretariat)", "Akte angelegt (Aktenzeichen, Mandant, Versicherung, E-Mail Mandant, "
                                  "E-Mail Versicherung)") in texte
    st_s.mandant_speichern(m, _basis={"email": "max@example.com"}, email="max.neu@example.com")
    mv = st_r.aenderungsverlauf("mandant", m)
    assert mv[0]["benutzer"] == "Anna (Sekretariat)" and mv[0]["text"] == "E-Mail geändert"
    assert mv[0]["rolle_text"] == "Sekretariat"
    # Passwörter tauchen nie im Verlauf auf
    alles = json.dumps(admin.aenderungen(0), ensure_ascii=False)
    assert "Sekretariat-1" not in alles and "Anwalt-Passwort-1" not in alles


def test_gleichzeitige_aenderung_kein_stilles_ueberschreiben(server):
    d, adr, admin, tmp = server
    sek, sk = _client(adr, "anna", "Sekretariat-1", tmp, "a")
    ra, rk = _client(adr, "ra", "Anwalt-Passwort-1", tmp, "b")
    m = netz._Fern(sek, "stammdaten").mandant_speichern(None, name="Erika", telefon="111", ort="Alt")
    basis_s = netz._Fern(sek, "stammdaten").mandant(m)
    basis_r = netz._Fern(ra, "stammdaten").mandant(m)
    netz._Fern(sek, "stammdaten").mandant_speichern(m, _basis={"telefon": basis_s["telefon"]}, telefon="222")
    # anderes Feld → kein Konflikt, beide Änderungen bleiben
    netz._Fern(ra, "stammdaten").mandant_speichern(m, _basis={"ort": basis_r["ort"]}, ort="Neu")
    # gleiches Feld mit altem Stand → Konflikt, nichts überschrieben
    with pytest.raises(pr.Konflikt) as k:
        netz._Fern(ra, "stammdaten").mandant_speichern(m, _basis={"telefon": basis_r["telefon"]}, telefon="333")
    assert k.value.felder == ["telefon"] and k.value.aktuell["telefon"] == "222"
    assert k.value.aktuell["geaendert_von"] in ("Anna (Sekretariat)", "RA Berger")
    jetzt = netz._Fern(ra, "stammdaten").mandant(m)
    assert (jetzt["telefon"], jetzt["ort"]) == ("222", "Neu")
    # Akte ebenso
    netz._Fern(sek, "stammdaten").akte_anlegen("A1", schaden_nr="S1")
    netz._Fern(sek, "stammdaten").akte_setzen("A1", _basis={"schaden_nr": "S1"}, schaden_nr="S2")
    with pytest.raises(pr.Konflikt):
        netz._Fern(ra, "stammdaten").akte_setzen("A1", _basis={"schaden_nr": "S1"}, schaden_nr="S3")
    assert netz._Fern(ra, "stammdaten").akte("A1")["schaden_nr"] == "S2"
    # Dokument gleichzeitig: zweite Fassung wird Konfliktkopie, keine geht verloren
    lokal = tmp / "Brief.docx"
    lokal.write_bytes(b"v1")
    netz.FernArchiv(sek, sk).erfassen(lokal, akte="A1")
    sp = netz._Fern(ra, "archiv").liste(akte="A1")[0]["pfad"]
    sk.direkt = rk.direkt = False
    sa = sk.lokal(sp, "A1")
    ra_k = rk.lokal(sp, "A1")
    sa.write_bytes(b"Fassung Sekretariat")
    ra_k.write_bytes(b"Fassung Anwalt")
    # Sekretariat darf Dokumente nicht überschreiben (Rolle) – Anwalt speichert zuerst
    with pytest.raises(Berechtigung):
        netz.FernArchiv(sek, sk).bearbeitet(sa)
    netz.FernArchiv(ra, rk).bearbeitet(ra_k)
    assert Path(sp).read_bytes() == b"Fassung Anwalt"
    # zweiter Anwalt-Client mit altem Stand → Konfliktkopie
    ra2, rk2 = _client(adr, "ra", "Anwalt-Passwort-1", tmp, "c")
    alt = tmp / "c" / "alt.docx"
    alt.write_bytes(b"x")
    rk2.index[netz._nc(alt)] = {"lokal": str(alt), "server": sp, "sha": netz._sha(b"v1")}
    alt.write_bytes(b"Fassung Anwalt 2")
    with pytest.raises(pr.Konflikt):
        netz.FernArchiv(ra2, rk2).bearbeitet(alt)
    assert Path(sp).read_bytes() == b"Fassung Anwalt"
    kopien = [x for x in netz._Fern(ra, "archiv").liste(akte="A1") if "_Konflikt_" in x["name"]]
    assert len(kopien) == 1 and Path(kopien[0]["pfad"]).read_bytes() == b"Fassung Anwalt 2"
    # Bearbeitungssperre zeigt den anderen Benutzer
    assert sek.sperren(sp, True) == ""
    assert ra.sperren(sp, True) == "Anna (Sekretariat)"
    sek.sperren(sp, False)
    assert ra.sperren(sp, True) == ""


def test_rechte_anmeldung_und_sicherheit(server):
    d, adr, admin, tmp = server
    sek, _ = _client(adr, "anna", "Sekretariat-1", tmp, "a")
    with pytest.raises(Berechtigung):
        sek.aufrufen("benutzer", "anlegen", ["x", "Passwort-123", "admin"])
    with pytest.raises(Berechtigung):
        sek.aufrufen("benutzer", "liste")
    with pytest.raises(Berechtigung):
        sek.sicherung_erstellen()
    with pytest.raises(Berechtigung, match="Unbekannte Funktion"):
        sek.aufrufen("journal", "con")
    with pytest.raises(ValueError, match="falsch"):
        netz.Verbindung(adr).anmelden("anna", "falsch-falsch")
    with pytest.raises(ValueError, match="falsch"):
        netz.Verbindung(adr).anmelden("gibtsnicht", "egal-egal")
    # manipulierte Signatur / wiederholte Anfrage werden abgewiesen
    sek.schluessel = b"x" * 32
    sek._anmeldung = None
    with pytest.raises(netz.SitzungFehler):
        netz._Fern(sek, "stammdaten").mandanten()
    # deaktivierter Benutzer: Sitzung sofort ungültig, Verlauf bleibt sichtbar
    anna = next(b for b in admin.aufrufen("benutzer", "liste") if b["name"] == "anna")
    ra, _ = _client(adr, "ra", "Anwalt-Passwort-1", tmp, "b")
    sek2, _ = _client(adr, "anna", "Sekretariat-1", tmp, "c")
    netz._Fern(sek2, "stammdaten").mandant_speichern(None, name="Von Anna")
    admin.aufrufen("benutzer", "aktiv_setzen", [anna["id"], False])
    sek2._anmeldung = None
    with pytest.raises(netz.SitzungFehler):
        netz._Fern(sek2, "stammdaten").mandanten()
    with pytest.raises(ValueError):
        netz.Verbindung(adr).anmelden("anna", "Sekretariat-1")
    assert any(e["benutzer"] == "Anna (Sekretariat)" for e in ra.aenderungen(0)["eintraege"])
    # letzter Administrator kann nicht deaktiviert werden
    chef = next(b for b in admin.aufrufen("benutzer", "liste") if b["name"] == "chef")
    with pytest.raises(ValueError, match="letzte"):
        admin.aufrufen("benutzer", "aktiv_setzen", [chef["id"], False])
    # Passwort nur als Hash gespeichert
    con = sqlite3.connect(d.db)
    zeilen = con.execute("SELECT * FROM benutzer").fetchall()
    con.close()
    assert "Sekretariat-1" not in repr(zeilen)
    # Passwort ändern → alte Anmeldung nicht mehr möglich
    ra_id = next(b for b in admin.aufrufen("benutzer", "liste") if b["name"] == "ra")["id"]
    admin.aufrufen("benutzer", "passwort_setzen", [ra_id, "Neues-Passwort-9"])
    with pytest.raises(ValueError):
        netz.Verbindung(adr).anmelden("ra", "Anwalt-Passwort-1")
    netz.Verbindung(adr).anmelden("ra", "Neues-Passwort-9")


def test_verbindung_weg_und_wieder_da(server, tmp_path):
    d, adr, admin, tmp = server
    port = d.port
    sek, _ = _client(adr, "anna", "Sekretariat-1", tmp, "a")
    m = netz._Fern(sek, "stammdaten").mandant_speichern(None, name="Offline-Test")
    d.beenden()
    with pytest.raises(netz.VerbindungFehler, match="nichts gespeichert"):
        netz._Fern(sek, "stammdaten").mandant_speichern(m, _basis={"ort": ""}, ort="Neustadt")
    # Server startet neu (gleiche Daten) → Client meldet sich automatisch neu an, Änderung kommt an
    d2 = netz.Dienst(d.daten, tmp, port=port, host="127.0.0.1", version="0.4.2").starten()
    try:
        netz._Fern(sek, "stammdaten").mandant_speichern(m, _basis={"ort": ""}, ort="Neustadt")
        assert netz._Fern(sek, "stammdaten").mandant(m)["ort"] == "Neustadt"
    finally:
        d2.beenden()


def test_zentrale_sicherung_und_wiederherstellung_in_anderer_umgebung(server):
    d, adr, admin, tmp = server
    sek, sk = _client(adr, "anna", "Sekretariat-1", tmp, "a")
    m = netz._Fern(sek, "stammdaten").mandant_speichern(None, name="Gesichert GmbH")
    netz._Fern(sek, "stammdaten").akte_anlegen("S-1", mandant_id=m)
    datei = tmp / "Anlage.pdf"
    datei.write_bytes(b"%PDF gesichert")
    netz.FernArchiv(sek, sk).erfassen(datei, akte="S-1")
    zip_daten, info = admin.sicherung_erstellen()
    assert info["anzahl"]["Mandanten"] == 1 and info["dateien"] >= 1
    usb = tmp / "USB" / info["name"]
    usb.parent.mkdir()
    usb.write_bytes(zip_daten)
    # getrennte Testumgebung (anderer Server, anderer Datenordner)
    test = tmp / "Testumgebung"
    test.mkdir()
    d2 = netz.Dienst(test, test, port=0, host="127.0.0.1", version="0.4.2").starten()
    try:
        a2 = netz.Verbindung(f"http://127.0.0.1:{d2.port}")
        a2.erster_admin("admin2", "Admin-Passwort-2")
        a2.anmelden("admin2", "Admin-Passwort-2")
        ra_test = netz.Verbindung(f"http://127.0.0.1:{d2.port}")
        ra_test.anmelden("admin2", "Admin-Passwort-2")
        vorher_gen = ra_test.aenderungen(0)["generation"]
        p = a2.sicherung_pruefen(usb.read_bytes())
        assert p["anzahl"]["Mandanten"] == 1 and p["aktuell"]["Mandanten"] == 0
        erg = a2.sicherung_wiederherstellen(p["token"])
        assert Path(erg["sicherheitskopie"]).exists()
        # Benutzer kommen aus der Sicherung → mit den Benutzern des Originals anmelden
        neu = netz.Verbindung(f"http://127.0.0.1:{d2.port}")
        neu.anmelden("anna", "Sekretariat-1")
        assert [x["name"] for x in netz._Fern(neu, "stammdaten").mandanten()] == ["Gesichert GmbH"]
        dok = netz._Fern(neu, "archiv").liste(akte="S-1")[0]
        assert Path(dok["pfad"]).is_relative_to(test) and Path(dok["pfad"]).read_bytes() == b"%PDF gesichert"
        assert neu.aenderungen(0)["generation"] == vorher_gen + 1
    finally:
        d2.beenden()
    # beschädigte Sicherung wird abgelehnt
    kaputt = bytearray(zip_daten)
    kaputt[len(kaputt) // 2] ^= 0xFF
    with pytest.raises(SicherungFehler):
        admin.sicherung_pruefen(bytes(kaputt))


def test_wartung_sperrt_schreiben(server):
    d, adr, admin, tmp = server
    sek, _ = _client(adr, "anna", "Sekretariat-1", tmp, "a")
    d.wartung = "Wartung läuft"
    with pytest.raises(netz.WartungFehler):
        netz._Fern(sek, "stammdaten").mandant_speichern(None, name="X")
    assert sek.aenderungen(0)["wartung"] == "Wartung läuft"
    d.wartung = ""
    netz._Fern(sek, "stammdaten").mandant_speichern(None, name="X")


def test_json_roundtrip():
    from core.kanzlei import Kanzlei
    o = {"p": Path(r"C:\x\y.pdf"), "k": Kanzlei(name="Fiktiv"), "b": b"\x00\x01", "t": (1, 2)}
    r = netz.loads(netz.dumps(o))
    assert r["p"] == Path(r"C:\x\y.pdf") and r["k"].name == "Fiktiv" and r["b"] == b"\x00\x01" and r["t"] == [1, 2]
    assert base64


def test_automatische_suche_findet_server(server):
    d, adr, admin, tmp = server
    from core.kanzlei import Kanzlei
    d.objekte["kanzlei"].speichern(Kanzlei(name="Kanzlei Fiktiv"))
    gefunden = [s for s in netz.suchen(1.5) if s["adresse"].endswith(f":{d.port}") or
                any(a.endswith(f":{d.port}") for a in s["alternativen"])]
    assert gefunden and gefunden[0]["kanzlei"] == "Kanzlei Fiktiv"
    erreichbar = []
    for a in [gefunden[0]["adresse"], *gefunden[0]["alternativen"]]:       # Dienst hört hier nur auf 127.0.0.1
        try:
            erreichbar.append(netz.Verbindung(a).ping()["kanzlei"])
        except netz.VerbindungFehler:
            pass
    assert erreichbar == ["Kanzlei Fiktiv"]


def test_konfliktkopie_beim_erfassen_wird_gemeldet(server):
    d, adr, admin, tmp = server
    ra, rk = _client(adr, "ra", "Anwalt-Passwort-1", tmp, "x1")
    ra2, rk2 = _client(adr, "ra", "Anwalt-Passwort-1", tmp, "x2")
    datei = tmp / "Scan.pdf"
    datei.write_bytes(b"%PDF v1")
    netz.FernArchiv(ra, rk).erfassen(datei, akte="K1")
    sp = netz._Fern(ra, "archiv").liste(akte="K1")[0]["pfad"]
    a, b = rk.lokal(sp, "K1"), rk2.lokal(sp, "K1")
    a.write_bytes(b"%PDF Fassung 1")
    netz.FernArchiv(ra, rk).erfassen(a, akte="K1")                   # wie Akten „bearbeiten“: erst erfassen
    b.write_bytes(b"%PDF Fassung 2")
    with pytest.raises(pr.Konflikt):
        netz.FernArchiv(ra2, rk2).erfassen(b, akte="K1")
    assert Path(sp).read_bytes() == b"%PDF Fassung 1"
    namen = [x["name"] for x in netz._Fern(ra, "archiv").liste(akte="K1")]
    assert any("_Konflikt_" in n for n in namen)
