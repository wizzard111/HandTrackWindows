# HandTrack installer for Windows (started by "Install HandTrack.bat").
#
# * Release download: copies the ready-made program from app\HandTrack.
# * Source code download: fetches uv, which installs a private Python 3.12 and the
#   libraries into the program folder (nothing is installed system-wide).
# Then: Start menu (+ optional desktop) shortcut, "Settings > Apps" entry with an
# uninstaller, and the "HandTrack Camera" virtual camera driver (one UAC prompt).
#
# Running it again only fills in what is missing or changed: unchanged files,
# the Python runtime, libraries, models, the registered driver and existing
# shortcuts are left alone.
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
$RunOnce = "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce"
$CameraName = "HandTrack Camera"

function Step([string]$text) { Write-Host ""; Write-Host ">> $text" -ForegroundColor Red }
function Have([string]$text) { Write-Host "   present: $text" -ForegroundColor DarkGray }
function Did([string]$text) { Write-Host "   + $text" -ForegroundColor White }
# Runs a program with its output hidden and returns its exit code.
function Invoke-Quiet([string]$exe, [string[]]$argList) {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"   # stderr must not throw
    try { & $exe @argList *> $null } finally { $ErrorActionPreference = $old }
    return $LASTEXITCODE
}
function Ask([string]$q) {
    if ($Yes) { return $true }
    $a = Read-Host "$q [Y/n]"
    return (-not $a) -or ($a -match '^[Yy]')
}
function Fail([string]$text) {
    Write-Host ""
    Write-Host "INSTALL FAILED: $text" -ForegroundColor Red
    Write-Host "Log: $log"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

# Any app that lists cameras (browsers, Discord, Telegram, Electron apps...)
# loads the camera driver DLL and keeps it locked. A loaded DLL cannot be
# deleted but can be renamed, so a locked file is moved aside as *.old-* and
# removed by a later install once it is free.
function Remove-OneFile($file) {
    try { Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop }
    catch {
        if ($file.Name -like "*.old-*") { return }          # still locked from an earlier update
        try { Rename-Item -LiteralPath $file.FullName "$($file.Name).old-$(Get-Random)" -ErrorAction Stop }
        catch { Fail "cannot replace a file: $($file.FullName)" }
    }
}
function Remove-EmptyDirs([string]$path) {
    Get-ChildItem -LiteralPath $path -Recurse -Force -Directory -ErrorAction SilentlyContinue |
        Sort-Object { $_.FullName.Length } -Descending |
        Where-Object { -not (Get-ChildItem -LiteralPath $_.FullName -Force | Select-Object -First 1) } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }
}
function Remove-Tree([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    if (-not (Get-Item -LiteralPath $path -Force).PSIsContainer) { Remove-OneFile (Get-Item -LiteralPath $path -Force); return }
    Get-ChildItem -LiteralPath $path -Recurse -Force -File | ForEach-Object { Remove-OneFile $_ }
    Remove-EmptyDirs $path
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}

# Mirror $src into $dst: copy only new or changed files (size + modified time),
# delete files that are no longer part of the program. Top-level names matching
# $keepTop are left alone. Returns the number of files copied and deleted.
function Sync-Tree([string]$src, [string]$dst, [string[]]$keepTop = @()) {
    $src = (Resolve-Path -LiteralPath $src).Path.TrimEnd('\')
    New-Item -ItemType Directory -Force $dst | Out-Null
    $dst = (Resolve-Path -LiteralPath $dst).Path.TrimEnd('\')
    $have = @{}
    Get-ChildItem -LiteralPath $dst -Recurse -Force -File -ErrorAction SilentlyContinue |
        ForEach-Object { $have[$_.FullName.Substring($dst.Length + 1).ToLowerInvariant()] = $_ }
    $copied = 0; $removed = 0
    foreach ($f in Get-ChildItem -LiteralPath $src -Recurse -Force -File) {
        $rel = $f.FullName.Substring($src.Length + 1)
        if ($rel -match '(^|\\)__pycache__\\') { continue }
        $key = $rel.ToLowerInvariant()
        $old = $have[$key]
        $have.Remove($key)
        if ($old -and $old.Length -eq $f.Length -and $old.LastWriteTimeUtc -eq $f.LastWriteTimeUtc) { continue }
        if ($old) { Remove-OneFile $old }
        $target = Join-Path $dst $rel
        $parent = Split-Path $target
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force $parent | Out-Null }
        Copy-Item -LiteralPath $f.FullName $target -Force    # keeps the modified time
        $copied++
    }
    foreach ($old in $have.Values) {
        $rel = $old.FullName.Substring($dst.Length + 1)
        $top = $rel.Split('\')[0]
        if ($keepTop | Where-Object { $top -like $_ }) { continue }
        # Bytecode caches stay next to sources that still exist.
        if ($rel -match '^(.*)\\__pycache__\\[^\\]+$' -and (Test-Path -LiteralPath (Join-Path $src $Matches[1]))) { continue }
        if ($old.Name -notlike "*.old-*") { $removed++ }
        Remove-OneFile $old
    }
    Remove-EmptyDirs $dst
    return @($copied, $removed)
}
function Show-Sync([string]$what, $result) {
    if ($result[0] -or $result[1]) { Did "$what — files updated: $($result[0]), removed: $($result[1])" }
    else { Have "$what — up to date" }
}

Write-Host "==================================================" -ForegroundColor DarkMagenta
Write-Host "   H A N D T R A C K   —   installer" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor DarkMagenta

# ------------------------------------------------------------ 1. close a running copy
Get-Process HandTrack, pythonw, python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 400

# A previous uninstall may have scheduled a folder cleanup for the next sign-in;
# it would wipe this install, so cancel it.
Remove-ItemProperty -Path $RunOnce -Name "HandTrackCleanup" -ErrorAction SilentlyContinue

Step "Checking what is already installed"
if (Test-Path $InstallDir) {
    $prev = (Get-ItemProperty $UninstallKey -ErrorAction SilentlyContinue).DisplayVersion
    Have "$InstallDir$(if ($prev) { "  (v$prev)" })"
    # Files set aside by an earlier update, free by now.
    Get-ChildItem -LiteralPath $InstallDir -Recurse -Force -File -Filter "*.old-*" -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-OneFile $_ }
} else {
    Did "fresh install: $InstallDir"
}
New-Item -ItemType Directory -Force $InstallDir | Out-Null

# ------------------------------------------------------------ 2. the program
if ($isRelease) {
    Step "The program"
    # Mirrors the whole folder; a source-code install (app, runtime...) is replaced.
    Show-Sync "HandTrack.exe" (Sync-Tree (Join-Path $here "HandTrack") $InstallDir @("uninstall.ps1", "HandTrack-*.ico"))
    $target = Join-Path $InstallDir "HandTrack.exe"
    $arguments = ""
    $iconSource = Join-Path $InstallDir "_internal\handtrack\assets\icon.ico"
    $driverDir = Join-Path $InstallDir "_internal\driver"
    # Windowed exe: PowerShell only waits for it through Start-Process -Wait.
    $selfTest = { $p = Start-Process $target -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden; $global:LASTEXITCODE = $p.ExitCode }
    $versionFile = Join-Path $here "VERSION"
} else {
    # A release install leaves HandTrack.exe and _internal behind.
    foreach ($n in "HandTrack.exe", "_internal") { Remove-Tree (Join-Path $InstallDir $n) }

    Step "Python 3.12 and libraries"
    $runtime = Join-Path $InstallDir "runtime"
    $uv = Join-Path $runtime "uv.exe"
    if (Test-Path $uv) { Have "uv" } else {
        $uvZip = Join-Path $env:TEMP "uv-handtrack.zip"
        $uvDir = Join-Path $env:TEMP "uv-handtrack"
        try {
            Invoke-WebRequest -UseBasicParsing "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $uvZip
            Remove-Item $uvDir -Recurse -Force -ErrorAction SilentlyContinue
            Expand-Archive $uvZip $uvDir -Force
            New-Item -ItemType Directory -Force $runtime | Out-Null
            Copy-Item (Join-Path $uvDir "uv.exe") $uv -Force
            Remove-Item $uvZip, $uvDir -Recurse -Force -ErrorAction SilentlyContinue
        } catch { Fail "could not download uv: $_" }
        Did "uv"
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtime "python"
    $venv = Join-Path $runtime "venv"
    $py = Join-Path $venv "Scripts\python.exe"
    $pyOk = $false
    if (Test-Path $py) {
        $pyOk = (Invoke-Quiet $py @("-c", "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)")) -eq 0
    }
    if ($pyOk) { Have "Python 3.12" } else {
        Write-Host "   Installing Python 3.12 (first time ~1 minute)"
        & $uv venv --clear --python 3.12 $venv
        if ($LASTEXITCODE -ne 0) { Fail "uv venv" }
        Did "Python 3.12"
    }
    # Offline first: succeeds without the network when every library is already
    # installed (or cached); only otherwise download what is missing.
    $req = Join-Path $root "packaging\requirements.txt"
    if ((Invoke-Quiet $uv @("pip", "install", "--offline", "--quiet", "--python", $py, "-r", $req)) -eq 0) { Have "libraries" } else {
        Write-Host "   Downloading libraries (first time ~2-5 minutes)"
        & $uv pip install --python $py -r $req
        if ($LASTEXITCODE -ne 0) { Fail "pip install" }
        Did "libraries"
    }

    Step "The program"
    Show-Sync "app" (Sync-Tree (Join-Path $root "src") (Join-Path $InstallDir "app"))

    Step "Models and the camera driver"
    # Downloads only missing files; the driver is checked against its SHA-256.
    $env:PYTHONPATH = Join-Path $InstallDir "app"
    & $py (Join-Path $root "packaging\fetch_deps.py") $InstallDir
    if ($LASTEXITCODE -ne 0) { Fail "fetch_deps" }
    $target = Join-Path $venv "Scripts\pythonw.exe"
    $arguments = "-m handtrack"
    $iconSource = Join-Path $InstallDir "app\handtrack\assets\icon.ico"
    $driverDir = Join-Path $InstallDir "driver"
    # MediaPipe logs a lot to stderr; show it only when the test fails.
    $selfTest = {
        Push-Location (Join-Path $InstallDir "app")
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        try { $out = & $py -m handtrack --self-test 2>&1 }
        finally { $ErrorActionPreference = $old; Pop-Location }
        if ($LASTEXITCODE -ne 0) { $out | ForEach-Object { Write-Host "$_" } }
    }
    $versionFile = $null
}
$uninstallPs1 = Join-Path $InstallDir "uninstall.ps1"
Copy-Item (Join-Path $here "uninstall.ps1") $uninstallPs1 -Force
Get-ChildItem $InstallDir -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

# Shortcut icon under a name that changes with its content: Explorer caches
# icons by path, so a redesigned icon would otherwise keep showing the old one.
$hash = (Get-FileHash -LiteralPath $iconSource -Algorithm SHA256).Hash.Substring(0, 8).ToLowerInvariant()
$icon = Join-Path $InstallDir "HandTrack-$hash.ico"
if (-not (Test-Path $icon)) { Copy-Item -LiteralPath $iconSource $icon -Force }
Get-ChildItem -LiteralPath $InstallDir -Filter "HandTrack-*.ico" | Where-Object { $_.FullName -ne $icon } |
    ForEach-Object { Remove-OneFile $_ }

Step "Self-test"
& $selfTest
if ($LASTEXITCODE -ne 0) { Fail "self-test" }
Did "OK"

# ------------------------------------------------------------ 3. virtual camera driver
$dll64 = Join-Path $driverDir "UnityCaptureFilter64.dll"
$dll32 = Join-Path $driverDir "UnityCaptureFilter32.dll"
# Registered = the COM entry carries our camera name and points at our DLL.
function Test-Filter([string]$clsidKey, [string]$dll) {
    $k = Get-Item -LiteralPath $clsidKey -ErrorAction SilentlyContinue
    $s = Get-Item -LiteralPath "$clsidKey\InprocServer32" -ErrorAction SilentlyContinue
    return $k -and $s -and ($k.GetValue("") -eq $CameraName) -and ($s.GetValue("") -eq $dll) -and (Test-Path $dll)
}
$registered = (Test-Filter "HKLM:\SOFTWARE\Classes\CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70010}" $dll64) -and
    (-not (Test-Path $dll32) -or (Test-Filter "HKLM:\SOFTWARE\WOW6432Node\Classes\CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70020}" $dll32))
Step "Virtual camera driver"
if ($NoDriver) { Write-Host "   (skipped)" }
elseif ($registered) { Have "'$CameraName'" }
else {
    Write-Host "   Confirm the Windows prompt"
    $cmd = "`"$env:SystemRoot\System32\regsvr32.exe`" /s `"/i:UnityCaptureName=$CameraName`" `"$dll64`""
    if (Test-Path $dll32) { $cmd += " && `"$env:SystemRoot\SysWOW64\regsvr32.exe`" /s `"/i:UnityCaptureName=$CameraName`" `"$dll32`"" }
    try {
        $p = Start-Process cmd.exe -ArgumentList "/c `"$cmd`"" -Verb RunAs -Wait -PassThru -WindowStyle Hidden
        if ($p.ExitCode -eq 0) { Did "'$CameraName'" }
        else { Write-Host "regsvr32 exit code $($p.ExitCode). Install it later: HandTrack > Settings > Install driver." -ForegroundColor Yellow }
    } catch {
        Write-Host "Permission declined. Install the camera later: HandTrack > Settings > Install driver." -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------ 4. shortcuts + Apps entry
Step "Shortcuts and the Apps entry"
$shell = New-Object -ComObject WScript.Shell
$workDir = if ($isRelease) { $InstallDir } else { Join-Path $InstallDir "app" }
# Writes the shortcut only when it is missing or points somewhere else.
function Set-Shortcut([string]$path, [string]$tgt, [string]$argLine, [string]$wd, [string]$ico, [string]$desc) {
    $exists = Test-Path $path
    $s = $shell.CreateShortcut($path)
    if ($exists -and $s.TargetPath -eq $tgt -and $s.Arguments -eq $argLine -and $s.WorkingDirectory -eq $wd -and $s.IconLocation -eq $ico) {
        Have (Split-Path $path -Leaf); return
    }
    $s.TargetPath = $tgt; $s.Arguments = $argLine; $s.WorkingDirectory = $wd
    $s.IconLocation = $ico; $s.Description = $desc
    $s.Save()
    Did "$(Split-Path $path -Leaf)$(if ($exists) { ' (updated)' })"
    $script:iconsChanged = $true
}
$iconsChanged = $false
$appArgs = @($target, $arguments, $workDir, "$icon,0", "HandTrack — gestures, gaze, virtual camera")
Set-Shortcut (Join-Path $StartMenu "HandTrack.lnk") @appArgs
Set-Shortcut (Join-Path $StartMenu "Uninstall HandTrack.lnk") "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    "-NoProfile -ExecutionPolicy Bypass -File `"$uninstallPs1`"" "" "$env:SystemRoot\System32\shell32.dll,31" "Uninstall HandTrack"
$desktopLnk = Join-Path $Desktop "HandTrack.lnk"
if (Test-Path $desktopLnk) { Set-Shortcut $desktopLnk @appArgs }
elseif (Ask "Desktop shortcut?") { Set-Shortcut $desktopLnk @appArgs }
# Ask Explorer to redraw shortcut icons now rather than after a restart.
if ($iconsChanged) {
    try { Start-Process "$env:SystemRoot\System32\ie4uinit.exe" -ArgumentList "-show" -Wait -WindowStyle Hidden } catch { }
}

$version = "8"
if ($versionFile -and (Test-Path $versionFile)) { $version = (Get-Content $versionFile -Raw).Trim() }
else {
    $m = Select-String -Path (Join-Path $root "src\handtrack\__init__.py") -Pattern '__version__ = "(.+)"' -ErrorAction SilentlyContinue
    if ($m) { $version = $m.Matches[0].Groups[1].Value }
}
New-Item -Force $UninstallKey | Out-Null
$props = @{
    DisplayName = "HandTrack"; DisplayVersion = "$version"; Publisher = "HandTrack"
    DisplayIcon = $icon; InstallLocation = $InstallDir
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninstallPs1`""
}
foreach ($k in $props.Keys) { New-ItemProperty -Path $UninstallKey -Name $k -Value $props[$k] -PropertyType String -Force | Out-Null }
foreach ($k in "NoModify", "NoRepair") { New-ItemProperty -Path $UninstallKey -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
$kb = [int]((Get-ChildItem $InstallDir -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
New-ItemProperty -Path $UninstallKey -Name EstimatedSize -Value $kb -PropertyType DWord -Force | Out-Null
Have "Settings > Apps: HandTrack $version"

# ------------------------------------------------------------ 5. start
if (-not $NoLaunch) {
    Step "Starting HandTrack"
    if ($arguments) { Start-Process $target -ArgumentList $arguments -WorkingDirectory $workDir }
    else { Start-Process $target -WorkingDirectory $workDir }
}
Write-Host ""
Write-Host "DONE. Find HandTrack in the Start menu. Camera for calls: '$CameraName'." -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch { }
exit 0
