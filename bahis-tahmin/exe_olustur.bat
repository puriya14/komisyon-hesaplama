@echo off
REM Bahis Tahmin - Windows .exe olusturma
cd /d "%~dp0"
if not exist .venv (
    py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\pyinstaller --noconfirm --clean BahisTahmin.spec
if errorlevel 1 (
    echo Derleme basarisiz.
    pause
    exit /b 1
)
echo.
echo Hazir: dist\BahisTahmin\BahisTahmin.exe
pause
