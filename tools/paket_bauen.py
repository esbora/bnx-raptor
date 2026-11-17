"""BnX-Raptor-Paket bauen – derselbe Ablauf lokal (build.bat) und auf GitHub (release.yml).

  1. PyInstaller mit BnX-Raptor.spec (ungenutzte PyMuPDF-Teile ausgeschlossen)
  2. ocr\\ (aus build/ocr, vorher: python tools/ocr_bereitstellen.py) neben die EXE
  3. lizenzen\\ (Drittanbieter-Hinweise + Lizenztexte), config.example.json
  4. Inhaltsprüfung, ZIP  BnX-Raptor-v<version>.zip  (ohne config.json – Büroeinstellungen bleiben)

Kullanım:  python tools/paket_bauen.py [--ausgabe KLASÖR]   (Standard: ./dist)
"""
from __future__ import annotations

import argparse
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
    return fehlend


def pruefen(paket: Path) -> list[str]:
    fehler = []
    intern = paket / "_internal"
    for verboten in ("pymupdf/layout", "pymupdf/mupdf-devel", "onnxruntime", "numpy"):
        if (intern / verboten).exists():
            fehler.append(f"ungenutzte Komponente im Paket: {verboten}")
    for pflicht in ("BnX-Raptor.exe", "ocr/tesseract.exe", "ocr/tessdata/deu.traineddata",
                    "ocr/tessdata/tur.traineddata", "ocr/tessdata/eng.traineddata", "ocr/tessdata/osd.traineddata",
                    "ocr/tessdata/configs/tsv", "lizenzen/DRITTANBIETER.md", "config.example.json",
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
    fehlend = lizenzen_sammeln(paket / "lizenzen")
    shutil.copy2(KOK / "config.example.json", paket / "config.example.json")
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
