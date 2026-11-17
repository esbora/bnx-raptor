"""Bakım betiği: Pakete giren üçüncü taraf kütüphanelerin lisans/telif metinlerini RESMÎ kaynaklardan indirir
→ lizenzen/drittanbieter/  +  QUELLEN.csv (Datei, Komponente, Version, URL, SHA-256, Abrufdatum).

OCR-Bibliotheken (Tesseract 5.5.4 aus MSYS2) bringen ihre Lizenzdateien selbst mit (tools/ocr_bereitstellen.py →
lizenzen/drittanbieter-ocr/); hier nur Texte, die dort fehlen (giflib, libidn2, JBIG-KIT, GCC-Ausnahme, GPL/LGPL) und Python/Qt/MuPDF. İndirilemeyen dosyalar
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
    ("lz4-LICENSE.txt", "LZ4 (liblz4, MSYS2-Paket ohne Lizenzdatei)", "1.11.1", f"{GH}/lz4/lz4/v1.11.1/lib/LICENSE"),
    ("giflib-COPYING.txt", "giflib (libgif)", "6.1.3", "https://sourceforge.net/p/giflib/code/ci/6.1.3/tree/COPYING?format=raw"),
    ("libwebp-PATENTS.txt", "libwebp (Patentzusage)", "1.6.0", f"{GH}/webmproject/libwebp/v1.6.0/PATENTS"),
    ("libidn2-COPYING.LESSERv3.txt", "libidn2", "2.3.8", "https://gitlab.com/libidn/libidn2/-/raw/v2.3.8/COPYING.LESSERv3"),
    ("libidn2-COPYINGv2.txt", "libidn2", "2.3.8", "https://gitlab.com/libidn/libidn2/-/raw/v2.3.8/COPYINGv2"),
    ("GCC-Runtime-Exception-3.1.txt", "libstdc++, libgcc_s (GCC Runtime Library Exception)", "3.1",
     "https://gcc.gnu.org/git/?p=gcc.git;a=blob_plain;f=COPYING.RUNTIME;hb=HEAD"),
    ("LGPL-2.1.txt", "libiconv, libintl (gettext)", "LGPL-2.1", "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt"),
    ("GPL-2.0.txt", "libunistring, libidn2 (Option), JBIG-KIT", "GPL-2.0", "https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt"),
    ("OpenSSL-LICENSE.txt", "OpenSSL 3 (libcrypto-3/libssl-3 von Python)", "3.x", f"{GH}/openssl/openssl/openssl-3.0.0/LICENSE.txt"),
    ("libffi-LICENSE.txt", "libffi (Python)", "3.4", f"{GH}/libffi/libffi/v3.4.4/LICENSE"),
    ("Python-license.rst.txt", "Python 3.13.17 – eingebundene Software (expat, zlib, libmpdec, OpenSSL, libffi, …)",
     "3.13.17", f"{GH}/python/cpython/v3.13.17/Doc/license.rst"),
]
JBIG = ("JBIG-KIT", "2.1", "https://www.cl.cam.ac.uk/~mgk25/jbigkit/download/jbigkit-2.1.tar.gz")


def laden(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "BnX-Raptor-Build"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


# --- Qt 6.12: Drittanbieter der ausgelieferten Module QtCore/QtGui (offizielle Qt-Dokumentation) -----------------
QT_BASIS = "https://doc.qt.io/qt-6/"
QT_NICHT_WINDOWS = {"android-native-style", "cocoa-platform-plugin", "xcb-xinput", "xserverhelper", "qeventdispatcher-cf",
                    "forkfd"}           # laut Qt-Doku nur Android/macOS/X11/Unix – nicht im Windows-Build


def _html_text(h: str) -> str:
    import html as _h
    import re as _re
    h = _re.sub(r"(?s)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", h)
    h = _re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li|pre|tr)>", "\n", h)
    t = _h.unescape(_re.sub(r"<[^>]+>", " ", h))
    t = _re.sub(r"[ \t\xa0]+", " ", t)
    return _re.sub(r"\n\s*\n+", "\n\n", t).strip()


def qt_hinweise(heute: str) -> list[list[str]]:
    import re as _re
    zeilen = []
    ordner = ZIEL / "qt"
    ordner.mkdir(exist_ok=True)
    try:
        index = laden(QT_BASIS + "licenses-used-in-qt.html").decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return [["qt/*", "Qt 6.12 Drittanbieter", "6.12", QT_BASIS, f"FEHLT ({e})", heute]]
    seiten = sorted(set(_re.findall(r'href="((?:qtcore|qtgui)-attribution-([^"#]+)\.html)"', index)))
    for seite, name in seiten:
        if name in QT_NICHT_WINDOWS:
            continue
        url = QT_BASIS + seite
        try:
            text = _html_text(laden(url).decode("utf-8", "replace"))
            daten = (f"Qt 6.12 – Drittanbieter-Hinweis ({seite})\nQuelle: {url}\n\n" + text).encode("utf-8")
            (ordner / f"{seite[:-5]}.txt").write_bytes(daten)
            zeilen.append([f"qt/{seite[:-5]}.txt", f"Qt 6.12 ({seite.split('-')[0]}): {name}", "6.12", url,
                           hashlib.sha256(daten).hexdigest(), heute])
        except Exception as e:  # noqa: BLE001
            zeilen.append([f"qt/{seite[:-5]}.txt", f"Qt 6.12: {name}", "6.12", url, f"FEHLT ({e})", heute])
    return zeilen


# --- MuPDF 1.28.6: Lizenzdateien der Drittbibliotheken aus dem offiziellen Quellpaket ----------------------------
MUPDF = ("https://mupdf.com/downloads/archive/mupdf-1.28.6-source.tar.gz",
         "dc85000640a45d90ca9b77b061f6ca67cce0c4d4fbecf8819647baf573eef101")
MUPDF_DRITT = ["brotli", "cmark-gfm", "extract", "freetype", "gumbo-parser", "harfbuzz", "jbig2dec", "lcms2", "leptonica",
               "libjpeg", "mujs", "openjpeg", "tesseract", "zint", "zlib", "zxing-cpp"]   # ohne curl/freeglut (nur Viewer)


def mupdf_hinweise(heute: str) -> list[list[str]]:
    import re as _re
    zeilen = []
    ordner = ZIEL / "mupdf"
    ordner.mkdir(exist_ok=True)
    try:
        roh = laden(MUPDF[0])
        if hashlib.sha256(roh).hexdigest() != MUPDF[1]:
            raise ValueError("SHA-256 des MuPDF-Quellpakets stimmt nicht")
        tar = tarfile.open(fileobj=io.BytesIO(roh), mode="r:gz")
    except Exception as e:  # noqa: BLE001
        return [["mupdf/*", "MuPDF 1.28.6 Drittanbieter", "1.28.6", MUPDF[0], f"FEHLT ({e})", heute]]
    for m in tar.getmembers():
        teil = m.name.split("/")
        ok = (len(teil) == 2 and teil[1] == "COPYING") or (
            len(teil) == 4 and teil[1] == "thirdparty" and teil[2] in MUPDF_DRITT
            and bool(_re.search(r"^(COPYING|LICEN[CS]E(\.TXT)?|leptonica-license\.txt)$", teil[3], _re.I)))
        if teil[-2:] == ["libjpeg", "README"]:
            ok = True                          # IJG-Lizenz steht in der README
        if not ok or not m.isfile():
            continue
        daten = tar.extractfile(m).read()
        name = "MuPDF-COPYING.txt" if len(teil) == 2 else f"{teil[2]}-{teil[3]}.txt"
        (ordner / name).write_bytes(daten)
        zeilen.append([f"mupdf/{name}", "MuPDF 1.28.6" + ("" if len(teil) == 2 else f" – thirdparty/{teil[2]}"), "1.28.6",
                       f"{MUPDF[0]} → {m.name}", hashlib.sha256(daten).hexdigest(), heute])
    return zeilen


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
    zeilen += qt_hinweise(heute) + mupdf_hinweise(heute)
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
