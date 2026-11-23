@echo off
rem HandTrack updater: double-click. Installs the newest version from GitHub; your settings are kept.
rem Options (from a command prompt): -Check, -Force, -Yes, -Package <zip>
setlocal
title HandTrack updater
chcp 65001 >nul
set "PS1=%~dp0app\update.ps1"
if not exist "%PS1%" set "PS1=%~dp0packaging\windows\update.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set RC=%ERRORLEVEL%
rem Double-clicked (no options): keep the window open to read the result.
if "%~1"=="" (echo. & pause)
exit /b %RC%
