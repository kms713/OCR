@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==================================================
echo  시험지 OCR 변환 - Windows 빌드
echo  (64비트 파이썬 3.12, Inno Setup 6, 인터넷 연결 필요)
echo ==================================================

rem ---- 1. 전용 가상환경 (기존 파이썬과 섞이지 않게) ----
if not exist ".venv\Scripts\python.exe" (
    echo [1/6] 가상환경 만드는 중...
    py -3.12 -m venv .venv || goto :fail
)
set PY=.venv\Scripts\python.exe

rem ---- 2. 버전 고정 설치 (paddlepaddle 3.3.x 는 CPU 오류 버그가 있어 3.2.2) ----
echo [2/6] 라이브러리 설치 중... (처음엔 몇 분 걸립니다)
%PY% -m pip install --upgrade pip --no-warn-script-location -q || goto :fail
%PY% -m pip install -r requirements.txt --no-warn-script-location -q || goto :fail

rem ---- 3. 모델 준비: 없으면 받고, 프로젝트의 models 폴더로 복사 ----
echo [3/6] 모델 준비 중...
set MSRC=%USERPROFILE%\.paddlex\official_models
if not exist "%MSRC%\PP-OCRv5_server_det" (
    %PY% -c "import ocr_paddle as op; op.build_ocr(op.default_options())" || goto :fail
)
if not exist "%MSRC%\korean_PP-OCRv5_mobile_rec" goto :fail
robocopy "%MSRC%\PP-OCRv5_server_det" "models\PP-OCRv5_server_det" /E /NFL /NDL /NJH /NJS >nul
robocopy "%MSRC%\korean_PP-OCRv5_mobile_rec" "models\korean_PP-OCRv5_mobile_rec" /E /NFL /NDL /NJH /NJS >nul

rem ---- 4. exe 만들기 ----
echo [4/6] 프로그램 묶는 중... (10분 이상 걸릴 수 있습니다)
if exist "dist\ExamOCR" rmdir /s /q "dist\ExamOCR"
%PY% -m PyInstaller --noconfirm --clean ExamOCR.spec || goto :fail
copy /y "사용법.txt" "dist\ExamOCR\사용법.txt" >nul

rem ---- 5. 점검 ----
echo [5/6] 점검 중...
start "" /wait "dist\ExamOCR\ExamOCR.exe" --check
type "dist\ExamOCR\ocr_check.txt"
findstr /c:"RESULT: PASS" "dist\ExamOCR\ocr_check.txt" >nul || (echo. & echo [주의] 점검에 실패한 항목이 있습니다. 위 내용을 확인하세요. & goto :end)
del /q "dist\ExamOCR\ocr_check.txt" "dist\ExamOCR\ocr_log.txt" "dist\ExamOCR\ocr_console.txt" "dist\ExamOCR\ocr_crash.txt" "dist\ExamOCR\cpu_check.txt" 2>nul
if exist "ExamOCR.zip" del /q "ExamOCR.zip"

rem ---- 6. 설치 파일 만들기 (Inno Setup 6 또는 7) ----
echo [6/6] 설치 파일 만드는 중... (몇 분 걸립니다)
set "PF86=%ProgramFiles(x86)%"
set "ISCC="
for %%P in ("%PF86%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 7\ISCC.exe" "%PF86%\Inno Setup 7\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe") do (
    if not defined ISCC if exist "%%~P" set "ISCC=%%~P"
)
if not defined ISCC (echo [실패] Inno Setup을 찾지 못했습니다. Inno Setup 6을 기본 경로에 설치하세요. & goto :fail)
if exist "installer" rmdir /s /q "installer"
"%ISCC%" /Q "ExamOCR.iss" || goto :fail
copy /y "사용법.txt" "installer\사용법.txt" >nul

echo.
echo 완료: installer 폴더의 ExamOCR_Setup.exe 와 사용법.txt 를 선생님들께 나눠 주세요.
goto :end

:fail
echo.
echo [실패] 위 오류 메시지를 확인하세요.
exit /b 1

:end
endlocal
pause
