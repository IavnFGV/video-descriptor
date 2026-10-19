#ifndef Payload
  #error Payload must name the prepared application directory
#endif
#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif
#include "WebView2Runtime.iss"
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
Source: "Ensure-WebView2.ps1"; Flags: dontcopy
Source: "{#Payload}\windows-app\desktop-sdk\WebView2Loader.dll"; DestName: "VD-WebView2Loader.dll"; Flags: dontcopy
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Icons]
Name: "{group}\Video Descriptor"; Filename: "{app}\windows-app\desktop-sdk\VideoDescriptor.exe"; WorkingDir: "{app}"; IconFilename: "{app}\windows-app\app.ico"
Name: "{autodesktop}\Video Descriptor"; Filename: "{app}\windows-app\desktop-sdk\VideoDescriptor.exe"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\windows-app\app.ico"
[Code]
var
  WebViewDownload: TDownloadWizardPage;

procedure InitializeWizard();
begin
  WebViewDownload := CreateDownloadPage('Microsoft Edge WebView2 Runtime',
    'WebView2 is required for the application window. Downloading from Microsoft...', nil);
end;

function WebViewCheck(Mode: String; var ResultCode: Integer): Boolean;
var
  Arguments: String;
begin
  Arguments := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\Ensure-WebView2.ps1') + '" -Mode ' + Mode +
    ' -LoaderPath "' + ExpandConstant('{tmp}\VD-WebView2Loader.dll') +
    '" -InstallerPath "' + ExpandConstant('{tmp}\WebView2Runtime.x64.cab') +
    '" -RuntimeDirectory "' + ExpandConstant('{app}\windows-app\webview2-runtime') +
    '" -ExpectedSha256 {#WebViewRuntimeSha256} -RuntimeVersion {#WebViewRuntimeVersion}' +
    ' -LogPath "' + ExpandConstant('{tmp}\VideoDescriptor-WebView2.jsonl') + '"';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Arguments, ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function EnsureWebView(): String;
var
  ResultCode: Integer;
begin
  Result := '';
  ExtractTemporaryFile('Ensure-WebView2.ps1');
  ExtractTemporaryFile('VD-WebView2Loader.dll');
  if not WebViewCheck('Detect', ResultCode) then begin
    Result := 'Could not check Microsoft Edge WebView2 Runtime. See the setup log.';
    exit;
  end;
  if ResultCode = 0 then begin
    Log('WebView2 Runtime detected; no download or installation needed.');
    exit;
  end;
  if ResultCode <> 20 then begin
    Result := 'WebView2 detection failed. See ' + ExpandConstant('{tmp}\VideoDescriptor-WebView2.jsonl');
    exit;
  end;
  WebViewDownload.Clear;
  WebViewDownload.Add('{#WebViewRuntimeUrl}', 'WebView2Runtime.x64.cab', '{#WebViewRuntimeSha256}');
  WebViewDownload.Show;
  try
    try
      WebViewDownload.Download;
      WebViewDownload.SetText('Installing Microsoft Edge WebView2 Runtime...',
        'The Microsoft publisher signature is checked before installation.');
      if not WebViewCheck('Install', ResultCode) then
        Result := 'Could not start WebView2 prerequisite installation.'
      else if ResultCode <> 0 then
        Result := 'WebView2 installation or verification failed. See ' +
          ExpandConstant('{tmp}\VideoDescriptor-WebView2.jsonl') + '. Retry setup after repairing WebView2.';
    except
      Result := 'WebView2 download failed or was cancelled. Check your connection and retry setup. ' + GetExceptionMessage;
    end;
  finally
    WebViewDownload.Hide;
  end;
end;

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
    Result := 'Close Video Descriptor and its workers before updating this installation. No processes were stopped.'
  else
    Result := EnsureWebView();
end;

function InitializeUninstall(): Boolean;
begin
  Result := not InstallationBusy();
  if not Result then
    MsgBox('Close Video Descriptor and its workers before uninstalling. Your data and models will be preserved.', mbError, MB_OK);
end;
