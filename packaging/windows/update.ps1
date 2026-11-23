# HandTrack updater for Windows (started by "Update HandTrack.bat").
# 1. asks GitHub for the latest release and compares it with the installed version;
# 2. backs up the settings, calibration and gestures (%APPDATA%\HandTrack);
# 3. downloads the release, checks its SHA-256, and installs it with the release's own installer
#    (it mirrors the new program into the install folder and deletes files the new version no longer has);
# 4. makes sure every setting is still there (restores from the backup otherwise),
#    deletes the download and starts the app again if it was running.
# The "HandTrack Camera" driver is only re-registered when it was installed before (then Windows may
# ask once for permission); otherwise the update needs no administrator rights.
# Options: -Check   only report whether an update exists (exit code 2 = update available)
#          -Force   reinstall even when the installed version is the latest
#          -Yes     no questions
#          -Package <file.zip>  install a release zip that is already downloaded (no internet needed)
#          -NoLaunch            do not start the app afterwards
#          -Pause               wait for Enter at the end (the Start menu shortcut uses it)
param(
    [switch]$Check,
    [switch]$Force,
    [switch]$Yes,
    [switch]$NoLaunch,
    [switch]$Pause,
    [string]$Package = "",
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\HandTrack",
    [string]$SettingsDir = "$env:APPDATA\HandTrack",
    [string]$BackupRoot = "$env:LOCALAPPDATA\HandTrack-updater\backups",
    [string]$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HandTrack",
    [string]$Api = "https://api.github.com/repos/wizzard111/HandTrackWindows/releases/latest"
)

# ---------------------------------------------------------------- what differs between the apps
$AppName = "HandTrack"
$Asset = "HandTrack-windows.zip"
$ExeName = "HandTrack.exe"
$DesktopLnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "HandTrack.lnk"
$KeepBackups = 3
$SkipInBackup = @("*.log", "*.lock", "logs")       # logs are not settings
# Arguments for the release's install.ps1 (it asks nothing with -Yes).
function Get-InstallerArgs {
    $a = @("-Yes", "-NoLaunch", "-InstallDir", $InstallDir)
    # Only HandTrack's own registration counts (another program may use the same Unity Capture driver).
    $registered = $false
    foreach ($view in "Registry64", "Registry32") {
        try {
            $key = [Microsoft.Win32.RegistryKey]::OpenBaseKey("ClassesRoot", $view).OpenSubKey(
                "CLSID\{5C2CD55C-92AD-4999-8666-912BD3E70010}\InprocServer32")
            if ($key -and ([string]$key.GetValue("")).StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) { $registered = $true }
        } catch { }
    }
    if (-not $registered) { $a += "-NoDriver" }
    return $a
}
# A release install has HandTrack.exe; a source-code install runs app\handtrack with its own Python.
function Test-Installed {
    (Test-Path -LiteralPath (Join-Path $InstallDir $ExeName)) -or (Test-Path -LiteralPath (Join-Path $InstallDir "app\handtrack\__init__.py"))
}
function Test-Running {
    # A source-code install runs as pythonw.exe from the install folder.
    @(Get-Process HandTrack, pythonw, python -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
}
function Start-App {
    $exe = Join-Path $InstallDir $ExeName
    if (Test-Path -LiteralPath $exe) { Start-Process $exe -WorkingDirectory $InstallDir }
}

# ---------------------------------------------------------------- common part (same in every app)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Windows PowerShell draws progress very slowly
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Step([string]$text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Info([string]$text) { Write-Host "    $text" }
function Fail([string]$text) {
    Write-Host ""; Write-Host "Update failed: $text" -ForegroundColor Red
    if ($script:backup) { Write-Host "Your settings are backed up in $script:backup" }
    exit 1
}
function Ask([string]$question) {
    if ($Yes) { return $true }
    $a = Read-Host "$question [Y/n]"
    return (-not $a) -or ($a -match '^[Yy]')
}
# "v5.1.0" / "5.1" -> [version]; $null when it is not a version number.
function ConvertTo-Version([string]$text) {
    $m = [regex]::Match("$text", '\d+(\.\d+){0,3}')
    if (-not $m.Success) { return $null }
    $v = $m.Value; while (($v.Split('.')).Count -lt 2) { $v += ".0" }
    return [version]$v
}
# Relative paths of the files that count as settings (logs and locks left out).
function Get-SettingFiles([string]$dir) {
    if (-not (Test-Path -LiteralPath $dir)) { return @() }
    $dir = (Resolve-Path -LiteralPath $dir).Path.TrimEnd('\')
    @(Get-ChildItem -LiteralPath $dir -Recurse -Force -File | ForEach-Object {
        $rel = $_.FullName.Substring($dir.Length + 1)
        $skip = $false
        foreach ($part in $rel.Split('\')) { foreach ($p in $SkipInBackup) { if ($part -like $p) { $skip = $true } } }
        if (-not $skip) { $rel }
    })
}
function Copy-Files([string]$from, [string]$to, [string[]]$files) {
    foreach ($rel in $files) {
        $dst = Join-Path $to $rel
        $parent = Split-Path $dst
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force $parent | Out-Null }
        Copy-Item -LiteralPath (Join-Path $from $rel) $dst -Force
    }
}
function Save-Download([string]$url, [string]$file) {
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"   # Windows 10 1803+: fast, shows progress
    if (Test-Path $curl) {
        & $curl -fL --retry 3 --retry-delay 2 --progress-bar -A "$AppName-updater" -o $file $url
        if ($LASTEXITCODE -ne 0) { throw "download failed (curl exit code $LASTEXITCODE)" }
    } else {
        Invoke-WebRequest -UseBasicParsing -UserAgent "$AppName-updater" $url -OutFile $file
    }
}

Write-Host "================================================"
Write-Host "  $AppName updater"
Write-Host "================================================"

$work = $null; $owned = $false
try {
    # One updater at a time.
    $mutex = New-Object Threading.Mutex($false, "Local\$($AppName -replace '\W', '')-updater")
    try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { Fail "another update of $AppName is already running" }

    # ------------------------------------------------------------ 1. versions
    $installedText = (Get-ItemProperty -Path $UninstallKey -ErrorAction SilentlyContinue).DisplayVersion
    $isInstalled = Test-Installed
    $installed = if ($isInstalled) { ConvertTo-Version $installedText } else { $null }
    Info ("Installed: " + $(if (-not $isInstalled) { "not installed" } elseif ($installedText) { "v$installedText" } else { "unknown version" }))

    $download = $null; $digest = $null; $latestText = $null
    if ($Package) {
        if (-not (Test-Path -LiteralPath $Package)) { Fail "file not found: $Package" }
        $Package = (Resolve-Path -LiteralPath $Package).Path
        Info "Package:   $Package"
    } else {
        $release = $null
        try { $release = Invoke-RestMethod -UseBasicParsing -Uri $Api -Headers @{ "User-Agent" = "$AppName-updater"; "Accept" = "application/vnd.github+json" } -TimeoutSec 30 }
        catch { }
        if ($release -and $release.tag_name) {
            $latestText = "$($release.tag_name)".TrimStart('v', 'V')
            $a = @($release.assets | Where-Object { $_.name -eq $Asset })[0]
            if (-not $a) { Fail "release $($release.tag_name) has no $Asset" }
            $download = $a.browser_download_url
            if ("$($a.digest)" -match '^sha256:([0-9a-fA-F]{64})$') { $digest = $Matches[1].ToUpperInvariant() }
            Info "Latest:    v$latestText ($([math]::Round($a.size / 1MB, 1)) MB)"
        } else {
            # The GitHub API answers 60 questions an hour per address; the release page names the latest version too.
            $repo = [regex]::Match($Api, 'repos/([^/]+/[^/]+)/').Groups[1].Value
            $page = ""
            try {
                $req = [Net.HttpWebRequest]::Create("https://github.com/$repo/releases/latest")
                $req.Method = "HEAD"; $req.UserAgent = "$AppName-updater"; $req.Timeout = 30000
                $resp = $req.GetResponse(); $page = $resp.ResponseUri.AbsoluteUri; $resp.Close()
            } catch { Fail "could not ask GitHub for the latest version ($($_.Exception.Message)). Check the internet connection." }
            if ($page -notmatch '/releases/tag/([^/?#]+)') { Fail "GitHub did not say which version is the latest" }
            $tag = $Matches[1]
            $latestText = $tag.TrimStart('v', 'V')
            $download = "https://github.com/$repo/releases/download/$tag/$Asset"
            Info "Latest:    v$latestText"
        }

        $latest = ConvertTo-Version $latestText
        $upToDate = $installed -and $latest -and ($installed -ge $latest)
        if ($Check) {
            if ($upToDate) { Write-Host "$AppName is up to date."; exit 0 }
            Write-Host "An update is available: v$latestText"; exit 2
        }
        if ($upToDate -and -not $Force) {
            Write-Host ""; Write-Host "$AppName is up to date. (-Force reinstalls it.)" -ForegroundColor Green
            exit 0
        }
    }
    if ($Check) { Fail "-Check needs the internet (it cannot be used with -Package)" }
    $what = if ($latestText) { "v$latestText" } else { "the package" }
    if (-not (Ask "Install $what now? Your settings are kept.")) { Write-Host "Nothing changed."; exit 0 }

    $work = Join-Path $env:TEMP ("$($AppName -replace '\W', '')-update-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Force $work | Out-Null

    # ------------------------------------------------------------ 2. download (before closing the app)
    if (-not $Package) {
        Step "Downloading $Asset"
        $Package = Join-Path $work $Asset
        try { Save-Download $download $Package } catch { Fail "$_" }
        if ($digest) {
            $hash = (Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash
            if ($hash -ne $digest) { Fail "the download is damaged (SHA-256 does not match). Try again." }
            Info "SHA-256 checked"
        }
    }
    Step "Unpacking"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $unpacked = Join-Path $work "release"
    try { [IO.Compression.ZipFile]::ExtractToDirectory($Package, $unpacked) } catch { Fail "cannot unpack $Package ($($_.Exception.Message))" }
    $installer = Get-ChildItem -LiteralPath $unpacked -Recurse -Filter "install.ps1" |
        Where-Object { $_.Directory.Name -eq "app" } | Select-Object -First 1
    if (-not $installer) { Fail "this is not a $AppName release (app\install.ps1 is missing)" }
    if (-not $latestText) {   # -Package: the version comes from the release itself, when it says
        $vf = Join-Path $installer.DirectoryName "VERSION"
        if (Test-Path $vf) { $latestText = (Get-Content $vf -Raw).Trim() }
    }

    # ------------------------------------------------------------ 3. settings backup
    $settingFiles = Get-SettingFiles $SettingsDir
    if ($settingFiles.Count) {
        Step "Backing up the settings"
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $script:backup = Join-Path $BackupRoot ("$stamp" + $(if ($installedText) { "-v$installedText" }))
        Copy-Files $SettingsDir $script:backup $settingFiles
        Info "$($settingFiles.Count) files -> $script:backup"
        # Only the newest backups are kept.
        Get-ChildItem -LiteralPath $BackupRoot -Directory | Sort-Object Name -Descending |
            Select-Object -Skip $KeepBackups | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Info "No settings yet: nothing to back up."
    }

    # ------------------------------------------------------------ 4. install
    $wasRunning = Test-Running
    $hadDesktopLnk = Test-Path -LiteralPath $DesktopLnk
    Step "Installing $AppName $(if ($latestText) { "v$latestText" })"
    if ($wasRunning) { Info "$AppName is running: it is closed for the update and started again afterwards." }
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $installer.FullName @(Get-InstallerArgs)
    if ($LASTEXITCODE -ne 0) { Fail "the installer stopped with code $LASTEXITCODE (see the messages above)" }
    # The installer answers "yes" to the desktop shortcut question; keep the user's earlier choice.
    if (-not $hadDesktopLnk -and (Test-Path -LiteralPath $DesktopLnk)) { Remove-Item -LiteralPath $DesktopLnk -Force }
    if ($latestText -and (Test-Path $UninstallKey)) {
        Set-ItemProperty -Path $UninstallKey -Name DisplayVersion -Value $latestText
    }

    # ------------------------------------------------------------ 5. settings check
    if ($settingFiles.Count) {
        Step "Checking the settings"
        $missing = @($settingFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $SettingsDir $_)) })
        if ($missing.Count) {
            Copy-Files $script:backup $SettingsDir $missing
            Info "Restored from the backup: $($missing -join ', ')"
        } else {
            Info "All $($settingFiles.Count) files are in place."
        }
    }

    if ($wasRunning -and -not $NoLaunch) { Step "Starting $AppName"; Start-App }
    Write-Host ""
    Write-Host "$AppName is updated$(if ($latestText) { " to v$latestText" }). Settings kept." -ForegroundColor Green
    exit 0
} finally {
    if ($work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
    if ($owned) { $mutex.ReleaseMutex() }
    if ($Pause) { Write-Host ""; Read-Host "Press Enter to close this window" | Out-Null }
}
