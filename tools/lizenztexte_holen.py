"""Bakım betiği: Pakete giren üçüncü taraf kütüphanelerin lisans/telif metinlerini RESMÎ kaynaklardan indirir
→ lizenzen/drittanbieter/  +  QUELLEN.csv (Datei, Komponente, Version, URL, SHA-256, Abrufdatum).

Sürümler `tesseract --version` çıktısına göredir (Tesseract 5.5.3, UB-Mannheim-Build). İndirilemeyen dosyalar
QUELLEN.csv'de "FEHLT" olarak işaretlenir – sessizce atlanmaz. Yalnızca geliştirici bilgisayarında çalıştırılır;
program kendisi internete bağlanmaz.
"""
from __future__ import annotations

import csv
import hashlib
import io
import tarfile
import urllib.request
from datetime import date
from pathlib import Path

ZIEL = Path(__file__).resolve().parent.parent / "lizenzen" / "drittanbieter"
GH = "https://raw.githubusercontent.com"
QUELLEN = [  # (Datei, Komponente, Version, URL)
    ("Leptonica-LICENSE.txt", "Leptonica (libleptonica)", "1.87.0", f"{GH}/DanBloomberg/leptonica/1.87.0/leptonica-license.txt"),
    ("giflib-COPYING.txt", "giflib (libgif)", "5.2.2", "https://sourceforge.net/p/giflib/code/ci/5.2.2/tree/COPYING?format=raw"),
    ("libjpeg-turbo-LICENSE.md", "libjpeg-turbo", "3.1.3", f"{GH}/libjpeg-turbo/libjpeg-turbo/3.1.3/LICENSE.md"),
    ("libjpeg-turbo-README.ijg.txt", "libjpeg-turbo (IJG-Teil)", "3.1.3", f"{GH}/libjpeg-turbo/libjpeg-turbo/3.1.3/README.ijg"),
    ("libpng-LICENSE.txt", "libpng (libpng16)", "1.6.58", f"{GH}/pnggroup/libpng/v1.6.58/LICENSE"),
    ("libtiff-LICENSE.md", "libtiff", "4.7.2", "https://gitlab.com/libtiff/libtiff/-/raw/v4.7.2/LICENSE.md"),
    ("zlib-LICENSE.txt", "zlib (zlib1)", "1.3.x", f"{GH}/madler/zlib/v1.3.1/LICENSE"),
    ("libwebp-COPYING.txt", "libwebp, libwebpmux, libsharpyuv", "1.6.0", f"{GH}/webmproject/libwebp/v1.6.0/COPYING"),
    ("libwebp-PATENTS.txt", "libwebp (Patentzusage)", "1.6.0", f"{GH}/webmproject/libwebp/v1.6.0/PATENTS"),
    ("OpenJPEG-LICENSE.txt", "OpenJPEG (libopenjp2)", "2.5.4", f"{GH}/uclouvain/openjpeg/v2.5.4/LICENSE"),
    ("libarchive-COPYING.txt", "libarchive", "3.8.8", f"{GH}/libarchive/libarchive/v3.8.8/COPYING"),
    ("xz-COPYING.txt", "XZ Utils (liblzma)", "5.8.3", f"{GH}/tukaani-project/xz/v5.8.3/COPYING"),
    ("xz-COPYING.0BSD.txt", "XZ Utils (liblzma, 0BSD)", "5.8.3", f"{GH}/tukaani-project/xz/v5.8.3/COPYING.0BSD"),
    ("bzip2-LICENSE.txt", "bzip2 (libbz2)", "1.0.8",
     "https://sourceware.org/git/?p=bzip2.git;a=blob_plain;f=LICENSE;hb=refs/tags/bzip2-1.0.8"),
    ("lz4-LICENSE.txt", "LZ4 (liblz4)", "1.10.0", f"{GH}/lz4/lz4/v1.10.0/lib/LICENSE"),
    ("zstd-LICENSE.txt", "Zstandard (libzstd)", "1.5.7", f"{GH}/facebook/zstd/v1.5.7/LICENSE"),
    ("expat-COPYING.txt", "Expat (libexpat)", "2.8.2", f"{GH}/libexpat/libexpat/R_2_8_2/expat/COPYING"),
    ("libb2-COPYING.txt", "libb2 (BLAKE2)", "(system)", f"{GH}/BLAKE2/libb2/master/COPYING"),
    ("curl-COPYING.txt", "curl (libcurl)", "8.21.0", f"{GH}/curl/curl/curl-8_21_0/COPYING"),
    ("brotli-LICENSE.txt", "Brotli (libbrotlicommon, libbrotlidec)", "1.2.0", f"{GH}/google/brotli/v1.2.0/LICENSE"),
    ("libidn2-COPYING.LESSERv3.txt", "libidn2", "2.3.8", "https://gitlab.com/libidn/libidn2/-/raw/v2.3.8/COPYING.LESSERv3"),
    ("libidn2-COPYINGv2.txt", "libidn2", "2.3.8", "https://gitlab.com/libidn/libidn2/-/raw/v2.3.8/COPYINGv2"),
    ("libpsl-COPYING.txt", "libpsl", "0.21.5", f"{GH}/rockdaboot/libpsl/0.21.5/COPYING"),
    ("libssh2-COPYING.txt", "libssh2", "1.11.1", f"{GH}/libssh2/libssh2/libssh2-1.11.1/COPYING"),
    ("libdeflate-COPYING.txt", "libdeflate", "(unbekannt)", f"{GH}/ebiggers/libdeflate/master/COPYING"),
    ("lerc-LICENSE.txt", "LERC (liblerc)", "(unbekannt)", f"{GH}/Esri/lerc/master/LICENSE"),
    ("winpthreads-COPYING.txt", "MinGW-w64 winpthreads (libwinpthread)", "(unbekannt)",
     "https://sourceforge.net/p/mingw-w64/mingw-w64/ci/master/tree/mingw-w64-libraries/winpthreads/COPYING?format=raw"),
    ("GCC-Runtime-Exception-3.1.txt", "libstdc++, libgcc_s (GCC Runtime Library Exception)", "3.1",
     "https://gcc.gnu.org/git/?p=gcc.git;a=blob_plain;f=COPYING.RUNTIME;hb=HEAD"),
    ("LGPL-2.1.txt", "libiconv, libintl (gettext)", "LGPL-2.1", "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt"),
    ("GPL-2.0.txt", "libunistring, libidn2 (Option), JBIG-KIT", "GPL-2.0", "https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt"),
    ("OpenSSL-LICENSE.txt", "OpenSSL 3 (libcrypto/libssl von Python und Qt)", "3.x", f"{GH}/openssl/openssl/openssl-3.0.0/LICENSE.txt"),
    ("libffi-LICENSE.txt", "libffi (Python)", "3.4", f"{GH}/libffi/libffi/v3.4.4/LICENSE"),
    ("Python-license.rst.txt", "Python 3.13.17 – eingebundene Software (expat, zlib, libmpdec, OpenSSL, libffi, …)",
     "3.13.17", f"{GH}/python/cpython/v3.13.17/Doc/license.rst"),
]
JBIG = ("JBIG-KIT", "2.1", "https://www.cl.cam.ac.uk/~mgk25/jbigkit/download/jbigkit-2.1.tar.gz")


def laden(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "BnX-Raptor-Build"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    zeilen = []
    heute = date.today().isoformat()
    for datei, komp, ver, url in QUELLEN:
        try:
            daten = laden(url)
            if b"<html" in daten[:400].lower():
                raise ValueError("HTML statt Lizenztext")
            (ZIEL / datei).write_bytes(daten)
            zeilen.append([datei, komp, ver, url, hashlib.sha256(daten).hexdigest(), heute])
        except Exception as e:  # noqa: BLE001
            zeilen.append([datei, komp, ver, url, f"FEHLT ({e})", heute])
    try:                       # JBIG-KIT: Lizenzhinweis steht im Paket (README + COPYING)
        tar = tarfile.open(fileobj=io.BytesIO(laden(JBIG[2])), mode="r:gz")
        for innen, aus in (("jbigkit-2.1/COPYING", "JBIG-KIT-COPYING.txt"), ("jbigkit-2.1/ANNOUNCE", "JBIG-KIT-ANNOUNCE.txt"),
                           ("jbigkit-2.1/libjbig/jbig.c", None)):
            daten = tar.extractfile(innen).read()
            if aus is None:                    # nur den Lizenzkopf der Quelldatei übernehmen
                aus, daten = "JBIG-KIT-jbig.c-Lizenzkopf.txt", daten[: daten.find(b"*/") + 2]
            (ZIEL / aus).write_bytes(daten)
            zeilen.append([aus, "JBIG-KIT (libjbig)", JBIG[1], JBIG[2] + f" → {innen}",
                           hashlib.sha256(daten).hexdigest(), heute])
    except Exception as e:  # noqa: BLE001
        zeilen.append(["JBIG-KIT-*", "JBIG-KIT (libjbig)", JBIG[1], JBIG[2], f"FEHLT ({e})", heute])
    with open(ZIEL / "QUELLEN.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Datei", "Komponente", "Version", "Quelle (offiziell)", "SHA-256", "Abgerufen"])
        w.writerows(zeilen)
    fehlt = [z[0] for z in zeilen if z[4].startswith("FEHLT")]
    print(f"{len(zeilen) - len(fehlt)} Lizenztexte geladen, fehlend: {fehlt or 'keine'}")
    for z in zeilen:
        if z[4].startswith("FEHLT"):
            print("  ", z[0], z[4])


if __name__ == "__main__":
    main()
