@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 교정 편집기 시험용 샘플 책(3쪽)을 책 폴더에 만듭니다. OCR 없이 4_교정.bat 를 시험할 수 있습니다.
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 아직 설치가 안 되어 있습니다. 설치.bat 또는 설치_교정용.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
.venv\Scripts\python.exe make_sample.py
pause
