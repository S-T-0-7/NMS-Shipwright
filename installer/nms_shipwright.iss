; Compiled by scripts/build_app.py via ISCC with /D defines (AppSrc, OutDir, Icon, AppVer).

#ifndef AppSrc
  #define AppSrc "..\dist\NMS Shipwright"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif
#ifndef Icon
  #define Icon "..\build\app.ico"
#endif
#ifndef AppVer
  #define AppVer "0.0.0"
#endif
#define AppName "NMS Shipwright"
#define AppExe "NMS Shipwright.exe"

[Setup]
AppId={{B7D4F0C2-9A3E-4D18-8C6B-5E1A2F7C9D40}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=Shikhar Tiwari
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=NMS Shipwright Setup
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#AppSrc}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
