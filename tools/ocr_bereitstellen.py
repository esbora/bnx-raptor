"""OCR bileşenini (Tesseract + deu/tur/eng/osd dil dosyaları) paket için hazırlar → build/ocr

Yerel derleme ve GitHub Actions AYNI betiği kullanır. Her indirme sabit bir SHA-256 ile doğrulanır;
uyuşmazsa derleme durur. Programın kendisi çalışırken internete bağlanmaz – bu yalnızca derleme adımıdır.

Kaynak (0.4.0'dan itibaren): MSYS2 mingw64 ikili paketleri (repo.msys2.org). Tesseract 5.5.4 için resmî bir
Windows kurulum dosyası yayımlanmadı; 5.5.3 kurulumu 5.5.4'te giderilen 20 güvenlik bildirimini ve curl 8.21.0'ı
içeriyordu. Paket listesi 17.11.2026'da çözümlendi; her paketin PGP imzası MSYS2 anahtar zinciriyle doğrulandı ve
SHA-256 değerleri aşağıya sabitlendi. Paketler yalnızca AÇILIR (pacman/kurulum yok, UAC/kayıt defteri/PATH yok).
Pakete yalnızca tesseract.exe'nin içe aktarma zincirinde gerçekten bulunan DLL'ler girer.

Kullanım:  python tools/ocr_bereitstellen.py [--cache KLASÖR]
  --cache: önceden indirilmiş dosyaların klasörü (aynı adlarla); yoksa indirilir.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
BAU = Path(os.environ.get("BNX_BAUORDNER", KOK / "build"))     # lokal z. B. außerhalb von OneDrive
ZIEL = BAU / "ocr"
LIZENZ_ZIEL = BAU / "lizenzen_ocr"
MSYS2_REPO = "https://repo.msys2.org/mingw/mingw64/"
MSYS2_QUELLEN = "https://repo.msys2.org/mingw/sources/"

TESSERACT_VERSION = "5.5.4"
MSYS2_PAKETE = [  # (Datei, SHA-256)  # mitgelieferte Dateien
    ("mingw-w64-x86_64-tesseract-ocr-5.5.4-1-any.pkg.tar.zst", "77cf3ee8b8c86cfa0286737b921de38e867491459a470319ac83c765f4d4caa5"),  # tesseract.exe, libtesseract-5.5.dll
    ("mingw-w64-x86_64-brotli-1.2.1-1-any.pkg.tar.zst", "3163fae24021624b49d3372a6a7fe05c0f3e01b301e65fcbcb3a95557019fb2d"),  # libbrotlidec.dll, libbrotlicommon.dll
    ("mingw-w64-x86_64-bzip2-1.0.8-4-any.pkg.tar.zst", "123768f30ae14ba654a6feb70f8526146a331bc85f831a91a549ffb3f6cbffc7"),  # libbz2-1.dll
    ("mingw-w64-x86_64-curl-8.23.0-3-any.pkg.tar.zst", "bae0baa3e2f0e173ed14b9c7679cee1e327cf4540d8a89d8f7134a8456427b2a"),  # libcurl-4.dll
    ("mingw-w64-x86_64-gettext-runtime-1.0-1-any.pkg.tar.zst", "be68d7f260633284b910c588c6d82ee304a81c8817a686d2cd9df83f872c27af"),  # libintl-8.dll
    ("mingw-w64-x86_64-giflib-6.1.3-1-any.pkg.tar.zst", "bfa540ab9892bbc5161e3f81fcfb0ca71f44bd2e00478b5df79f899825c523f5"),  # libgif-7.dll
    ("mingw-w64-x86_64-jbigkit-2.1-6-any.pkg.tar.zst", "3db9e32abca5d208920a096e5ae01952f2d8a361780428b9646b6da6750f7321"),  # libjbig-0.dll
    ("mingw-w64-x86_64-leptonica-1.87.0-2-any.pkg.tar.zst", "741e6ef13b7994dd2ce166135f32e3c6c1bc4eeb7b657242a8aaf3b479a04d7f"),  # libleptonica-6.dll
    ("mingw-w64-x86_64-lerc-4.1.1-1-any.pkg.tar.zst", "5bc170650bc02812a7c674a5f7b8ff2781b4bfa259ab2da2264c3008e2a04c72"),  # libLerc.dll
    ("mingw-w64-x86_64-libarchive-3.8.11-3-any.pkg.tar.zst", "72ffd8ccd4e55ece25799be463cc08b25780d76d7884c596f49b6dc67eca1960"),  # libarchive-13.dll
    ("mingw-w64-x86_64-libb2-0.98.1-3-any.pkg.tar.zst", "3c898f08c5f19e25dc6d7e39aa36b6f323141f0e62c5c50f089cd3f89711854c"),  # libb2-1.dll
    ("mingw-w64-x86_64-libdeflate-1.26-1-any.pkg.tar.zst", "aa0d9b5e2d0413d5e01745a48ef0c8fa293172d48c13f87b61ada627ab7407ad"),  # libdeflate.dll
    ("mingw-w64-x86_64-libgcc-16.2.0-7-any.pkg.tar.zst", "6d1311b397ba33be542fd46bae3de60338bfd967e95e221847f01269e98983b8"),  # libgcc_s_seh-1.dll
    ("mingw-w64-x86_64-libgomp-16.2.0-7-any.pkg.tar.zst", "4c5b9fdf1bb8ca44d7563498b90680af113de0682c54d6817b37aac083d30eaf"),  # libgomp-1.dll
    ("mingw-w64-x86_64-libiconv-1.19.1-1-any.pkg.tar.zst", "50e915aa36fdbe6c84acc8954e939275609ba051cdb4eeeff3884453c28efde0"),  # libiconv-2.dll
    ("mingw-w64-x86_64-libidn2-2.3.8-5-any.pkg.tar.zst", "988a94544c71fd425edc9f6aea57dcd90f73057cf046a2d78c6cd5ac7d381af8"),  # libidn2-0.dll
    ("mingw-w64-x86_64-libjpeg-turbo-3.2.1-1-any.pkg.tar.zst", "26474b95df3cb70abae8c74653d0ab0eb7ae22eeb2c2342c0d54313998a96b04"),  # libjpeg-8.dll
    ("mingw-w64-x86_64-libpng-1.6.59-2-any.pkg.tar.zst", "8cf4e17ed9f592d23a5d1f1f8875c6a8da42eaf7772a997908565e94131cfc20"),  # libpng16-16.dll
    ("mingw-w64-x86_64-libpsl-0.21.5-3-any.pkg.tar.zst", "2a86f7ce3cd3fabff7eb8e5c0d3eb1134808881a44c3838e1b518b75cb402e35"),  # libpsl-5.dll
    ("mingw-w64-x86_64-libssh2-1.11.1-4-any.pkg.tar.zst", "8ffbe55f91bf85fda6b52a40db4d0ea100efd68dc8c7aede21db8cfdf0a9c50a"),  # libssh2-1.dll
    ("mingw-w64-x86_64-libstdc++-16.2.0-7-any.pkg.tar.zst", "578db695632bdb5bafd716958c4caa62560f3de2633680b258ae6f684201276d"),  # libstdc++-6.dll
    ("mingw-w64-x86_64-libtiff-4.7.2-2-any.pkg.tar.zst", "e330307e569ea912f6911d6ceae994d96ac68c27b4860c1f805ce9078439786c"),  # libtiff-6.dll
    ("mingw-w64-x86_64-libunistring-1.4.2-1-any.pkg.tar.zst", "c940cf52fb2b579baa596d3c1d911f7544cbf90f8bd19c260377aa115c65b059"),  # libunistring-5.dll
    ("mingw-w64-x86_64-libwebp-1.6.0-1-any.pkg.tar.zst", "360b1690d41eb497dfe50526460a2424600a6a806cbb76c5b0fec9f14623ac59"),  # libwebp-7.dll, libsharpyuv-0.dll, libwebpmux-3.dll
    ("mingw-w64-x86_64-libwinpthread-14.0.0.r598.ge3d18511f-1-any.pkg.tar.zst", "942a62a3ecafbb4f5a80016685a0e3002a8de903012eed49c213e4f5b693668a"),  # libwinpthread-1.dll
    ("mingw-w64-x86_64-lz4-1.11.1-2-any.pkg.tar.zst", "95df600c6f39d484c3179b6f539303261aab862ca56b2fa620a1dc3d036790d0"),  # liblz4.dll
    ("mingw-w64-x86_64-nghttp2-1.71.0-1-any.pkg.tar.zst", "e868085eed6dd47d81fe19e5048477f8ca0dcc8b8bd3b74a8181b063b6609c6f"),  # libnghttp2-14.dll
    ("mingw-w64-x86_64-nghttp3-1.19.0-1-any.pkg.tar.zst", "9c10bf707c2adcef0bce9ade9d3cab96249b5cbd8088c7002770041003aa49d3"),  # libnghttp3-9.dll
    ("mingw-w64-x86_64-ngtcp2-1.26.0-3-any.pkg.tar.zst", "490a49567fad619770ba74876d208768b03c2670bba7a1c45488a50ad700635a"),  # libngtcp2-16.dll, libngtcp2_crypto_ossl-0.dll
    ("mingw-w64-x86_64-openjpeg2-2.5.4-2-any.pkg.tar.zst", "32f8f5dc7df9f1f2d57157717136fbba431e15bc000420c953c00ffdf76ecde4"),  # libopenjp2-7.dll
    ("mingw-w64-x86_64-openssl-4.1.0-1-any.pkg.tar.zst", "d23a605bd7543ea1143324fd70f4db40d26b588321c6e4e8cdcadf9d15998daf"),  # libcrypto-4-x64.dll, libssl-4-x64.dll
    ("mingw-w64-x86_64-xz-5.8.4-1-any.pkg.tar.zst", "2de0f26da60b7ff7aa192a226330d7de6b1099cb9b9f9de4145affb80146bbc8"),  # liblzma-5.dll
    ("mingw-w64-x86_64-zlib-1.4-2-any.pkg.tar.zst", "2a065fb3311d6c08bd2c7431a092b912ade08a83954474e06ea4eb0479d908cd"),  # zlib1.dll, libz-1.dll
    ("mingw-w64-x86_64-zstd-1.5.7-2-any.pkg.tar.zst", "1add6705b344664f6aca108c85f79ab5bdd9e1162662bb06a4cf40a34f6e0907"),  # libzstd.dll
]
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
# Quellcode der (L)GPL-Bibliotheken unter den Tesseract-DLLs (unveränderte MSYS2-Quellpakete zu exakt diesen
# Binärpaketen); wird dem Paket beigelegt (GPL-2.0 §3a, LGPL).
# GCC-Laufzeit (libgcc/libstdc++/libgomp, GPL-3.0 mit Laufzeitausnahme): Quellpaket wird ebenfalls beigelegt.
QUELLCODE = [
    ("mingw-w64-jbigkit-2.1-6.src.tar.zst", "64757867df26308c14d22b184aaecb43742c25ee8d24f18da51e3d1e09be8ac2"),
    ("mingw-w64-libiconv-1.19.1-1.src.tar.zst", "ed46bb1b524ad9bd9d843091bf7b18ab23e5cd21fef6de743c8c943bdc11dabe"),
    ("mingw-w64-gettext-1.0-1.src.tar.zst", "cca0d0c8f60353faccc5ad40405240014e4a7ccc8b1c6ca9f4626aef3097d26e"),
    ("mingw-w64-libunistring-1.4.2-1.src.tar.zst", "a5bafb360d5c13c5c52ef071d5a8288ce2345346b902f20ed6e9322766ec60eb"),
    ("mingw-w64-libidn2-2.3.8-5.src.tar.zst", "0d8c964fc0a203bd982070c736e0fad9ca53db409c95e215b907f8a384d2e3ec"),
    ("mingw-w64-gcc-16.2.0-7.src.tar.zst", "bdd1b2cd820cd67d38b42a174180bdd589b80b97af1a8b042d6c4da9176bac93"),
]
QUELL_ZIEL = BAU / "quellcode"
QUELL_LIESMICH = r"""Quellcode zu mitgelieferten (L)GPL-Bibliotheken (Ordner ocr\)
==============================================================
Die folgenden Dateien sind die unveränderten MSYS2-Quellpakete (Originalquelle + Build-Anleitung PKGBUILD
+ Patches) zu exakt den MSYS2-Binärpaketen, aus denen die Dateien im Ordner ocr\ stammen
(siehe lizenzen\OCR-PAKETE.txt). Quelle: https://repo.msys2.org/mingw/sources/

  libjbig-0.dll       → mingw-w64-jbigkit-2.1-6          (GPL-2.0-or-later)
  libiconv-2.dll      → mingw-w64-libiconv-1.19.1-1      (LGPL-2.1-or-later)
  libintl-8.dll       → mingw-w64-gettext-1.0-1          (LGPL-2.1-or-later; gettext-runtime)
  libunistring-5.dll  → mingw-w64-libunistring-1.4.2-1   (LGPL-3.0-or-later ODER GPL-2.0-or-later)
  libidn2-0.dll       → mingw-w64-libidn2-2.3.8-5        (LGPL-3.0-or-later ODER GPL-2.0-or-later)

GCC-Laufzeit (libgcc_s_seh-1.dll, libstdc++-6.dll, libgomp-1.dll; GPL-3.0 mit GCC Runtime Library Exception):
Quellpaket mingw-w64-gcc-16.2.0-7.src.tar.zst ist beigefügt (Originalquelle, Build-Anleitung und Patches).

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
        req = urllib.request.Request(url, headers={"User-Agent": "BnX-Raptor-Build"})
        with urllib.request.urlopen(req, timeout=300) as r, open(ziel, "wb") as f:
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


def _msys2_entpacken(paket: Path, inst: Path, lizenzen: Path) -> tuple[str, list[str]]:
    """Paket nur entpacken: mingw64/bin/*.exe|*.dll → inst, tessdata/configs → inst, Lizenzdateien → lizenzen/<paket>."""
    import zstandard   # nur für den Build (requirements.txt)
    roh = zstandard.ZstdDecompressor().stream_reader(open(paket, "rb")).read()
    tar = tarfile.open(fileobj=io.BytesIO(roh))
    info = tar.extractfile(".PKGINFO").read().decode()
    name = next(z.split(" = ", 1)[1] for z in info.splitlines() if z.startswith("pkgname = "))
    lizenz = [z.split(" = ", 1)[1] for z in info.splitlines() if z.startswith("license = ")]
    for m in tar.getmembers():
        if not m.isfile() or ".." in m.name:
            continue
        teil = m.name.split("/")
        if len(teil) == 3 and teil[:2] == ["mingw64", "bin"] and teil[2].lower().endswith((".dll", ".exe")):
            (inst / teil[2]).write_bytes(tar.extractfile(m).read())
        elif m.name.startswith("mingw64/share/tessdata/configs/"):
            (inst / "configs").mkdir(exist_ok=True)
            (inst / "configs" / teil[-1]).write_bytes(tar.extractfile(m).read())
        elif len(teil) >= 5 and teil[:3] == ["mingw64", "share", "licenses"]:
            z = lizenzen / name.replace("mingw-w64-x86_64-", "")
            z.mkdir(parents=True, exist_ok=True)
            (z / "_".join(teil[4:])).write_bytes(tar.extractfile(m).read())
    return name, lizenz


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path)
    args = ap.parse_args()
    for d in (ZIEL, LIZENZ_ZIEL):
        if d.exists():
            shutil.rmtree(d)
    (ZIEL / "tessdata").mkdir(parents=True)
    LIZENZ_ZIEL.mkdir(parents=True)
    herkunft: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="bnx-ocr-bau-") as td:
        td = Path(td)
        inst, lz = td / "inst", td / "lizenzen"
        inst.mkdir(); lz.mkdir()
        pakete = []
        for datei, sha in MSYS2_PAKETE:
            p = holen(datei, MSYS2_REPO + urllib.parse.quote(datei), sha, args.cache, td)
            vorher = {f.name for f in inst.iterdir()}
            name, lizenz = _msys2_entpacken(p, inst, lz)
            for f in inst.iterdir():
                if f.name not in vorher and f.is_file():
                    herkunft[f.name.lower()] = {"paket": name, "version": datei[len(name) + 1:-len("-any.pkg.tar.zst")],
                                                "lizenz": " ".join(lizenz)}
            pakete.append((name, datei, sha, lizenz))
            p.unlink()
        v = __import__("subprocess").run([str(inst / "tesseract.exe"), "--version"], capture_output=True, text=True,
                                         cwd=str(inst)).stdout
        if TESSERACT_VERSION not in v.splitlines()[0]:
            raise SystemExit(f"unerwartete Tesseract-Version: {v.splitlines()[:1]}")
        dlls = benoetigte_dlls(inst)
        shutil.copy2(inst / "tesseract.exe", ZIEL)
        for d in dlls:
            shutil.copy2(inst / d, ZIEL)
        shutil.copytree(inst / "configs", ZIEL / "tessdata" / "configs")
        genutzt = {herkunft[f.lower()]["paket"] for f in ["tesseract.exe", *dlls]}
        for name, *_ in pakete:
            kurz = name.replace("mingw-w64-x86_64-", "")
            if name in genutzt and (lz / kurz).exists():
                shutil.copytree(lz / kurz, LIZENZ_ZIEL / "msys2" / kurz)
        shutil.copy2(LIZENZ_ZIEL / "msys2" / "tesseract-ocr" / "LICENSE", LIZENZ_ZIEL / "Tesseract-LICENSE-Apache-2.0.txt")
        zeilen = ["Mitgelieferte Dateien im Ordner ocr\\ – Herkunft: MSYS2 mingw64 (https://repo.msys2.org/mingw/mingw64/),",
                  "Pakete mit gültiger MSYS2-PGP-Signatur, SHA-256 fest im Build-Skript tools/ocr_bereitstellen.py.", "",
                  f"{'Datei':<28} {'MSYS2-Paket':<40} {'Version':<30} Lizenz (laut Paket)"]
        for f in ["tesseract.exe", *dlls]:
            h = herkunft[f.lower()]
            zeilen.append(f"{f:<28} {h['paket']:<40} {h['version']:<30} {h['lizenz']}")
        zeilen += ["", "Lizenzdateien der Pakete: lizenzen\\drittanbieter-ocr\\<paket>\\", "",
                   "Paketdateien (SHA-256):"] + [f"  {d}  {s}" for n, d, s, _ in pakete if n in genutzt]
        (LIZENZ_ZIEL / "OCR-PAKETE.txt").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        (BAU / "ocr_herkunft.json").write_text(json.dumps({f.lower(): herkunft[f.lower()] for f in ["tesseract.exe", *dlls]},
                                                          indent=1), encoding="utf-8")
    for name, url, sha in SPRACHDATEN:
        holen(name, url, sha, args.cache, ZIEL / "tessdata")
    holen(*LIZENZ_TESSDATA, args.cache, LIZENZ_ZIEL)
    if QUELL_ZIEL.exists():
        shutil.rmtree(QUELL_ZIEL)
    QUELL_ZIEL.mkdir(parents=True)
    for name, sha in QUELLCODE:
        holen(name, MSYS2_QUELLEN + name, sha, args.cache, QUELL_ZIEL)
    (QUELL_ZIEL / "LIESMICH.txt").write_text(QUELL_LIESMICH, encoding="utf-8")
    (LIZENZ_ZIEL / "LICENSE_tessdata_best").rename(LIZENZ_ZIEL / "tessdata_best-LICENSE-Apache-2.0.txt")
    groesse = sum(f.stat().st_size for f in ZIEL.rglob("*") if f.is_file())
    print(f"OCR bereit: {ZIEL} – Tesseract {TESSERACT_VERSION}, {len(dlls)} DLLs, {groesse / 1e6:.1f} MB, Sprachen deu/tur/eng + osd")


if __name__ == "__main__":
    sys.exit(main())
