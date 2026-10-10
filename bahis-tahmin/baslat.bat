@echo off
REM Bahis Tahmin - kaynak koddan calistirma (Python 3.11+ gerekir)
cd /d "%~dp0"
if not exist .venv (
    echo Sanal ortam olusturuluyor...
    py -3 -m venv .venv || python -m venv .venv
    if errorlevel 1 (
        echo Python bulunamadi. https://www.python.org/downloads/ adresinden Python 3.12 kurun ^(Add to PATH secili olsun^).
        pause
        exit /b 1
    )
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe run_app.py
