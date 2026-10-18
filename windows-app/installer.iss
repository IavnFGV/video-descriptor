#ifndef Payload
  #error Payload must name the prepared application directory
#endif
#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif
[Setup]
AppId={{CA05C8BE-4CF2-4BCA-9B3C-597742FF04D1}
AppName=Video Descriptor
AppVersion={#AppVersion}
AppPublisher=Video Descriptor contributors
DefaultDirName={localappdata}\Programs\VideoDescriptor
DefaultGroupName=Video Descriptor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=VideoDescriptor-{#AppVersion}-windows-x64-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayName=Video Descriptor
UninstallDisplayIcon={app}\windows-app\app.ico
Uninstallable=yes
SetupLogging=yes
[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Icons]
Name: "{group}\Video Descriptor"; Filename: "{app}\windows-app\desktop-sdk\VideoDescriptor.exe"; WorkingDir: "{app}"; IconFilename: "{app}\windows-app\app.ico"
Name: "{autodesktop}\Video Descriptor"; Filename: "{app}\windows-app\desktop-sdk\VideoDescriptor.exe"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\windows-app\app.ico"
[Code]
function InstallationBusy(): Boolean;
var
  ResultCode: Integer;
  PythonPath: String;
begin
  Result := False;
  PythonPath := ExpandConstant('{app}\python\python.exe');
  if FileExists(PythonPath) then
  begin
    if not Exec(PythonPath, '-X utf8 "' + ExpandConstant('{app}\windows-app\release_lifecycle.py') + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := True
    else
      Result := ResultCode <> 0;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if InstallationBusy() then
    Result := 'Close Video Descriptor and its workers before updating this installation. No processes were stopped.';
end;

function InitializeUninstall(): Boolean;
begin
  Result := not InstallationBusy();
  if not Result then
    MsgBox('Close Video Descriptor and its workers before uninstalling. Your data and models will be preserved.', mbError, MB_OK);
end;
