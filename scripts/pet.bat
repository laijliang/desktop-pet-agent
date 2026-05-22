@echo off
start "" /MIN cmd /c "cd /d "%~dp0" && call .venv\Scripts\activate.bat && python main.py"
