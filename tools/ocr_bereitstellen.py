"""OCR bileşenini (Tesseract + deu/tur/eng/osd dil dosyaları) paket için hazırlar → build/ocr

Yerel derleme ve GitHub Actions AYNI betiği kullanır. Her indirme sabit bir SHA-256 ile doğrulanır;
uyuşmazsa derleme durur. Programın kendisi çalışırken internete bağlanmaz – bu yalnızca derleme adımıdır.

Kullanım:  python tools/ocr_bereitstellen.py [--cache KLASÖR] [--tesseract-ordner KLASÖR]
  Standard: resmî kurulum dosyası indirilir ve 7-Zip ile yalnızca AÇILIR (kurulmaz) → yönetici onayı (UAC),
    kayıt defteri veya PATH değişikliği yok. 7-Zip GitHub Windows sunucularında hazır bulunur.
  --cache: önceden indirilmiş dosyaların klasörü (aynı adlarla); yoksa indirilir.
  --tesseract-ordner: aynı resmî 5.5.3 sürümünün mevcut bir klasörü (7-Zip olmayan bilgisayarlar için).
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
# Quellcode der (L)GPL-Bibliotheken unter den Tesseract-DLLs. Zuordnung DLL → MSYS2-Paket per SHA-256-Vergleich
# des Binärpakets (lizenzen/drittanbieter/MSYS2-Zuordnung.json); wird dem Paket beigelegt (GPL-2.0 §3a, LGPL).
QUELLCODE = [
    ("mingw-w64-jbigkit-2.1-5.src.tar.zst", "402e264e13ffd10424d3217e83076d9e1e3ab0db16303a33d42a4bd4cda4088b"),
    ("mingw-w64-libiconv-1.19-1.src.tar.zst", "74428280c17094da5b702c29b2e1a0abae59556ea5dfdd65705cc8ccc1e000fb"),
    ("mingw-w64-gettext-1.0-1.src.tar.zst", "cca0d0c8f60353faccc5ad40405240014e4a7ccc8b1c6ca9f4626aef3097d26e"),
    ("mingw-w64-libunistring-1.4.2-1.src.tar.zst", "a5bafb360d5c13c5c52ef071d5a8288ce2345346b902f20ed6e9322766ec60eb"),
    ("mingw-w64-libidn2-2.3.8-4.src.tar.zst", "cd83e8514fbeb6a4499299b88691b9b9ecc3114cca1e2be4f6c54aab6ae9ddd0"),
]
QUELL_ZIEL = BAU / "quellcode"
QUELL_LIESMICH = r"""Quellcode zu mitgelieferten (L)GPL-Bibliotheken (Ordner ocr\)
==============================================================
Die folgenden Dateien sind die unveränderten MSYS2-Quellpakete (Originalquelle + Build-Anleitung PKGBUILD
+ Patches) zu exakt den Binärdateien, die im Ordner ocr\ mitgeliefert werden (Zuordnung per SHA-256 des
MSYS2-Binärpakets, siehe lizenzen\drittanbieter\MSYS2-Zuordnung.json). Quelle: https://repo.msys2.org/mingw/sources/

  libjbig-0.dll       → mingw-w64-jbigkit-2.1-5          (GPL-2.0-or-later)
  libiconv-2.dll      → mingw-w64-libiconv-1.19-1        (LGPL-2.1-or-later)
  libintl-8.dll       → mingw-w64-gettext-1.0-1          (LGPL-2.1-or-later; gettext-runtime)
  libunistring-5.dll  → mingw-w64-libunistring-1.4.2-1   (LGPL-3.0-or-later ODER GPL-2.0-or-later)
  libidn2-0.dll       → mingw-w64-libidn2-2.3.8-4        (LGPL-3.0-or-later ODER GPL-2.0-or-later)

Die Archive sind mit Zstandard komprimiert (.tar.zst), z. B. mit 7-Zip zu öffnen.
"""

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


def _sieben_zip() -> str:
    for kandidat in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if kandidat and Path(kandidat).exists():
            return kandidat
    raise SystemExit("7-Zip (7z.exe) nicht gefunden – oder --tesseract-ordner angeben")


def _entpacken(setup: Path, ziel: Path) -> Path:
    """NSIS-Setup nur entpacken (nicht ausführen): keine Rechte, keine Registry, kein PATH."""
    print("  entpacke Tesseract-Setup mit 7-Zip (keine Installation) …")
    subprocess.run([_sieben_zip(), "x", "-y", f"-o{ziel}", str(setup)], check=True,
                   stdout=subprocess.DEVNULL, timeout=600)
    exe = next(ziel.rglob("tesseract.exe"), None)
    if not exe:
        raise SystemExit("tesseract.exe nicht im entpackten Setup gefunden")
    inst = exe.parent
    for pflicht in ("tessdata/configs/tsv", "doc/LICENSE"):
        if not (inst / pflicht).exists():
            raise SystemExit(f"entpacktes Setup unvollständig: {pflicht} fehlt neben tesseract.exe")
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
            inst = _entpacken(holen(*TESSERACT, args.cache, td), td / "tesseract")
        dlls = benoetigte_dlls(inst)
        shutil.copy2(inst / "tesseract.exe", ZIEL)
        for d in dlls:
            shutil.copy2(inst / d, ZIEL)
        shutil.copytree(inst / "tessdata" / "configs", ZIEL / "tessdata" / "configs")
        shutil.copy2(inst / "doc" / "LICENSE", LIZENZ_ZIEL / "Tesseract-LICENSE-Apache-2.0.txt")
        (LIZENZ_ZIEL / "Tesseract-DLLs.txt").write_text(
            "Mitgelieferte Laufzeitbibliotheken von Tesseract 5.5.3 (UB-Mannheim-Build):\n"
            + "\n".join(dlls) + "\n", encoding="utf-8")
    for name, url, sha in SPRACHDATEN:
        holen(name, url, sha, args.cache, ZIEL / "tessdata")
    holen(*LIZENZ_TESSDATA, args.cache, LIZENZ_ZIEL)
    if QUELL_ZIEL.exists():
        shutil.rmtree(QUELL_ZIEL)
    QUELL_ZIEL.mkdir(parents=True)
    for name, sha in QUELLCODE:
        holen(name, "https://repo.msys2.org/mingw/sources/" + name, sha, args.cache, QUELL_ZIEL)
    (QUELL_ZIEL / "LIESMICH.txt").write_text(QUELL_LIESMICH, encoding="utf-8")
    (LIZENZ_ZIEL / "LICENSE_tessdata_best").rename(LIZENZ_ZIEL / "tessdata_best-LICENSE-Apache-2.0.txt")
    groesse = sum(f.stat().st_size for f in ZIEL.rglob("*") if f.is_file())
    print(f"OCR bereit: {ZIEL} – {len(dlls)} DLLs, {groesse / 1e6:.1f} MB, Sprachen deu/tur/eng + osd")


if __name__ == "__main__":
    sys.exit(main())
