import email
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import DEFAULTS  # noqa: E402
from core.extractor import extract, find_emails, find_number, safe_filename  # noqa: E402
from core.mail_service import EmlDrafter, MailDraft, insert_into_body  # noqa: E402

BRIEF = (
    "Rechtsanwaltskanzlei Muster · info@kanzlei-beispiel.de · Tel. 0221 123\r"
    "Allianz Versicherungs-AG\rSchadenabteilung\rschaden@allianz.de\r"
    "Ihre Versicherungs-Nr.: AS-4711/2026 \r"
    "Sehr geehrte Damen und Herren, ..."
)


def test_eigene_domain_wird_ignoriert():
    assert find_emails(BRIEF, ["kanzlei-beispiel.de"]) == ["schaden@allianz.de"]


def test_nummer_mit_varianten():
    labels = DEFAULTS["nummer_bezeichnungen"] + ["Versicherungs-Nr."]
    assert find_number(BRIEF, labels) == "AS-4711/2026"
    assert find_number("VS-Nr. 123 456 789\rweiter", labels) == "123 456 789"
    assert find_number("Versicherungsnummer: 99887766.", labels) == "99887766"
    assert find_number("Schadennummer:\tKFZ-2026-001", labels) == "KFZ-2026-001"
    assert find_number("keine Nummer hier", labels) == ""


def test_vorlagenfelder_haben_vorrang():
    cfg = dict(DEFAULTS, eigene_domains=["kanzlei-beispiel.de"])
    r = extract(BRIEF, {"Empfaenger_Email": "post@huk.de", "Versicherungsnummer": "X-1"}, cfg)
    assert (r.email, r.quelle_email, r.nummer, r.quelle_nummer) == ("post@huk.de", "feld", "X-1", "feld")


def test_textsuche_als_fallback():
    cfg = dict(DEFAULTS, eigene_domains=["kanzlei-beispiel.de"],
               nummer_bezeichnungen=["Versicherungs-Nr."])
    r = extract(BRIEF, {}, cfg)
    assert (r.email, r.quelle_email, r.nummer) == ("schaden@allianz.de", "text", "AS-4711/2026")


def test_dateiname():
    assert safe_filename('AS-4711/2026: "x"') == "AS-4711-2026- -x"


def test_signatur_bleibt_unten():
    html = '<html><body lang="DE"><p>-- Signatur</p></body></html>'
    out = insert_into_body(html, "<p>Text</p>")
    assert out.index("Text") < out.index("Signatur")


def test_eml_ist_unversendeter_entwurf(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.7 test")
    msg = EmlDrafter().build(MailDraft("x@y.de", "Versicherungsnummer: 1", "<p>Hallo</p>", [pdf]))
    parsed = email.message_from_bytes(bytes(msg))
    assert parsed["X-Unsent"] == "1"
    assert [p.get_filename() for p in parsed.walk() if p.get_filename()] == ["a.pdf"]


# --- Kanzleidaten ---
from core.kanzlei import (Kanzlei, KanzleiStore, iban_gueltig, pruefen,  # noqa: E402
                          signatur_html, ust_id_gueltig)


def test_iban():
    assert iban_gueltig("DE89 3704 0044 0532 0130 00")
    assert not iban_gueltig("DE89 3704 0044 0532 0130 01")
    assert not iban_gueltig("DE89 3704")
    assert iban_gueltig("")


def test_ust_id():
    assert ust_id_gueltig("DE 123456789") and not ust_id_gueltig("DE12345")


def test_pruefen_meldet_fehler():
    f = pruefen(Kanzlei(name="", email="kaputt", iban="DE00 1234"))
    assert len(f) == 3


def test_store_speichert_und_laedt(tmp_path):
    store = KanzleiStore(tmp_path)
    logo = tmp_path / "quelle.PNG"
    logo.write_bytes(b"\x89PNG")
    k = Kanzlei(name="Kanzlei Muster", email="info@muster-recht.de",
                iban="de89370400440532013000", ust_id="de 123456789")
    k.logo = store.logo_uebernehmen(logo)
    store.speichern(k)
    g = store.laden()
    assert g.iban == "DE89 3704 0044 0532 0130 00" and g.ust_id == "DE123456789"
    assert g.domain == "muster-recht.de" and store.logo_pfad(g).name == "logo.png"


def test_signatur_escaped_und_vollstaendig():
    k = Kanzlei(name="Müller & Partner", anwaelte="RA A\nRA B", ust_id="DE123456789",
                kammer="RAK Köln")
    h = signatur_html(k, "kanzleilogo")
    assert "Müller &amp; Partner" in h and "cid:kanzleilogo" in h
    assert "RA B" in h and "USt-IdNr.: DE123456789" in h and "RAK Köln" in h


def test_eml_mit_signatur_und_logo(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG fake")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    d = MailDraft("x@y.de", "S", "<p>Text</p>", [pdf],
                  signature_html=signatur_html(Kanzlei(name="K"), "kanzleilogo"), logo=logo)
    parsed = email.message_from_bytes(bytes(EmlDrafter().build(d)))
    cids = [p["Content-ID"] for p in parsed.walk() if p["Content-ID"]]
    assert cids == ["<kanzleilogo>"]
    assert [p.get_filename() for p in parsed.walk() if p.get_filename()] == ["a.pdf"]


def test_eigene_domain_aus_kanzleidaten(tmp_path):
    from workflows.base import AppContext
    store = KanzleiStore(tmp_path)
    store.speichern(Kanzlei(name="K", email="info@muster-recht.de"))
    ctx = AppContext(dict(DEFAULTS), store, None)
    assert "muster-recht.de" in ctx.eigene_domains()
