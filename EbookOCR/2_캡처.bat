@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 아직 설치가 안 되어 있습니다. 같은 폴더의 설치.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
set /p BOOK=책 이름(저장 폴더 이름)을 입력하세요: 
if "%BOOK%"=="" exit /b 1
rem 잘라낼 영역이 있으면 아래 줄 끝에 --crop x1,y1,x2,y2 를 붙이세요 (예: --crop 0,120,1600,2440)
.venv\Scripts\python.exe ebook_capture.py -o "books\%BOOK%" %*
pause
