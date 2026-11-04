@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 전자책 OCR - 처음 한 번만 설치 (64비트 파이썬 3.12, 인터넷 필요)
echo.
if exist ".venv\Scripts\python.exe" goto :install

rem 파이썬 찾기: py 런처(3.12) → python 명령
set "PYEXE="
py -3.12 -c "import sys" >nul 2>&1 && set "PYEXE=py -3.12"
rem 3.12 가 없고 Python Install Manager 의 py 가 있으면 3.12 를 옆에 설치 - 다른 버전은 그대로 둠
if not defined PYEXE (
    where py >nul 2>&1 && (
        echo 파이썬 3.12 를 설치합니다. (이미 있는 다른 버전은 그대로 둡니다^)
        py install 3.12
        py -3.12 -c "import sys" >nul 2>&1 && set "PYEXE=py -3.12"
    )
)
if not defined PYEXE (
    python -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,13)) and sys.maxsize > 2**32 else 1)" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo [실패] 64비트 파이썬 3.12 를 찾지 못했습니다.
    echo        https://www.python.org/downloads/ 에서 Python 3.12 Windows installer 64-bit 를 받아 설치한 뒤
    echo        이 파일을 다시 실행하세요. 설치 첫 화면에서 "Add python.exe to PATH" 를 체크하세요.
    goto :fail
)
echo [1/2] 가상환경 만드는 중... (%PYEXE%)
%PYEXE% -m venv .venv || goto :fail

:install
echo [2/2] 라이브러리 설치 중... (처음엔 몇 분 걸립니다)
.venv\Scripts\python.exe -m pip install --upgrade pip -q || goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt -q || goto :fail
echo.
echo 설치 완료. 이제 1_캡처점검.bat 를 실행하세요.
pause
exit /b 0

:fail
echo.
echo [실패] 위 메시지를 확인하세요. 문제가 계속되면 이 창 내용을 그대로 알려 주세요.
if exist ".venv" if not exist ".venv\Scripts\python.exe" rmdir /s /q ".venv"
pause
exit /b 1
