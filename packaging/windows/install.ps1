# HandTrack installer for Windows (started by "Install HandTrack.bat").
#
# * Release download: copies the ready-made program from app\HandTrack.
# * Source code download: fetches uv, which installs a private Python 3.12 and the
#   libraries into the program folder (nothing is installed system-wide).
# Then: Start menu (+ optional desktop) shortcut, "Settings > Apps" entry with an
# uninstaller, and the "HandTrack Camera" virtual camera driver (one UAC prompt).
param(
    [switch]$Yes,
    [switch]$NoLaunch,
    [switch]$NoDriver,
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\HandTrack"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$here = $PSScriptRoot
$isRelease = Test-Path (Join-Path $here "HandTrack\HandTrack.exe")
$root = if ($isRelease) { (Resolve-Path (Join-Path $here "..")).Path } else { (Resolve-Path (Join-Path $here "..\..")).Path }
$log = Join-Path $env:TEMP "handtrack-install.log"
try { Start-Transcript -Path $log -Force | Out-Null } catch { }

$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Desktop = [Environment]::GetFolderPath("Desktop")
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HandTrack"
$CameraName = "HandTrack Camera"

function Step([string]$text) { Write-Host ""; Write-Host ">> $text" -ForegroundColor Red }
function Ask([string]$q) {
    if ($Yes) { return $true }
    $a = Read-Host "$q [Y/n]"
    return (-not $a) -or ($a -match '^[YyДд]')
}
function Fail([string]$text) {
    Write-Host ""
    Write-Host "ОШИБКА УСТАНОВКИ / INSTALL FAILED: $text" -ForegroundColor Red
    Write-Host "Журнал / log: $log"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

Write-Host "==================================================" -ForegroundColor DarkMagenta
Write-Host "   H A N D T R A C K   —   установка / installer" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor DarkMagenta

# ------------------------------------------------------------ 1. close a running copy
Get-Process HandTrack, pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 400

# Replace the previous version. The camera driver DLL stays locked while a call
# app (Discord, Telegram, Zoom...) has the camera open.
if (Test-Path $InstallDir) {
    try {
        Get-ChildItem $InstallDir -Force | Where-Object { $_.Name -ne "runtime" } | Remove-Item -Recurse -Force
    } catch {
        Fail "закройте Discord / Telegram / Zoom / браузер и запустите установку снова (файл камеры занят) / close your call apps and run again"
    }
}
New-Item -ItemType Directory -Force $InstallDir | Out-Null

# ------------------------------------------------------------ 2. the program
if ($isRelease) {
    Step "Копирую программу / Copying the program"
    Remove-Item (Join-Path $InstallDir "runtime") -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $here "HandTrack\*") $InstallDir -Recurse -Force
    $target = Join-Path $InstallDir "HandTrack.exe"
    $arguments = ""
    $icon = "$target,0"
    $driverDir = Join-Path $InstallDir "_internal\driver"
    # Windowed exe: PowerShell only waits for it through Start-Process -Wait.
    $selfTest = { $p = Start-Process $target -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden; $global:LASTEXITCODE = $p.ExitCode }
    $versionFile = Join-Path $here "VERSION"
} else {
    Step "Скачиваю uv (установщик Python) / Getting uv"
    $uvZip = Join-Path $env:TEMP "uv-handtrack.zip"
    $uvDir = Join-Path $env:TEMP "uv-handtrack"
    try {
        Invoke-WebRequest -UseBasicParsing "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $uvZip
        Remove-Item $uvDir -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive $uvZip $uvDir -Force
    } catch { Fail "не удалось скачать uv / could not download uv: $_" }
    $uv = Join-Path $uvDir "uv.exe"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $InstallDir "runtime\python"
    $venv = Join-Path $InstallDir "runtime\venv"

    Step "Ставлю Python 3.12 и библиотеки (первый раз ~2-5 минут) / Installing Python 3.12 and libraries"
    & $uv venv --allow-existing --python 3.12 $venv
    if ($LASTEXITCODE -ne 0) { Fail "uv venv" }
    & $uv pip install --python (Join-Path $venv "Scripts\python.exe") -r (Join-Path $root "packaging\requirements.txt")
    if ($LASTEXITCODE -ne 0) { Fail "pip install" }

    Step "Копирую программу / Copying the program"
    Copy-Item (Join-Path $root "src") (Join-Path $InstallDir "app") -Recurse -Force
    Step "Скачиваю модели и драйвер камеры / Downloading models and the camera driver"
    $env:PYTHONPATH = Join-Path $InstallDir "app"
    & (Join-Path $venv "Scripts\python.exe") (Join-Path $root "packaging\fetch_deps.py") $InstallDir
    if ($LASTEXITCODE -ne 0) { Fail "fetch_deps" }
    $target = Join-Path $venv "Scripts\pythonw.exe"
    $arguments = "-m handtrack"
    $icon = Join-Path $InstallDir "app\handtrack\assets\icon.ico"
    $driverDir = Join-Path $InstallDir "driver"
    $py = Join-Path $venv "Scripts\python.exe"
    $selfTest = { Push-Location (Join-Path $InstallDir "app"); try { & $py -m handtrack --self-test } finally { Pop-Location } }
    $versionFile = $null
}
Copy-Item (Join-Path $here "uninstall.ps1") (Join-Path $InstallDir "uninstall.ps1") -Force
Get-ChildItem $InstallDir -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

Step "Проверка программы / Self-test"
& $selfTest
if ($LASTEXITCODE -ne 0) { Fail "self-test" }

# ------------------------------------------------------------ 3. virtual camera driver
if ($NoDriver) { Write-Host "(драйвер пропущен / driver skipped)" } else {
Step "Драйвер виртуальной камеры «$CameraName» (подтвердите запрос Windows) / Camera driver (confirm the Windows prompt)"
$dll64 = Join-Path $driverDir "UnityCaptureFilter64.dll"
$dll32 = Join-Path $driverDir "UnityCaptureFilter32.dll"
$cmd = "`"$env:SystemRoot\System32\regsvr32.exe`" /s `"/i:UnityCaptureName=$CameraName`" `"$dll64`""
if (Test-Path $dll32) { $cmd += " && `"$env:SystemRoot\SysWOW64\regsvr32.exe`" /s `"/i:UnityCaptureName=$CameraName`" `"$dll32`"" }
try {
    $p = Start-Process cmd.exe -ArgumentList "/c `"$cmd`"" -Verb RunAs -Wait -PassThru -WindowStyle Hidden
    if ($p.ExitCode -eq 0) { Write-Host "Камера «$CameraName» установлена / installed." -ForegroundColor Green }
    else { Write-Host "regsvr32: код $($p.ExitCode). Позже: HandTrack > Настройки > Установить драйвер." -ForegroundColor Yellow }
} catch {
    Write-Host "Запрос прав отклонён — камеру можно поставить позже: HandTrack > Настройки > Установить драйвер." -ForegroundColor Yellow
}
}

# ------------------------------------------------------------ 4. shortcuts + Apps entry
Step "Добавляю в меню «Пуск» / Adding to the Start menu"
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut([string]$path) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $target; $s.Arguments = $arguments
    $s.WorkingDirectory = if ($isRelease) { $InstallDir } else { Join-Path $InstallDir "app" }
    $s.IconLocation = $icon; $s.Description = "HandTrack — gestures, gaze, virtual camera"
    $s.Save()
}
New-Shortcut (Join-Path $StartMenu "HandTrack.lnk")
$un = $shell.CreateShortcut((Join-Path $StartMenu "Uninstall HandTrack.lnk"))
$un.TargetPath = "powershell.exe"
$un.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'uninstall.ps1')`""
$un.IconLocation = "$env:SystemRoot\System32\shell32.dll,31"
$un.Save()
if (Ask "Ярлык на рабочем столе? / Desktop shortcut?") { New-Shortcut (Join-Path $Desktop "HandTrack.lnk") }

$version = "7"
if ($versionFile -and (Test-Path $versionFile)) { $version = (Get-Content $versionFile -Raw).Trim() }
else {
    $m = Select-String -Path (Join-Path $root "src\handtrack\__init__.py") -Pattern '__version__ = "(.+)"' -ErrorAction SilentlyContinue
    if ($m) { $version = $m.Matches[0].Groups[1].Value }
}
New-Item -Force $UninstallKey | Out-Null
$props = @{
    DisplayName = "HandTrack"; DisplayVersion = "$version"; Publisher = "HandTrack"
    DisplayIcon = $icon.Split(",")[0]; InstallLocation = $InstallDir
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'uninstall.ps1')`""
}
foreach ($k in $props.Keys) { New-ItemProperty -Path $UninstallKey -Name $k -Value $props[$k] -PropertyType String -Force | Out-Null }
foreach ($k in "NoModify", "NoRepair") { New-ItemProperty -Path $UninstallKey -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
$kb = [int]((Get-ChildItem $InstallDir -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
New-ItemProperty -Path $UninstallKey -Name EstimatedSize -Value $kb -PropertyType DWord -Force | Out-Null

# ------------------------------------------------------------ 5. start
if (-not $NoLaunch) {
    Step "Запускаю HandTrack / Starting HandTrack"
    $wd = if ($isRelease) { $InstallDir } else { Join-Path $InstallDir "app" }
    if ($arguments) { Start-Process $target -ArgumentList $arguments -WorkingDirectory $wd }
    else { Start-Process $target -WorkingDirectory $wd }
}
Write-Host ""
Write-Host "ГОТОВО. HandTrack в меню «Пуск». Камера для звонков: «$CameraName»." -ForegroundColor Green
Write-Host "DONE. Find HandTrack in the Start menu. Camera for calls: '$CameraName'." -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch { }
exit 0
