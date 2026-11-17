"""SBOM (CycloneDX 1.6, JSON) aus dem tatsächlich ausgelieferten Programmordner.

Orientierung: BSI TR-03183-2 v2.1.0 – je ausgelieferter Datei SHA-512, Dateiname, Eigenschaften
„executable/archive/structured“; logische Komponenten mit Version, Lizenz, Quelle. Unbekanntes bleibt
„unbekannt“ (wird nicht geschätzt). Zusätzlich eine Kurzfassung für docs/CRA/erzeugen.py.

Kullanım: python tools/sbom_erzeugen.py --paket <…\\BnX-Raptor> --zip <ZIP> --commit <sha> --ziel <datei.cdx.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import ssl
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "tools"))
from paket_bauen import ZUORDNUNG  # noqa: E402


def dateiversion(p: Path) -> str:
    try:
        import win32api
        i = win32api.GetFileVersionInfo(str(p), "\\")
        ms, ls = i["FileVersionMS"] & 0xFFFFFFFF, i["FileVersionLS"] & 0xFFFFFFFF
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:  # noqa: BLE001
        return "unbekannt"


def logische(paket: Path, version: str) -> list[dict]:
    i = paket / "_internal"
    py = ".".join(map(str, sys.version_info[:3]))
    L = [
        ("bnx-raptor", "BnX-Raptor", version, "NOASSERTION", "Projekt-Repository (nicht veröffentlicht für 0.4.0)",
         "Projektlizenz nicht festgelegt", None),
        ("python", "CPython (eingebettete Laufzeit)", py, "PSF-2.0", "https://www.python.org/", "", f"pkg:generic/cpython@{py}"),
        ("pyinstaller", "PyInstaller-Bootloader", "6.22.3", "GPL-2.0-or-later WITH Bootloader-exception",
         "https://pypi.org/project/pyinstaller/6.22.3/", "Bootloader in BnX-Raptor.exe", "pkg:pypi/pyinstaller@6.22.3"),
        ("pyside6", "PySide6 / Qt", "6.12.0", "LGPL-3.0-only", "https://pypi.org/project/PySide6/6.12.0/",
         "Qt-interne Drittbibliotheken nicht einzeln erfasst (u. a. PCRE2, libjpeg-turbo aus Binärdateien erkennbar)", "pkg:pypi/pyside6@6.12.0"),
        ("shiboken6", "Shiboken6", "6.12.0", "LGPL-3.0-only", "https://pypi.org/project/shiboken6/6.12.0/", "", "pkg:pypi/shiboken6@6.12.0"),
        ("pymupdf", "PyMuPDF / MuPDF", "2.1 / MuPDF 1.28.6", "AGPL-3.0-only OR LicenseRef-Artifex-Commercial",
         "https://pypi.org/project/pymupdf/2.1/", "In mupdfcpp64.dll enthaltene Drittbibliotheken nur teilweise erkennbar "
         "(Little CMS, OpenJPEG, Brotli, extract); Versionen unbekannt", "pkg:pypi/pymupdf@2.1"),
        ("pywin32", "pywin32", "312", "LicenseRef-pywin32", "https://pypi.org/project/pywin32/312/", "", "pkg:pypi/pywin32@312"),
        ("openssl-python", "OpenSSL (Python)", ssl.OPENSSL_VERSION.split()[1], "Apache-2.0", "https://www.openssl.org/",
         "libcrypto-3.dll, libssl-3.dll", None),
        ("openssl-qt", "OpenSSL (Qt TLS-Backend)", dateiversion(i / "libcrypto-3-x64.dll"), "Apache-2.0",
         "mit PySide6-Wheel geliefert", "Dateiversion aus Versionsressource; nur Qt-TLS-Backend – BnX-Raptor nutzt für die "
         "Update-Abfrage Python/urllib (OpenSSL der Python-Laufzeit)", None),
        ("sqlite", "SQLite", sqlite3.sqlite_version, "blessing", "https://www.sqlite.org/", "gemeinfrei", None),
        ("libffi", "libffi", dateiversion(i / "libffi-8.dll"), "MIT", "https://sourceware.org/libffi/", "", None),
        ("msvc", "Microsoft Visual C++ Runtime", dateiversion(i / "VCRUNTIME140.dll"), "LicenseRef-Microsoft-Distributable-Code",
         "Microsoft", "Weitergabebedingungen juristisch prüfen", None),
        ("tesseract", "Tesseract OCR (UB-Mannheim-Build)", "5.5.3.20260724", "Apache-2.0",
         "https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3", "Setup-SHA-256 bee9e343…0ae4 geprüft", "pkg:github/tesseract-ocr/tesseract@5.5.3"),
        ("tessdata", "Tesseract-Sprachdaten deu/tur/eng (tessdata_best) + osd (tessdata)", "4.1.0", "Apache-2.0",
         "https://github.com/tesseract-ocr/tessdata_best/tree/4.1.0", "SHA-256 je Datei im Build geprüft", None),
    ]
    return [{"ref": r, "name": n, "version": v, "lizenz": li, "quelle": q, "hinweis": h, "purl": pu} for r, n, v, li, q, h, pu in L]


TESS_LIBS = {  # Tesseract-Laufzeitbibliotheken: Version laut `tesseract --version` (sonst unbekannt)
    "libleptonica": "1.87.0", "libgif": "5.2.2", "libjpeg": "3.1.3 (libjpeg-turbo)", "libpng16": "1.6.58", "libtiff": "4.7.2",
    "zlib1": "1.3.x", "libwebp": "1.6.0", "libwebpmux": "1.6.0", "libsharpyuv": "1.6.0", "libopenjp2": "2.5.4",
    "libarchive": "3.8.8", "liblzma": "5.8.3", "libbz2": "1.0.8", "liblz4": "1.10.0", "libzstd": "1.5.7", "libexpat": "2.8.2",
    "libcurl": "8.21.0", "libbrotlicommon": "1.2.0", "libbrotlidec": "1.2.0", "libidn2": "2.3.8", "libpsl": "0.21.5",
    "libssh2": "1.11.1", "libtesseract": "5.5.3",
}


def zuordnen(rel: str) -> tuple[str, str]:
    r = rel.lower()
    if r == "bnx-raptor.exe" or r.startswith(("lizenzen/", "config.example")):
        return "bnx-raptor", ""
    if r.startswith("ocr/tessdata/") and r.endswith(".traineddata"):
        return "tessdata", ""
    if r.startswith("ocr/"):
        komp = next((k for pre, k, *_ in ZUORDNUNG if r.startswith(pre.lower())), "")
        return "tesseract", komp
    if r.startswith("_internal/pymupdf"):
        return "pymupdf", ""
    if r.startswith("_internal/pyside6"):
        if "msvcp" in r or "vcruntime" in r:
            return "msvc", ""
        if "libcrypto" in r or "libssl" in r:
            return "openssl-qt", ""
        return "pyside6", ""
    if r.startswith("_internal/shiboken6"):
        return ("msvc", "") if ("msvcp" in r or "vcruntime" in r) else ("shiboken6", "")
    if r.startswith(("_internal/pywin32", "_internal/win32", "_internal/pythonwin")):
        return "pywin32", ""
    if r.startswith("_internal/vcruntime"):
        return "msvc", ""
    if r.startswith(("_internal/libcrypto-3.dll", "_internal/libssl-3.dll")):
        return "openssl-python", ""
    if r.startswith("_internal/libcrypto-3-x64") or r.startswith("_internal/libssl-3-x64"):
        return "openssl-qt", ""
    if r.startswith("_internal/sqlite3"):
        return "sqlite", ""
    if r.startswith("_internal/libffi"):
        return "libffi", ""
    return "python", ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paket", type=Path, required=True)
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--ziel", type=Path, required=True)
    a = ap.parse_args()
    ns: dict = {}
    exec((KOK / "version.py").read_text(encoding="utf-8"), ns)
    version = ns["__version__"]
    log = logische(a.paket, version)
    komps, deps = [], {x["ref"]: [] for x in log}
    for x in log:
        c = {"type": "application" if x["ref"] == "bnx-raptor" else ("data" if x["ref"] == "tessdata" else "library"),
             "bom-ref": x["ref"], "name": x["name"], "version": x["version"],
             "licenses": [{"expression": x["lizenz"]}] if x["lizenz"] != "NOASSERTION" else [],
             "externalReferences": [{"type": "distribution", "url": x["quelle"]}] if x["quelle"].startswith("http") else []}
        if x["purl"]:
            c["purl"] = x["purl"]
        if x["hinweis"]:
            c["properties"] = [{"name": "bnx:hinweis", "value": x["hinweis"]}]
        komps.append(c)
    unbekannt, dateien = [], 0
    for f in sorted(a.paket.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(a.paket).as_posix()
        log_ref, detail = zuordnen(rel)
        stamm = Path(rel).stem.rsplit("-", 1)[0]
        ver = TESS_LIBS.get(stamm, TESS_LIBS.get(Path(rel).stem, "")) if rel.startswith("ocr/") else ""
        if rel.startswith("ocr/") and rel.lower().endswith(".dll") and not ver:
            unbekannt.append(Path(rel).name)
        ref = "datei:" + rel
        exe = f.suffix.lower() in (".exe", ".dll", ".pyd")
        archiv = f.suffix.lower() in (".zip",) or rel.lower() == "bnx-raptor.exe"
        komps.append({"type": "file", "bom-ref": ref, "name": rel, "version": ver or "unbekannt",
                      "hashes": [{"alg": "SHA-512", "content": hashlib.sha512(f.read_bytes()).hexdigest()}],
                      "properties": [{"name": "bsi:component:filename", "value": f.name},
                                     {"name": "bsi:component:executable", "value": "executable" if exe else "non-executable"},
                                     {"name": "bsi:component:archive", "value": "archive" if archiv else "no archive"},
                                     {"name": "bsi:component:structured", "value": "structured" if archiv else "unstructured"}]
                      + ([{"name": "bnx:komponente", "value": detail}] if detail else [])})
        deps[log_ref].append(ref)
        dateien += 1
    zip_sha512 = hashlib.sha512(a.zip.read_bytes()).hexdigest()
    bom = {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "serialNumber": f"urn:uuid:{uuid.uuid4()}", "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "tools": {"components": [{"type": "application", "name": "tools/sbom_erzeugen.py (BnX-Raptor)"}]},
            "component": {"type": "application", "bom-ref": "produkt", "name": "BnX-Raptor", "version": version,
                          "properties": [{"name": "bnx:commit", "value": a.commit},
                                         {"name": "bnx:hersteller", "value": "OFFEN – Herstellerangaben fehlen"}],
                          "externalReferences": [{"type": "distribution", "url": "file:" + a.zip.name,
                                                  "hashes": [{"alg": "SHA-512", "content": zip_sha512}]}]},
        },
        "components": komps,
        "dependencies": [{"ref": "produkt", "dependsOn": [x["ref"] for x in log]}]
                        + [{"ref": k, "dependsOn": v} for k, v in deps.items()],
    }
    a.ziel.parent.mkdir(parents=True, exist_ok=True)
    a.ziel.write_text(json.dumps(bom, ensure_ascii=False, indent=1), encoding="utf-8")
    kurz = {"datei": a.ziel.name, "format": "1.6", "dateien": dateien, "logisch_anzahl": len(log), "logisch": log,
            "unbekannte_dll_versionen": unbekannt,
            "luecken": [
                "Herstellerangaben (SBOM-Ersteller/Kontakt) fehlen – Pflichtfeld nach TR-03183-2.",
                "Projektlizenz BnX-Raptor nicht festgelegt (NOASSERTION).",
                "Qt-interne Drittbibliotheken (z. B. PCRE2, HarfBuzz, libpng, zlib, libjpeg-turbo, libtiff, libwebp in Plug-ins) nicht einzeln mit Version/Lizenztext erfasst.",
                "In MuPDF eingebaute Drittbibliotheken nur teilweise erkennbar (Little CMS, OpenJPEG, Brotli, extract); Versionen und Lizenztexte offen.",
                "Tesseract-DLLs ohne Versionsangabe in `tesseract --version`: " + (", ".join(unbekannt) or "keine") + ".",
                "Microsoft-VC++-Laufzeit: Weitergabebedingungen nicht juristisch geprüft.",
                "Lizenztext-Lücken für Weitergabe: siehe lizenzen/DLL-LISTE.txt (Einträge mit OFFEN).",
            ]}
    a.ziel.with_suffix("").with_suffix(".kurz.json").write_text(json.dumps(kurz, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"SBOM: {a.ziel} – {len(log)} logische Komponenten, {dateien} Dateien; DLL ohne Version: {len(unbekannt)}")


if __name__ == "__main__":
    main()
