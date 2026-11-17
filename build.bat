@echo off
REM BnX-Raptor: yerel bilgisayarda paket oluşturur (test için).
REM GitHub (release.yml) AYNI adımları kullanır: tools\ocr_bereitstellen.py + tools\paket_bauen.py + BnX-Raptor.spec
REM Çıktı klasörü: BNX_AUSGABE ortam değişkeni (yoksa .\dist). OneDrive içindeyseniz dışarıda bir klasör seçin.
cd /d "%~dp0"

if not exist .venv (
    py -3 -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt

python -m pytest -q tests || (echo TESTLER BASARISIZ & pause & exit /b 1)

REM OCR (Tesseract + deu/tur/eng): indirir, SHA-256 ile doğrular -> build\ocr
python tools\ocr_bereitstellen.py || (echo OCR HAZIRLANAMADI & pause & exit /b 1)

if "%BNX_AUSGABE%"=="" set BNX_AUSGABE=dist
python tools\paket_bauen.py --ausgabe "%BNX_AUSGABE%" || (echo PAKET HATASI & pause & exit /b 1)

echo.
echo Hazir: %BNX_AUSGABE%\BnX-Raptor\BnX-Raptor.exe
pause
