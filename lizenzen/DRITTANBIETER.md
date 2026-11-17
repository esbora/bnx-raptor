# Drittanbieter-Komponenten in BnX-Raptor 0.4.0

Stand: 17.11.2026 · **Entwurf – vor einer Weitergabe des Programms zu vervollständigen** (siehe „Offen“).

BnX-Raptor selbst: Lizenz **noch nicht festgelegt** (Entscheidung des Projektinhabers; mit PyMuPDF unter AGPL
muss das Gesamtprogramm AGPL-3.0-kompatibel weitergegeben werden – oder es wird eine kommerzielle Artifex-Lizenz erworben).

| Komponente | Version | Lizenz | Lizenztext im Ordner `lizenzen` |
|---|---|---|---|
| PyMuPDF / MuPDF (Artifex) | 2.1 / 1.28.6 | AGPL-3.0 **oder** kommerziell | `PyMuPDF-COPYING-AGPL-3.0.txt` ✓ |
| Tesseract OCR | 5.5.3 | Apache-2.0 | `Tesseract-LICENSE-Apache-2.0.txt` ✓ |
| Tesseract-Sprachdaten (tessdata_best deu/tur/eng, tessdata osd) | 4.1.0 | Apache-2.0 | `tessdata_best-LICENSE-Apache-2.0.txt` ✓ |
| Qt 6 / PySide6 / Shiboken6 | 6.12.0 | LGPL-3.0 (alternativ GPL/kommerziell) | `LGPL-3.0.txt` + `GPL-3.0.txt` ✓ |
| Python | 3.12/3.13 | PSF-2.0 | `Python-LICENSE.txt` ✓ |
| pywin32 | 312 | PSF-ähnlich | `pywin32-License.txt` ✓ |
| PyInstaller (Bootloader) | 6.22 | GPL-2.0 mit Bootloader-Ausnahme | `PyInstaller-COPYING.txt` ✓ |
| OpenSSL (über Python) | 3.x | Apache-2.0 | Text wie Tesseract (Apache-2.0) – Copyright-Hinweis **offen** |
| SQLite (über Python) | 3.x | gemeinfrei | – |

## Laufzeitbibliotheken von Tesseract (Ordner `ocr`, Liste: `Tesseract-DLLs.txt`)

| Bibliothek (DLL) | Lizenz | Lizenztext |
|---|---|---|
| libtesseract | Apache-2.0 | ✓ |
| libleptonica | BSD-2-Clause (Leptonica) | **offen** |
| libstdc++, libgcc_s_seh | GPL-3.0 mit GCC-Runtime-Ausnahme | GPL-3.0 ✓, Ausnahmetext **offen** |
| libwinpthread | MIT/BSD (MinGW-w64) | **offen** |
| libarchive | BSD-2-Clause | **offen** |
| libb2 | CC0-1.0 | **offen** |
| libbrotlicommon, libbrotlidec | MIT | **offen** |
| libbz2 | bzip2-Lizenz (BSD-ähnlich) | **offen** |
| libcurl | curl-Lizenz (MIT-ähnlich) | **offen** |
| libdeflate | MIT | **offen** |
| libexpat | MIT | **offen** |
| libgif | MIT | **offen** |
| libiconv | LGPL-2.1-or-later | **offen** (LGPL-2.1-Text) |
| libidn2 | LGPL-3.0-or-later / GPL-2.0-or-later | LGPL-3.0 ✓ |
| libintl (gettext) | LGPL-2.1-or-later | **offen** (LGPL-2.1-Text) |
| libjbig (JBIG-KIT) | GPL-2.0-or-later | **offen** – mit AGPL-Weitergabe vereinbar, bei kommerzieller Lizenz prüfen |
| libjpeg-turbo | IJG + BSD-3-Clause + zlib | **offen** |
| liblerc | Apache-2.0 | ✓ |
| liblz4 | BSD-2-Clause | **offen** |
| liblzma (xz) | 0BSD / gemeinfrei | **offen** |
| libopenjp2 (OpenJPEG) | BSD-2-Clause | **offen** |
| libpng16 | libpng-Lizenz | **offen** |
| libpsl | MIT | **offen** |
| libsharpyuv, libwebp, libwebpmux | BSD-3-Clause | **offen** |
| libssh2 | BSD-3-Clause | **offen** |
| libtiff | libtiff-Lizenz (BSD-ähnlich) | **offen** |
| libunistring | LGPL-3.0-or-later / GPL-2.0-or-later | LGPL-3.0 ✓ |
| libzstd | BSD-3-Clause (oder GPL-2.0) | **offen** |
| zlib1 | zlib-Lizenz | **offen** |

## Offen vor einer Weitergabe

1. Lizenz von BnX-Raptor selbst festlegen (LICENSE-Datei im Repository).
2. Fehlende Lizenztexte/Copyright-Hinweise der oben mit **offen** markierten Bibliotheken beilegen
   (Quelle: MSYS2-Pakete `mingw-w64-x86_64-*`, jeweils `share/licenses`).
3. Bei AGPL/LGPL/GPL: Hinweis, wo der Quellcode erhältlich ist (BnX-Raptor-Repository, Tesseract, MuPDF, Qt).
4. Juristische Prüfung durch die Kanzlei.
