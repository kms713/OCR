@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 시험지 OCR - CPU 와 그래픽카드 결과 비교 시험
echo gpu_test 폴더의 PDF 를 CPU 로 한 번, 그래픽카드로 한 번 변환합니다.
echo.
if not exist "gpu_test" mkdir "gpu_test"
dir /b "gpu_test\*.pdf" >nul 2>&1
if errorlevel 1 goto :nopdf
if not exist ".venv_gpu\Scripts\python.exe" goto :nogpu

echo [1/2] 그래픽카드로 변환 중... 끝나면 다음 단계로 넘어갑니다.
.venv_gpu\Scripts\python.exe ocr_paddle.py "gpu_test" -o "gpu_test\result_gpu" --device gpu > "gpu_test\log_gpu.txt" 2>&1
type "gpu_test\log_gpu.txt"
echo.

if not exist ".venv\Scripts\python.exe" goto :nocpu
echo [2/2] CPU 로 변환 중... 그래픽카드보다 오래 걸립니다.
.venv\Scripts\python.exe ocr_paddle.py "gpu_test" -o "gpu_test\result_cpu" --device cpu > "gpu_test\log_cpu.txt" 2>&1
type "gpu_test\log_cpu.txt"
echo.
echo 완료. gpu_test 폴더의 result_gpu, result_cpu 폴더 안 txt 파일과 log_gpu.txt, log_cpu.txt 를 보내 주세요.
goto :end

:nopdf
echo [안내] gpu_test 폴더에 시험지 PDF 를 넣은 뒤 다시 실행하세요.
goto :end
:nogpu
echo [안내] 그래픽카드 판이 아직 설치되지 않았습니다. 설치_GPU.bat 를 먼저 실행하세요.
goto :end
:nocpu
echo [안내] CPU 판 가상환경이 없어 CPU 변환은 건너뜁니다. build_windows.bat 를 한 번 실행하면 생깁니다.
:end
endlocal
pause
