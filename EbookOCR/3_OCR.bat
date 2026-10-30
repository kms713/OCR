@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /p BOOK=책 이름(캡처한 폴더 이름)을 입력하세요: 
if "%BOOK%"=="" exit /b 1
.venv\Scripts\python.exe ebook_ocr.py "books\%BOOK%" %*
pause
