; HandTrack installer — Inno Setup 6.
; Installs the app and registers the bundled Unity Capture DirectShow filter
; as "HandTrack Camera", so no OBS install is needed for the virtual camera.
;
; Built by packaging/build.ps1:  ISCC /DAppVersion=7.0.0 packaging\HandTrack.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "HandTrack"
#define CameraName "HandTrack Camera"
#define DriverDir "{app}\_internal\driver"

[Setup]
AppId={{6F0B7C1E-3A44-4C8B-9E0D-2B7B1C5E9A71}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=HandTrack contributors
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=HandTrack-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\HandTrack.exe
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
LicenseFile=..\LICENSE
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[CustomMessages]
en.DesktopIcon=Create a desktop shortcut
ru.DesktopIcon=Создать ярлык на рабочем столе
en.InstallDriver=Install the "{#CameraName}" virtual camera driver (recommended)
ru.InstallDriver=Установить драйвер виртуальной камеры «{#CameraName}» (рекомендуется)
en.RegisteringDriver=Registering the virtual camera driver...
ru.RegisteringDriver=Регистрация драйвера виртуальной камеры...
en.Launch=Launch HandTrack
ru.Launch=Запустить HandTrack

[Tasks]
Name: "driver"; Description: "{cm:InstallDriver}"
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked

[Files]
Source: "..\dist\HandTrack\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\HandTrack.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\HandTrack.exe"; Tasks: desktopicon

[Run]
; 64-bit filter for 64-bit apps (Discord, Telegram, Zoom, browsers, OBS) …
Filename: "{sys}\regsvr32.exe"; \
  Parameters: "/s ""/i:UnityCaptureName={#CameraName}"" ""{#DriverDir}\UnityCaptureFilter64.dll"""; \
  StatusMsg: "{cm:RegisteringDriver}"; Flags: runhidden waituntilterminated; Tasks: driver
; … and the 32-bit one for older 32-bit apps (Skype classic, etc.).
Filename: "{syswow64}\regsvr32.exe"; \
  Parameters: "/s ""/i:UnityCaptureName={#CameraName}"" ""{#DriverDir}\UnityCaptureFilter32.dll"""; \
  StatusMsg: "{cm:RegisteringDriver}"; Flags: runhidden waituntilterminated; Tasks: driver
Filename: "{app}\HandTrack.exe"; Description: "{cm:Launch}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\regsvr32.exe"; Parameters: "/u /s ""{#DriverDir}\UnityCaptureFilter64.dll"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "UnregDriver64"
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/u /s ""{#DriverDir}\UnityCaptureFilter32.dll"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "UnregDriver32"

[Code]
// Unregister an older copy of the driver before files are replaced on upgrade,
// so the registry never points at a DLL that is about to be overwritten.
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Dll: String;
begin
  if CurStep = ssInstall then
  begin
    Dll := ExpandConstant('{app}\_internal\driver\UnityCaptureFilter64.dll');
    if FileExists(Dll) then
      Exec(ExpandConstant('{sys}\regsvr32.exe'), '/u /s "' + Dll + '"', '', SW_HIDE,
           ewWaitUntilTerminated, ResultCode);
    Dll := ExpandConstant('{app}\_internal\driver\UnityCaptureFilter32.dll');
    if FileExists(Dll) then
      Exec(ExpandConstant('{syswow64}\regsvr32.exe'), '/u /s "' + Dll + '"', '', SW_HIDE,
           ewWaitUntilTerminated, ResultCode);
  end;
end;
