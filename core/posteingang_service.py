"""Posteingang: Eingangsstücke einlesen und ablegen (gemeinsamer Weg für Outlook, .eml/.msg und Dateien).

- Quelldateien und das Postfach werden nie verändert: BnX-Raptor speichert Kopien in seiner Ablage
  (`ctx.ablage("Posteingang")`) und erfasst sie im Dokumentenarchiv (Arbeitsplatz: Übertragung zum Server).
- Doppelte vermeiden: vor dem Ablegen Message-ID bzw. SHA-256 der Rohdatei prüfen; jedes Stück hat eine eigene
  client_id – ein erneuter Versuch nach einem Verbindungsabbruch legt nichts doppelt an.
- Text (Mailtext + Text der PDF/Word-Anhänge) dient nur dem Akte-Vorschlag und der Suche; keine externe KI.
"""
from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.eingang import eml_lesen
from core.extractor import safe_filename
from core.posteingang import belegart_vorschlag, datum_vorschlag

DATEI_ENDUNGEN = {".pdf", ".docx", ".docm", ".doc", ".rtf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".txt",
                  ".xlsx", ".eml", ".msg"}
TEXT_JE_DATEI = 6000


@dataclass
class Stueck:
    quelle: str                                    # outlook | eml | msg | datei
    betreff: str = ""
    absender: str = ""
    absender_name: str = ""
    text: str = ""
    eingang_am: str = ""
    dokument_datum: str = ""
    quelle_id: str = ""                            # Message-ID (E-Mail)
    sha256: str = ""                               # Prüfsumme der Rohdatei (.eml/.msg/Einzeldatei)
    dateien: list[dict] = field(default_factory=list)   # {name, rolle: mail|anhang|datei, daten?: bytes, pfad?: Path}
    hinweise: list[str] = field(default_factory=list)
    client_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def titel(self) -> str:
        return self.betreff or (self.dateien[0]["name"] if self.dateien else "Eingang")


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_datei(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _datei_text(name: str, daten: bytes | None = None, pfad: Path | None = None) -> str:
    """Text eines PDF/Word-Anhangs (nur für Vorschlag/Suche). Scans ohne Textebene → '' (kein OCR hier)."""
    endung = Path(name).suffix.lower()
    if endung not in (".pdf", ".docx", ".docm", ".txt"):
        return ""
    import tempfile
    from core.versand import text_lesen
    try:
        if pfad is None:
            with tempfile.TemporaryDirectory(prefix="bnx-text-") as td:
                p = Path(td) / ("x" + endung)
                p.write_bytes(daten or b"")
                text, _ = text_lesen(p)
        else:
            text, _ = text_lesen(pfad)
    except Exception:  # noqa: BLE001
        return ""
    return (text or "")[:TEXT_JE_DATEI]


def aus_eml(pfad: Path) -> Stueck:
    roh = Path(pfad).read_bytes()
    m = eml_lesen(roh)
    s = Stueck("eml", betreff=m.betreff, absender=m.absender, text=m.text or "", quelle_id=m.quelle_id,
               sha256=_sha_bytes(roh),
               eingang_am=(m.datum.strftime("%Y-%m-%d %H:%M:%S") if m.datum else ""))
    s.dateien.append({"name": Path(pfad).name, "rolle": "mail", "daten": roh})
    for name, daten in m.anhaenge:
        s.dateien.append({"name": name, "rolle": "anhang", "daten": daten})
        t = _datei_text(name, daten=daten)
        if t:
            s.text += f"\n\n[Anlage {name}]\n{t}"
    s.dokument_datum = datum_vorschlag(m.text) or ((m.datum.date().isoformat()) if m.datum else "")
    return s


def aus_datei(pfad: Path) -> Stueck:
    """Einzelne Datei (PDF, Word, Scan …) – Inhalt bleibt unverändert, Text nur zum Vorschlagen."""
    p = Path(pfad)
    s = Stueck("datei", betreff=p.stem, sha256=_sha_datei(p),
               eingang_am=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    s.dateien.append({"name": p.name, "rolle": "datei", "pfad": p})
    s.text = _datei_text(p.name, pfad=p)
    if p.suffix.lower() == ".pdf" and not s.text.strip():
        s.hinweise.append("PDF ohne Textebene (Scan) – Vorschlag nur aus Dateiname; Texterkennung möglich.")
    s.dokument_datum = datum_vorschlag(s.text)
    return s


def aus_msg_ohne_outlook(pfad: Path) -> Stueck:
    s = aus_datei(pfad)
    s.quelle = "msg"
    s.dateien[0]["rolle"] = "mail"
    s.hinweise.append("Outlook-Datei (.msg) ohne klassisches Outlook übernommen – Absender, Text und Anhänge wurden "
                      "nicht gelesen. Bitte Datei öffnen und Angaben ergänzen.")
    return s


def belegart(s: Stueck) -> str:
    return belegart_vorschlag(s.betreff, [d["name"] for d in s.dateien], s.text) or \
        ("E-Mail" if s.quelle in ("outlook", "eml", "msg") else "")


def _ordner(ctx, s: Stueck) -> Path:
    basis = ctx.ablage("Posteingang") / datetime.now().strftime("%Y-%m")
    name = f"{datetime.now():%Y-%m-%d}_{safe_filename(s.titel, 50)}_{s.client_id[:6]}"
    o = basis / name
    o.mkdir(parents=True, exist_ok=True)
    return o


def ablegen(ctx, s: Stueck, verantwortlich: str = "") -> dict:
    """Stück als Eingang anlegen. → {id, doppelt, wiederholt, betreff}. Doppelte: nichts wird abgelegt."""
    dup = ctx.posteingang.vorhanden(s.quelle_id, s.sha256)
    if dup:
        return {"id": dup["id"], "doppelt": True, "wiederholt": False, "betreff": dup.get("betreff") or s.titel,
                "akte": dup.get("akte") or ""}
    ordner = _ordner(ctx, s)
    dateien = []
    vergeben: set[str] = set()
    for i, d in enumerate(s.dateien):
        name = safe_filename(Path(d["name"]).stem, 90) + Path(d["name"]).suffix.lower()
        if d["rolle"] == "anhang":
            name = f"Anlage_{name}"
        n = 2
        basis = name
        while name.lower() in vergeben:
            name = f"{Path(basis).stem}_{n}{Path(basis).suffix}"
            n += 1
        vergeben.add(name.lower())
        ziel = ordner / name
        if not ziel.exists():
            if d.get("daten") is not None:
                ziel.write_bytes(d["daten"])
            else:
                shutil.copyfile(d["pfad"], ziel)               # Quelldatei bleibt unverändert
        sha = _sha_datei(ziel)
        did = ctx.archiv.erfassen(ziel, akte="", rolle="eingang", notiz=f"Posteingang: {s.titel}"[:200])
        dok = ctx.archiv.dokument(did) if did else None
        dateien.append({"rolle": d["rolle"], "dokument_id": did, "name": name,
                        "pfad": (dok or {}).get("pfad") or str(ziel), "sha256": sha, "position": i})
    erg = ctx.posteingang.anlegen(s.client_id, s.quelle, dateien, quelle_id=s.quelle_id, sha256=s.sha256,
                                  absender=s.absender, absender_name=s.absender_name, betreff=s.betreff,
                                  text=s.text, eingang_am=s.eingang_am, dokument_datum=s.dokument_datum,
                                  belegart=belegart(s), verantwortlich=verantwortlich)
    erg["betreff"] = s.titel
    return erg
