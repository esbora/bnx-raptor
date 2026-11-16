"""Belge metninden e-posta adresi ve sigorta numarası çıkarma.

Windows/Word'e bağımlı değildir, bu yüzden her yerde test edilebilir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")


@dataclass
class ExtractResult:
    email: str = ""
    email_candidates: list[str] = field(default_factory=list)
    nummer: str = ""
    quelle_email: str = ""   # "feld" | "text" | ""
    quelle_nummer: str = ""


def _label_pattern(label: str) -> str:
    """'Versicherungsschein-Nr.' -> esnek kalıp (boşluk/tire/nokta isteğe bağlı)."""
    parts = [p for p in re.split(r"[\s\-]+", label.strip()) if p]
    escaped = [re.escape(p).replace(r"\.", r"\.?") for p in parts]
    return r"[\s\-]?".join(escaped)


def find_emails(text: str, own_domains: list[str]) -> list[str]:
    own = [d.lower().lstrip("@") for d in own_domains]
    result: list[str] = []
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0).rstrip(".")
        domain = addr.split("@", 1)[1].lower()
        if any(domain == d or domain.endswith("." + d) for d in own):
            continue
        if addr.lower() not in (a.lower() for a in result):
            result.append(addr)
    return result


def find_number(text: str, labels: list[str]) -> str:
    """Etiket listesindeki sıraya göre ilk bulunan numarayı döndürür."""
    for label in labels:
        pat = re.compile(
            r"(?<![A-Za-zÄÖÜäöüß])" + _label_pattern(label)
            + r"\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-. ]{2,40})",
            re.IGNORECASE,
        )
        m = pat.search(text)
        if m:
            value = m.group(1).strip().rstrip(".-/ ")
            if any(ch.isdigit() for ch in value):
                return value
    return ""


def extract(text: str, controls: dict[str, str], cfg: dict) -> ExtractResult:
    """Önce şablondaki içerik denetimleri (kesin), sonra metin araması (tahmin)."""
    r = ExtractResult()
    r.email_candidates = find_emails(text, cfg.get("eigene_domains", []))

    feld_email = controls.get(cfg.get("feld_email", "Empfaenger_Email"), "").strip()
    if feld_email and EMAIL_RE.fullmatch(feld_email):
        r.email, r.quelle_email = feld_email, "feld"
    elif r.email_candidates:
        r.email, r.quelle_email = r.email_candidates[0], "text"

    feld_nr = controls.get(cfg.get("feld_nummer", "Versicherungsnummer"), "").strip()
    if feld_nr:
        r.nummer, r.quelle_nummer = feld_nr, "feld"
    else:
        nr = find_number(text, cfg.get("nummer_bezeichnungen", []))
        if nr:
            r.nummer, r.quelle_nummer = nr, "text"
    return r


def is_valid_email(addr: str) -> bool:
    return bool(EMAIL_RE.fullmatch(addr.strip()))


def safe_filename(s: str, max_len: int = 60) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", s).strip(" .-")
    return s[:max_len] or "Dokument"
