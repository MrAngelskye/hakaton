#define AppVersion "1.8"
#ifndef DistributionDir
  #define DistributionDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\build\windows\naryadai.ico"
#endif
[Setup]
AppId={{CE5D6EB0-0714-4D88-85A9-18E1FD6A7DC5}
AppName=НарядAI
AppVersion={#AppVersion}
AppPublisher=Команда НарядAI
DefaultDirName={localappdata}\Programs\NaryadAI
DefaultGroupName=НарядAI
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=NaryadAI-Setup-1.8
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\NaryadAI.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык НарядAI на рабочем столе"; Flags: checkedonce
[Files]
Source: "{#DistributionDir}\NaryadAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\НарядAI"; Filename: "{app}\NaryadAI.exe"
Name: "{group}\НарядAI — обработчик ИИ"; Filename: "{app}\NaryadAI-AI.exe"
Name: "{group}\НарядAI — сменить сервер"; Filename: "{app}\NaryadAI.exe"; Parameters: "--change-server"
Name: "{group}\НарядAI — настройки ИИ"; Filename: "{app}\NaryadAI-AI.exe"; Parameters: "--change-settings"
Name: "{group}\НарядAI — проверка скорости ИИ"; Filename: "{app}\NaryadAI-Diagnostics.exe"
Name: "{autodesktop}\НарядAI"; Filename: "{app}\NaryadAI.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\NaryadAI.exe"; Description: "Открыть НарядAI"; Flags: nowait postinstall skipifsilent
