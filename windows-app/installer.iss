#ifndef Payload
  #error Payload must name the prepared application directory
#endif
#if defined(PublicRelease) && (defined(Domestic) || defined(CachedComponents))
  #error PublicRelease cannot include Domestic or CachedComponents payloads
#endif
#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif
#include "WebView2Runtime.iss"
[Setup]
#ifdef CachedComponents
AppId={code:CachedApplicationId}
UsePreviousLanguage=no
#else
AppId={{CA05C8BE-4CF2-4BCA-9B3C-597742FF04D1}
#endif
AppName=Video Descriptor
AppVersion={#AppVersion}
#ifdef BuildNumber
AppVerName=Video Descriptor {#AppVersion} (Build {#BuildNumber})
VersionInfoDescription=Video Descriptor {#AppVersion} (Build {#BuildNumber})
#endif
AppPublisher=Video Descriptor contributors
DefaultDirName={localappdata}\Programs\VideoDescriptor
DefaultGroupName=Video Descriptor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
#ifdef ArtifactPrefix
OutputBaseFilename={#ArtifactPrefix}-setup
#else
OutputBaseFilename=VideoDescriptor-{#AppVersion}-windows-x64-setup
#endif
Compression=lzma2/fast
SolidCompression=yes
#ifdef CachedComponents
ArchiveExtraction=full
#endif
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayName=Video Descriptor
UninstallDisplayIcon={app}\windows-app\app.ico
Uninstallable=yes
SetupLogging=yes
[Files]
Source: "release_lifecycle.py"; DestName: "VD-release-lifecycle.py"; Flags: dontcopy
Source: "Ensure-WebView2.ps1"; Flags: dontcopy
Source: "{#Payload}\windows-app\desktop-sdk\WebView2Loader.dll"; DestName: "VD-WebView2Loader.dll"; Flags: dontcopy
#if defined(Domestic) && !defined(CachedComponents)
Source: "{#Payload}\windows-app\domestic\WebView2Runtime.x64.cab"; DestName: "WebView2Runtime.x64.cab"; Flags: dontcopy
#endif
#ifdef CachedComponents
Source: "component_cache.py"; DestName: "VD-component-cache.py"; Flags: dontcopy
Source: "{#Payload}\release-manifest.json"; DestName: "VD-component-manifest.json"; Flags: dontcopy
Source: "{#CachedComponents}\components.zip"; DestName: "VD-components.zip"; Flags: dontcopy nocompression
Source: "{tmp}\VD-components.zip"; DestDir: "{app}"; Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs; ExternalSize: {#ComponentsSize}; Check: NeedComponents
#endif
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Icons]
Name: "{group}\Video Descriptor"; Filename: "{app}\windows-app\desktop-sdk\VideoDescriptor.exe"; WorkingDir: "{app}"; IconFilename: "{app}\windows-app\app.ico"
Name: "{autodesktop}\Video Descriptor"; Filename: "{app}\windows-app\desktop-sdk\VideoDescriptor.exe"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\windows-app\app.ico"
[Code]
var
  WebViewDownload: TDownloadWizardPage;
#ifdef CachedComponents
  ComponentsRequired: Boolean;

function CachedApplicationId(Param: String): String;
begin
  { Test the exact produced EXE without changing the real application's registration. }
  if ExpandConstant('{param:VDLocalTest|0}') = '1' then
    Result := '{683C5737-64A0-47EE-AC74-684EF3CD77B8}'
  else
    Result := '{CA05C8BE-4CF2-4BCA-9B3C-597742FF04D1}';
end;

function NeedComponents(): Boolean;
begin
  Result := ComponentsRequired;
end;
#endif

procedure InitializeWizard();
begin
#ifdef CachedComponents
  ComponentsRequired := True;
#endif
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
#ifdef Domestic
  ExtractTemporaryFile('WebView2Runtime.x64.cab');
  if not WebViewCheck('Install', ResultCode) then
    Result := 'Could not start bundled WebView2 preparation.'
  else if ResultCode <> 0 then
    Result := 'Bundled WebView2 verification failed. See the setup log.';
#else
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
#endif
end;

#ifdef Domestic
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then exit;
  WizardForm.StatusLabel.Caption := 'Проверяем встроенные модели распознавания и участников...';
  if not Exec(ExpandConstant('{app}\python\python.exe'),
    '-X utf8 "' + ExpandConstant('{app}\windows-app\domestic_setup.py') + '"',
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    RaiseException('Could not prepare domestic components. Retry setup.')
  else if ResultCode <> 0 then
    RaiseException('Domestic model checks failed. See windows-app\runtime\domestic-setup.log or run Prepare Domestic.cmd in the installation folder, then retry setup.');
end;
#endif

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

function PrepareInstallationProcesses(): String;
var
  PythonPath, Arguments: String;
  ProcessList: AnsiString;
  ResultCode: Integer;
begin
  Result := '';
  PythonPath := ExpandConstant('{app}\python\python.exe');
  if not FileExists(PythonPath) then exit;
  { Use the NEW helper, including when upgrading an older installation. }
  ExtractTemporaryFile('VD-release-lifecycle.py');
  Arguments := '-X utf8 "' + ExpandConstant('{tmp}\VD-release-lifecycle.py') +
    '" --root "' + ExpandConstant('{app}') +
    '" --snapshot "' + ExpandConstant('{tmp}\VD-install-processes.json') +
    '" --report "' + ExpandConstant('{tmp}\VD-install-processes.txt') + '"';
  if not Exec(PythonPath, Arguments, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin
    Result := 'Не удалось проверить процессы приложения. Закройте приложение и повторите установку.';
    exit;
  end;
  if ResultCode = 0 then exit;
  Result := 'Установка приостановлена: приложение или его фоновые процессы ещё работают.';
  if ResultCode <> 64 then exit;
  LoadStringFromFile(ExpandConstant('{tmp}\VD-install-processes.txt'), ProcessList);
  Log('Processes blocking installation: ' + String(ProcessList));
  { Silent setup must never interpret absence of a person as consent. }
  if WizardSilent then exit;
  if MsgBox('Остались работающие процессы Video Descriptor:' + #13#10#13#10 +
    String(ProcessList) + #13#10#13#10 +
    'Остановить их и продолжить установку?' + #13#10#13#10 +
    'Текущая обработка будет прервана. Несохранённые правки могут быть потеряны. ' +
    'Сохранённые записи и модели останутся. Внешние сервисы не останавливаются.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then exit;
  if not Exec(PythonPath, Arguments + ' --stop-confirmed', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then exit;
  if ResultCode = 0 then begin
    Log('Confirmed installation processes stopped; installation is unblocked.');
    Result := '';
  end else
    Result := 'Не все процессы удалось остановить или их состав изменился. Повторите проверку установкой; файлы ещё не заменялись.';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
#ifdef CachedComponents
var
  ResultCode: Integer;
  PythonPath, Arguments: String;
#endif
begin
  Result := PrepareInstallationProcesses();
  if Result <> '' then exit;
#ifdef CachedComponents
  PythonPath := ExpandConstant('{app}\python\python.exe');
  ComponentsRequired := True;
  if FileExists(PythonPath) then begin
    ExtractTemporaryFile('VD-component-cache.py');
    ExtractTemporaryFile('VD-component-manifest.json');
    Arguments := '-X utf8 "' + ExpandConstant('{tmp}\VD-component-cache.py') +
      '" --root "' + ExpandConstant('{app}') + '" --manifest "' +
      ExpandConstant('{tmp}\VD-component-manifest.json') + '"';
    if Exec(PythonPath, Arguments, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      ComponentsRequired := ResultCode <> 0;
  end;
  if ComponentsRequired then begin
    Log('Component cache: installing the complete bundled runtime');
    ExtractTemporaryFile('VD-components.zip');
  end else
    Log('Component cache: compatible installed runtime retained without extraction');
#else
  Result := EnsureWebView();
#endif
end;

function InitializeUninstall(): Boolean;
begin
  Result := not InstallationBusy();
  if not Result then
    MsgBox('Close Video Descriptor and its workers before uninstalling. Your data and models will be preserved.', mbError, MB_OK);
end;
