; Paragon PR7-FS installer (Inno Setup 6): folder comparison and sync, the way FreeFileSync works.
;   iscc /DAppVersion=0.1.0 installer\pr7fs.iss      (after pyinstaller pr7fs.spec has made dist\PR7-FS)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-FS, with a Start menu entry; .pr7fs settings files open
; in PR7-FS, and their right-click menu has "Synchronize now (batch)" (HKCU, removed on uninstall).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{D573AEAF-B102-484A-AD03-42624DC18A25}
AppName=Paragon PR7-FS
AppVersion={#AppVersion}
AppVerName=Paragon PR7-FS {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-FS
DefaultGroupName=Paragon PR7-FS
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-FS-Setup-{#AppVersion}
SetupIconFile=..\pr7fs\icons\app.ico
UninstallDisplayIcon={app}\PR7-FS.exe
UninstallDisplayName=Paragon PR7-FS
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-FS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\NOTICE.md"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
; .pr7fs settings files open in PR7-FS (per user; removed on uninstall)
Root: HKCU; Subkey: "Software\Classes\.pr7fs"; ValueType: string; ValueName: ""; ValueData: "Paragon.PR7FS.Settings"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Paragon.PR7FS.Settings"; ValueType: string; ValueName: ""; ValueData: "PR7-FS sync settings"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Paragon.PR7FS.Settings\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\PR7-FS.exe,0"
Root: HKCU; Subkey: "Software\Classes\Paragon.PR7FS.Settings\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PR7-FS.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Paragon.PR7FS.Settings\shell\runbatch"; ValueType: string; ValueName: ""; ValueData: "Synchronize now (batch)"
Root: HKCU; Subkey: "Software\Classes\Paragon.PR7FS.Settings\shell\runbatch\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PR7-FS.exe"" --batch ""%1"""

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-FS"; Filename: "{app}\PR7-FS.exe"; Comment: "Folder comparison and sync"
Name: "{autodesktop}\Paragon PR7-FS"; Filename: "{app}\PR7-FS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-FS.exe"; Description: "{cm:LaunchProgram,Paragon PR7-FS}"; Flags: nowait postinstall skipifsilent
; Updates (Check for updates runs this installer with /SILENT /relaunch=1): start PR7-FS again when done.
Filename: "{app}\PR7-FS.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
