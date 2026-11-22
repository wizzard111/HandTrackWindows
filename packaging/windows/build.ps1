# Builds the Windows release: dist\HandTrack-windows.zip
#   root:  Install HandTrack.bat, Uninstall HandTrack.bat, HOW-TO-INSTALL.txt
#   app\:  the program (HandTrack\HandTrack.exe) and the install/uninstall scripts
# Usage: powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 [-Python python]
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "src"

$Version = (& $Python -c "import handtrack; print(handtrack.__version__)").Trim()
Write-Host "HandTrack $Version" -ForegroundColor Red

& $Python packaging\fetch_deps.py
if ($LASTEXITCODE -ne 0) { throw "fetch_deps failed" }

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

& $Python -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build\pyinstaller packaging\windows\handtrack.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
# Windowed exe: PowerShell only waits for it through Start-Process -Wait.
$st = Start-Process dist\HandTrack\HandTrack.exe -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden
if ($st.ExitCode -ne 0) { throw "self-test of the built program failed (exit $($st.ExitCode))" }
Write-Host "self-test OK"

$pkg = "dist\package\HandTrack"
Remove-Item -Recurse -Force dist\package -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$pkg\app" | Out-Null
Copy-Item "Install HandTrack.bat", "Uninstall HandTrack.bat", "HOW-TO-INSTALL.txt" $pkg
Copy-Item -Recurse dist\HandTrack "$pkg\app\HandTrack"
Copy-Item packaging\windows\install.ps1, packaging\windows\uninstall.ps1, LICENSE "$pkg\app"
Copy-Item docs\THIRD_PARTY_NOTICES.md "$pkg\app"
Set-Content -Encoding ascii "$pkg\app\VERSION" $Version
$zip = "dist\HandTrack-windows.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $pkg -DestinationPath $zip -CompressionLevel Optimal
Write-Host ("Release: $zip  ({0:N0} MB)" -f ((Get-Item $zip).Length / 1MB)) -ForegroundColor Green
