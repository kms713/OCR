@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 저장소의 최신 코드를 받아 이 폴더에 반영합니다 (books, .venv, gemini_key.txt 등은 건드리지 않음)
where git >nul 2>nul
if errorlevel 1 (
    echo [안내] Git 이 설치되어 있지 않습니다. https://git-scm.com 에서 설치한 뒤 다시 실행하세요.
    pause
    exit /b 1
)
if not exist ".git" (
    echo [안내] 이 폴더는 아직 Git 으로 연결되지 않았습니다. 처음 한 번 연결하는 방법은 사용 안내를 보세요.
    pause
    exit /b 1
)
echo 최신 코드를 받는 중...
git pull --ff-only
if errorlevel 1 (
    echo.
    echo [주의] 업데이트하지 못했습니다. 이 창을 캡처해 보내 주세요.
) else (
    echo.
    echo 완료. 열려 있는 교정 편집기 탭은 F5 로 새로고침하세요.
)
pause
