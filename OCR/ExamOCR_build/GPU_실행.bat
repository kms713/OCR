@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 시험지 OCR 변환 프로그램을 그래픽카드(NVIDIA)로 실행 - 집 PC 대량 변환용
rem 화면과 결과 파일 이름은 설치판과 같고, 창 제목에 (그래픽카드)가 붙는다
if not exist ".venv_gpu\Scripts\pythonw.exe" goto :nogpu
set EXAMOCR_DEVICE=gpu
start "" ".venv_gpu\Scripts\pythonw.exe" ocr_gui.py
exit /b 0

:nogpu
echo [안내] 그래픽카드 판이 아직 설치되지 않았습니다. 설치_GPU.bat 를 먼저 실행하세요.
pause
exit /b 1
