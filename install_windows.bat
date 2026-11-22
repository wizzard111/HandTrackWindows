@echo off
setlocal
cd /d "%~dp0"
py -m pip install --upgrade pip
if errorlevel 1 goto :error
py -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo.
echo Installation completed successfully.
pause
exit /b 0

:error
echo.
echo Installation failed. Check the messages above.
pause
exit /b 1
