"""Versandkontrolle – Ablauf für Anlagen-Assistent, Akten-E-Mails und Erinnerungen (ein gemeinsamer Weg).

prüfen → (Bestätigung durch den Benutzer, falls nötig) → feste Versandkopien (optional bereinigt) →
Outlook-/eml-Entwurf aus diesen Kopien (Anhänge werden geprüft) → Versandnachweis „Entwurf erstellt“.
Es wird NIE gesendet. Die Originale im Archiv bleiben unverändert.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from core.entwurf import entwurf_erstellen
from core.mail_service import MailDraft
from core.versand import (Bereinigung, Ergebnis, Parteien, aenderungen_seit_entwurf, bereinigen, feste_kopien,
                          gesendet_passt, pruefen)


def _feld(x, name, standard=None):
    return x.get(name, standard) if isinstance(x, dict) else getattr(x, name, standard)


def parteien_aus_infos(infos: list, akte: str) -> Parteien:
    """Aus `posteingang.akten_infos()` (lokal: AktenInfo, über das Netz: dict) die Beteiligten der Akte und –
    für die Gegenprobe – die Adressen und Nummern aller anderen Akten."""
    p = Parteien()
    for info in infos:
        ref = _feld(info, "referenz")
        emails = [tuple(e) for e in _feld(info, "emails", [])]
        nummern = [tuple(n) for n in _feld(info, "nummern", [])]
        if ref == akte:
            p.mandant += [m for r, m in emails if r == "Mandant"]
            p.versicherung += [m for r, m in emails if r == "Versicherung"]
            p.nummern += [w for _, w in nummern if w]
        else:
            for _r, m in emails:
                p.andere.setdefault(m.lower(), []).append(ref)
            for _b, w in nummern:
                if w and len(w.replace(" ", "")) >= 5:
                    p.andere_nummern.setdefault(w, ref)
    eigene = {m.lower() for m in p.mandant + p.versicherung}
    p.andere = {k: v for k, v in p.andere.items() if k not in eigene}
    eigene_n = set(p.nummern)
    p.andere_nummern = {k: v for k, v in p.andere_nummern.items() if k not in eigene_n}
    return p


def parteien(ctx, akte: str) -> Parteien | None:
    if not akte:
        return None
    return parteien_aus_infos(ctx.posteingang.akten_infos(), akte)


def kontrolle(ctx, akte: str, empfaenger: str, hauptdokument: Path | None, anlagen: list[tuple[Path, str]],
              weitere: list[Path] | None = None) -> Ergebnis:
    return pruefen(empfaenger, akte, parteien(ctx, akte), hauptdokument, anlagen, weitere)


@dataclass
class Anhang:
    pfad: Path                     # Datei, wie sie der Benutzer gewählt hat (Paketdatei, Arbeitskopie …)
    rolle: str = "anlage"          # hauptdokument | anlage | weitere
    bezeichnung: str = ""
    bereinigen: bool = False
    kommentare_entfernen: bool = False


@dataclass
class EntwurfErgebnis:
    meldung: str
    eintrag: dict | None
    bereinigungen: list[Bereinigung] = field(default_factory=list)
    nachweis_fehler: str = ""      # Entwurf erstellt, aber Nachweis (noch) nicht gespeichert


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _server_pfad(ctx, p: Path) -> str:
    k = getattr(ctx, "_kopien", None)
    if k is not None:
        e = k._eintrag_lokal(Path(p))
        if e:
            return e["server"]
    return str(p)


def entwurf_mit_nachweis(ctx, akte: str, empfaenger: str, betreff: str, html: str, anhaenge: list[Anhang],
                         ergebnis: Ergebnis, akzeptiert: list[dict] | None = None,
                         erwartungen: list[int] | None = None, client_id: str | None = None) -> EntwurfErgebnis:
    client_id = client_id or uuid.uuid4().hex
    ordner = ctx.ablage("Versand") / f"{datetime.now():%Y-%m-%d_%H%M%S}_{client_id[:6]}"
    originale = [Path(a.pfad) for a in anhaenge]
    original_sha = [_sha(p) for p in originale]
    kopien = feste_kopien(originale, ordner)
    bereinigt: list[Bereinigung] = []
    bereinigt_flag = [False] * len(kopien)
    for i, a in enumerate(anhaenge):
        if a.bereinigen or a.kommentare_entfernen:
            b = bereinigen(originale[i], kopien[i], kommentare_entfernen=a.kommentare_entfernen)
            bereinigt.append(b)
            bereinigt_flag[i] = b.ok
            if not b.ok:                                   # Kopie bleibt das unveränderte Original
                if _sha(kopien[i]) != original_sha[i]:
                    raise OSError(f"{kopien[i].name}: Versandkopie unerwartet verändert – Entwurf abgebrochen.")
    draft = MailDraft(to=empfaenger, subject=betreff, html_body=html, attachments=kopien)
    msg = entwurf_erstellen(ctx, draft, ordner, anhaenge_pruefen=True)
    dateien = []
    for i, (a, k) in enumerate(zip(anhaenge, kopien)):
        did = None
        kopie_pfad = str(k)
        try:
            did = ctx.archiv.erfassen(k, akte=akte, rolle="ausgang", notiz=f"Versandkopie: {betreff}"[:200])
            dok = ctx.archiv.dokument(did) if did else None
            kopie_pfad = (dok or {}).get("pfad") or kopie_pfad
        except Exception:  # noqa: BLE001 – Kopie bleibt lokal; Nachweis nennt den lokalen Pfad
            pass
        orig_id = None
        try:
            orig_id = ctx.archiv.id_von(originale[i])
        except Exception:  # noqa: BLE001
            pass
        dateien.append({"position": i, "rolle": a.rolle, "bezeichnung": a.bezeichnung, "name": k.name,
                        "original_pfad": _server_pfad(ctx, originale[i]), "original_dokument_id": orig_id,
                        "original_sha256": original_sha[i], "sha256": _sha(k), "kopie_pfad": kopie_pfad,
                        "groesse": k.stat().st_size, "bereinigt": bereinigt_flag[i]})
    try:
        eintrag = ctx.versand.anlegen(client_id, akte, empfaenger, ergebnis.rolle, betreff, dateien,
                                      pruefung=ergebnis.zusammenfassung(), akzeptiert=akzeptiert or [],
                                      erwartungen=erwartungen or [])
        return EntwurfErgebnis(msg, eintrag, bereinigt)
    except Exception as e:  # noqa: BLE001 – Entwurf ist offen; Nachweis später erneut speichern
        from core.fehlertexte import meldung
        ctx._versand_ausstehend = getattr(ctx, "_versand_ausstehend", [])
        ctx._versand_ausstehend.append(dict(client_id=client_id, akte=akte, empfaenger=empfaenger,
                                            empfaenger_rolle=ergebnis.rolle, betreff=betreff, dateien=dateien,
                                            pruefung=ergebnis.zusammenfassung(), akzeptiert=akzeptiert or [],
                                            erwartungen=erwartungen or []))
        return EntwurfErgebnis(msg, None, bereinigt, meldung(e))


def ausstehende_nachweise_speichern(ctx) -> int:
    """Nach einem Verbindungsabbruch: Versandnachweise erneut speichern (gleiche client_id → nie doppelt)."""
    offen = getattr(ctx, "_versand_ausstehend", [])
    n = 0
    for k in list(offen):
        ctx.versand.anlegen(k["client_id"], k["akte"], k["empfaenger"], k["empfaenger_rolle"], k["betreff"],
                            k["dateien"], pruefung=k["pruefung"], akzeptiert=k["akzeptiert"],
                            erwartungen=k["erwartungen"])
        offen.remove(k)
        n += 1
    return n


def sha_jetzt(ctx, pfad: str) -> str | None:
    """Aktuelle Prüfsumme eines Originals (Arbeitsplatz: aktuelle Fassung vom Server)."""
    if Path(pfad).is_file():                    # Original liegt auf diesem Rechner (oder Server-Rechner)
        return _sha(Path(pfad))
    try:
        lokal = ctx.dateien.lokal(pfad) if getattr(ctx, "dateien", None) is not None else None
    except Exception:  # noqa: BLE001
        lokal = None
    if lokal is None or not Path(lokal).is_file():
        return None
    return _sha(Path(lokal))


def gueltigkeit_pruefen(ctx, eintrag: dict) -> list[str]:
    """Geänderte Originale anzeigen; bei Änderungen wird der Eintrag als „veraltet“ markiert (nicht gelöscht)."""
    aend = aenderungen_seit_entwurf(eintrag, lambda p: sha_jetzt(ctx, p))
    if aend and eintrag.get("gueltig") and eintrag.get("status") == "entwurf_erstellt":
        try:
            ctx.versand.veraltet(eintrag["id"], "; ".join(aend)[:500])
        except Exception:  # noqa: BLE001
            pass
    return aend


def gesendet_suchen(ctx, eintrag: dict, gesendete: list[dict] | None = None) -> str:
    """In „Gesendete Elemente“ eine zuverlässig passende Mail suchen; gefunden → Versand bestätigt (Quelle
    Outlook). → Text für den Benutzer."""
    if gesendete is None:
        from core.outlook_eingang import gesendete_mails
        seit = datetime.strptime(eintrag["erstellt_am"], "%Y-%m-%d %H:%M:%S") - timedelta(minutes=1)
        gesendete = gesendete_mails(seit)
    gruende = []
    for k in gesendete:
        ok, text = gesendet_passt(eintrag, k)
        if ok:
            ctx.versand.bestaetigen(eintrag["id"], "outlook_gesendet", text)
            return "Versand bestätigt – " + text
        gruende.append(text)
    if not gesendete:
        return "Keine gesendete E-Mail seit dem Entwurf gefunden. Der Versand ist NICHT bestätigt."
    return ("Keine eindeutig passende gesendete E-Mail gefunden (Empfänger und Anhänge müssen übereinstimmen). "
            "Der Versand ist NICHT bestätigt.")
