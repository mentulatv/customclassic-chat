@echo off
rem Builds dist\CustomClassicChat\ (the .exe version, nothing to install), dist\CustomClassicChat-win64.zip to share,
rem and dist\CustomClassicChat-setup.exe, the Windows installer (needs Inno Setup 6: winget install JRSoftware.InnoSetup).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call "%~dp0setup.bat"
.venv\Scripts\python.exe -m pip install -q pyinstaller || (pause & exit /b 1)
rem OpenCV without its window toolkit: the text recognition only needs its image functions
.venv\Scripts\python.exe -m pip uninstall -q -y opencv-python opencv-python-headless >nul 2>nul
.venv\Scripts\python.exe -m pip install -q opencv-python-headless || (pause & exit /b 1)
if exist dist\CustomClassicChat rmdir /s /q dist\CustomClassicChat
if not exist build mkdir build
rem the watch list's item names as they are now, for a first start without internet (kept as it was when offline)
curl -sf https://customclassic.chat/api/names -o build\names.json && move /y build\names.json data\names.json >nul
.venv\Scripts\python.exe -c "import customclassic_chat, pathlib; customclassic_chat.save_icon(pathlib.Path('build/customclassic_chat.ico'))" || (pause & exit /b 1)
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name CustomClassicChat ^
  --icon build\customclassic_chat.ico --add-data "data;data" ^
  --collect-all rapidocr --collect-all windows_capture --collect-binaries onnxruntime ^
  --hidden-import pystray._win32 customclassic_chat.py || (pause & exit /b 1)
set OUT=dist\CustomClassicChat
rem OpenCV's video player isn't used
del /q "%OUT%\_internal\cv2\opencv_videoio_ffmpeg*.dll" 2>nul
copy /y README.md "%OUT%\" >nul
copy /y LICENSE "%OUT%\LICENSE.txt" >nul
copy /y config.example.toml "%OUT%\" >nul
(echo @echo off& echo start "" "%%~dp0CustomClassicChat.exe" --demo) > "%OUT%\CustomClassic Chat demo.bat"
rem no chat.json or history in the zip: they are made on first run, so unzipping an update never overwrites them
powershell -NoProfile -Command "Compress-Archive -Force -Path %OUT% -DestinationPath dist\CustomClassicChat-win64.zip"
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (echo. & echo Built dist\CustomClassicChat-win64.zip ^(no installer: Inno Setup 6 isn't installed^) & exit /b 0)
.venv\Scripts\python.exe installer\wizard_images.py build\installer || (pause & exit /b 1)
for /f %%v in ('.venv\Scripts\python.exe -c "import updates; print(updates.VERSION)"') do set VERSION=%%v
"%ISCC%" /Q /DAppVersion=%VERSION% installer\CustomClassicChat.iss || (pause & exit /b 1)
echo.
echo Built dist\CustomClassicChat-win64.zip and dist\CustomClassicChat-setup.exe (%VERSION%)
