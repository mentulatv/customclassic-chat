@echo off
rem Maple Chat. start.bat --demo shows made-up messages without reading the game.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
start "" .venv\Scripts\pythonw.exe maple_chat.py %*
