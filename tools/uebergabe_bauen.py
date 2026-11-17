"""Übergabepaket für eine Kanzlei (lokal, keine Veröffentlichung).

Nimmt das mit tools/paket_bauen.py gebaute Programmverzeichnis, ergänzt die deutsche Installationsanleitung
(docs/CRA/05_…pdf) und LIESMICH.txt und erzeugt eine eindeutig versionierte ZIP + .sha256-Datei.
Interne CRA-Unterlagen, Kanzleidaten, Testakten, Datenbanken, config.json usw. gelangen NICHT in das Paket.

Kullanım:  python tools/uebergabe_bauen.py --paket C:\\…\\BnX-Raptor --ausgabe C:\\…\\uebergabe
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
ANLEITUNG = KOK / "docs" / "CRA" / "05_Benutzerinformationen_und_Installation_DE.pdf"
VERBOTEN = (".sqlite", ".db", ".msg", ".eml", "config.json", "kanzlei.json", ".bnx-tmp")


def hersteller() -> dict:
    """Angaben aus docs/CRA/hersteller.json (vom Projektinhaber); fehlende bleiben OFFEN."""
    h = json.loads((KOK / "docs" / "CRA" / "hersteller.json").read_text(encoding="utf-8"))
    return {"hersteller": h["name"], "email": h["email"],
            "anschrift": "OFFEN (noch nicht angegeben)" if h["postanschrift"] == "OFFEN" else h["postanschrift"],
            "satz": ("Bitte melden Sie mögliche Sicherheitslücken oder Sicherheitsvorfälle per E-Mail an "
                     f"{h['sicherheitskontakt']}. Verwenden Sie nach Möglichkeit den Betreff ‚{h['betreff_sicherheitsmeldung']}‘ "
                     "und senden Sie keine vertraulichen Mandantendaten mit.")}


def version() -> str:
    ns: dict = {}
    exec((KOK / "version.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=KOK, capture_output=True,
                          text=True, check=True).stdout.strip()


LIESMICH = """BnX-Raptor {v} – Testversion für den Pilotbetrieb
==================================================

Paket:   {name}
Stand:   Code-Stand (Git-Commit) {c}

WICHTIG – TESTVERSION
Diese Version wird ausschließlich für einen begrenzten Pilot- und Testbetrieb bereitgestellt.
Sie erfüllt die Anforderungen der Verordnung (EU) 2024/2847 (Cyberresilienz-Verordnung) noch nicht
vollständig und ist außer zu Testzwecken nicht auf dem Markt verfügbar.
Bitte nur mit Test- oder ausdrücklich freigegebenen Dokumenten verwenden.

Inhalt
------
BnX-Raptor\\BnX-Raptor.exe      Programm (Start per Doppelklick)
BnX-Raptor\\ocr\\                Texterkennung (Tesseract) mit Deutsch, Türkisch, Englisch – nicht löschen
BnX-Raptor\\lizenzen\\           Hinweise und Lizenztexte der Drittanbieter-Komponenten
BnX-Raptor\\config.example.json  Beispiel-Einstellungen
Installationsanleitung_BnX-Raptor_{v}.pdf   Installation, sichere Nutzung, Updates, Support

Installation (Kurzfassung – Details in der Installationsanleitung)
1. Prüfsumme der ZIP-Datei mit dem mitgeteilten SHA-256-Wert vergleichen.
2. ZIP VOLLSTÄNDIG entpacken (Rechtsklick → „Alle extrahieren…“), nicht aus der ZIP heraus starten.
3. BnX-Raptor\\BnX-Raptor.exe starten.

Das Programm arbeitet lokal. Dokumente und OCR-Text werden nicht an Dritte übertragen.
Einzige Internetverbindung: Abfrage, ob eine neue Version vorliegt (abschaltbar, siehe Anleitung).
E-Mails werden nie automatisch gesendet; es entstehen nur Entwürfe.

Hersteller: {hersteller}
Postanschrift: {anschrift}
E-Mail: {email}

Meldung von Sicherheitsproblemen:
{satz}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paket", type=Path, required=True)
    ap.add_argument("--ausgabe", type=Path, required=True)
    a = ap.parse_args()
    if not ANLEITUNG.exists():
        raise SystemExit(f"Installationsanleitung fehlt: {ANLEITUNG} (zuerst docs/CRA/erzeugen.py --nur 05)")
    v, c = version(), commit()
    name = f"BnX-Raptor-{v}-Pilot-win64-{c}"
    a.ausgabe.mkdir(parents=True, exist_ok=True)
    zip_pfad = a.ausgabe / f"{name}.zip"
    if zip_pfad.exists():
        zip_pfad.unlink()
    verboten = [p for p in a.paket.rglob("*") if p.is_file() and
                (p.name.lower().endswith(VERBOTEN) or p.name.lower() in VERBOTEN)]
    if verboten:
        raise SystemExit("Nicht erlaubte Dateien im Programmordner: " + ", ".join(map(str, verboten)))
    with zipfile.ZipFile(zip_pfad, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(a.paket.rglob("*")):
            if f.is_file():
                z.write(f, Path(name) / "BnX-Raptor" / f.relative_to(a.paket))
        z.write(ANLEITUNG, Path(name) / f"Installationsanleitung_BnX-Raptor_{v}.pdf")
        z.writestr(str(Path(name) / "LIESMICH.txt"), LIESMICH.format(v=v, c=c, name=zip_pfad.name, **hersteller())
                   .replace("\n", "\r\n").encode("utf-8-sig"))
    sha = hashlib.sha256(zip_pfad.read_bytes()).hexdigest()
    (a.ausgabe / f"{zip_pfad.name}.sha256").write_text(f"{sha}  {zip_pfad.name}\n", encoding="ascii")
    print(f"ZIP:     {zip_pfad}\nGröße:   {zip_pfad.stat().st_size / 1e6:.1f} MB\nSHA-256: {sha}")


if __name__ == "__main__":
    main()
