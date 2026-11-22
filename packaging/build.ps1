# Builds dist\HandTrack-Setup-<version>.exe
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# Requires: Python with the project deps + pyinstaller, and Inno Setup 6.
param(
    [string]$Python = "python",
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Version = (& $Python -c "import handtrack; print(handtrack.__version__)").Trim()
Write-Host "HandTrack $Version" -ForegroundColor Cyan

& $Python packaging\fetch_deps.py
if ($LASTEXITCODE -ne 0) { throw "fetch_deps failed" }

# Windows version resource for HandTrack.exe
$parts = ($Version.Split(".") + @("0", "0", "0"))[0..3] -join ", "
New-Item -ItemType Directory -Force build | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'HandTrack'),
    StringStruct('ProductName', 'HandTrack'),
    StringStruct('FileVersion', '$Version'),
    StringStruct('ProductVersion', '$Version'),
    StringStruct('LegalCopyright', 'MIT License')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding utf8 build\version_info.txt

& $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller packaging\handtrack.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

if ($SkipInstaller) { return }

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }

& $iscc "/DAppVersion=$Version" packaging\HandTrack.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
Write-Host "Installer: dist\HandTrack-Setup-$Version.exe" -ForegroundColor Green
