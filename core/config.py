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
    "betreff_vorlage": "Versicherungsnummer: {nummer}",
    "mail_text_html": (
        "<p>Sehr geehrte Damen und Herren,</p>"
        "<p>in der oben genannten Angelegenheit übersenden wir Ihnen anliegend unser Schreiben.</p>"
        "<p>Mit freundlichen Grüßen</p>"
    ),
    "mail_modus": "outlook",          # "outlook" (klasik Outlook) | "eml" (her programda taslak)
    "pdf_ordner": "",                 # boş = Word dosyasının yanına
    "pdf_dateiname": "{datum}_{nummer}_{dokument}",
    "pdfa": True,
    "mandant_betreff_vorlage": "Ihre Angelegenheit – Versicherungsnummer {nummer}",
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
    "update_repo": "",                # GitHub "kullanici/repo" – boş = güncelleme kontrolü kapalı
    "update_pruefen": True,
    "signatur_quelle": "outlook",     # "outlook" (Outlook imzası) | "programm" (Kanzleidaten'dan)
    "daten_ordner": "",               # boş = %APPDATA%\BnX-Raptor; çok kullanıcı için ağ klasörü
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
