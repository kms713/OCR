@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 찍어 둔 쪽 이미지(page_0001.png ...)를 한 PDF 로 합칩니다. 이미지는 그대로 둡니다. 결과: 책 폴더 옆 '책이름.pdf'
if not exist ".venv\Scripts\python.exe" (
    echo [안내] 아직 설치가 안 되어 있습니다. 설치.bat 또는 설치_교정용.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
.venv\Scripts\python.exe bookdir.py --list
echo.
set /p BOOK=책 번호 또는 이름을 입력하세요: 
if "%BOOK%"=="" exit /b 1
.venv\Scripts\python.exe ebook_capture.py -o "books\%BOOK%" --pdf %*
pause
