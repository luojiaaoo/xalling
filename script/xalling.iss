; Xalling 安装程序脚本 (Inno Setup 6)
; 先运行 .\script\package_windows.bat 生成 dist\Xalling\，再由 ISCC 编译本脚本。
; 版本号需与 pyproject.toml 保持一致。

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "Xalling"

[Setup]
AppId={{A9C5B2D1-4E6F-4A3B-8C7D-2E1F0A9B8C7D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Xalling
DefaultDirName={autopf}\Xalling
DefaultGroupName=Xalling
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Xalling-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\Xalling.exe
SetupIconFile=..\favicon.ico

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Xalling\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Xalling"; Filename: "{app}\Xalling.exe"
Name: "{group}\{cm:UninstallProgram,Xalling}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Xalling"; Filename: "{app}\Xalling.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Xalling.exe"; Description: "{cm:LaunchProgram,Xalling}"; Flags: nowait postinstall skipifsilent
