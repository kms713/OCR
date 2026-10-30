@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==================================================
echo  시험지 OCR 변환 (저사양용, ONNX 엔진) - Windows 빌드
echo  (64비트 파이썬 3.12, Inno Setup 6, 인터넷 연결 필요)
echo  기본판 빌드 환경(.venv)과 결과물(dist\ExamOCR, installer)은 건드리지 않습니다.
echo ==================================================

rem ---- 1. 저사양판 전용 가상환경 (PaddlePaddle 없음) ----
if not exist ".venv_lite\Scripts\python.exe" (
    echo [1/5] 가상환경 만드는 중...
    py -3.12 -m venv .venv_lite || goto :fail
)
set PY=.venv_lite\Scripts\python.exe
echo [1/5] 라이브러리 설치 중... 처음엔 몇 분 걸립니다
%PY% -m pip install --upgrade pip --no-warn-script-location -q || goto :fail
%PY% -m pip install -r requirements_lite.txt --no-warn-script-location -q || goto :fail
%PY% -c "import importlib.util,sys; sys.exit(1 if importlib.util.find_spec('paddle') else 0)" || (echo [실패] .venv_lite 에 PaddlePaddle이 설치되어 있습니다. .venv_lite 폴더를 지우고 다시 실행하세요. & goto :fail)

rem ---- 2. ONNX 모델 준비: 없으면 공식 ONNX 모델을 받는다 ----
echo [2/5] ONNX 모델 준비 중...
%PY% -c "import onnx_test as t; t.fetch_onnx()" || goto :fail

rem ---- 3. exe 만들기 ----
echo [3/5] 프로그램 묶는 중... 몇 분 걸립니다
if exist "dist\ExamOCR_Lite" rmdir /s /q "dist\ExamOCR_Lite"
%PY% -m PyInstaller --noconfirm --clean --workpath build_lite ExamOCR_Lite.spec || goto :fail
copy /y "사용법.txt" "dist\ExamOCR_Lite\사용법.txt" >nul

rem ---- 4. 점검 ----
echo [4/5] 점검 중...
start "" /wait "dist\ExamOCR_Lite\ExamOCR.exe" --check
type "dist\ExamOCR_Lite\ocr_check.txt"
findstr /c:"RESULT: PASS" "dist\ExamOCR_Lite\ocr_check.txt" >nul || (echo. & echo [주의] 점검에 실패한 항목이 있습니다. 위 내용을 확인하세요. & goto :end)
findstr /c:"onnxruntime" "dist\ExamOCR_Lite\ocr_check.txt" >nul || (echo. & echo [주의] ONNX 엔진으로 동작하지 않았습니다. 위 내용을 보내 주세요. & goto :end)
del /q "dist\ExamOCR_Lite\ocr_check.txt" "dist\ExamOCR_Lite\ocr_log.txt" "dist\ExamOCR_Lite\ocr_console.txt" "dist\ExamOCR_Lite\ocr_crash.txt" "dist\ExamOCR_Lite\cpu_check.txt" 2>nul

rem ---- 5. 설치 파일 만들기 (Inno Setup 6 또는 7) ----
echo [5/5] 설치 파일 만드는 중... 몇 분 걸립니다
set "PF86=%ProgramFiles(x86)%"
set "ISCC="
for %%P in ("%PF86%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 7\ISCC.exe" "%PF86%\Inno Setup 7\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe") do (
    if not defined ISCC if exist "%%~P" set "ISCC=%%~P"
)
if not defined ISCC (echo [실패] Inno Setup을 찾지 못했습니다. & goto :fail)
if exist "installer_lite" rmdir /s /q "installer_lite"
"%ISCC%" /Q "ExamOCR_Lite.iss" || goto :fail
copy /y "사용법.txt" "installer_lite\사용법.txt" >nul

echo.
echo 완료: installer_lite 폴더의 ExamOCR_Lite_Setup.exe 를 구형 PC에서 실행해 시험하세요.
goto :end

:fail
echo.
echo [실패] 위 오류 메시지를 확인하세요. (창 내용을 복사해 보내 주세요)

:end
endlocal
pause
