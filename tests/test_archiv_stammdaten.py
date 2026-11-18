"""0.4.1: Dokumentenarchiv, Mandanten, Versicherungen (eine Datenbank, Adressbuch wiederverwendet)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.adressbuch import Adressbuch  # noqa: E402
from core.archiv import Archiv  # noqa: E402
from core.journal import Journal  # noqa: E402
from core.stammdaten import Stammdaten  # noqa: E402


@pytest.fixture
def db(tmp_path):
    return tmp_path / "verlauf.sqlite"


def test_archiv_akte_typ_zeiten_und_neustart(db, tmp_path):
    pdf = tmp_path / "Rechnung.pdf"
    pdf.write_bytes(b"%PDF-1.4 a")
    word = tmp_path / "Rechnung (Word).docx"
    word.write_bytes(b"PK x")
    j = Journal(db)
    j.akte_speichern("FV-1", mandant_name="Erika Erfunden")
    a = Archiv(j.con)
    did = a.erfassen(pdf)                                         # ohne Akte bearbeitet
    a.erfassen(word, rolle="umgewandelt", quelle=pdf)              # Word-Arbeitskopie ← PDF
    assert [d["name"] for d in a.liste(ohne_akte=True)] == ["Rechnung (Word).docx", "Rechnung.pdf"]
    a.zuordnen(did, "FV-1")                                       # später einer Akte zuordnen
    pdf.write_bytes(b"%PDF-1.4 b")
    a.bearbeitet(pdf)
    j.con.close()
    # Programm neu gestartet: gleiche Datei, neue Verbindung
    a2 = Archiv(Journal(db).con)
    d = a2.liste(akte="FV-1")[0]
    assert (d["name"], d["typ"], d["akte"]) == ("Rechnung.pdf", "PDF", "FV-1") and d["bearbeitet"] and d["hinzugefuegt"]
    w = a2.liste(ohne_akte=True)[0]
    assert w["typ"] == "Word" and w["rolle"] == "umgewandelt" and w["quelle_name"] == "Rechnung.pdf"
    assert a2.arbeitskopie(pdf) == word
    a2.erfassen(pdf)                                              # erneutes Erfassen löscht die Akte nicht
    assert a2.liste(akte="FV-1")[0]["id"] == did


def test_mandanten_mehrere_akten_und_alte_akten(db):
    j = Journal(db)
    j.akte_speichern("SCH 2026/1", nummer_art="Schaden-Nr.", versicherer_email="s@example.com")   # alte Akte
    st = Stammdaten(j.con, Adressbuch(j.con))
    m = st.mandant_speichern(None, name="Muster GmbH", art="firma", strasse="Weg 1", plz="12345", ort="Musterstadt",
                             telefon="0000", email="info@example.com", notiz="fiktiv")
    st.akte_anlegen("2026/0815", aktenzeichen="0815/26", mandant_id=m, versicherungsnummer="FV-4711",
                    schaden_nr="SCH 99")
    st.akte_setzen("SCH 2026/1", mandant_id=m)
    assert {a["referenz"] for a in st.akten_von_mandant(m)} == {"2026/0815", "SCH 2026/1"}
    alt = st.akte("SCH 2026/1")
    assert alt["schaden_nr"] == "SCH 2026/1" and not alt["versicherungsnummer"]       # alte Akte bleibt lesbar
    assert alt["versicherer_email"] == "s@example.com"
    neu = st.akte("2026/0815")
    assert (neu["versicherungsnummer"], neu["schaden_nr"], neu["aktenzeichen"]) == ("FV-4711", "SCH 99", "0815/26")
    st.mandant_speichern(m, telefon="1111")
    assert st.mandant(m)["telefon"] == "1111" and st.mandant(m)["name"] == "Muster GmbH"
    assert st.mandanten("muster")[0]["akten"] == 2
    st.mandant_loeschen(m)
    assert st.akte("2026/0815") is not None and st.akte("2026/0815")["mandant_id"] is None


def test_versicherungen_nutzen_das_adressbuch(db):
    j = Journal(db)
    buch = Adressbuch(j.con)
    buch.lernen("Fiktiva Versicherung AG", "schaden@example.com")          # bestehendes Adressbuch
    buch.lernen("Andere Vers. AG", "a@example.com")
    st = Stammdaten(j.con, buch)
    liste = st.versicherungen()
    assert [v["quelle"] for v in liste] == ["Adressbuch", "Adressbuch"]     # sofort sichtbar
    vid = st.versicherung_speichern(None, name="Fiktiva Versicherung AG", strasse="Ausgedachter Weg 99",
                                    telefon="0000")
    st.email_hinzufuegen(vid, "post@example.com")
    v = st.versicherung(vid)
    assert set(v["emails"]) == {"schaden@example.com", "post@example.com"}
    assert {e for e, _ in buch.emails("Fiktiva Versicherung AG")} == set(v["emails"])   # eine Quelle
    assert len([x for x in st.versicherungen() if "Fiktiva" in x["name"]]) == 1
    st.versicherung_speichern(vid, name="Fiktiva Versicherung SE")          # Umbenennen nimmt E-Mails mit
    assert len(st.versicherung(vid)["emails"]) == 2
    st.email_entfernen(vid, "post@example.com")
    assert st.versicherung(vid)["emails"] == ["schaden@example.com"]
    st.akte_anlegen("FV-1", versicherung_id=vid)
    assert st.akten_von_versicherung(vid)[0]["referenz"] == "FV-1"
