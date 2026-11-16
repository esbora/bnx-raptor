"""Belge metninden e-posta adresi ve sigorta numarası çıkarma.

Windows/Word'e bağımlı değildir, bu yüzden her yerde test edilebilir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")


# Numaranın türü: e-posta konusunda ve kontrol penceresinde bu ad kullanılır
ART_VERSICHERUNG = "Versicherungsnummer"
ART_SCHADEN = "Schaden-Nr."


@dataclass
class NummerFund:
    wert: str
    bezeichnung: str          # mektupta yazdığı gibi, ör. "RS Schaden-Nr."
    art: str                  # ART_VERSICHERUNG | ART_SCHADEN


@dataclass
class ExtractResult:
    email: str = ""
    email_candidates: list[str] = field(default_factory=list)
    nummer: str = ""
    quelle_email: str = ""   # "feld" | "text" | ""
    quelle_nummer: str = ""
    nummern: list[NummerFund] = field(default_factory=list)   # mektupta bulunan tüm numaralar
    nummer_art: str = ""
    eigene_adresse_gefunden: bool = False   # mektupta büronun kendi adresi vardı (aday yapılmadı)


def _label_pattern(label: str) -> str:
    """'Versicherungsschein-Nr.' -> esnek kalıp (boşluk/tire/nokta isteğe bağlı)."""
    parts = [p for p in re.split(r"[\s\-]+", label.strip()) if p]
    escaped = [re.escape(p).replace(r"\.", r"\.?") for p in parts]
    return r"[\s\-]?".join(escaped)


def ist_eigene_adresse(addr: str, own_domains: list[str]) -> bool:
    """Adres büronun kendi alan adına (veya alt alan adına) mı ait?"""
    domain = addr.split("@", 1)[-1].lower()
    own = [d.lower().strip().lstrip("@") for d in own_domains if d.strip()]
    return any(domain == d or domain.endswith("." + d) for d in own)


def find_emails(text: str, own_domains: list[str]) -> list[str]:
    result: list[str] = []
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0).rstrip(".")
        if ist_eigene_adresse(addr, own_domains):
            continue
        if addr.lower() not in (a.lower() for a in result):
            result.append(addr)
    return result


def nummer_art(label: str) -> str:
    """Etiketten tür: "Schaden…" -> Schaden-Nr., diğerleri Versicherungsnummer."""
    return ART_SCHADEN if "schaden" in label.lower() else ART_VERSICHERUNG


def _bezeichnung(text: str, m: re.Match) -> str:
    """Numaranın mektuptaki etiketi. Satır başı kısa ise onu alır ("RS Schaden-Nr."),
    yoksa sadece eşleşen etiketi ("Versicherungsschein-Nr.")."""
    satir_anfang = max(text.rfind(c, 0, m.start()) for c in "\r\n\x0b\x07") + 1
    vorne = text[satir_anfang:m.start(1)].strip().rstrip(":#").strip()
    if vorne and len(vorne) <= 40 and not any(ch.isdigit() for ch in vorne):
        return vorne
    return text[m.start():m.start(1)].strip().rstrip(":#").strip()


def find_numbers(text: str, labels: list[str]) -> list[NummerFund]:
    """Tüm numaralar: önce Versicherungsnummer türleri, sonra Schaden-Nr. (etiket sırası korunur).
    Aynı değer bir kez listelenir."""
    funde: list[NummerFund] = []
    for label in labels:
        pat = re.compile(
            r"(?<![A-Za-zÄÖÜäöüß])" + _label_pattern(label)
            + r"\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-. ]{2,40})",
            re.IGNORECASE,
        )
        for m in pat.finditer(text):
            value = m.group(1).strip().rstrip(".-/ ")
            if not any(ch.isdigit() for ch in value):
                continue
            if value.lower() in (f.wert.lower() for f in funde):
                continue
            funde.append(NummerFund(value, _bezeichnung(text, m), nummer_art(label)))
    return sorted(funde, key=lambda f: f.art != ART_VERSICHERUNG)


def find_number(text: str, labels: list[str]) -> str:
    """Öncelikli numara: Versicherungsnummer varsa o, yoksa Schaden-Nr."""
    funde = find_numbers(text, labels)
    return funde[0].wert if funde else ""


def betreff(vorlage: str, nummer: str, art: str = "") -> str:
    """E-posta konusu. {nummer_art} = "Versicherungsnummer" veya "Schaden-Nr.".
    Eski config.json'larda sabit yazılmış "Versicherungsnummer" kelimesi de türe göre değişir."""
    if "{nummer_art}" not in vorlage:
        vorlage = vorlage.replace(ART_VERSICHERUNG, "{nummer_art}")
    return vorlage.format(nummer=nummer, nummer_art=art or ART_VERSICHERUNG)


def extract(text: str, controls: dict[str, str], cfg: dict) -> ExtractResult:
    """Önce şablondaki içerik denetimleri (kesin), sonra metin araması (tahmin)."""
    r = ExtractResult()
    eigene = cfg.get("eigene_domains", [])
    r.email_candidates = find_emails(text, eigene)
    r.eigene_adresse_gefunden = any(ist_eigene_adresse(m.group(0).rstrip("."), eigene)
                                    for m in EMAIL_RE.finditer(text))

    feld_email = controls.get(cfg.get("feld_email", "Empfaenger_Email"), "").strip()
    if feld_email and EMAIL_RE.fullmatch(feld_email):
        r.email, r.quelle_email = feld_email, "feld"
    elif r.email_candidates:
        r.email, r.quelle_email = r.email_candidates[0], "text"

    r.nummern = find_numbers(text, cfg.get("nummer_bezeichnungen", []))
    feld_nr = controls.get(cfg.get("feld_nummer", "Versicherungsnummer"), "").strip()
    if feld_nr:
        r.nummer, r.quelle_nummer, r.nummer_art = feld_nr, "feld", ART_VERSICHERUNG
        r.nummern = [f for f in r.nummern if f.wert.lower() != feld_nr.lower()]
    elif r.nummern:
        r.nummer, r.quelle_nummer, r.nummer_art = r.nummern[0].wert, "text", r.nummern[0].art
    return r


def is_valid_email(addr: str) -> bool:
    return bool(EMAIL_RE.fullmatch(addr.strip()))


def safe_filename(s: str, max_len: int = 60) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", s).strip(" .-")
    return s[:max_len] or "Dokument"
