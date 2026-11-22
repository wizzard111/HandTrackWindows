@echo off
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
    start "" .venv\Scripts\pythonw.exe -m handtrack
) else (
    py -3 -m handtrack
    if errorlevel 1 pause
)
