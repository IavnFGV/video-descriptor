# Guest only. SAC preparation/restart is confined to the verified disposable guest.
$ErrorActionPreference='Stop'
. "$PSScriptRoot\Acceptance.Common.ps1"
$machine=Get-CimInstance Win32_ComputerSystem
if ($env:USERNAME -ne 'WDAGUtilityAccount' -or $machine.Model -ne 'Virtual Machine' -or
    !(Get-Service -Name CExecSvc -ErrorAction SilentlyContinue)) {
    throw 'REFUSED: requires WDAGUtilityAccount, Hyper-V Virtual Machine and Sandbox CExecSvc'
}
$plan=Read-Json 'C:\VD-Acceptance\plan.json'
if ($plan.schema -ne 1 -or $plan.profile -notin @('Security','Functional')) { throw 'Invalid guest plan' }
$out='C:\VD-Results'; $work='C:\VD-Work'; $checkpoint=Join-Path $out 'checkpoint.json'
$mutex=[Threading.Mutex]::new($false,'Local\VD-Acceptance')
if (!$mutex.WaitOne(0)) { $mutex.Dispose(); exit 0 }
$report=$null
$restartPending=$false
function Save-Report {
    if (Test-Path -LiteralPath (Join-Path $out 'host-timeout.json')) {
        $script:report.status='BLOCKED'
        $script:report.error='Host deadline expired; see host-timeout.json. Late completion is not an on-time PASS.'
    }
    Write-Json (Join-Path $out 'report.json') $script:report
}
function Snapshot-Policy($Name) {
    $raw= & "$env:WINDIR\System32\CiTool.exe" --list-policies --json 2>&1 | Out-String
    $raw | Set-Content -LiteralPath (Join-Path $out ($Name+'-citool.json')) -Encoding UTF8
    $state=Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -ErrorAction SilentlyContinue
    Write-Json (Join-Path $out ($Name+'-sac.json')) @{registry_state=$state.VerifiedAndReputablePolicyState;citool_exit=$LASTEXITCODE}
    $script:sacState=$state.VerifiedAndReputablePolicyState
    try { @((($raw | ConvertFrom-Json).Policies) | Where-Object { $null -ne $_ }) } catch { @() }
}
function Active-Policy($Policies, $Pattern) {
    @($Policies | Where-Object { $_.FriendlyName -match $Pattern -and [string]$_.IsEnforced -match '^true$' }).Count -gt 0
}
function Invoke-OwnedProcess($Exe, $Arguments, $Name, [int]$Seconds=600) {
    $p=Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $out ($Name+'.stdout.log')) -RedirectStandardError (Join-Path $out ($Name+'.stderr.log'))
    # Cache the handle before a short-lived process exits (PowerShell 5.1).
    $null=$p.Handle
    if (!$p.WaitForExit($Seconds*1000)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; throw "Timed out: $Name" }
    $p.WaitForExit(); $p.Refresh()
    if ($p.ExitCode -ne 0) { throw "$Name failed (exit $($p.ExitCode)); see $Name.stderr.log" }
}
function Invoke-UI($Name, [switch]$Cached) {
    $driver=if ($plan.interaction -eq 'Api') {'acceptance_api.py'} else {'acceptance_ui.py'}
    $arguments='-X utf8 C:\VD-Acceptance\'+$driver+' --stage '+$Name+' --root "'+$script:install+'" --reports C:\VD-Results --model '+$plan.ollama_model
    if ($Cached -and $plan.interaction -ne 'Api') { $arguments+=' --reuse-expensive-proof' }
    Invoke-OwnedProcess (Join-Path $script:install 'python\python.exe') $arguments $Name 900
    $result=Read-Json (Join-Path $out ($Name+'.json'))
    if ($result.status -eq 'BLOCKED') { throw ('BLOCKED: '+$result.reason) }
    if ($result.status -ne 'PASS') { throw ('Acceptance stage failed: '+$Name+'; '+$result.error) }
    if ($Name -eq 'desktop') {
        $script:report.dependency_versions=@{openvino=$result.diagnostics.inventory.openvino;genai=$result.diagnostics.inventory.genai}
    }
    if ($Name -eq 'ollama-install') {
        $script:report.dependency_versions.ollama=$result.ollama_version.version
    }
    $result
}
try {
    Start-Transcript -LiteralPath (Join-Path $out ('bootstrap-'+(Get-Date -Format 'HHmmss')+'.log')) -Force | Out-Null
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    $identity=Join-Path $work 'guest-id.txt'
    if (Test-Path -LiteralPath $checkpoint) {
        $saved=Read-Json $checkpoint
        if (!(Test-Path -LiteralPath $identity) -or (Get-Content $identity -Raw).Trim() -ne $saved.guest_id) {
            throw 'Previous guest was destroyed. Host checkpoint cannot restore its installed state; start a NEW run.'
        }
        if ($saved.attempts -ge $plan.max_resume_attempts) { throw 'Resume attempt limit reached' }
        $guestId=$saved.guest_id; $attempts=1+$saved.attempts
        $report=Read-Json (Join-Path $out 'report.json')
    } else {
        $guestId=[guid]::NewGuid().ToString('N'); $attempts=1
        $guestId | Set-Content -LiteralPath $identity
        $report=[pscustomobject]@{
            schema=1;run_id=$plan.run_id;profile=$plan.profile;git_sha=$plan.git_sha;git_dirty=$plan.git_dirty
            fingerprint=$plan.fingerprint;harness=$plan.harness;artifacts=$plan.artifacts;cache=$plan.cache;guest_id=$guestId
            artifact_versions=@($plan.artifacts | ForEach-Object { if ($_.file -match '^VideoDescriptor-(.+)-windows-x64') { $Matches[1] } } | Select-Object -Unique)
            dependency_versions=@{};interaction=$plan.interaction;sac_mode=$(if ($plan.profile -eq 'Security') {'Default'} else {$plan.guest_sac_mode});restart=$null
            environment='Windows Sandbox';contracts=$plan.contracts;status='RUNNING';started_at=(Get-Date).ToUniversalTime().ToString('o')
            finished_at=$null;elapsed_seconds=0;os=$null;policy=$null;compatibility=$null;error=$null
            stages=@($StageOrder | ForEach-Object { [pscustomobject]@{name=$_;status='NOT_TESTED';reason='Not selected';started_at=$null;finished_at=$null;seconds=0;evidence=@();checks=@();previous_run=$null} })
        }
    }
    $report.status='RUNNING'; Save-Report
    $clock=[Diagnostics.Stopwatch]::StartNew()
    $snapshotName=if ($attempts -eq 1) {'initial'} else {'resumed'}
    $policies=@(Snapshot-Policy $snapshotName)
    $os=Get-CimInstance Win32_OperatingSystem
    $report.os=@{caption=$os.Caption;version=$os.Version;build=$os.BuildNumber;architecture=$os.OSArchitecture;memory_mb=[math]::Round($machine.TotalPhysicalMemory/1MB)}
    $report.policy=$policies
    if ($plan.profile -eq 'Functional' -and $plan.guest_sac_mode -eq 'Off') {
        if (!$plan.guest_sac_off_authorization) { throw 'Guest SAC Off authorization missing' }
        if ($sacState -ne 0) {
            if ($attempts -ne 1) { throw 'SAC did not remain Off after one guest restart; no further policy attempts' }
            $policyPath='HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy'
            $before=$sacState
            Set-ItemProperty -LiteralPath $policyPath -Name VerifiedAndReputablePolicyState -Type DWord -Value 0
            $refresh=& "$env:WINDIR\System32\CiTool.exe" --refresh --json 2>&1 | Out-String
            $refresh | Set-Content -LiteralPath (Join-Path $out 'sac-refresh.json') -Encoding UTF8
            $after=(Get-ItemProperty -LiteralPath $policyPath -Name VerifiedAndReputablePolicyState).VerifiedAndReputablePolicyState
            Write-Json (Join-Path $out 'sac-change.json') @{guest_id=$guestId;authorization=$plan.guest_sac_off_authorization;before=$before;after=$after;host_changed=$false;timestamp=(Get-Date).ToUniversalTime().ToString('o')}
            if ($after -ne 0) { throw 'SAC registry setting was not accepted; no ACL/ownership/boot-policy changes will be attempted' }
            $runOnce='HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
            New-Item -Path $runOnce -Force | Out-Null
            New-ItemProperty -LiteralPath $runOnce -Name 'VD-Acceptance-Resume' -PropertyType String -Value 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\VD-Acceptance\Resume-Acceptance.ps1' -Force | Out-Null
            $report.restart=@{requested=$true;before_boot=$os.LastBootUpTime.ToUniversalTime().ToString('o');attempt=1;guest_id=$guestId}
            Write-Json $checkpoint @{run_id=$plan.run_id;guest_id=$guestId;attempts=$attempts;phase='policy-restart';state='RESTART_PENDING'}
            $restartPending=$true
            return
        }
        if ($attempts -gt 1 -and $report.restart) {
            $currentBoot=$os.LastBootUpTime.ToUniversalTime().ToString('o')
            if ($currentBoot -eq $report.restart.before_boot) { throw 'Resume ran before the requested guest reboot completed' }
            $report.restart | Add-Member -Force -NotePropertyName after_boot -NotePropertyValue $currentBoot
            $report.restart | Add-Member -Force -NotePropertyName resumed_same_guest -NotePropertyValue $true
        }
    }
    $report.compatibility=Get-TextHash (ConvertTo-CanonicalJson @{os=$report.os;policy=$policies;sac_registry=$sacState})
    Save-Report
    $install=Join-Path $env:LOCALAPPDATA 'Programs\VideoDescriptor'
    $previous=$null
    if ($attempts -gt 1) {
        # Resume preserves evidence, not assumptions about processes surviving a reboot.
        Write-Json (Join-Path $out ('attempt-'+($attempts-1)+'.json')) $report
        $previous=$report | ConvertTo-Json -Depth 40 | ConvertFrom-Json
    }
    foreach ($candidate in $plan.history) { if ($candidate.compatibility -eq $report.compatibility) { $previous=$candidate;break } }
    foreach ($stage in $report.stages) {
        if ($stage.name -notin $plan.selected) { continue }
        if (Test-Path -LiteralPath (Join-Path $out 'host-timeout.json')) { throw 'Host deadline expired; no further stages will run' }
        # Provision dependencies again after resume. Only explicit expensive proofs are reused.
        $stage.started_at=(Get-Date).ToUniversalTime().ToString('o'); $stage.reason=''; $stage.status='NOT_TESTED'
        Write-Json $checkpoint @{run_id=$plan.run_id;guest_id=$guestId;attempts=$attempts;phase=$stage.name;state='ENTERED';timestamp=$stage.started_at}
        Save-Report
        $stageClock=[Diagnostics.Stopwatch]::StartNew()
        try {
            $failedDependencies=@($report.stages | Where-Object { $_.name -in $StageDependencies[$stage.name] -and $_.status -notin @('PASS','CACHED_PASS') })
            if ($failedDependencies.Count -and $stage.name -ne 'cleanup') { throw ('BLOCKED: dependency '+($failedDependencies.name -join ', ')) }
            $cached=@($previous.stages | Where-Object { $_.name -eq $stage.name -and $_.status -in @('PASS','CACHED_PASS') })
            switch ($stage.name) {
                'preflight' {
                    Test-ObjectFiles 'C:\VD-Acceptance' $plan.artifacts
                    foreach ($obj in $plan.cache) {
                        if ($plan.network_download -and $obj.component -in @('whisper-model','ollama-model')) { throw 'Network test must not mount model cache' }
                        Test-ObjectFiles (Get-CachePayload $obj) $obj.files
                    }
                    $stage.evidence=@('initial-citool.json','initial-sac.json')
                    if ($plan.profile -eq 'Functional' -and $plan.guest_sac_mode -eq 'Off' -and $sacState -ne 0) { throw 'BLOCKED: guest SAC Off was not verified' }
                    if ($plan.profile -eq 'Functional' -and $plan.guest_sac_mode -ne 'Off' -and !(Active-Policy $policies '^VerifiedAndReputableDesktopEvaluation(Audit|AuditNoISG)?$')) {
                        $permission=if ($plan.allow_guest_evaluation) { 'Owner authorized Evaluation/Audit. ' } else { 'Evaluation/Audit authorization not supplied. ' }
                        throw ('BLOCKED: '+$permission+'No active supported SAC Evaluation/Audit policy. Microsoft documented transitions need recovery, ACL/ownership or EFI changes excluded by this task. No policy was changed.')
                    }
                }
                'installer' {
                    $exe=@($plan.artifacts | Where-Object file -like '*-setup.exe')[0].file
                    if ($plan.profile -eq 'Security') {
                        if (!(Active-Policy $policies '^VerifiedAndReputableDesktop$') -and $sacState -ne 1) { throw 'BLOCKED: default guest does not report SAC enforcement; cannot prove unsigned binary rejection' }
                        $began=Get-Date; $rejected=$false
                        try { Invoke-OwnedProcess (Join-Path 'C:\VD-Acceptance' $exe) '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG=C:\VD-Results\installer.log' 'security-launch' 180 }
                        catch {
                            $stage.reason=$_.Exception.Message; $rejected=$true
                            $_.Exception.ToString() | Set-Content -LiteralPath (Join-Path $out 'security-launch-error.txt') -Encoding UTF8
                        }
                        $events=@(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational';Id=3077,3033;StartTime=$began} -ErrorAction SilentlyContinue | Where-Object { $_.ToXml() -like ('*'+$exe+'*') })
                        $events | ForEach-Object { $_.ToXml() } | Set-Content (Join-Path $out 'security-block-events.xml')
                        if (!$rejected -or !$events.Count) { throw 'BLOCKED: no correlated 3077/3033 rejection of this installer; failure alone is not SAC proof' }
                        $stage.reason='Unsigned installer rejected under unchanged default SAC enforcement; correlated Code Integrity rejection recorded'
                        $stage.evidence=@('security-block-events.xml','security-launch-error.txt')
                    } else {
                        $lifecycleCached=@($cached | Where-Object { $_.checks -contains 'full-installer-lifecycle' })
                        if ($stage.name -in $plan.requested -and !$lifecycleCached.Count) {
                            $zip=@($plan.artifacts | Where-Object file -like '*.zip')[0].file
                            $bootstrap=Join-Path $work 'lifecycle-runtime'
                            Expand-Archive -LiteralPath (Join-Path 'C:\VD-Acceptance' $zip) -DestinationPath $bootstrap -Force
                            Invoke-OwnedProcess (Join-Path $bootstrap 'python\python.exe') ('-X utf8 C:\VD-Acceptance\verify_release.py C:\VD-Acceptance\'+$zip+' --installer C:\VD-Acceptance\'+$exe+' --output C:\VD-Results\installer-lifecycle.json') 'installer-lifecycle' 900
                            $stage.checks=@('full-installer-lifecycle')
                        } elseif ($lifecycleCached.Count) { $stage.status='CACHED_PASS';$stage.previous_run=$previous.run_id;$stage.checks=@('full-installer-lifecycle') }
                        else { $stage.reason='Fresh guest silent install and file presence; full lifecycle not requested' }
                        Invoke-OwnedProcess (Join-Path 'C:\VD-Acceptance' $exe) '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG=C:\VD-Results\installer.log' 'install'
                        if (!(Test-Path (Join-Path $install 'python\python.exe')) -or !(Test-Path (Join-Path $install 'windows-app\desktop-sdk\VideoDescriptor.exe'))) { throw 'Installation files missing' }
                        $stage.evidence=@('installer.log')
                    }
                }
                'desktop' {
                    if ($plan.profile -eq 'Security') { throw 'BLOCKED: Security profile never relaxes policy or continues functional tests' }
                    # Environment variable applies only to this guest process tree; debugger stays on loopback.
                    $shortcut=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Video Descriptor\Video Descriptor.lnk'
                    if (!(Test-Path -LiteralPath $shortcut)) { throw 'Installed Start Menu shortcut missing' }
                    if ($plan.interaction -eq 'Api') {
                        Start-Process -FilePath (Join-Path $install 'python\python.exe') -ArgumentList ('-X utf8 "'+(Join-Path $install 'windows-app\app.py')+'" --no-browser') -WorkingDirectory $install -WindowStyle Hidden -RedirectStandardOutput (Join-Path $out 'backend.stdout.log') -RedirectStandardError (Join-Path $out 'backend.stderr.log')
                        $stage.reason='Installed backend API and component detection; no desktop/UI assertion'
                    } else {
                        $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-address=127.0.0.1 --remote-debugging-port=9222'
                        # Launch the installed shortcut target directly so this test process's
                        # DevTools environment is inherited instead of Explorer's old environment.
                        $shell=New-Object -ComObject WScript.Shell
                        $target=$shell.CreateShortcut($shortcut).TargetPath
                        if ($target -ne (Join-Path $install 'windows-app\desktop-sdk\VideoDescriptor.exe')) { throw 'Unexpected installed shortcut target' }
                        $start=[Diagnostics.ProcessStartInfo]::new($target)
                        $start.UseShellExecute=$false;$start.WorkingDirectory=$install
                        [Diagnostics.Process]::Start($start) | Out-Null
                    }
                    Invoke-UI 'desktop' | Out-Null; $stage.evidence=@('desktop.json')
                }
                'whisper' {
                    Invoke-UI 'whisper' -Cached:($cached.Count -gt 0) | Out-Null
                    if ($cached.Count) { $stage.reason='Reused prior short probe proof; fresh CPU preparation and real MP4 UI inference passed';$stage.previous_run=$previous.run_id }
                    $stage.checks=@('cpu-ready',('real-video-'+$plan.interaction.ToLowerInvariant()));$stage.evidence=@('whisper.json')
                }
                'ollama-install' {
                    $obj=@($plan.cache | Where-Object component -eq 'ollama-installer')
                    if (!$obj.Count) { throw 'BLOCKED: register a pinned official ollama-installer cache object; no unpinned latest download is allowed' }
                    $installers=@($obj[0].files | Where-Object { $_.file -like '*.exe' })
                    if ($installers.Count -ne 1) { throw 'BLOCKED: ollama-installer object must contain exactly one installer EXE' }
                    $source=Get-ContainedPath (Get-CachePayload $obj[0]) $installers[0].file
                    $signature=Get-AuthenticodeSignature -LiteralPath $source
                    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Ollama') { throw 'Installer must have a valid Ollama Authenticode signature' }
                    $env:OLLAMA_MODELS=Join-Path $work 'ollama-models'
                    $env:OLLAMA_HOST='127.0.0.1:11434'
                    $env:OLLAMA_NO_CLOUD='1'
                    Invoke-OwnedProcess $source '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG=C:\VD-Results\ollama-install.log' 'ollama-install'
                    $ollama=Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
                    if (!(Test-Path $ollama)) { throw 'Ollama executable absent after install' }
                    if (!(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)) { Start-Process $ollama -ArgumentList 'serve' -WindowStyle Hidden }
                    Invoke-UI 'ollama-install' | Out-Null; $stage.evidence=@('ollama-install.json','ollama-install.log')
                }
                'ollama-model' {
                    $obj=@($plan.cache | Where-Object component -eq 'ollama-model')
                    if ($obj.Count) {
                        if ($obj[0].version -ne $plan.ollama_model) { throw 'BLOCKED: cached Ollama model version does not match plan' }
                        $source=Get-CachePayload $obj[0]
                        New-Item -ItemType Directory -Path $env:OLLAMA_MODELS -Force | Out-Null
                        foreach ($entry in $obj[0].files) {
                            $target=Get-ContainedPath $env:OLLAMA_MODELS $entry.file
                            New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
                            Copy-Item -LiteralPath (Get-ContainedPath $source $entry.file) -Destination $target
                        }
                    } elseif ($plan.network_download) {
                        Invoke-OwnedProcess $ollama ('pull '+$plan.ollama_model) 'ollama-pull' 900
                    } else { throw 'BLOCKED: verified Ollama model cache absent; opt in with -NetworkDownload for real network pull' }
                    Invoke-UI 'ollama-model' | Out-Null; $stage.evidence=@('ollama-model.json','ollama-model.png')
                }
                'ollama-inference' { Invoke-UI 'ollama-inference' | Out-Null; $stage.evidence=@('ollama-inference.json') }
                'translation' { Invoke-UI 'translation' | Out-Null; $stage.evidence=@('translation.json','translation.png','translated.srt') }
                'notes' { Invoke-UI 'notes' | Out-Null; $stage.evidence=@('notes.json','notes.png','notes-report.html') }
                'cleanup' {
                    # Only this isolated installation's processes. Leave the guest visible with reports.
                    $rootPrefix=$install+'\'
                    Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
                    $ollamaRoot=(Join-Path $env:LOCALAPPDATA 'Programs\Ollama')+'\'
                    Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($ollamaRoot,[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
                    $stage.reason='Disposed application processes in this guest; cache and host reports preserved'
                }
            }
            if ($stage.status -ne 'CACHED_PASS') { $stage.status='PASS' }
        } catch {
            $stage.reason=$_.Exception.Message
            $stage.status=if ($stage.reason.StartsWith('BLOCKED:')) {'BLOCKED'} else {'FAIL'}
        } finally {
            if ($plan.interaction -eq 'Api') { $stage.evidence=@($stage.evidence | Where-Object { $_ -notlike '*.png' }) }
            $stage.seconds=[math]::Round($stageClock.Elapsed.TotalSeconds,3);$stage.finished_at=(Get-Date).ToUniversalTime().ToString('o')
            Write-Json $checkpoint @{run_id=$plan.run_id;guest_id=$guestId;attempts=$attempts;phase=$stage.name;state=$stage.status;timestamp=$stage.finished_at}
            Save-Report
        }
    }
    $report.status=if (@($report.stages | Where-Object status -eq 'FAIL').Count) {'FAIL'} elseif (@($report.stages | Where-Object status -eq 'BLOCKED').Count) {'BLOCKED'} else {'PASS'}
} catch {
    if (!$report) { $report=Read-Json (Join-Path $out 'report.json');$report | Add-Member -Force -NotePropertyName error -NotePropertyValue '' }
    $report.status='BLOCKED';$report.error=$_.Exception.Message
} finally {
    try {
        Snapshot-Policy 'final' | Out-Null
        & wevtutil.exe epl Microsoft-Windows-CodeIntegrity/Operational (Join-Path $out 'code-integrity.evtx') /ow:true
    } catch { $_.Exception.Message | Set-Content (Join-Path $out 'diagnostic-error.txt') }
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
    if ($report) {
        if (!$restartPending) { $report.finished_at=(Get-Date).ToUniversalTime().ToString('o') }
        $report.elapsed_seconds=[math]::Round(((Get-Date).ToUniversalTime()-[DateTime]::Parse($report.started_at).ToUniversalTime()).TotalSeconds,3)
        Save-Report
    }
    $mutex.ReleaseMutex();$mutex.Dispose()
    if ($restartPending) { & "$env:WINDIR\System32\shutdown.exe" /r /t 5 }
}
