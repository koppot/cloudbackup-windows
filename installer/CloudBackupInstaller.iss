; CloudBackupInstaller.iss — Inno Setup Script for CloudBackup for Windows (x64 Phase 1 Development Preview)

#define MyAppName "CloudBackup"
#define MyAppVersion "1.0.0-phase1"
#define MyAppPublisher "Koppot Open Source"
#define MyAppURL "https://github.com/koppot/cloudbackup-windows"
#define MyAppExeName "CloudBackup.exe"

[Setup]
AppId={{2A32A121-3B0F-4279-A17C-A61E77ACC4C7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=CloudBackup-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
Name: "{commonappdata}\{#MyAppName}"; Permissions: system-full admins-full users-readexec
Name: "{commonappdata}\{#MyAppName}\config"; Permissions: system-full admins-full
Name: "{commonappdata}\{#MyAppName}\state"; Permissions: system-full admins-full
Name: "{commonappdata}\{#MyAppName}\logs"; Permissions: system-full admins-full users-readexec
Name: "{commonappdata}\{#MyAppName}\temp"; Permissions: system-full admins-full

[Files]
Source: "..\dist\CloudBackup\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName} Web Dashboard"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--server"
Name: "{group}\{#MyAppName} Diagnostics Verify"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--verify"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--server"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--server"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\{#MyAppName}\temp"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('Do you also want to remove local configuration files, logs, and database state?' + #13#10 + #13#10 + '(Note: Backed-up data on Google Drive will NOT be deleted)', mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{commonappdata}\{#MyAppName}'), True, True, True);
    end;
  end;
end;
