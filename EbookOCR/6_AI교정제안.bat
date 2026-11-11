@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 아직 설치가 안 되어 있습니다. 설치.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
.venv\Scripts\python.exe bookdir.py --list
echo.
set /p BOOK=책 이름(위 목록 중 하나)을 입력하세요: 
if "%BOOK%"=="" exit /b 1
rem 모델은 ai_models.txt 목록에서 고름 (자동 = 위에서부터, 막히면 다음 모델). 키: nvidia_key.txt, gemini_key.txt
.venv\Scripts\python.exe ebook_suggest.py "books\%BOOK%" --menu %*
pause
