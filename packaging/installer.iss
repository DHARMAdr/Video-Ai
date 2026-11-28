; installer.iss - turns dist\ShortsForge into a normal "Setup.exe" (Inno Setup, free tool).
;
; WHY: a single Setup file is easier to share than a folder. It installs the app into the user's
;      own AppData (no administrator rights needed), adds a Start-menu entry and an uninstaller.
; HOW: install Inno Setup from jrsoftware.org, open this file, press Compile.
;      (The GitHub build does this automatically.) Run AFTER the app is built into dist\ShortsForge.
; IMPROVE: add an icon (SetupIconFile), a licence page and code signing.

#define AppName "ShortsForge"
#ifndef AppVersion
  #define AppVersion "0.11.0"
#endif

[Setup]
AppId={{6F1C2D44-9B2E-4C8A-9E55-3A5B0D7C1F21}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ShortsForge-Setup
Compression=lzma2/fast
SolidCompression=no
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Files]
Source: "..\dist\ShortsForge\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\ShortsForge.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ShortsForge.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\ShortsForge.exe"; Description: "Open ShortsForge"; Flags: nowait postinstall skipifsilent
