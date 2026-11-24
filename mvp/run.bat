@echo off
REM EchoMe MVP - Windows launcher
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000
pause
