"""0.3.0 düzeltmeleri: numara kaynağı/seçimi, büronun kendi adresi, Word zaman sınırı.
Saf Python testleri – Word/Outlook gerekmez."""
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import word_service as ws  # noqa: E402
from core.config import DEFAULTS  # noqa: E402
from core.extractor import (ART_SCHADEN, ART_VERSICHERUNG, betreff, extract,  # noqa: E402
                            find_numbers)
from core.journal import Journal  # noqa: E402
from core.kanzlei import Kanzlei, KanzleiStore  # noqa: E402
from workflows import versicherung_brief as vb  # noqa: E402
from workflows.base import AppContext  # noqa: E402

L = DEFAULTS["nummer_bezeichnungen"]

# Büro şablonu testinden (anonim): adres bloğu, RS Schaden-Nr., büronun kendi adresi antette
BRIEF_RS = "\r".join([
    "Rae BEISPIEL & KOLLEGEN • MUSTERWEG 1 • D - 12345 MUSTERSTADT", "An die",
    "Fiktiva Rechtsschutz-Service GmbH", "54321 Nirgendwo", "",
    "Telefon +49 (0)000 00 00 000", "info@kanzlei-anonym.example.org",
    "Aktenzeichen: (stets angeben)", "N 999/26", "",
    "per E-Mail: test@example.com", "RS Schaden-Nr.: AS2026-00012345", "",
    "Sehr geehrte Damen und Herren,",
])


@pytest.fixture
def ctx(tmp_path):
    store = KanzleiStore(tmp_path / "d")
    store.speichern(Kanzlei(name="Beispiel & Kollegen", plz="12345",
                            email="info@kanzlei-anonym.example.org"))
    # eigene_domains enthält die Büro-Domain NICHT: sie muss aus Büro-Informationen kommen
    return AppContext(dict(DEFAULTS, eigene_domains=["andere-domain.example.net"]), store,
                      Journal(tmp_path / "v.sqlite"))


def felder(ctx, text, controls=None):
    wf = vb.VersicherungBrief(ctx)
    return wf, {f.key: f for f in wf.felder(text, controls or {})}


# --- 1. Numaranın kaynağı ve seçimi --------------------------------------------
def test_nur_rs_schadennummer_wird_klar_benannt():
    funde = find_numbers(BRIEF_RS, L)
    assert [(f.wert, f.bezeichnung, f.art) for f in funde] == [
        ("AS2026-00012345", "RS Schaden-Nr.", ART_SCHADEN)]


def test_feld_zeigt_quelle_wenn_keine_versicherungsnummer(ctx):
    wf, f = felder(ctx, BRIEF_RS)
    n = f["nummer"]
    assert n.value == "AS2026-00012345"
    assert n.hint == "aus ‚RS Schaden-Nr.‘ – keine Versicherungsnummer gefunden"
    assert wf.nummer_art("AS2026-00012345") == ART_SCHADEN


def test_beide_nummern_im_dropdown_versicherungsnummer_vorausgewaehlt(ctx):
    text = BRIEF_RS.replace("RS Schaden-Nr.:", "Versicherungsnummer: RS-4711-0001\rRS Schaden-Nr.:")
    wf, f = felder(ctx, text)
    n = f["nummer"]
    assert n.value == "RS-4711-0001"
    assert n.choices == ["RS-4711-0001", "AS2026-00012345"]
    assert n.hint == "aus ‚Versicherungsnummer‘ – bitte prüfen"
    assert n.choice_hints["AS2026-00012345"] == "aus ‚RS Schaden-Nr.‘"
    assert wf.nummer_art("RS-4711-0001") == ART_VERSICHERUNG
    assert wf.nummer_art("AS2026-00012345") == ART_SCHADEN


def test_inhaltssteuerelement_hat_vorrang_andere_nummern_bleiben_waehlbar(ctx):
    wf, f = felder(ctx, BRIEF_RS, {"Versicherungsnummer": "VS-1"})
    n = f["nummer"]
    assert (n.value, n.hint) == ("VS-1", "aus Vorlage")
    assert "AS2026-00012345" in n.choices


def test_keine_nummer(ctx):
    _, f = felder(ctx, "An die\rFiktiva Versicherung AG\r54321 Nirgendwo")
    assert (f["nummer"].value, f["nummer"].hint) == ("", "nicht gefunden")


@pytest.mark.parametrize("vorlage, art, erwartet", [
    ("{nummer_art}: {nummer}", ART_SCHADEN, "Schaden-Nr.: AS1"),
    ("{nummer_art}: {nummer}", ART_VERSICHERUNG, "Versicherungsnummer: AS1"),
    ("Versicherungsnummer: {nummer}", ART_SCHADEN, "Schaden-Nr.: AS1"),      # alte config.json
    ("Ihre Angelegenheit – {nummer_art} {nummer}", ART_SCHADEN, "Ihre Angelegenheit – Schaden-Nr. AS1"),
    ("Az. {nummer}", ART_SCHADEN, "Az. AS1"),
])
def test_betreff(vorlage, art, erwartet):
    assert betreff(vorlage, "AS1", art) == erwartet


class _WordDummy:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def export_pdf(self, path, pdf, pdfa=True):
        pdf.write_bytes(b"%PDF-1.7")


@pytest.mark.parametrize("gewaehlt, betreff_erwartet", [
    ("AS2026-00012345", "Schaden-Nr.: AS2026-00012345"),
    ("RS-4711-0001", "Versicherungsnummer: RS-4711-0001"),
])
def test_entwurf_betreff_folgt_gewaehlter_nummer(ctx, tmp_path, monkeypatch, gewaehlt, betreff_erwartet):
    entwuerfe = []
    monkeypatch.setattr(vb, "WordService", _WordDummy)
    monkeypatch.setattr(vb, "entwurf_erstellen", lambda c, d, o: entwuerfe.append(d) or "ok")
    text = BRIEF_RS.replace("RS Schaden-Nr.:", "Versicherungsnummer: RS-4711-0001\rRS Schaden-Nr.:")
    wf, _ = felder(ctx, text)
    doc = tmp_path / "Brief.docx"
    doc.write_bytes(b"x")
    wf.execute(doc, {"versicherer": "", "empfaenger": "test@example.com",
                     "nummer": gewaehlt, "mandant_email": ""})
    assert entwuerfe[0].subject == betreff_erwartet
    assert entwuerfe[0].attachments[0].name.endswith(".pdf")
    assert ctx.journal.akte(gewaehlt)["nummer_art"] in (ART_SCHADEN, ART_VERSICHERUNG)
    assert ctx.adressbuch.alle() == []          # Versicherer leer -> kein Adressbuch-Eintrag


# --- 2. Büronun kendi adresi ----------------------------------------------------
def test_kanzlei_domain_aus_bueroinformationen_wird_ausgeschlossen(ctx):
    _, f = felder(ctx, BRIEF_RS)
    e = f["empfaenger"]
    assert e.value == "test@example.com"
    assert "info@kanzlei-anonym.example.org" not in e.choices


def test_eigene_domains_einstellung_gilt_weiter(ctx):
    text = BRIEF_RS.replace("test@example.com", "post@andere-domain.example.net")
    _, f = felder(ctx, text)
    assert f["empfaenger"].value == ""


def test_nur_kanzleiadresse_feld_leer_und_manuell(ctx):
    text = BRIEF_RS.replace("per E-Mail: test@example.com", "")
    _, f = felder(ctx, text)
    e = f["empfaenger"]
    assert (e.value, e.choices, e.must_choose) == ("", [], False)
    assert e.hint == "nur Kanzlei-Adresse im Brief – bitte manuell eintragen"
    assert e.required                     # ohne manuelle Eingabe kein Entwurf


def test_unterdomain_der_kanzlei_ist_eigen():
    r = extract("mail@sekretariat.kanzlei-anonym.example.org", {},
                dict(DEFAULTS, eigene_domains=["kanzlei-anonym.example.org"]))
    assert r.email == "" and r.eigene_adresse_gefunden


# --- 3. Word zaman sınırı -------------------------------------------------------
def test_zeitlimit_beendet_nur_eigene_word_sitzung(monkeypatch):
    beendet = []
    blockiert = threading.Event()
    monkeypatch.setattr(ws, "word_pids", lambda: {111, 222})       # 222 = Word des Benutzers
    monkeypatch.setattr(ws, "_prozess_beenden", lambda pid: beendet.append(pid) or blockiert.set() or True)
    monkeypatch.setattr(ws, "resiliency_bereinigen", lambda v, p: 0)
    w = ws.WordService(zeitlimit=0.2)
    w.pid = 111
    with pytest.raises(ws.WordError) as e:
        with w._waechter(Path("C:/x/brief.docx")):
            # wie ein hängender COM-Aufruf: kehrt erst zurück, wenn der Prozess beendet wurde
            if blockiert.wait(5):
                raise OSError("RPC-Server ist nicht verfügbar")
    assert beendet == [111]                        # 222 (Word des Benutzers) bleibt unberührt
    assert "Word-Sitzung wurde beendet" in str(e.value)


def test_zeitlimit_ohne_sichere_pid_beendet_nichts(monkeypatch):
    beendet = []
    monkeypatch.setattr(ws, "word_pids", lambda: {222})
    monkeypatch.setattr(ws, "_prozess_beenden", lambda pid: beendet.append(pid) or True)
    w = ws.WordService(zeitlimit=0.1)
    w.pid = None                                   # nicht eindeutig -> nichts beenden
    with pytest.raises(ws.WordError) as e:
        with w._waechter(Path("C:/x/brief.docx")):
            threading.Event().wait(0.4)
    assert beendet == []
    assert "konnte nicht automatisch beendet werden" in str(e.value)


def test_ohne_zeitueberschreitung_kein_eingriff(monkeypatch):
    monkeypatch.setattr(ws, "_prozess_beenden", lambda pid: pytest.fail("darf nicht beenden"))
    w = ws.WordService(zeitlimit=5)
    w.pid = 111
    with w._waechter(Path("C:/x/brief.docx")):
        pass


def test_tasklist_ausgabe_mit_umlauten_und_ohne_word():
    # Windows-Test: deutsche/türkische Meldung in OEM-Codepage ließ word_pids() abstürzen
    ohne = "INFORMATION: Es werden keine Aufgaben mit den angegebenen Kriterien ausgeführt.\r\n"
    assert ws._pids_aus_tasklist(ohne.encode("cp850")) == set()
    assert ws._pids_aus_tasklist("Bilgi: Belirtilen ölçütlerle çalışan görev yok.".encode("cp857")) == set()
    mit = b'"WINWORD.EXE","4711","Console","1","209.428 K"\r\n"WINWORD.EXE","815","Console","1","1 K"\r\n'
    assert ws._pids_aus_tasklist(mit) == {4711, 815}


def test_sperrdatei_nur_wenn_von_eigener_sitzung(tmp_path):
    import time
    doc = tmp_path / "Brief_mit_Kennwort.docx"
    doc.write_bytes(b"x")
    sperre = tmp_path / "~$ief_mit_Kennwort.docx"
    sperre.write_bytes(b"owner")
    # Sperre älter als unsere Sitzung (= Word des Benutzers) -> bleibt
    assert ws.sperrdatei_entfernen(doc, seit=time.time() + 60) == []
    assert sperre.exists()
    # Sperre nach Start unserer Sitzung entstanden -> wird entfernt
    assert ws.sperrdatei_entfernen(doc, seit=time.time() - 60) == ["~$ief_mit_Kennwort.docx"]
    assert not sperre.exists() and doc.exists()


def test_resiliency_eintrag_nur_fuer_genau_diese_datei():
    pfad = Path(r"C:\BnX-Test\buero_vorlage\Brief.docx")
    daten = b"\x01\x00" + str(pfad).lower().encode("utf-16-le") + b"\x00\x00"
    assert ws.eintrag_betrifft(daten, pfad)
    assert not ws.eintrag_betrifft(daten, Path(r"C:\Andere\Brief.docx"))
    assert not ws.eintrag_betrifft("kein bytes", pfad)
