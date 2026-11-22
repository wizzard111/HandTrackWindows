@echo off
setlocal
cd /d "%~dp0"
rem Developer setup from source. End users: use HandTrack-Setup.exe from Releases.
py -3 -m venv .venv || goto :error
.venv\Scripts\python -m pip install --upgrade pip || goto :error
.venv\Scripts\python -m pip install -r requirements.txt || goto :error
echo.
echo Done. Start with run_windows.bat
pause
exit /b 0

:error
echo.
echo Installation failed. Check the messages above.
pause
exit /b 1
