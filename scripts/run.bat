@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Launch failed. Check that .venv exists and dependencies are installed.
    pause
)
REM Launch desktop pet agent