"""Ayarlar: programın yanındaki config.json okunur; eksik anahtarlar varsayılanla doldurulur."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS: dict = {
    "eigene_domains": ["kanzlei-beispiel.de"],
    "feld_email": "Empfaenger_Email",
    "feld_nummer": "Versicherungsnummer",
    "nummer_bezeichnungen": [
        "Versicherungsnummer", "Versicherungsschein-Nr.", "Versicherungsscheinnummer",
        "VS-Nr.", "Vers.-Nr.", "Schadennummer", "Schaden-Nr.",
    ],
    "betreff_vorlage": "{nummer_art}: {nummer}",   # {nummer_art} = Versicherungsnummer | Schaden-Nr.
    "mail_text_html": (
        "<p>Sehr geehrte Damen und Herren,</p>"
        "<p>in der oben genannten Angelegenheit übersenden wir Ihnen anliegend unser Schreiben.</p>"
        "<p>Mit freundlichen Grüßen</p>"
    ),
    "mail_modus": "auto",             # "auto" (algıla) | "outlook" (klasik) | "eml" (her programda taslak)
    "pdf_ordner": "",                 # boş = Word dosyasının yanına
    "pdf_dateiname": "{datum}_{nummer}_{dokument}",
    "pdfa": True,
    "mandant_betreff_vorlage": "Ihre Angelegenheit – {nummer_art} {nummer}",
    "mandant_text_html": (
        "<p>Guten Tag,</p>"
        "<p>zu Ihrer Information erhalten Sie anbei eine Kopie unseres heutigen Schreibens "
        "an die Versicherung.</p><p>Mit freundlichen Grüßen</p>"
    ),
    "mandant_info_text_html": (
        "<p>Guten Tag,</p>"
        "<p>anbei erhalten Sie zu Ihrer Information die aktuellen Unterlagen in Ihrer Angelegenheit.</p>"
        "<p>Mit freundlichen Grüßen</p>"
    ),
    "feld_mandant_email": "Mandant_Email",
    "eingang_unterordner": "",        # gelen cevaplar için alt klasör, ör. "Eingang"
    "eingang_tage": 30,               # Outlook'ta kaç gün geriye bakılsın
    "update_repo": "esbora/BnX-Raptor",  # GitHub "kullanici/repo" – boş = güncelleme kontrolü kapalı
    "update_pruefen": True,
    "signatur_quelle": "outlook",     # "outlook" (Outlook imzası) | "programm" (Kanzleidaten'dan)
    "daten_ordner": "",
    "word_zeitlimit_sekunden": 90,    # gizli Word penceresi takılırsa işlem bu süre sonunda biter               # boş = %APPDATA%\BnX-Raptor; çok kullanıcı için ağ klasörü
    # --- Versicherer-Adressbuch (0.3) ---
    "feld_versicherer": "Versicherer",  # Word içerik denetiminin etiketi (Tag/Title)
    # Adres bloğunda sigorta satırını tanıyan kelimeler. >= 8 harf: kelime içinde de aranır,
    # daha kısa olanlar sadece tam kelime olarak.
    "versicherer_stichwoerter": [
        "versicherung", "versicherer", "assekuranz", "rechtsschutz", "haftpflicht",
        "krankenkasse", "insurance", "assurance", "VVaG", "a.G.",
        "Allianz", "AXA", "ERGO", "HDI", "HUK", "DEVK", "LVM", "VHV", "Generali", "Zurich",
        "R+V", "Gothaer", "Debeka", "ARAG", "ADAC", "Provinzial", "Signal Iduna", "Helvetia",
        "Baloise", "Barmenia", "Continentale", "Alte Leipziger", "Württembergische", "WGV",
    ],
    # Bilinen kısaltmalar (eşleştirmede açılır; görünen ad değişmez)
    "versicherer_abkuerzungen": {
        "Vers.": "Versicherung", "Versich.": "Versicherung",
        "Lebensvers.": "Lebensversicherung", "Krankenvers.": "Krankenversicherung",
        "Rechtsschutzvers.": "Rechtsschutzversicherung", "Sachvers.": "Sachversicherung",
        "Allg.": "Allgemeine", "Dt.": "Deutsche", "Ges.": "Gesellschaft",
    },
}


def app_dir() -> Path:
    """exe olarak paketlendiğinde exe'nin klasörü, aksi halde proje klasörü."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def data_dir(cfg: dict | None = None) -> Path:
    if cfg and cfg.get("daten_ordner"):
        d = Path(cfg["daten_ordner"])
    else:
        d = Path(os.environ.get("APPDATA") or str(Path.home())) / "BnX-Raptor"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_config() -> dict:
    """config.json release paketinde YOK – böylece güncelleme büro ayarlarını ezmez.

    Dosya yoksa ilk açılışta varsayılan değerlerle oluşturulur.
    """
    cfg = dict(DEFAULTS)
    path = app_dir() / "config.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        try:
            path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass                      # yazma izni yoksa varsayılanlarla devam
    return cfg
