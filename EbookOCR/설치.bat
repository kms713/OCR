@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 전자책 OCR - 처음 한 번만 설치 (64비트 파이썬 3.12, 인터넷 필요)
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install --upgrade pip -q || goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt -q || goto :fail
echo.
echo 설치 완료.
pause
exit /b 0
:fail
echo [실패] 위 오류를 확인하세요. (파이썬 3.12 64비트가 설치되어 있어야 합니다)
pause
exit /b 1
