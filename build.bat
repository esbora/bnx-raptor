@echo off
REM BnX-Raptor: yerel bilgisayarda .exe oluşturur (test için).
REM Resmi sürümler GitHub'da otomatik oluşturulur – bkz. RELEASE.md
cd /d "%~dp0"

if not exist .venv (
    py -3 -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt

python -m pytest -q tests || (echo TESTLER BASARISIZ & pause & exit /b 1)

pyinstaller --noconfirm --windowed --name BnX-Raptor ^
    --hidden-import win32com.client --hidden-import pythoncom ^
    main.py

copy /Y config.example.json dist\BnX-Raptor\config.example.json
echo.
echo Hazir: dist\BnX-Raptor\BnX-Raptor.exe
pause
