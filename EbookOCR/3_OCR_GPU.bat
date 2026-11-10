@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv_gpu\Scripts\python.exe" (
    echo [안내] 그래픽카드 판이 아직 설치되지 않았습니다. 설치_GPU.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
set /p BOOK=책 이름(캡처한 폴더 이름)을 입력하세요: 
if "%BOOK%"=="" exit /b 1
rem 결과는 3_OCR.bat 와 같은 books\책이름_OCR (그래픽카드·CPU 결과 글자 99.99%% 동일, 속도만 다름)
.venv_gpu\Scripts\python.exe ebook_ocr.py "books\%BOOK%" --device gpu %*
pause
