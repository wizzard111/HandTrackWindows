# HandTrack uninstaller for Windows.
# Removes the program, its shortcuts, the "Settings > Apps" entry and the
# "HandTrack Camera" driver registration (one UAC prompt). Asks whether to
# also delete the settings, calibration and gesture images.
# Non-interactive: -KeepSettings or -All.
param(
    [switch]$KeepSettings,
    [switch]$All,
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\HandTrack"
)
$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Desktop = [Environment]::GetFolderPath("Desktop")
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HandTrack"
$DataDir = Join-Path $env:APPDATA "HandTrack"

Write-Host "==================================================" -ForegroundColor DarkMagenta
Write-Host "   H A N D T R A C K   —   удаление / uninstall" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor DarkMagenta

if ($All) { $removeData = $true }
elseif ($KeepSettings) { $removeData = $false }
else {
    Write-Host "Удалить также настройки, калибровку и картинки жестов?"
    Write-Host "Also delete settings, calibration and gesture images?"
    Write-Host "  ($DataDir)"
    $a = Read-Host "[y/N]"
    $removeData = $a -match '^[YyДд]'
}

Write-Host ">> Закрываю HandTrack / Closing HandTrack" -ForegroundColor Red
Get-Process HandTrack, pythonw, python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# Only unregister when the registered filter really is HandTrack's copy, so a
# Unity Capture installed by another program is left alone (and no UAC prompt
# appears when nothing is registered).
function Get-RegisteredFilter([string]$view) {
    try {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey("ClassesRoot", $view)
        $key = $base.OpenSubKey("CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70010}\InprocServer32")
        if (-not $key) { $key = $base.OpenSubKey("CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70020}\InprocServer32") }
        if ($key) { return [string]$key.GetValue("") }
    } catch { }
    return ""
}
$ours = $false
foreach ($view in "Registry64", "Registry32") {
    $path = Get-RegisteredFilter $view
    if ($path -and $path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) { $ours = $true }
}
$dlls = @()
if ($ours) { $dlls = @(Get-ChildItem $InstallDir -Recurse -Filter "UnityCaptureFilter*.dll" -ErrorAction SilentlyContinue) }
if ($dlls) {
    Write-Host ">> Удаляю драйвер камеры (подтвердите запрос Windows) / Removing the camera driver" -ForegroundColor Red
    $cmd = ($dlls | ForEach-Object {
        $reg = if ($_.Name -like "*32.dll") { "$env:SystemRoot\SysWOW64\regsvr32.exe" } else { "$env:SystemRoot\System32\regsvr32.exe" }
        "`"$reg`" /u /s `"$($_.FullName)`""
    }) -join " & "
    try { Start-Process cmd.exe -ArgumentList "/c `"$cmd`"" -Verb RunAs -Wait -WindowStyle Hidden }
    catch { Write-Host "Отменено — драйвер останется зарегистрированным / cancelled" -ForegroundColor Yellow }
}

Write-Host ">> Удаляю ярлыки и запись в «Приложениях» / Removing shortcuts" -ForegroundColor Red
foreach ($lnk in (Join-Path $StartMenu "HandTrack.lnk"), (Join-Path $StartMenu "Uninstall HandTrack.lnk"),
                 (Join-Path $Desktop "HandTrack.lnk")) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
}
if (Test-Path $UninstallKey) { Remove-Item $UninstallKey -Recurse -Force }

Write-Host ">> Удаляю программу / Removing the program" -ForegroundColor Red
if (Test-Path $InstallDir) {
    $self = $PSCommandPath
    if ($self -and $self.StartsWith((Resolve-Path $InstallDir).Path, [StringComparison]::OrdinalIgnoreCase)) {
        # This script lives in the folder being deleted: finish after it exits.
        # ("timeout" fails without a console window, so wait with ping instead.)
        Start-Process cmd.exe -ArgumentList "/c ping -n 4 127.0.0.1 >nul & rmdir /s /q `"$InstallDir`"" -WindowStyle Hidden
    } else {
        Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    # Apps that list cameras (browsers, Discord, Telegram, Electron apps) keep
    # the camera DLL loaded until they quit, so a file may stay behind. Finish
    # the job at the next sign-in; no administrator rights needed.
    $runOnce = "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce"
    if (-not (Test-Path $runOnce)) { New-Item -Path $runOnce | Out-Null }
    New-ItemProperty -Path $runOnce -Name "HandTrackCleanup" -PropertyType String -Force `
        -Value "cmd.exe /c rmdir /s /q `"$InstallDir`"" | Out-Null
    if ((-not $self -or -not $self.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) -and (Test-Path $InstallDir)) {
        Write-Host "Файл драйвера камеры ещё занят другой программой — папка дочистится при следующем входе в Windows." -ForegroundColor Yellow
        Write-Host "The camera driver file is still in use — the folder is cleaned up at your next sign-in." -ForegroundColor Yellow
    } elseif (-not (Test-Path $InstallDir)) {
        Remove-ItemProperty -Path $runOnce -Name "HandTrackCleanup" -ErrorAction SilentlyContinue
    }
}
if ($removeData -and (Test-Path $DataDir)) {
    Remove-Item $DataDir -Recurse -Force
    Write-Host "Настройки удалены / settings deleted."
} elseif (Test-Path $DataDir) {
    Write-Host "Настройки сохранены / settings kept: $DataDir"
}
Write-Host ""
Write-Host "HandTrack удалён. / HandTrack has been removed." -ForegroundColor Green
if (-not ($All -or $KeepSettings)) { Read-Host "Enter — закрыть / close" | Out-Null }
exit 0
