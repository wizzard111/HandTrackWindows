@echo off
rem HandTrack uninstaller: removes the app, its shortcuts and the camera driver.
setlocal
title HandTrack uninstaller
chcp 65001 >nul
set "PS1=%LOCALAPPDATA%\Programs\HandTrack\uninstall.ps1"
if not exist "%PS1%" set "PS1=%~dp0app\uninstall.ps1"
if not exist "%PS1%" set "PS1=%~dp0packaging\windows\uninstall.ps1"
rem The installed copy deletes its own folder, so run a temporary copy of it.
copy /y "%PS1%" "%TEMP%\handtrack-uninstall.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\handtrack-uninstall.ps1" %*
del "%TEMP%\handtrack-uninstall.ps1" >nul 2>&1
