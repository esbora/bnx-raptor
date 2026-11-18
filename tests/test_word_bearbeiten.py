"""0.4.1: Word-Bearbeitung über echte Word-Kopie + verständliche Fehlermeldungen (ohne Windows/Word testbar)."""
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import fehlertexte as ft  # noqa: E402
from core import word_dokument as wd  # noqa: E402


class FakeComError(Exception):
    """Gleiche Form wie pywintypes.com_error: (hresult, text, excepinfo, argerr)."""


ARALIK = FakeComError(-2147352567, "Ausnahmefehler aufgetreten.",
                      (0, "Microsoft Word", "Aralık silinemez.", "wdmain11.chm", 25508, -2146822260), None)


def test_com_fehler_wird_deutsch_und_ohne_tupel(tmp_path):
    ft.protokoll_einrichten(tmp_path)
    text = ft.meldung(ARALIK, "Speichern")
    assert text.startswith("Speichern: Word konnte diesen Teil des Dokuments nicht ändern")
    assert "-2147352567" not in text and "wdmain11" not in text and "(" not in text.split(":", 1)[1][:3]
    for h in ft.LOG.handlers:
        h.flush()
    log = (tmp_path / "bnx-raptor.log").read_text(encoding="utf-8")
    assert "-2146822260" in log and "Aralık silinemez" in log          # Technik nur im Protokoll


def test_unbekannter_com_fehler_und_hresult_direkt():
    unbekannt = FakeComError(-2147352567, "Ausnahmefehler aufgetreten.", (0, "Word", "x", None, 0, -1234), None)
    assert ft.meldung(unbekannt) == ft.ALLGEMEIN
    rpc = FakeComError(-2147023170, "Der Remoteprozeduraufruf ist fehlgeschlagen.", None, None)
    assert "unerwartet beendet" in ft.meldung(rpc)
    # COM-Fehler als Ursache einer leeren Ausnahme
    try:
        try:
            raise ARALIK
        except FakeComError as e:
            raise RuntimeError("") from e
    except RuntimeError as r:
        assert "geschützt oder gesperrt" in ft.meldung(r)


def test_normale_fehler_bleiben_lesbar_und_tupel_nie_sichtbar():
    assert ft.meldung(ValueError("Bitte einen Namen eingeben.")) == "Bitte einen Namen eingeben."
    assert ft.meldung(RuntimeError(str(ARALIK.args))) == ft.ALLGEMEIN        # eingebettetes Tupel → allgemein


def test_kopie_name_datum_und_zaehler(tmp_path):
    orig = tmp_path / "11_Vollmacht.docx"
    orig.write_bytes(b"PK")
    tag = date(2026, 11, 18)
    k1 = wd.bearbeitungskopie(orig, tag)
    assert k1.name == "11_Vollmacht_2026-11-18.docx" and orig.read_bytes() == b"PK"
    k2 = wd.bearbeitungskopie(orig, tag)
    assert k2.name == "11_Vollmacht_2026-11-18_2.docx"
    assert wd.ist_bnx_kopie(k1) and wd.ist_bnx_kopie(k2) and not wd.ist_bnx_kopie(orig)
    assert wd.ist_bnx_kopie(tmp_path / "Mietvertrag (Word).docx")


def test_schutz_hinweise():
    assert wd.schutz_texte(wd.WD_KEIN_SCHUTZ, []) == []
    h = wd.schutz_texte(3, [("Versicherungsnummer", True, True), ("Datum", False, True), ("", False, False)], True)
    assert any("schreibgeschützt" in x for x in h)
    assert any("nur Lesen" in x and "Schutz aufheben" in x for x in h)
    assert any("1 Inhaltssteuerelement(e) sind gegen Änderungen gesperrt (Versicherungsnummer)" in x for x in h)
    assert any("1 Inhaltssteuerelement(e) können nicht gelöscht werden (Datum)" in x for x in h)


def test_wird_bearbeitet_nur_diese_datei(tmp_path):
    f = tmp_path / "11_Vollmacht_2026-11-18.docx"
    f.write_bytes(b"PK")
    assert not wd.wird_bearbeitet(f)
    besitzer = tmp_path / "~$_Vollmacht_2026-11-18.docx"         # so legt Word die Besitzerdatei an
    besitzer.write_bytes(b"x")
    assert wd.wird_bearbeitet(f)
    besitzer.unlink()
    assert not wd.wird_bearbeitet(f)
    andere = tmp_path / "~$deres.docx"                          # Besitzerdatei eines anderen Dokuments
    andere.write_bytes(b"x")
    assert not wd.wird_bearbeitet(f)
    logging.getLogger("bnx").handlers.clear()
