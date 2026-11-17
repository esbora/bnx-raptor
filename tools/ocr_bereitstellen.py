"""OCR bileşenini (Tesseract + deu/tur/eng/osd dil dosyaları) paket için hazırlar → build/ocr

Yerel derleme ve GitHub Actions AYNI betiği kullanır. Her indirme sabit bir SHA-256 ile doğrulanır;
uyuşmazsa derleme durur. Programın kendisi çalışırken internete bağlanmaz – bu yalnızca derleme adımıdır.

Kullanım:  python tools/ocr_bereitstellen.py [--cache KLASÖR] [--tesseract-ordner KLASÖR]
  --cache: önceden indirilmiş dosyaların klasörü (aynı adlarla); yoksa indirilir.
  --tesseract-ordner: aynı resmî kurulumla (5.5.3) önceden kurulmuş klasör. Kurulum programı yönetici
    onayı (UAC) ister; GitHub'da sorun değil, yerelde bu seçenekle onay penceresi gerekmez.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
BAU = Path(os.environ.get("BNX_BAUORDNER", KOK / "build"))     # lokal z. B. außerhalb von OneDrive
ZIEL = BAU / "ocr"
LIZENZ_ZIEL = BAU / "lizenzen_ocr"

TESSERACT = ("tesseract-ocr-w64-setup-5.5.3.20260724.exe",
             "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/"
             "tesseract-ocr-w64-setup-5.5.3.20260724.exe",
             "bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4")
SPRACHDATEN = [  # (Datei, URL, SHA-256) – Tag 4.1.0, LSTM "best"-Modelle; osd aus tessdata
    ("deu.traineddata", "https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/deu.traineddata",
     "8407331d6aa0229dc927685c01a7938fc5a641d1a9524f74838cdac599f0d06e"),
    ("tur.traineddata", "https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/tur.traineddata",
     "e0c3338dc17503dc7d335a507c9ae01b2b46cfd07561171e1e1ac55d85e8e438"),
    ("eng.traineddata", "https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/eng.traineddata",
     "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba"),
    ("osd.traineddata", "https://github.com/tesseract-ocr/tessdata/raw/4.1.0/osd.traineddata",
     "e19f2ae860792fdf372cf48d8ce70ae5da3c4052962fe22e9de1f680c374bb0e"),
]
LIZENZ_TESSDATA = ("LICENSE_tessdata_best", "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/4.1.0/LICENSE",
                   "a6cba85bc92e0cff7a450b1d873c0eaa2e9fc96bf472df0247a26bec77bf3ff9")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def holen(name: str, url: str, sha: str, cache: Path | None, ordner: Path) -> Path:
    ziel = ordner / name
    quelle = cache / name if cache else None
    if quelle and quelle.exists():
        shutil.copy2(quelle, ziel)
    else:
        print(f"  lade {url}")
        with urllib.request.urlopen(url, timeout=300) as r, open(ziel, "wb") as f:
            shutil.copyfileobj(r, f)
    if _sha(ziel) != sha:
        raise SystemExit(f"SHA-256 stimmt nicht: {name} (erwartet {sha})")
    return ziel


def pe_importe(pfad: Path) -> list[str]:
    """Namen der DLLs aus der Import-Tabelle einer Windows-EXE/DLL."""
    b = pfad.read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    nsec, optsz = struct.unpack_from("<H", b, pe + 6)[0], struct.unpack_from("<H", b, pe + 20)[0]
    opt = pe + 24
    dd = opt + (112 if struct.unpack_from("<H", b, opt)[0] == 0x20B else 96)
    imp_rva = struct.unpack_from("<I", b, dd + 8)[0]
    sek = [struct.unpack_from("<IIII", b, opt + optsz + i * 40 + 8) for i in range(nsec)]

    def off(rva):
        for vsz, va, rsz, raw in sek:
            if va <= rva < va + max(vsz, rsz):
                return rva - va + raw
        raise ValueError(rva)
    out, p = [], off(imp_rva)
    while (name_rva := struct.unpack_from("<I", b, p + 12)[0]):
        o = off(name_rva)
        out.append(b[o:b.index(b"\0", o)].decode())
        p += 20
    return out


def benoetigte_dlls(ordner: Path) -> list[str]:
    vorhanden = {f.name.lower(): f for f in ordner.glob("*.dll")}
    noetig, offen = set(), [ordner / "tesseract.exe"]
    while offen:
        for d in pe_importe(offen.pop()):
            d = d.lower()
            if d in vorhanden and d not in noetig:
                noetig.add(d)
                offen.append(vorhanden[d])
    return sorted(vorhanden[d].name for d in noetig)


def _installieren(setup: Path, inst: Path) -> Path:
    print("  installiere Tesseract still in einen temporären Ordner …")
    # Setup verlangt erhöhte Rechte (Manifest) → über die Windows-Shell starten, nicht per CreateProcess
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Start-Process -FilePath '{setup}' -ArgumentList '/S','/D={inst}' -Wait"],
                   timeout=600, check=True)
    if not (inst / "tesseract.exe").exists():
        raise SystemExit("Tesseract-Installation fehlgeschlagen")
    return inst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--tesseract-ordner", type=Path)
    args = ap.parse_args()
    if ZIEL.exists():
        shutil.rmtree(ZIEL)
    if LIZENZ_ZIEL.exists():
        shutil.rmtree(LIZENZ_ZIEL)
    (ZIEL / "tessdata").mkdir(parents=True)
    LIZENZ_ZIEL.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="bnx-ocr-bau-") as td:
        td = Path(td)
        if args.tesseract_ordner:
            inst = args.tesseract_ordner
            v = subprocess.run([str(inst / "tesseract.exe"), "--version"], capture_output=True, text=True).stdout
            if "5.5.3" not in v:
                raise SystemExit(f"{inst}: keine Tesseract-5.5.3-Installation ({v.splitlines()[:1]})")
            print(f"  verwende vorhandene Installation {inst} ({v.splitlines()[0]})")
        else:
            inst = _installieren(holen(*TESSERACT, args.cache, td), td / "tesseract")
        dlls = benoetigte_dlls(inst)
        shutil.copy2(inst / "tesseract.exe", ZIEL)
        for d in dlls:
            shutil.copy2(inst / d, ZIEL)
        shutil.copytree(inst / "tessdata" / "configs", ZIEL / "tessdata" / "configs")
        shutil.copy2(inst / "doc" / "LICENSE", LIZENZ_ZIEL / "Tesseract-LICENSE-Apache-2.0.txt")
        (LIZENZ_ZIEL / "Tesseract-DLLs.txt").write_text(
            "Mitgelieferte Laufzeitbibliotheken von Tesseract 5.5.3 (UB-Mannheim-Build):\n"
            + "\n".join(dlls) + "\n", encoding="utf-8")
        deinst = inst / "tesseract-uninstall.exe"
        if not args.tesseract_ordner and deinst.exists():     # temporäre Installation wieder austragen
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"Start-Process -FilePath '{deinst}' -ArgumentList '/S' -Wait"], timeout=300)
    for name, url, sha in SPRACHDATEN:
        holen(name, url, sha, args.cache, ZIEL / "tessdata")
    holen(*LIZENZ_TESSDATA, args.cache, LIZENZ_ZIEL)
    (LIZENZ_ZIEL / "LICENSE_tessdata_best").rename(LIZENZ_ZIEL / "tessdata_best-LICENSE-Apache-2.0.txt")
    groesse = sum(f.stat().st_size for f in ZIEL.rglob("*") if f.is_file())
    print(f"OCR bereit: {ZIEL} – {len(dlls)} DLLs, {groesse / 1e6:.1f} MB, Sprachen deu/tur/eng + osd")


if __name__ == "__main__":
    sys.exit(main())
