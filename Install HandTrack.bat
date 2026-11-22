@echo off
rem HandTrack installer: double-click. A window shows every step.
rem Windows asks once for permission to register the "HandTrack Camera" driver.
setlocal
title HandTrack installer
chcp 65001 >nul
set "PS1=%~dp0app\install.ps1"
if not exist "%PS1%" set "PS1=%~dp0packaging\windows\install.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
echo.
pause
