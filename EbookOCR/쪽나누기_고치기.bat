@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 예전 판 OCR 로 만든 책: 앞 쪽에 붙어 들어간 다음 쪽 글을 제 쪽으로 돌려놓습니다 (고친 내용은 그대로).
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 아직 설치가 안 되어 있습니다. 설치.bat 또는 설치_교정용.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
.venv\Scripts\python.exe -c "import numpy" >nul 2>&1 || (
    echo [안내] 설치_교정용.bat 를 한 번 더 실행해 필요한 라이브러리를 추가하세요.
    pause
    exit /b 1
)
.venv\Scripts\python.exe bookdir.py --list
echo.
echo 이 책의 편집기(4_교정.bat)는 닫은 상태에서 실행하세요.
set /p BOOK=책 번호 또는 이름을 입력하세요: 
if "%BOOK%"=="" exit /b 1
.venv\Scripts\python.exe fix_page_split.py "books\%BOOK%" %*
pause
