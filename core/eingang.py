"""Gelen e-postalar: sigorta numarasına göre dosya eşleştirme, .eml okuma, dosya adı.

Saf Python – Outlook gerektirmez, test edilebilir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime

from .extractor import safe_filename

MIN_LAENGE = 6     # daha kısa numaralar yanlış eşleşmeye (telefon, tarih) yol açar


def normalisieren(s: str) -> str:
    return re.sub(r"[\s\-/.]", "", s).upper()


def finde_referenz(text: str, referenzen: list[str]) -> str | None:
    """Metinde geçen ilk bilinen sigorta numarasını döndürür (uzun numaralar önce).

    'AS-4711/2026', 'AS 4711 2026' ve 'as47112026' aynı kabul edilir.
    Numaranın önünde/arkasında harf/rakam varsa eşleşme sayılmaz.
    """
    kandidaten = sorted(
        ((normalisieren(r), r) for r in referenzen
         if len(normalisieren(r)) >= MIN_LAENGE and any(c.isdigit() for c in r)),
        key=lambda x: -len(x[0]))
    if not kandidaten:
        return None
    # Ayırıcıları atarak tarama: her karakterin orijinal konumunu da tut
    zeichen = [(c.upper(), i) for i, c in enumerate(text) if c not in " \t\r\n-/."]
    flach = "".join(c for c, _ in zeichen)
    for norm, original in kandidaten:
        start = 0
        while (pos := flach.find(norm, start)) != -1:
            vor = text[zeichen[pos][1] - 1] if zeichen[pos][1] > 0 else " "
            ende = zeichen[pos + len(norm) - 1][1]
            nach = text[ende + 1] if ende + 1 < len(text) else " "
            if not vor.isalnum() and not nach.isalnum():
                return original
            start = pos + 1
    return None


@dataclass
class EingangsMail:
    quelle_id: str
    datum: datetime | None
    absender: str
    betreff: str
    text: str
    anhaenge: list[tuple[str, bytes]] = field(default_factory=list)


def eml_lesen(daten: bytes) -> EingangsMail:
    msg = BytesParser(policy=policy.default).parsebytes(daten)
    try:
        datum = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    except (TypeError, ValueError):
        datum = None
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    anhaenge = [(p.get_filename(), p.get_payload(decode=True) or b"")
                for p in msg.iter_attachments() if p.get_filename()]
    return EingangsMail(
        quelle_id=(msg["Message-ID"] or "").strip(),
        datum=datum,
        absender=parseaddr(msg["From"] or "")[1],
        betreff=str(msg["Subject"] or ""),
        text=text,
        anhaenge=anhaenge,
    )


def dateiname_eingang(datum: datetime | None, absender: str, betreff: str) -> str:
    """'2026-11-20_Eingang_allianz.de_Re Versicherungsnummer AS-4711'"""
    d = (datum or datetime.now()).strftime("%Y-%m-%d")
    domain = absender.split("@", 1)[1] if "@" in absender else absender
    return f"{d}_Eingang_{safe_filename(domain, 30)}_{safe_filename(betreff, 60)}"
