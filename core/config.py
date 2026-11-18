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
    "grosse_vorschau": True,          # 0.4.2: große Vorschau beim Darüberfahren (Einstellungen)
    "signatur_quelle": "outlook",     # "outlook" (Outlook imzası) | "programm" (Kanzleidaten'dan)
    "daten_ordner": "",               # boş = %APPDATA%\BnX-Raptor; çok kullanıcı için ağ klasörü
    "word_zeitlimit_sekunden": 90,    # gizli Word penceresi takılırsa işlem bu süre sonunda biter
    # --- PDF-Editor / Anlagen-Assistent (0.4) ---
    "anlagen_praefix": "Anlage K",    # Anlage K1, K2 … (Kläger); z. B. "Anlage B" für Beklagte
    "ocr_sprachen": ["deu", "tur", "eng"],   # Tesseract-Sprachen; die erste hat Vorrang
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


class ConfigFehler(Exception):
    """config.json okunamadı – programın başında Almanca mesajla gösterilir."""


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
        # utf-8-sig: Not Defteri'nin eklediği BOM'u da kabul eder
        with open(path, encoding="utf-8-sig") as f:
            try:
                cfg.update(json.load(f))
            except json.JSONDecodeError as e:
                raise ConfigFehler(
                    f"Die Datei config.json ist fehlerhaft (Zeile {e.lineno}, Spalte {e.colno}).\n"
                    f"{path}\n\nBitte die Datei korrigieren oder löschen – BnX-Raptor legt sie "
                    "dann mit den Standardwerten neu an.") from e
    else:
        try:
            path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass                      # yazma izni yoksa varsayılanlarla devam
    return cfg


def einstellung_speichern(schluessel: str, wert) -> bool:
    """Einen Wert in config.json setzen (andere Einträge bleiben unverändert). False, wenn nicht schreibbar."""
    path = app_dir() / "config.json"
    try:
        daten = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else dict(DEFAULTS)
        daten[schluessel] = wert
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True
    except (OSError, ValueError):
        return False
