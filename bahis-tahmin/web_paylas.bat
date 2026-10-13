@echo off
REM Bahis Tahmin - web arayuzunu ayni agdaki cihazlara (or. telefon) parolayla ac.
REM Acilista bir giris parolasi sorulur; telefonda ekrandaki http://192.168...:8765 adresini acin.
cd /d "%~dp0"
call web_baslat.bat --paylas
