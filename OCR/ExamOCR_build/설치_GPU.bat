@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 시험지 OCR - 그래픽카드(NVIDIA) 판 설치 (처음 한 번만, 인터넷 필요, 수 GB 내려받음)
echo 기존 설치(.venv)와 따로 .venv_gpu 에 설치합니다. 기존 설치는 그대로 둡니다.
echo.

rem 1. NVIDIA 드라이버 확인
where nvidia-smi >nul 2>&1
if errorlevel 1 goto :nodriver
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
echo.

rem 2. 파이썬 3.12 찾기
set "PYEXE="
py -3.12 -c "import sys" >nul 2>&1 && set "PYEXE=py -3.12"
if not defined PYEXE goto :nopython

if exist ".venv_gpu\Scripts\python.exe" goto :install
echo [1/3] 가상환경 만드는 중...
%PYEXE% -m venv .venv_gpu || goto :fail

:install
set PY=.venv_gpu\Scripts\python.exe
echo [2/3] 라이브러리 설치 중... (처음엔 10분 이상 걸릴 수 있습니다)
%PY% -m pip install --upgrade pip -q || goto :fail
%PY% -m pip install paddleocr==3.7.0 python-hwpx==6.8.0 -q || goto :fail
rem 그래픽카드용 PaddlePaddle 은 PaddlePaddle 공식 저장소에서 받는다 - CUDA 12.6 용
%PY% -m pip install paddlepaddle-gpu==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/ -q
if errorlevel 1 %PY% -m pip install paddlepaddle-gpu==3.2.2 --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ --extra-index-url https://pypi.org/simple -q || goto :fail

echo [3/3] 그래픽카드 사용 점검 중...
%PY% -c "import paddle; ok = paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0; print('GPU 사용 가능' if ok else 'GPU 를 쓸 수 없음'); raise SystemExit(0 if ok else 1)" || goto :nogpu
%PY% -c "import paddle; paddle.utils.run_check()" > gpu_check.txt 2>&1
type gpu_check.txt
echo.
echo 설치 완료. 이제 GPU_실행.bat 를 실행하세요.
pause
exit /b 0

:nodriver
echo [실패] NVIDIA 그래픽카드 드라이버를 찾지 못했습니다.
echo        https://www.nvidia.com/drivers 에서 최신 드라이버를 설치한 뒤 다시 실행하세요.
goto :fail
:nopython
echo [실패] 64비트 파이썬 3.12 를 찾지 못했습니다. build_windows.bat 를 먼저 실행해 보세요.
goto :fail
:nogpu
echo [실패] 설치는 됐지만 그래픽카드를 쓰지 못합니다. 이 창 내용을 그대로 보내 주세요.
goto :fail
:fail
echo.
echo [실패] 위 메시지를 확인하세요. 문제가 계속되면 이 창 내용을 그대로 알려 주세요.
pause
exit /b 1
