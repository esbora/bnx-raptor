"""BnX-Raptor-Paket bauen – derselbe Ablauf lokal (build.bat) und auf GitHub (release.yml).

  1. PyInstaller mit BnX-Raptor.spec (ungenutzte PyMuPDF-Teile ausgeschlossen)
  2. ocr\\ (aus build/ocr, vorher: python tools/ocr_bereitstellen.py) neben die EXE
  3. lizenzen\\ (Drittanbieter-Hinweise + Lizenztexte), config.example.json
  4. Inhaltsprüfung, ZIP  BnX-Raptor-v<version>.zip  (ohne config.json – Büroeinstellungen bleiben)

Kullanım:  python tools/paket_bauen.py [--ausgabe KLASÖR]   (Standard: ./dist)
"""
from __future__ import annotations

import argparse
import json
import hashlib
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
SITE = Path(sysconfig.get_paths()["purelib"])
BAU = Path(os.environ.get("BNX_BAUORDNER", KOK / "build"))


def version() -> str:
    ns: dict = {}
    exec((KOK / "version.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def lizenzen_sammeln(ziel: Path) -> list[str]:
    ziel.mkdir(parents=True, exist_ok=True)
    kopien = {
        **{f.name: f for f in (KOK / "lizenzen").iterdir() if f.is_file()},
        **{f.name: f for f in (BAU / "lizenzen_ocr").iterdir() if f.is_file()},
    }
    funde = {
        "PyMuPDF-COPYING-AGPL-3.0.txt": next(SITE.glob("pymupdf-*.dist-info/COPYING"), None),
        "Python-LICENSE.txt": Path(sys.base_prefix) / "LICENSE.txt",
        "pywin32-License.txt": next(SITE.glob("pywin32-*.dist-info/licenses/win32/License.txt"), None),
        "PyInstaller-COPYING.txt": next(SITE.glob("pyinstaller-*.dist-info/licenses/COPYING.txt"), None),
    }
    fehlend = [n for n, p in funde.items() if not p or not p.exists()]
    kopien.update({n: p for n, p in funde.items() if p and p.exists()})
    for name, quelle in sorted(kopien.items()):
        shutil.copy2(quelle, ziel / name)
    if (BAU / "lizenzen_ocr" / "msys2").exists():                 # Lizenzdateien der MSYS2-Pakete (OCR)
        shutil.copytree(BAU / "lizenzen_ocr" / "msys2", ziel / "drittanbieter-ocr", dirs_exist_ok=True)
    if (BAU / "ocr_herkunft.json").exists():
        shutil.copy2(BAU / "ocr_herkunft.json", ziel / "OCR-PAKETE.json")
    if (KOK / "lizenzen" / "drittanbieter").exists():          # offizielle Texte (tools/lizenztexte_holen.py)
        shutil.copytree(KOK / "lizenzen" / "drittanbieter", ziel / "drittanbieter", dirs_exist_ok=True)
    return fehlend


# Zuordnung Datei → (Komponente, Lizenz, Lizenztext im Ordner lizenzen\)
ZUORDNUNG = [
    ("_internal/pymupdf/", "MuPDF/PyMuPDF (Artifex)", "AGPL-3.0 ODER kommerziell",
     "PyMuPDF-COPYING-AGPL-3.0.txt, drittanbieter/mupdf/ (Drittbibliotheken aus offiziellem Quellpaket 1.28.6)"),
    ("_internal/PySide6/opengl32sw", "Mesa llvmpipe (Software-OpenGL von Qt)", "MIT (+ LLVM Apache-2.0)",
     "OFFEN"),
    ("_internal/PySide6/Qt6Pdf", "Qt PDF (enthält PDFium)", "LGPL-3.0 (+ PDFium BSD-3-Clause u. a.)",
     "LGPL-3.0.txt (PDFium-Drittanbieter: OFFEN)"),
    ("_internal/PySide6/plugins/imageformats/qpdf", "Qt PDF (enthält PDFium)", "LGPL-3.0 (+ PDFium BSD-3-Clause u. a.)",
     "LGPL-3.0.txt (PDFium-Drittanbieter: OFFEN)"),
    ("_internal/PySide6/MSVCP", "Microsoft Visual C++ Runtime", "Microsoft Distributable Code",
     "Python-LICENSE.txt (Abschnitt Microsoft Distributable Code); Microsoft: Weitergabe nur für lizenzierte Visual-Studio-Nutzer – OFFEN (juristisch prüfen)"),
    ("_internal/PySide6/VCRUNTIME", "Microsoft Visual C++ Runtime", "Microsoft Distributable Code",
     "Python-LICENSE.txt (Abschnitt Microsoft Distributable Code); Microsoft: Weitergabe nur für lizenzierte Visual-Studio-Nutzer – OFFEN (juristisch prüfen)"),
    ("_internal/shiboken6/MSVCP", "Microsoft Visual C++ Runtime", "Microsoft Distributable Code",
     "Python-LICENSE.txt (Abschnitt Microsoft Distributable Code); Microsoft: Weitergabe nur für lizenzierte Visual-Studio-Nutzer – OFFEN (juristisch prüfen)"),
    ("_internal/shiboken6/VCRUNTIME", "Microsoft Visual C++ Runtime", "Microsoft Distributable Code",
     "Python-LICENSE.txt (Abschnitt Microsoft Distributable Code); Microsoft: Weitergabe nur für lizenzierte Visual-Studio-Nutzer – OFFEN (juristisch prüfen)"),
    ("_internal/VCRUNTIME", "Microsoft Visual C++ Runtime", "Microsoft Distributable Code",
     "Python-LICENSE.txt (Abschnitt Microsoft Distributable Code); Microsoft: Weitergabe nur für lizenzierte Visual-Studio-Nutzer – OFFEN (juristisch prüfen)"),
    ("_internal/PySide6/", "Qt 6.12 / PySide6", "LGPL-3.0", "LGPL-3.0.txt, GPL-3.0.txt, drittanbieter/qt/ (Qt-Doku 6.12; Qt-Quellcode-Bezug: OFFEN)"),
    ("_internal/shiboken6/", "Shiboken6", "LGPL-3.0", "LGPL-3.0.txt"),
    ("_internal/pywin32_system32/", "pywin32", "PSF-ähnlich", "pywin32-License.txt"),
    ("_internal/win32", "pywin32", "PSF-ähnlich", "pywin32-License.txt"),
    ("_internal/pythonwin", "pywin32", "PSF-ähnlich", "pywin32-License.txt"),
    ("_internal/libcrypto", "OpenSSL 3", "Apache-2.0", "drittanbieter/OpenSSL-LICENSE.txt"),
    ("_internal/libssl", "OpenSSL 3", "Apache-2.0", "drittanbieter/OpenSSL-LICENSE.txt"),
    ("_internal/libffi", "libffi", "MIT", "drittanbieter/libffi-LICENSE.txt"),
    ("_internal/sqlite3", "SQLite", "gemeinfrei", "–"),
    ("_internal/python", "Python 3.13", "PSF-2.0", "Python-LICENSE.txt, drittanbieter/Python-license.rst.txt"),
    ("_internal/", "Python 3.13 (Erweiterungsmodul)", "PSF-2.0 (+ eingebundene Bibliotheken)",
     "Python-LICENSE.txt, drittanbieter/Python-license.rst.txt"),
]


Q = "quellcode-drittanbieter/"
GCC = "GPL-3.0.txt, drittanbieter/GCC-Runtime-Exception-3.1.txt; Quellcode: https://repo.msys2.org/mingw/sources/mingw-w64-gcc-16.2.0-7.src.tar.zst (nicht beigelegt) – juristisch bestätigen"
OCR_ZUSATZ = {  # MSYS2-Paket → zusätzliche Lizenztexte/Quellcode (neben lizenzen/drittanbieter-ocr/<paket>/)
    "jbigkit": "drittanbieter/JBIG-KIT-COPYING.txt, drittanbieter/JBIG-KIT-jbig.c-Lizenzkopf.txt; Quellcode: " + Q + "mingw-w64-jbigkit-2.1-6.src.tar.zst",
    "libiconv": "Quellcode: " + Q + "mingw-w64-libiconv-1.19.1-1.src.tar.zst",
    "gettext-runtime": "Quellcode: " + Q + "mingw-w64-gettext-1.0-1.src.tar.zst",
    "libunistring": "Quellcode: " + Q + "mingw-w64-libunistring-1.4.2-1.src.tar.zst",
    "libidn2": "drittanbieter/libidn2-COPYING.LESSERv3.txt, drittanbieter/libidn2-COPYINGv2.txt; Quellcode: " + Q + "mingw-w64-libidn2-2.3.8-5.src.tar.zst",
    "giflib": "drittanbieter/giflib-COPYING.txt",
    "libgcc": GCC, "libstdc++": GCC, "libgomp": GCC,
}


def ocr_zuordnung(rel: str, paket: Path) -> tuple[str, str, str] | None:
    """ocr/-Dateien: Herkunft aus lizenzen/OCR-PAKETE.json (von tools/ocr_bereitstellen.py, MSYS2-Pakete)."""
    j = paket / "lizenzen" / "OCR-PAKETE.json"
    if not rel.startswith("ocr/") or not j.exists():
        return None
    h = json.loads(j.read_text(encoding="utf-8")).get(rel[4:].lower())
    if not h:
        return None
    kurz = h["paket"].replace("mingw-w64-x86_64-", "")
    texte = [f"drittanbieter-ocr/{kurz}/"] if (paket / "lizenzen" / "drittanbieter-ocr" / kurz).exists() else []
    if kurz in OCR_ZUSATZ:
        texte.append(OCR_ZUSATZ[kurz])
    lizenz = h["lizenz"].replace("spdx:", "") or "?"
    return f"{kurz} {h['version']} (MSYS2)", lizenz, ", ".join(texte) or "OFFEN"


def dll_liste(paket: Path) -> tuple[str, int]:
    """Alle DLL/PYD/EXE-Binärdateien des Pakets mit Komponente und Lizenz – Grundlage der Lizenzprüfung."""
    zeilen, offen = [], 0
    for f in sorted(paket.rglob("*")):
        if f.suffix.lower() not in (".dll", ".pyd", ".exe") or f.name == "BnX-Raptor.exe":
            continue
        rel = f.relative_to(paket).as_posix()
        komp, liz, text = ocr_zuordnung(rel, paket) or next(
            ((k, li, t) for pre, k, li, t in ZUORDNUNG if rel.lower().startswith(pre.lower())), ("UNBEKANNT", "?", "OFFEN"))
        offen += "OFFEN" in text or komp == "UNBEKANNT"
        zeilen.append(f"{rel}\t{f.stat().st_size // 1024} KB\t{komp}\t{liz}\t{text}")
    kopf = ("Binärdateien im Paket (automatisch erzeugt von tools/paket_bauen.py)\n"
            "Datei\tGröße\tKomponente\tLizenz\tLizenztext im Ordner lizenzen\n")
    return kopf + "\n".join(zeilen) + "\n", offen


def pruefen(paket: Path) -> list[str]:
    fehler = []
    intern = paket / "_internal"
    for verboten in ("pymupdf/layout", "pymupdf/mupdf-devel", "onnxruntime", "numpy", "PySide6/Qt6Network.dll",
                     "libcrypto-3-x64.dll", "PySide6/plugins/tls", "PySide6/plugins/generic"):
        if (intern / verboten).exists():
            fehler.append(f"ungenutzte Komponente im Paket: {verboten}")
    for pflicht in ("BnX-Raptor.exe", "ocr/tesseract.exe", "ocr/tessdata/deu.traineddata",
                    "ocr/tessdata/tur.traineddata", "ocr/tessdata/eng.traineddata", "ocr/tessdata/osd.traineddata",
                    "ocr/tessdata/configs/tsv", "lizenzen/DRITTANBIETER.md", "config.example.json",
                    "quellcode-drittanbieter/mingw-w64-jbigkit-2.1-6.src.tar.zst", "lizenzen/OCR-PAKETE.json",
                    "_internal/pymupdf"):
        if not (paket / pflicht).exists():
            fehler.append(f"fehlt: {pflicht}")
    if (paket / "config.json").exists():
        fehler.append("config.json darf nicht im Paket sein")
    return fehler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ausgabe", type=Path, default=KOK / "dist")
    args = ap.parse_args()
    aus = args.ausgabe.resolve()
    ocr = BAU / "ocr"
    if not (ocr / "tesseract.exe").exists():
        raise SystemExit("build/ocr fehlt – zuerst: python tools/ocr_bereitstellen.py")
    paket = aus / "BnX-Raptor"
    if paket.exists():
        shutil.rmtree(paket)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(aus),
                    "--workpath", str(aus / "work"), str(KOK / "BnX-Raptor.spec")], cwd=KOK, check=True)
    shutil.copytree(ocr, paket / "ocr")
    if (BAU / "quellcode").exists():                    # Quellcode der (L)GPL-DLLs (GPL §3a)
        shutil.copytree(BAU / "quellcode", paket / "quellcode-drittanbieter")
    fehlend = lizenzen_sammeln(paket / "lizenzen")
    shutil.copy2(KOK / "config.example.json", paket / "config.example.json")
    liste, offen = dll_liste(paket)
    (paket / "lizenzen" / "DLL-LISTE.txt").write_text(liste, encoding="utf-8")
    print(f"DLL-Liste: {liste.count(chr(10)) - 2} Binärdateien, davon {offen} mit offenem Lizenzpunkt")
    if "UNBEKANNT" in liste:
        print("WARNUNG – Binärdateien ohne Zuordnung:",
              [z.split("\t")[0] for z in liste.splitlines() if "UNBEKANNT" in z])
    fehler = pruefen(paket)
    if fehlend:
        print("WARNUNG – Lizenztexte nicht gefunden:", ", ".join(fehlend))
    if fehler:
        raise SystemExit("Paketprüfung fehlgeschlagen:\n" + "\n".join(fehler))
    zip_basis = aus / f"BnX-Raptor-v{version()}"
    zip_pfad = Path(shutil.make_archive(str(zip_basis), "zip", root_dir=aus, base_dir="BnX-Raptor"))
    ordner_mb = sum(f.stat().st_size for f in paket.rglob("*") if f.is_file()) / 1e6
    print(f"Paket: {paket}  ({ordner_mb:.1f} MB)")
    print(f"ZIP:   {zip_pfad}  ({zip_pfad.stat().st_size / 1e6:.1f} MB)  "
          f"SHA-256 {hashlib.sha256(zip_pfad.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
