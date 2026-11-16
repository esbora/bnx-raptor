"""Gelen cevabı dosyaya kaydetme + günlüğe yazma. Outlook ve .eml için ortak akış."""
from __future__ import annotations

from pathlib import Path

from .eingang import EingangsMail, dateiname_eingang
from .extractor import safe_filename


def zielordner(ctx, referenz: str) -> Path | None:
    """Dosyanın klasörü (+ ayarlardaki alt klasör). Bilinmiyorsa None."""
    akte = ctx.journal.akte(referenz)
    if not akte or not akte.get("ordner"):
        return None
    ordner = Path(akte["ordner"])
    unter = ctx.cfg.get("eingang_unterordner", "")
    return ordner / unter if unter else ordner


def _frei(p: Path) -> Path:
    i = 2
    while p.exists():
        p = p.with_name(f"{p.stem}_{i}{p.suffix}")
        i += 1
    return p


def eml_ablegen(ctx, mail: EingangsMail, rohdaten: bytes, referenz: str, ordner: Path) -> list[Path]:
    """.eml dosyasını ve eklerini dosya klasörüne kaydeder, günlüğe yazar."""
    ordner.mkdir(parents=True, exist_ok=True)
    basis = dateiname_eingang(mail.datum, mail.absender, mail.betreff)
    eml = _frei(ordner / f"{basis}.eml")
    eml.write_bytes(rohdaten)
    dateien = [eml]
    for name, daten in mail.anhaenge:
        ziel = _frei(ordner / f"{basis}_Anlage_{safe_filename(name, 80)}")
        ziel.write_bytes(daten)
        dateien.append(ziel)
    protokollieren(ctx, referenz, mail.absender, mail.betreff, dateien, mail.quelle_id)
    return dateien


def protokollieren(ctx, referenz: str, absender: str, betreff: str,
                   dateien: list[Path], quelle_id: str) -> None:
    anl = len(dateien) - 1
    ctx.journal.add("eingang", str(dateien[0]), str(dateien[0]), absender, referenz,
                    meldung=f"{betreff}" + (f" ({anl} Anlage(n))" if anl else ""),
                    art="eingang", quelle_id=quelle_id)
