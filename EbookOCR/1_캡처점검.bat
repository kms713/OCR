@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem LD플레이어에서 전자책을 연 상태로 실행 → test\test_screen.png 확인
.venv\Scripts\python.exe ebook_capture.py --test -o test %*
pause
