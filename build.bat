@echo off
rem Builds dist\MapleChat\ (the .exe version, nothing to install) and dist\MapleChat-win64.zip to share.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call "%~dp0setup.bat"
.venv\Scripts\python.exe -m pip install -q pyinstaller || (pause & exit /b 1)
rem OpenCV without its window toolkit: the text recognition only needs its image functions
.venv\Scripts\python.exe -m pip uninstall -q -y opencv-python opencv-python-headless >nul 2>nul
.venv\Scripts\python.exe -m pip install -q opencv-python-headless || (pause & exit /b 1)
if exist dist\MapleChat rmdir /s /q dist\MapleChat
if not exist build mkdir build
.venv\Scripts\python.exe -c "import maple_chat, pathlib; maple_chat.save_icon(pathlib.Path('build/maple_chat.ico'))" || (pause & exit /b 1)
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name MapleChat ^
  --icon build\maple_chat.ico --add-data "data;data" ^
  --collect-all rapidocr --collect-all windows_capture --collect-binaries onnxruntime ^
  --hidden-import pystray._win32 maple_chat.py || (pause & exit /b 1)
set OUT=dist\MapleChat
rem OpenCV's video player isn't used
del /q "%OUT%\_internal\cv2\opencv_videoio_ffmpeg*.dll" 2>nul
copy /y README.md "%OUT%\" >nul
copy /y LICENSE "%OUT%\LICENSE.txt" >nul
copy /y config.example.toml "%OUT%\" >nul
(echo @echo off& echo start "" "%%~dp0MapleChat.exe" --demo) > "%OUT%\Maple Chat demo.bat"
rem no chat.json or history in the zip: they are made on first run, so unzipping an update never overwrites them
powershell -NoProfile -Command "Compress-Archive -Force -Path %OUT% -DestinationPath dist\MapleChat-win64.zip"
echo.
echo Built dist\MapleChat-win64.zip
