@echo off
REM Bahis Tahmin - web arayuzu (tarayicidan kullanim). Python 3.11+ gerekir.
REM Yalnizca bu bilgisayardan erisilir: http://127.0.0.1:8765
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
.venv\Scripts\python -c "import flask, waitress" 2>nul
if errorlevel 1 (
    echo Web arayuzu paketleri kuruluyor...
    .venv\Scripts\python -m pip install -r requirements.txt
)
title Bahis Tahmin - web
.venv\Scripts\python -m bahis_tahmin web %*
pause
