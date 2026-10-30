@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==================================================
echo  저사양 PC용 엔진(ONNX) 시험 - 정확도·속도 비교
echo  사용법: 비교할 PDF 파일들을 이 bat 파일 위에 끌어다 놓기
echo ==================================================
if "%~1"=="" (echo. & echo 비교할 PDF 파일들을 이 bat 파일 위에 끌어다 놓으세요. & goto :end)
if not exist "models\PP-OCRv5_server_det" (echo [실패] models 폴더가 없습니다. 먼저 build_windows.bat 을 한 번 실행하세요. & goto :end)

rem ---- 1. 시험 전용 가상환경 (배포용 빌드 환경 .venv 는 건드리지 않음) ----
if not exist ".venv_onnx\Scripts\python.exe" (
    echo [1/4] 시험용 가상환경 만드는 중... 처음 한 번만, 몇 분 걸립니다
    py -3.12 -m venv .venv_onnx || goto :fail
)
set PY=.venv_onnx\Scripts\python.exe
echo [1/4] 라이브러리 설치 중...
%PY% -m pip install --upgrade pip --no-warn-script-location -q || goto :fail
%PY% -m pip install -r requirements.txt onnxruntime==1.29.0 --no-warn-script-location -q || goto :fail

rem ---- 2~4. 변환, 수치 비교, 시험지 비교 ----
%PY% onnx_test.py %* || goto :fail

echo.
echo 완료: onnx_report.txt 를 보내 주세요.
goto :end

:fail
echo.
echo [실패] 위 오류 메시지를 확인하세요. (창 내용을 복사해 보내 주세요)

:end
endlocal
pause
