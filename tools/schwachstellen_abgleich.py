"""Abgleich der ausgelieferten Komponenten mit öffentlichen Sicherheitsmeldungen (nur Produktname + Version werden
abgefragt, keine Dateien): NIST NVD (CPE-Abgleich), curl-Projekt (vuln.json), OSV (PyPI).

Kullanım: python tools/schwachstellen_abgleich.py --ziel docs/CRA/nachweise/schwachstellen_<datum>.json
Ergebnis ist ein Momentbild; ein Treffer muss fachlich bewertet werden (betroffene Funktion genutzt?).
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

CPE = [  # (Komponente, Version, CPE 2.3) – Versionen laut SBOM (OCR: MSYS2-Pakete, lizenzen/OCR-PAKETE.txt)
    ("CPython", "3.13.17", "cpe:2.3:a:python:python:3.13.17:*:*:*:*:*:*:*"),
    ("Qt", "6.12.0", "cpe:2.3:a:qt:qt:6.12.0:*:*:*:*:*:*:*"),
    ("MuPDF", "1.28.6", "cpe:2.3:a:artifex:mupdf:1.28.6:*:*:*:*:*:*:*"),
    ("Brotli (in MuPDF eingebaut)", "1.2.1", "cpe:2.3:a:google:brotli:1.2.1:*:*:*:*:*:*:*"),
    ("OpenSSL (Python _ssl/_hashlib)", "3.5.9", "cpe:2.3:a:openssl:openssl:3.5.9:*:*:*:*:*:*:*"),
    ("SQLite (Python _sqlite3)", "3.50.4", "cpe:2.3:a:sqlite:sqlite:3.50.4:*:*:*:*:*:*:*"),
    ("Expat (Python pyexpat)", "2.8.5", "cpe:2.3:a:libexpat_project:libexpat:2.8.5:*:*:*:*:*:*:*"),
    ("Tesseract", "5.5.4", "cpe:2.3:a:tesseract_project:tesseract:5.5.4:*:*:*:*:*:*:*"),
    ("Leptonica", "1.87.0", "cpe:2.3:a:leptonica:leptonica:1.87.0:*:*:*:*:*:*:*"),
    ("libpng", "1.6.59", "cpe:2.3:a:libpng:libpng:1.6.59:*:*:*:*:*:*:*"),
    ("libtiff", "4.7.2", "cpe:2.3:a:libtiff:libtiff:4.7.2:*:*:*:*:*:*:*"),
    ("libjpeg-turbo", "3.2.1", "cpe:2.3:a:libjpeg-turbo:libjpeg-turbo:3.2.1:*:*:*:*:*:*:*"),
    ("libwebp", "1.6.0", "cpe:2.3:a:webmproject:libwebp:1.6.0:*:*:*:*:*:*:*"),
    ("OpenJPEG", "2.5.4", "cpe:2.3:a:uclouvain:openjpeg:2.5.4:*:*:*:*:*:*:*"),
    ("giflib", "6.1.3", "cpe:2.3:a:giflib_project:giflib:6.1.3:*:*:*:*:*:*:*"),
    ("libarchive", "3.8.11", "cpe:2.3:a:libarchive:libarchive:3.8.11:*:*:*:*:*:*:*"),
    ("curl (ocr/libcurl-4.dll)", "8.23.0", "cpe:2.3:a:haxx:curl:8.23.0:*:*:*:*:*:*:*"),
    ("libssh2 (ocr, von libcurl)", "1.11.1", "cpe:2.3:a:libssh2:libssh2:1.11.1:*:*:*:*:*:*:*"),
    ("OpenSSL (ocr, von libcurl)", "4.1.0", "cpe:2.3:a:openssl:openssl:4.1.0:*:*:*:*:*:*:*"),
    ("nghttp2 (ocr, von libcurl)", "1.71.0", "cpe:2.3:a:nghttp2:nghttp2:1.71.0:*:*:*:*:*:*:*"),
    ("nghttp3 (ocr, von libcurl)", "1.19.0", "cpe:2.3:a:ngtcp2:nghttp3:1.19.0:*:*:*:*:*:*:*"),
    ("ngtcp2 (ocr, von libcurl)", "1.26.0", "cpe:2.3:a:ngtcp2:ngtcp2:1.26.0:*:*:*:*:*:*:*"),
    ("Brotli (ocr, von libcurl)", "1.2.1", "cpe:2.3:a:google:brotli:1.2.1:*:*:*:*:*:*:*"),
    ("XZ Utils", "5.8.4", "cpe:2.3:a:tukaani:xz:5.8.4:*:*:*:*:*:*:*"),
    ("zlib", "1.4", "cpe:2.3:a:zlib:zlib:1.4:*:*:*:*:*:*:*"),
    ("Zstandard", "1.5.7", "cpe:2.3:a:facebook:zstandard:1.5.7:*:*:*:*:*:*:*"),
    ("LZ4", "1.11.1", "cpe:2.3:a:lz4_project:lz4:1.11.1:*:*:*:*:*:*:*"),
    ("libiconv", "1.19.1", "cpe:2.3:a:gnu:libiconv:1.19.1:*:*:*:*:*:*:*"),
    ("libidn2", "2.3.8", "cpe:2.3:a:gnu:libidn2:2.3.8:*:*:*:*:*:*:*"),
    ("libunistring", "1.4.2", "cpe:2.3:a:gnu:libunistring:1.4.2:*:*:*:*:*:*:*"),
    ("JBIG-KIT", "2.1", "cpe:2.3:a:jbig-kit_project:jbig-kit:2.1:*:*:*:*:*:*:*"),
    ("bzip2", "1.0.8", "cpe:2.3:a:bzip:bzip2:1.0.8:*:*:*:*:*:*:*"),
    ("libpsl", "0.21.5", "cpe:2.3:a:libpsl_project:libpsl:0.21.5:*:*:*:*:*:*:*"),
]
OSV = [("pymupdf", "2.1"), ("PySide6", "6.12.0"), ("shiboken6", "6.12.0"), ("PySide6-Essentials", "6.12.0"),
       ("pywin32", "312"), ("pyinstaller", "6.22.3")]


def get(url: str, daten: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=daten, headers={"User-Agent": "BnX-Raptor-Build",
                                                         "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ziel", type=Path, required=True)
    a = ap.parse_args()
    erg = {"datum": date.today().isoformat(), "nvd": [], "curl": {}, "osv": []}
    for komp, ver, cpe in CPE:
        url = ("https://services.nvd.nist.gov/rest/json/cves/2.0?resultsPerPage=200&virtualMatchString="
               + urllib.parse.quote(cpe))
        for versuch in range(3):
            try:
                d = get(url)
                cves = [{"id": v["cve"]["id"], "veroeffentlicht": v["cve"].get("published", "")[:10],
                         "status": v["cve"].get("vulnStatus", ""),
                         "cvss": next((m[0]["cvssData"].get("baseScore") for k, m in v["cve"].get("metrics", {}).items()
                                       if m), None),
                         "beschreibung": next((x["value"] for x in v["cve"]["descriptions"] if x["lang"] == "en"), "")[:300]}
                        for v in d.get("vulnerabilities", [])]
                cves = [c for c in cves if c["status"] not in ("Rejected",)]
                erg["nvd"].append({"komponente": komp, "version": ver, "cpe": cpe, "anzahl": len(cves), "cves": cves})
                print(f"{komp} {ver}: {len(cves)} CVE(s) {[c['id'] for c in cves][:8]}")
                break
            except Exception as e:  # noqa: BLE001
                if versuch == 2:
                    erg["nvd"].append({"komponente": komp, "version": ver, "cpe": cpe, "fehler": str(e)})
                    print(f"{komp}: FEHLER {e}")
                time.sleep(12)
        time.sleep(7)                                   # NVD ohne API-Schlüssel: max. 5 Anfragen / 30 s
    try:                                                # curl: offizielle Liste des curl-Projekts
        vulns = get("https://curl.se/docs/vuln.json")
        betroffen = [v["id"] for v in vulns if any(
            "8.23.0" in r.get("versions", []) for r in v.get("affected", []))]
        erg["curl"] = {"quelle": "https://curl.se/docs/vuln.json", "betroffen_8_23_0": betroffen}
        print("curl-Projekt, 8.23.0 betroffen:", betroffen)
    except Exception as e:  # noqa: BLE001
        erg["curl"] = {"fehler": str(e)}
    try:                                                # Tesseract: GitHub Security Advisories (nicht vollständig in NVD)
        adv = get("https://api.github.com/repos/tesseract-ocr/tesseract/security-advisories?per_page=100")
        offen_ = [x["ghsa_id"] for x in adv if not any(
            (v.get("patched_versions") or "").strip() in ("5.5.3", "5.5.4") for v in x["vulnerabilities"])]
        erg["tesseract_ghsa"] = {"anzahl": len(adv), "fuer_5_5_4_nicht_behoben": offen_}
        print(f"Tesseract-GHSA: {len(adv)}, für 5.5.4 nicht als behoben geführt: {offen_}")
    except Exception as e:  # noqa: BLE001
        erg["tesseract_ghsa"] = {"fehler": str(e)}
    q = {"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in OSV]}
    r = get("https://api.osv.dev/v1/querybatch", json.dumps(q).encode())
    for (n, v), res in zip(OSV, r["results"]):
        erg["osv"].append({"paket": n, "version": v, "vulns": [x["id"] for x in res.get("vulns", [])]})
    a.ziel.parent.mkdir(parents=True, exist_ok=True)
    a.ziel.write_text(json.dumps(erg, ensure_ascii=False, indent=1), encoding="utf-8")
    print("gespeichert:", a.ziel)


if __name__ == "__main__":
    main()
