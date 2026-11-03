; The Windows installer: build.bat compiles it with Inno Setup 6 (ISCC /DAppVersion=x.y.z) into
; dist\CustomClassicChat-setup.exe, from the same dist\CustomClassicChat folder as the zip.
;
; It installs for this Windows user only (no administrator needed), into
; %LOCALAPPDATA%\Programs\CustomClassic Chat: the app keeps its settings, cache and chat log next
; to its .exe, so the folder has to be one the player can write to. Installing a newer version
; over it keeps all of that; uninstalling asks before deleting it.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=2.1.0 installer\CustomClassicChat.iss
#endif
#define AppName "CustomClassic Chat"
#define AppExe "CustomClassicChat.exe"
#define Source "..\dist\CustomClassicChat"
#define Pictures "..\build\installer"

[Setup]
AppId={{6C1C7A3E-2F4B-4F7E-9C55-0B3D8A1E7C21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=mentulatv
AppPublisherURL=https://customclassic.chat
AppSupportURL=https://github.com/mentulatv/customclassic-chat/issues
AppUpdatesURL=https://github.com/mentulatv/customclassic-chat/releases/latest
AppCopyright=Not made or endorsed by Nexon
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} setup
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 1903: the first with the screen capture the app reads the chat through
MinVersion=10.0.18362
LicenseFile=..\LICENSE
InfoBeforeFile=disclaimer.txt
OutputDir=..\dist
OutputBaseFilename=CustomClassicChat-setup
SetupIconFile=..\build\customclassic_chat.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSizePercent=110
WizardImageFile={#Pictures}\wizard.bmp,{#Pictures}\wizard_1.bmp,{#Pictures}\wizard_2.bmp,{#Pictures}\wizard_3.bmp,{#Pictures}\wizard_4.bmp,{#Pictures}\wizard_5.bmp
WizardSmallImageFile={#Pictures}\wizard_small.bmp,{#Pictures}\wizard_small_1.bmp,{#Pictures}\wizard_small_2.bmp,{#Pictures}\wizard_small_3.bmp,{#Pictures}\wizard_small_4.bmp,{#Pictures}\wizard_small_5.bmp
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
; a running copy is closed before its files are replaced, and started again after
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; the program's own files only: settings, cache and chat log are made on first run and never overwritten
Source: "{#Source}\*"; DestDir: "{app}"; Excludes: "\cache,\chat log,\chat.json,\config.toml,\*.bat"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} demo"; Filename: "{app}\{#AppExe}"; Parameters: "--demo"; Comment: "Try it with a made-up chat, no game needed"
Name: "{group}\{#AppName} problem report"; Filename: "{app}\{#AppExe}"; Parameters: "--report"; Comment: "When it doesn't read the game: what it sees, in a file to send"
Name: "{group}\Chat log folder"; Filename: "{app}\chat log"; Flags: createonlyiffileexists
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExe}"; Flags: runhidden; RunOnceId: "CloseApp"

[Code]
// Uninstalling removes the program; the player's settings and chat log go only if they say so.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App: String;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    App := ExpandConstant('{app}');
    if (FileExists(App + '\chat.json') or DirExists(App + '\chat log')) and
       (MsgBox('Also delete your settings and chat log?' + #13#10#13#10 +
               'Keep them if you plan to install CustomClassic Chat again.',
               mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(App, True, True, True);
  end;
end;
