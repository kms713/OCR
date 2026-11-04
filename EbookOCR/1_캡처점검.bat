@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 아직 설치가 안 되어 있습니다. 같은 폴더의 설치.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
rem LD플레이어에서 전자책을 연 상태로 실행 → test\test_screen.png 확인
.venv\Scripts\python.exe ebook_capture.py --test -o test %*
pause
