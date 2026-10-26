@echo off
rem One-time setup: a private Python environment with what Maple Chat needs.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if errorlevel 1 (
  echo.
  echo Python 3.11+ is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  pause & exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
echo.
echo Done. Double-click start.bat with the game running.
pause
