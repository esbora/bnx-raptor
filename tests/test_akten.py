import sqlite3
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import DEFAULTS  # noqa: E402
from core.eingang import dateiname_eingang, eml_lesen, finde_referenz  # noqa: E402
from core.eingang_service import eml_ablegen, zielordner  # noqa: E402
from core.journal import Journal  # noqa: E402
from core.kanzlei import KanzleiStore  # noqa: E402
from core.update import ist_neuer, release_parsen, version_tuple  # noqa: E402
from workflows.base import AppContext  # noqa: E402

REFS = ["AS-4711/2026", "123 456 789", "KFZ-2026-001"]


# --- Eşleştirme ---
def test_referenz_in_varianten():
    assert finde_referenz("AW: Versicherungsnummer AS 4711 2026", REFS) == "AS-4711/2026"
    assert finde_referenz("Ihr Zeichen: as4711/2026, Schaden", REFS) == "AS-4711/2026"
    assert finde_referenz("Vertrag 123-456-789 betreffend", REFS) == "123 456 789"


def test_keine_falschen_treffer():
    assert finde_referenz("Tel. 0221 1234567890", REFS) is None          # daha uzun sayının parçası
    assert finde_referenz("XAS-4711/2026", REFS) is None                 # önünde harf
    assert finde_referenz("nichts", REFS) is None
    assert finde_referenz("12345 kommt vor", ["12345"]) is None          # çok kısa numara yok sayılır


# --- Veritabanı ---
def test_alte_datenbank_wird_migriert(tmp_path):
    db = tmp_path / "v.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE vorgaenge (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit TEXT, workflow TEXT,"
                " dokument TEXT, ergebnis TEXT, empfaenger TEXT, referenz TEXT, status TEXT, meldung TEXT)")
    con.execute("INSERT INTO vorgaenge (zeit, referenz, status) VALUES ('2026-01-01', 'X', 'ok')")
    con.commit()
    con.close()
    j = Journal(db)
    assert j.recent()[0]["art"] == "ausgang"


def test_akte_und_verlauf(tmp_path):
    j = Journal(tmp_path / "v.sqlite")
    j.akte_speichern("AS-4711/2026", ordner="C:/Akten/1", versicherer_email="s@allianz.de")
    j.akte_speichern("AS-4711/2026", mandant_email="m@x.de", ordner="")   # boş, eskiyi silmez
    j.add("w", "a.docx", "a.pdf", "s@allianz.de", "AS-4711/2026")
    j.add("w", "a.docx", "a.pdf", "m@x.de", "AS-4711/2026", art="mandant")
    j.add("w", "b.docx", referenz="AS-4711/2026", status="abgebrochen")
    a = j.akte("AS-4711/2026")
    assert a["ordner"] == "C:/Akten/1" and a["mandant_email"] == "m@x.de"
    assert [v["art"] for v in j.verlauf("AS-4711/2026")] == ["mandant", "ausgang"]
    liste = j.akten("allianz")
    assert len(liste) == 1 and liste[0]["anzahl"] == 2


# --- Gelen e-posta (.eml) ---
def _eml(betreff: str) -> bytes:
    m = EmailMessage()
    m["From"] = "Schaden Team <schaden@allianz.de>"
    m["Subject"] = betreff
    m["Date"] = "Fri, 20 Nov 2026 10:15:00 +0100"
    m["Message-ID"] = "<abc@allianz.de>"
    m.set_content("Sehr geehrte Damen und Herren, ...")
    m.add_attachment(b"%PDF-1.7", maintype="application", subtype="pdf", filename="Gutachten.pdf")
    return bytes(m)


def test_eml_lesen():
    mail = eml_lesen(_eml("AW: Versicherungsnummer AS-4711/2026"))
    assert mail.absender == "schaden@allianz.de" and mail.quelle_id == "<abc@allianz.de>"
    assert mail.anhaenge[0][0] == "Gutachten.pdf"
    assert dateiname_eingang(mail.datum, mail.absender, mail.betreff).startswith(
        "2026-11-20_Eingang_allianz.de_AW- Versicherungsnummer AS-4711-2026")


def test_eml_ablegen_und_kein_doppelimport(tmp_path):
    j = Journal(tmp_path / "v.sqlite")
    ctx = AppContext(dict(DEFAULTS, eingang_unterordner="Eingang"), KanzleiStore(tmp_path / "d"), j)
    akte_ordner = tmp_path / "Akte1"
    j.akte_speichern("AS-4711/2026", ordner=str(akte_ordner))
    roh = _eml("AW: AS-4711/2026")
    mail = eml_lesen(roh)
    ziel = zielordner(ctx, "AS-4711/2026")
    assert ziel == akte_ordner / "Eingang"
    dateien = eml_ablegen(ctx, mail, roh, "AS-4711/2026", ziel)
    assert [d.suffix for d in dateien] == [".eml", ".pdf"] and all(d.exists() for d in dateien)
    assert j.bereits_importiert("<abc@allianz.de>")
    assert j.verlauf("AS-4711/2026")[0]["art"] == "eingang"


# --- Güncelleme ---
def test_versionen():
    assert version_tuple("v1.2.10") == (1, 2, 10) and version_tuple("0.3") == (0, 3, 0)
    assert ist_neuer("v0.10.0", "0.9.9") and not ist_neuer("0.2.0", "0.2.0")
    assert not ist_neuer("0.2.0-beta", "0.2.0")


def test_release_parsen():
    r = release_parsen({"tag_name": "v0.3.0", "html_url": "https://github.com/x/y/releases/v0.3.0",
                        "body": "Neu: …", "assets": [{"name": "BnX-Raptor-0.3.0.zip",
                                                      "browser_download_url": "https://dl/zip"}]})
    assert (r.version, r.download) == ("0.3.0", "https://dl/zip")


def test_mail_modus_auto_ohne_outlook(monkeypatch):
    # Gerçek Outlook aranmaz: sonuç makineden bağımsız olmalı (Windows'ta Outlook başlatmasın)
    from core import entwurf
    monkeypatch.setattr(entwurf, "klassisches_outlook_verfuegbar", lambda: False)
    assert entwurf.mail_modus({"mail_modus": "auto"}) == "eml"
    monkeypatch.setattr(entwurf, "klassisches_outlook_verfuegbar", lambda: True)
    assert entwurf.mail_modus({"mail_modus": "auto"}) == "outlook"
    assert entwurf.mail_modus({"mail_modus": "outlook"}) == "outlook"
