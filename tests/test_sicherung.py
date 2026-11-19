"""Sicherung/Wiederherstellung mit fiktiven Daten: Inhalt, Rückkehr nach Änderungen, anderer Datenordner
(anderer Rechner), beschädigte Sicherung, Abbruch mit Rückweg, Absturz + Start-Wiederherstellung, Ziel weg."""
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from core import sicherung as s
from core.adressbuch import Adressbuch
from core.archiv import Archiv
from core.journal import Journal
from core.stammdaten import Stammdaten

V = "0.4.2"


def _welt(tmp: Path):
    daten = tmp / "Daten"
    daten.mkdir(parents=True)
    app = tmp / "Programm"
    app.mkdir()
    (app / "config.json").write_text(json.dumps({"daten_ordner": str(daten), "pdfa": False}), encoding="utf-8")
    (daten / "kanzlei.json").write_text(json.dumps({"name": "Kanzlei Fiktiv"}), encoding="utf-8")
    (daten / "logo.png").write_bytes(b"\x89PNG fiktiv")
    akte = tmp / "Rechner_alt" / "Akten" / "Mustermann"
    akte.mkdir(parents=True)
    (akte / "Klage.docx").write_bytes(b"Word fiktiv v1")
    (akte / "Anlage_K1.pdf").write_bytes(b"%PDF fiktiv v1")
    (akte / "BnX-Raptor_Backup_2026-01-01_00-00-00.zip").write_bytes(b"alte Sicherung")   # nie mitsichern
    einzeln = tmp / "Rechner_alt" / "Downloads"
    einzeln.mkdir(parents=True)
    (einzeln / "Antwort.pdf").write_bytes(b"%PDF Antwort")
    j = Journal(daten / "verlauf.sqlite")
    buch = Adressbuch(j.con)
    st = Stammdaten(j.con, buch)
    ar = Archiv(j.con)
    buch.lernen("Fiktiva Versicherung AG", "schaden@example.com")
    v = st.versicherung_speichern(None, name="Fiktiva Versicherung AG")
    m = st.mandant_speichern(None, name="Max Mustermann", email="max@example.com")
    st.mandant_speichern(None, name="Erika Erfunden")
    st.akte_anlegen("2026/0815", aktenzeichen="0815/26", mandant_id=m, versicherung_id=v,
                    versicherungsnummer="FV-1", schaden_nr="SN-1", ordner=str(akte))
    ar.erfassen(akte / "Klage.docx", akte="2026/0815")
    ar.erfassen(akte / "Anlage_K1.pdf", akte="2026/0815")
    ar.erfassen(einzeln / "Antwort.pdf", akte="2026/0815", rolle="eingang")
    j.add("Schreiben", str(akte / "Klage.docx"), ergebnis=str(akte / "Anlage_K1.pdf"), referenz="2026/0815")
    j.add("Schreiben", str(tmp / "weg" / "Geloescht.pdf"), referenz="2026/0815")         # fehlt
    return {"daten": daten, "app": app, "akte": akte, "einzeln": einzeln, "j": j, "st": st, "ar": ar, "m": m}


def _stand(w) -> dict:
    con = w["j"].con
    return {
        "mandanten": [r[0] for r in con.execute("SELECT name FROM mandanten ORDER BY id")],
        "akte": tuple(con.execute("SELECT aktenzeichen, versicherungsnummer, schaden_nr FROM akten").fetchone()),
        "versicherungen": con.execute("SELECT COUNT(*) FROM versicherungen").fetchone()[0],
        "verlauf": con.execute("SELECT COUNT(*) FROM vorgaenge").fetchone()[0],
        "dokumente": con.execute("SELECT COUNT(*) FROM dokumente").fetchone()[0],
    }


def test_sicherung_inhalt_und_vollstaendige_rueckkehr(tmp_path):
    w = _welt(tmp_path)
    usb = tmp_path / "USB"
    usb.mkdir()
    (usb / "BnX-Raptor_Backup_alt.zip").write_bytes(b"vorher")
    vorher = _stand(w)
    zip_pfad, fehlend = s.sicherung_erstellen(w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V,
                                              usb / s.dateiname())
    assert zip_pfad.parent == usb and s.NAME_MUSTER.match(zip_pfad.name)
    assert (usb / "BnX-Raptor_Backup_alt.zip").read_bytes() == b"vorher"            # alte Sicherung bleibt
    assert not list(usb.glob("*.part"))
    assert [f["pfad"] for f in fehlend] == [str(tmp_path / "weg" / "Geloescht.pdf")]
    info = s.pruefen(zip_pfad, V)
    assert info.anzahl["Mandanten"] == 2 and info.anzahl["Akten/Mandate"] == 1
    assert info.anzahl["Versicherungen"] == 1 and info.anzahl["Adressbuch-Einträge"] == 1
    assert info.anzahl["Dokumente im Archiv"] == 3 and info.anzahl["Verlaufseinträge"] == 2
    namen = zipfile.ZipFile(zip_pfad).namelist()
    assert not any("Backup_2026-01-01" in n for n in namen)
    assert any(n.endswith("kanzlei.json") for n in namen) and any(n.endswith("logo.png") for n in namen)
    assert any(n.endswith("Antwort.pdf") for n in namen) and "einstellungen/config.json" in namen

    # Änderungen nach der Sicherung
    st = w["st"]
    st.mandant_loeschen(w["m"])
    st.akte_setzen("2026/0815", aktenzeichen="GEÄNDERT", schaden_nr="SN-NEU")
    w["j"].add("Schreiben", "neu")
    (w["akte"] / "Klage.docx").write_bytes(b"Word fiktiv v2 - geaendert")
    (w["akte"] / "Anlage_K1.pdf").unlink()
    (w["daten"] / "kanzlei.json").write_text("{}", encoding="utf-8")
    assert _stand(w) != vorher

    erg = s.wiederherstellen(zip_pfad, w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V)
    assert _stand(w) == vorher                                   # über die OFFENE Verbindung sichtbar
    assert (w["akte"] / "Klage.docx").read_bytes() == b"Word fiktiv v1"
    assert (w["akte"] / "Anlage_K1.pdf").read_bytes() == b"%PDF fiktiv v1"
    assert json.loads((w["daten"] / "kanzlei.json").read_text(encoding="utf-8"))["name"] == "Kanzlei Fiktiv"
    assert erg.sicherheitskopie.exists() and erg.sicherheitskopie.parent.name == s.SICHERHEITSKOPIEN
    assert erg.umgezogen == {}                                   # gleicher Rechner: Pfade bleiben
    assert not (w["daten"] / s.ARBEIT).exists()
    # Sicherheitskopie enthält den geänderten Stand und wird nie in neue Sicherungen aufgenommen
    sk = s.pruefen(erg.sicherheitskopie, V)
    assert sk.anzahl["Mandanten"] == 1 and sk.anzahl["Verlaufseinträge"] == 3
    neu, _ = s.sicherung_erstellen(w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V, usb / s.dateiname())
    assert not any(s.SICHERHEITSKOPIEN in n for n in zipfile.ZipFile(neu).namelist())


def test_anderer_rechner_anderer_datenordner(tmp_path):
    w = _welt(tmp_path / "alt")
    zip_pfad, _ = s.sicherung_erstellen(w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V,
                                        tmp_path / s.dateiname())
    w["j"].con.close()
    shutil.rmtree(tmp_path / "alt")                              # alter Rechner existiert nicht mehr
    daten = tmp_path / "neu" / "BnX-Daten"
    daten.mkdir(parents=True)
    app = tmp_path / "neu" / "Programm"
    app.mkdir()
    (app / "config.json").write_text(json.dumps({"daten_ordner": str(daten)}), encoding="utf-8")
    j = Journal(daten / "verlauf.sqlite")                         # neue, leere Installation (offen)
    erg = s.wiederherstellen(zip_pfad, daten / "verlauf.sqlite", daten, app, V)
    st = Stammdaten(j.con, Adressbuch(j.con))
    assert [m["name"] for m in st.mandanten()] == ["Erika Erfunden", "Max Mustermann"]
    akte = st.akte("2026/0815")
    neuer_ordner = Path(akte["ordner"])
    assert neuer_ordner == daten / s.WIEDERHERGESTELLT / "Mustermann"       # Aktenordner → Datenordner
    assert (neuer_ordner / "Klage.docx").read_bytes() == b"Word fiktiv v1"
    assert (daten / s.WIEDERHERGESTELLT / "Downloads" / "Antwort.pdf").exists()
    pfade = [r[0] for r in j.con.execute("SELECT pfad FROM dokumente")]
    assert all(Path(p).exists() and str(p).startswith(str(daten)) for p in pfade), pfade
    schl = {r[0] for r in j.con.execute("SELECT schluessel FROM dokumente")}
    assert all(k.startswith(str(daten).lower()) for k in schl)
    verlauf = [r[0] for r in j.con.execute("SELECT dokument FROM vorgaenge")]
    assert verlauf[0].startswith(str(daten))
    assert (daten / "kanzlei.json").exists() and (daten / "logo.png").exists()
    cfg = json.loads((app / "config.json").read_text(encoding="utf-8"))
    assert cfg["daten_ordner"] == str(daten) and cfg["pdfa"] is False       # Datenordner dieses Rechners
    assert erg.umgezogen


def test_beschaedigte_und_fremde_sicherungen_werden_abgelehnt(tmp_path):
    w = _welt(tmp_path)
    zip_pfad, _ = s.sicherung_erstellen(w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V,
                                        tmp_path / s.dateiname())
    daten = zip_pfad.read_bytes()
    abgeschnitten = tmp_path / "abgeschnitten.zip"
    abgeschnitten.write_bytes(daten[: len(daten) // 2])
    with pytest.raises(s.SicherungFehler, match="keine gültige BnX-Raptor-Sicherung|beschädigt"):
        s.pruefen(abgeschnitten, V)
    # ein Byte in einem Dokument verändert → Prüfsumme
    kaputt = tmp_path / "kaputt.zip"
    with zipfile.ZipFile(zip_pfad) as zi, zipfile.ZipFile(kaputt, "w") as zo:
        for n in zi.namelist():
            b = zi.read(n)
            zo.writestr(n, b + b"x" if n.endswith("Klage.docx") else b)
    with pytest.raises(s.SicherungFehler, match="Prüfsumme"):
        s.pruefen(kaputt, V)
    fremd = tmp_path / "fremd.zip"
    with zipfile.ZipFile(fremd, "w") as zf:
        zf.writestr("irgendwas.txt", "x")
    with pytest.raises(s.SicherungFehler, match="keine BnX-Raptor-Sicherung"):
        s.pruefen(fremd, V)
    with pytest.raises(s.SicherungFehler, match="neueren|aktualisieren"):
        s.pruefen(zip_pfad, "0.4.1")
    vorher = _stand(w)
    with pytest.raises(s.SicherungFehler):
        s.wiederherstellen(kaputt, w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V)
    assert _stand(w) == vorher                                    # nichts verändert


def _vorbereiten_aenderung(w, tmp_path):
    zip_pfad, _ = s.sicherung_erstellen(w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V,
                                        tmp_path / s.dateiname())
    w["st"].mandant_loeschen(w["m"])
    (w["akte"] / "Klage.docx").write_bytes(b"aktueller Stand")
    return zip_pfad, _stand(w)


def test_fehler_mitten_drin_setzt_alles_zurueck(tmp_path):
    w = _welt(tmp_path)
    zip_pfad, vorher = _vorbereiten_aenderung(w, tmp_path)
    with pytest.raises(s.SicherungFehler, match="vorherige Stand wurde wiederhergestellt"):
        s.wiederherstellen(zip_pfad, w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V, _test_fehler_nach=3)
    assert _stand(w) == vorher
    assert (w["akte"] / "Klage.docx").read_bytes() == b"aktueller Stand"
    assert not (w["daten"] / s.ARBEIT).exists()


def test_absturz_wird_beim_naechsten_start_zurueckgesetzt(tmp_path):
    w = _welt(tmp_path)
    zip_pfad, vorher = _vorbereiten_aenderung(w, tmp_path)
    dateien_vorher = {p: p.read_bytes() for p in w["akte"].iterdir() if p.is_file()}
    with pytest.raises(s._SimulierterAbsturz):
        s.wiederherstellen(zip_pfad, w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V,
                           _test_absturz_nach=4)
    assert (w["daten"] / s.ARBEIT / "aktionen.json").exists()   # halb fertig
    assert s.offene_wiederherstellung_zuruecksetzen(w["daten"]) is True
    assert {p: p.read_bytes() for p in w["akte"].iterdir() if p.is_file()} == dateien_vorher
    assert _stand(w) == vorher
    assert s.offene_wiederherstellung_zuruecksetzen(w["daten"]) is False


def test_ziel_weg_oder_voll_kein_erfolg(tmp_path, monkeypatch):
    w = _welt(tmp_path)
    paket = s.paket_erstellen(w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V)
    try:
        with pytest.raises(s.SicherungFehler, match="USB-Stick entfernt"):
            s.speichern(paket, tmp_path / "USB_weg" / s.dateiname())
        usb = tmp_path / "USB"
        usb.mkdir()
        echt = shutil.disk_usage
        monkeypatch.setattr(s.shutil, "disk_usage", lambda p: echt(p)._replace(free=10))
        with pytest.raises(s.SicherungFehler, match="Speicherplatz"):
            s.speichern(paket, usb / s.dateiname())
        assert list(usb.iterdir()) == []
        monkeypatch.setattr(s.shutil, "disk_usage", echt)
        a = s.speichern(paket, usb / "BnX-Raptor_Backup_X.zip")
        b = s.speichern(paket, usb / "BnX-Raptor_Backup_X.zip")       # gleicher Name → nicht überschreiben
        assert a != b and a.exists() and b.exists()
    finally:
        s.verwerfen(paket)
    assert not paket.arbeitsordner.exists()                             # temporäres Paket aufgeräumt


def test_abbrechen_raeumt_auf(tmp_path):
    w = _welt(tmp_path)
    vorher = set(Path(s.tempfile.gettempdir()).glob("bnx-sicherung-*"))
    with pytest.raises(s.Abgebrochen):
        s.paket_erstellen(w["daten"] / "verlauf.sqlite", w["daten"], w["app"], V, abbrechen=lambda: True)
    assert set(Path(s.tempfile.gettempdir()).glob("bnx-sicherung-*")) == vorher
