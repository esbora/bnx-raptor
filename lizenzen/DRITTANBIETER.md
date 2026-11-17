# Drittanbieter-Komponenten in BnX-Raptor 0.4.0

Stand: 17.11.2026 · **Entwurf – vor einer externen Weitergabe juristisch zu prüfen.**

- Vollständige Liste aller mitgelieferten Programmdateien mit Komponente, Lizenz und zugehörigem Lizenztext:
  **`DLL-LISTE.txt`** (wird bei jedem Build automatisch erzeugt).
- Offizielle Lizenztexte und Copyright-Hinweise: Ordner **`drittanbieter\`** (Herkunft, SHA-256 und Abrufdatum in
  **`drittanbieter\QUELLEN.csv`**), darin `qt\` (Qt-6.12-Dokumentation) und `mupdf\` (offizielles MuPDF-Quellpaket 1.28.6).
- Texterkennung (Ordner `ocr\`): Herkunft jeder Datei (MSYS2-Paket, Version, Lizenz, Paket-SHA-256) in
  **`OCR-PAKETE.txt`**; die Lizenzdateien der Pakete in **`drittanbieter-ocr\<paket>\`**.
- Quellcode der mitgelieferten GPL/LGPL-Bibliotheken der Texterkennung: Ordner **`..\quellcode-drittanbieter\`**.

BnX-Raptor selbst: Lizenz **noch nicht festgelegt** (Entscheidung des Herstellers). Mit PyMuPDF/MuPDF unter
AGPL-3.0 muss das Gesamtprogramm AGPL-3.0-kompatibel weitergegeben werden – oder es wird eine kommerzielle
Artifex-Lizenz erworben.

| Komponente | Version | Lizenz | Lizenztext |
|---|---|---|---|
| PyMuPDF / MuPDF (Artifex) | 2.1 / 1.28.6 | AGPL-3.0 oder kommerziell | `PyMuPDF-COPYING-AGPL-3.0.txt`, `drittanbieter\mupdf\` |
| Tesseract OCR (MSYS2-Paket) | 5.5.4 | Apache-2.0 | `Tesseract-LICENSE-Apache-2.0.txt` |
| Tesseract-Sprachdaten (deu/tur/eng best, osd) | 4.1.0 | Apache-2.0 | `tessdata_best-LICENSE-Apache-2.0.txt` |
| Laufzeitbibliotheken von Tesseract (40 DLLs, MSYS2) | siehe `OCR-PAKETE.txt` | u. a. BSD, MIT, Zlib, Apache-2.0 (OpenSSL 4), LGPL-2.1/3.0, GPL-2.0-or-later (libjbig), GPL-3.0 + GCC Runtime Library Exception (libgcc, libstdc++, libgomp) | `drittanbieter-ocr\`, `drittanbieter\` |
| Qt 6 / PySide6 / Shiboken6 | 6.12.0 | LGPL-3.0 | `LGPL-3.0.txt`, `GPL-3.0.txt`, `drittanbieter\qt\` |
| Python | 3.13 | PSF-2.0 (+ eingebundene Bibliotheken) | `Python-LICENSE.txt`, `drittanbieter\Python-license.rst.txt` |
| OpenSSL (Python) | 3.x | Apache-2.0 | `drittanbieter\OpenSSL-LICENSE.txt` |
| libffi | – | MIT | `drittanbieter\libffi-LICENSE.txt` |
| pywin32 | 312 | PSF-ähnlich | `pywin32-License.txt` |
| PyInstaller (Bootloader) | 6.22 | GPL-2.0 mit Bootloader-Ausnahme | `PyInstaller-COPYING.txt` |
| Microsoft Visual C++ Runtime | 14.x | Microsoft Distributable Code | Abschnitt in `Python-LICENSE.txt` |
| SQLite | 3.50 | gemeinfrei | – |

## Offen vor einer externen Weitergabe

1. Lizenz von BnX-Raptor festlegen (AGPL-3.0 oder kommerzielle Artifex-Lizenz für PyMuPDF/MuPDF).
2. Bezugsweg für den Quellcode von Qt/PySide6 (LGPL-3.0) festlegen.
3. GCC-Laufzeit (libgcc, libstdc++, libgomp): Einordnung unter der GCC Runtime Library Exception bestätigen;
   Quellcode nicht beigelegt (Bezugsquelle in `..\quellcode-drittanbieter\LIESMICH.txt`).
4. Microsoft-Bedingungen für die mitgelieferte VC++-Laufzeit prüfen.
5. Juristische Prüfung insgesamt.
