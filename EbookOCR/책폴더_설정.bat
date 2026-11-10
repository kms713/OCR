@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 책 자료(books) 위치를 클라우드 동기화 폴더 등으로 지정합니다. PC 마다 한 번.
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 아직 설치가 안 되어 있습니다. 설치.bat 또는 설치_교정용.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
.venv\Scripts\python.exe bookdir.py
pause
