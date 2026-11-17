# Drittanbieter-Komponenten in BnX-Raptor 0.4.0

Stand: 17.11.2026 · **Entwurf – vor einer externen Weitergabe juristisch zu prüfen.**

- Vollständige Liste aller mitgelieferten Programmdateien mit Komponente, Lizenz und zugehörigem Lizenztext:
  **`DLL-LISTE.txt`** (wird bei jedem Build automatisch erzeugt).
- Offizielle Lizenztexte und Copyright-Hinweise: Ordner **`drittanbieter\`**; Herkunft (offizielle Quelle,
  SHA-256, Abrufdatum) in **`drittanbieter\QUELLEN.csv`**.

BnX-Raptor selbst: Lizenz **noch nicht festgelegt** (Entscheidung des Herstellers). Mit PyMuPDF/MuPDF unter
AGPL-3.0 muss das Gesamtprogramm AGPL-3.0-kompatibel weitergegeben werden – oder es wird eine kommerzielle
Artifex-Lizenz erworben.

| Komponente | Version | Lizenz | Lizenztext |
|---|---|---|---|
| PyMuPDF / MuPDF (Artifex) | 2.1 / 1.28.6 | AGPL-3.0 oder kommerziell | `PyMuPDF-COPYING-AGPL-3.0.txt` |
| Tesseract OCR | 5.5.3 | Apache-2.0 | `Tesseract-LICENSE-Apache-2.0.txt` |
| Tesseract-Sprachdaten (deu/tur/eng best, osd) | 4.1.0 | Apache-2.0 | `tessdata_best-LICENSE-Apache-2.0.txt` |
| Laufzeitbibliotheken von Tesseract (33 DLLs) | siehe `DLL-LISTE.txt` | u. a. BSD, MIT, Zlib, LGPL-2.1/3.0, GPL-2.0-or-later (libjbig), GPL-3.0 + GCC Runtime Exception | `drittanbieter\` |
| Qt 6 / PySide6 / Shiboken6 | 6.12.0 | LGPL-3.0 | `LGPL-3.0.txt`, `GPL-3.0.txt` |
| Python | 3.13 | PSF-2.0 (+ eingebundene Bibliotheken) | `Python-LICENSE.txt`, `drittanbieter\Python-license.rst.txt` |
| OpenSSL (Python und Qt) | 3.x | Apache-2.0 | `drittanbieter\OpenSSL-LICENSE.txt` |
| libffi | – | MIT | `drittanbieter\libffi-LICENSE.txt` |
| pywin32 | 312 | PSF-ähnlich | `pywin32-License.txt` |
| PyInstaller (Bootloader) | 6.22 | GPL-2.0 mit Bootloader-Ausnahme | `PyInstaller-COPYING.txt` |
| Microsoft Visual C++ Runtime | 14.x | Microsoft Distributable Code | Abschnitt in `Python-LICENSE.txt` |
| SQLite | 3.50 | gemeinfrei | – |

## Offen vor einer externen Weitergabe

1. Lizenz von BnX-Raptor festlegen (LICENSE-Datei im Repository).
2. Drittbibliotheken innerhalb von Qt (z. B. PCRE2, HarfBuzz, libpng, libjpeg-turbo, libtiff, libwebp in Plug-ins)
   und innerhalb von MuPDF (u. a. Little CMS, OpenJPEG, Brotli, extract) einzeln mit Lizenztext erfassen.
3. Quellcode-Angebot bzw. Bezugsquelle für AGPL/LGPL/GPL-Teile (BnX-Raptor, MuPDF, Qt, Tesseract-Build mit libjbig).
4. Microsoft-Bedingungen für die mitgelieferte VC++-Laufzeit prüfen.
5. Juristische Prüfung.
