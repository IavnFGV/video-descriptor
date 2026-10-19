[CmdletBinding()]
param(
    [ValidateSet('Run','Status','Report','Clean')][string]$Action='Run',
    [ValidateSet('Security','Functional')][string]$Profile='Security',
    [ValidateSet('all','preflight','installer','desktop','whisper','ollama-install','ollama-model','ollama-inference','translation','notes','cleanup')][string[]]$Stage=@('all'),
    [switch]$FailedOnly, [switch]$Force, [switch]$PrepareOnly,
    [ValidateSet('Verified','None')][string]$Cache='Verified', [switch]$NetworkDownload,
    [switch]$AllowGuestEvaluation,
    [ValidateSet('Off','Evaluation')][string]$GuestSacMode='Off',
    [ValidateSet('UI','Api')][string]$Interaction='Api',
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,150}$')][string]$OllamaModel='qwen3.5:9b',
    [string]$CacheDirectory,
    [string]$RunsDirectory,
    [ValidateRange(60,14400)][int]$TimeoutSeconds=1800
)
. "$PSScriptRoot\Acceptance.Common.ps1"
if (!$CacheDirectory) { $CacheDirectory=Join-Path $PSScriptRoot '..\runtime\acceptance-cache-v2' }
if (!$RunsDirectory) { $RunsDirectory=Join-Path $PSScriptRoot '..\runtime\acceptance' }
$project = Split-Path (Split-Path $PSScriptRoot)
New-Item -ItemType Directory -Force -Path $RunsDirectory | Out-Null
$RunsDirectory = (Resolve-Path -LiteralPath $RunsDirectory).Path
$previous = @(Get-ChildItem -LiteralPath $RunsDirectory -Directory | Sort-Object Name -Descending | Where-Object {
    $candidate = Join-Path $_.FullName 'reports\report.json'
    (Test-Path -LiteralPath $candidate) -and (Read-Json $candidate).profile -eq $Profile
})
$last = if ($previous.Count) { Join-Path $previous[0].FullName 'reports\report.json' } else { $null }
if ($Action -in @('Status','Report')) {
    if (!$last) { throw "No $Profile report" }
    if ($Action -eq 'Report') { Get-Content -LiteralPath $last -Raw } else {
        $r=Read-Json $last; $r | Select-Object run_id,profile,status,started_at,finished_at; $r.stages | Format-Table name,status,reason
    }
    return
}
if ($Action -eq 'Clean') {
    # Only our generated input snapshots; reports, cache and unrelated Sandboxes survive.
    foreach ($dir in $previous) {
        $r=Read-Json (Join-Path $dir.FullName 'reports\report.json')
        if ($r.status -in @('RUNNING','PREPARED')) { continue }
        $target=Get-ContainedPath $RunsDirectory ($dir.Name + '\input')
        if (Test-Path -LiteralPath $target) {
            foreach ($path in @($RunsDirectory,$dir.FullName)) {
                if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing cleanup through a link' }
            }
            Assert-PlainTree $target
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
    return
}
$requested = if ($Stage -contains 'all') { if ($Profile -eq 'Security') { @('preflight','installer','cleanup') } else { $StageOrder } } else { $Stage }
if ($FailedOnly) {
    if (!$last) { throw 'FailedOnly needs a previous report for this profile' }
    $requested=@((Read-Json $last).stages | Where-Object { $_.status -in @('FAIL','BLOCKED') } | ForEach-Object { $_.name })
    if (!$requested.Count) { Write-Output 'No failed or blocked stages'; return }
}
$selected=Get-StageClosure $requested
$runId=(Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + $Profile.ToLowerInvariant()
$run=Join-Path $RunsDirectory $runId
$inputDirectory=Join-Path $run 'input'; $reports=Join-Path $run 'reports'
New-Item -ItemType Directory -Path $inputDirectory,$reports -Force | Out-Null
$artifacts=@(Read-Json (Join-Path $project 'dist\SHA256SUMS.json'))
Test-ObjectFiles (Join-Path $project 'dist') $artifacts
foreach ($artifact in $artifacts) { Copy-Item -LiteralPath (Join-Path $project ('dist\'+$artifact.file)) -Destination $inputDirectory }
Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object { $_.Extension -in @('.ps1','.py','.json','.wsb') } | Copy-Item -Destination $inputDirectory
Copy-Item -LiteralPath (Join-Path $project 'windows-app\verify_release.py') -Destination $inputDirectory
Copy-Item -LiteralPath (Join-Path $project 'windows-app\verify_installed.py') -Destination $inputDirectory
$objects=@()
$neededComponents=@()
if ($selected -contains 'whisper' -and !$NetworkDownload) { $neededComponents+='whisper-model' }
if ($selected -contains 'ollama-install') { $neededComponents+='ollama-installer' }
if ($selected -contains 'ollama-model' -and !$NetworkDownload) { $neededComponents+='ollama-model' }
if ($Cache -eq 'Verified' -and (Test-Path -LiteralPath $CacheDirectory)) {
    $CacheDirectory=(Resolve-Path -LiteralPath $CacheDirectory).Path
    foreach ($dir in Get-ChildItem -LiteralPath $CacheDirectory -Directory | Sort-Object Name) {
        $manifest=Join-Path $dir.FullName 'cache-object.json'
        if (!(Test-Path -LiteralPath $manifest)) { continue }
        $obj=Read-Json $manifest
        if ($obj.id -ne $dir.Name -or $obj.schema -ne 1) { throw 'Invalid cache object manifest' }
        if ($obj.component -notin $neededComponents) { continue }
        if ($NetworkDownload -and $obj.component -in @('whisper-model','ollama-model')) { continue }
        $objects+= $obj
    }
    if (@($objects | Group-Object component | Where-Object Count -gt 1).Count) { throw 'Keep exactly one version per cache component in the selected cache directory' }
}
$harness=@(Get-ChildItem -LiteralPath $inputDirectory -File | Where-Object Extension -in @('.ps1','.py','.json','.wsb') | Sort-Object Name | ForEach-Object {
    @{file=$_.Name;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
$sha=(& git -C $project rev-parse HEAD).Trim()
$dirty=(& git -C $project status --porcelain | Out-String).Trim()
$fingerprint=Get-TextHash (ConvertTo-CanonicalJson @{artifacts=$artifacts;harness=$harness;cache=$objects;profile=$Profile;model=$OllamaModel;network_download=[bool]$NetworkDownload;git_sha=$sha;sac_mode=$GuestSacMode;interaction=$Interaction})
$history=@()
if (!$Force -and !$NetworkDownload) {
    foreach ($dir in $previous) {
        $r=Read-Json (Join-Path $dir.FullName 'reports\report.json')
        if ($r.fingerprint -eq $fingerprint -and $r.status -ne 'RUNNING') { $history+= $r; break }
    }
}
Write-Json (Join-Path $inputDirectory 'plan.json') @{
    schema=1; run_id=$runId; profile=$Profile; selected=$selected; requested=@($requested)
    git_sha=$sha; git_dirty=[bool]$dirty; artifacts=$artifacts; fingerprint=$fingerprint
    cache=$objects; network_download=[bool]$NetworkDownload; allow_guest_evaluation=[bool]$AllowGuestEvaluation
    ollama_model=$OllamaModel; history=$history; max_resume_attempts=2; timeout_seconds=$TimeoutSeconds
    contracts=(Read-Json (Join-Path $PSScriptRoot 'stage-contracts.json')); harness=$harness
    guest_sac_mode=$GuestSacMode;interaction=$Interaction
    guest_sac_off_authorization='Ivan explicitly authorized guest-only SAC Off and guest restart for disposable application testing on 2026-10-19'
}
Write-Json (Join-Path $reports 'report.json') @{
    run_id=$runId;profile=$Profile;git_sha=$sha;fingerprint=$fingerprint;status='PREPARED'
    started_at=(Get-Date).ToUniversalTime().ToString('o');finished_at=$null;elapsed_seconds=0;error=$null
    stages=@($StageOrder | ForEach-Object { @{name=$_;status='NOT_TESTED';reason='Guest has not started'} })
}
$esc={ param($v) [Security.SecurityElement]::Escape($v) }
$mappings="<MappedFolder><HostFolder>$(& $esc $inputDirectory)</HostFolder><SandboxFolder>C:\VD-Acceptance</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder><MappedFolder><HostFolder>$(& $esc $reports)</HostFolder><SandboxFolder>C:\VD-Results</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>"
if ($objects.Count) { $mappings+="<MappedFolder><HostFolder>$(& $esc $CacheDirectory)</HostFolder><SandboxFolder>C:\VD-Cache</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>" }
$wsb=Join-Path $run 'Acceptance.wsb'
$template=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Acceptance.template.wsb') -Raw
$template.Replace('@@MAPPED_FOLDERS@@',$mappings) | Set-Content -LiteralPath $wsb -Encoding UTF8
Write-Output "Run: $runId`nReports: $reports`nConfiguration: $wsb"
if ($Profile -eq 'Functional' -and $GuestSacMode -eq 'Off') {
    Write-Output 'Functional test: SAC Off is confined to the disposable guest; one guest restart may be performed. Host security and host reboot are excluded.'
}
if ($PrepareOnly) { return }
$sandbox=Join-Path $env:WINDIR 'System32\WindowsSandbox.exe'
if (!(Test-Path -LiteralPath $sandbox)) { throw 'Windows Sandbox unavailable; no host components were changed' }
$cli=Get-Command wsb.exe -ErrorAction SilentlyContinue
function Invoke-SandboxCli([string]$Arguments, [string]$Label) {
    $stdout=Join-Path $reports ($Label+'.json');$stderr=Join-Path $reports ($Label+'.stderr.log')
    # -Wait waits the entire activation process tree, including the long-lived
    # Sandbox broker on some Store builds. Wait only for this CLI process.
    $p=Start-Process -FilePath $cli.Source -ArgumentList $Arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $null=$p.Handle
    if (!$p.WaitForExit(15000)) { throw "Sandbox CLI timeout: $Label" }
    $p.WaitForExit();$p.Refresh()
    if ($p.ExitCode -ne 0) { throw "Sandbox CLI failed: $Label; see $stderr" }
    if ($Label -like '*list*') { Read-Json $stdout }
}
try {
    if ($cli) {
        $active=Invoke-SandboxCli 'list --raw' 'wsb-list-before'
        foreach ($instance in $active.WindowsSandboxEnvironments) {
            $owned=$false
            foreach ($directory in Get-ChildItem -LiteralPath $RunsDirectory -Directory) {
                $instanceFile=Join-Path $directory.FullName 'sandbox-instance.json'
                $oldReport=Join-Path $directory.FullName 'reports\report.json'
                if (!(Test-Path -LiteralPath $instanceFile) -or !(Test-Path -LiteralPath $oldReport)) { continue }
                $identity=Read-Json $instanceFile
                if ($identity.id -ne $instance.Id -or $identity.project -ne $project) { continue }
                $old=Read-Json $oldReport
                if ($old.status -in @('PREPARED','RUNNING')) { throw ('Another harness run is active: '+$old.run_id) }
                Invoke-SandboxCli ('stop --id '+$instance.Id) 'wsb-stop-previous' | Out-Null
                $owned=$true;break
            }
            if (!$owned) { throw 'An unrelated or untracked Sandbox is active. It was not stopped; cannot guarantee a fresh guest.' }
        }
    } elseif (Get-Process WindowsSandboxRemoteSession -ErrorAction SilentlyContinue) {
        throw 'A Sandbox is already active and wsb CLI is unavailable; cannot identify and dispose a previous harness guest safely.'
    }
    Start-Process -FilePath $sandbox -ArgumentList ('"'+$wsb+'"')
} catch {
    $r=Read-Json (Join-Path $reports 'report.json');$r.status='BLOCKED';$r.error=$_.Exception.Message
    $r.finished_at=(Get-Date).ToUniversalTime().ToString('o')
    foreach ($s in $r.stages) { if ($s.name -in $selected) { $s.status='BLOCKED';$s.reason=$r.error } }
    Write-Json (Join-Path $reports 'report.json') $r
    throw
}
$deadline=(Get-Date).AddSeconds($TimeoutSeconds)
$recorded=$false
$resumeProbe=Get-Date
do {
    Start-Sleep -Seconds 2
    $r=Read-Json (Join-Path $reports 'report.json')
    if ($cli -and !$recorded -and $r.run_id -eq $runId -and $r.guest_id) {
        try {
            $running=Invoke-SandboxCli 'list --raw' 'wsb-list-after'
            $instances=@($running.WindowsSandboxEnvironments)
            if ($instances.Count -eq 1) {
                Write-Json (Join-Path $run 'sandbox-instance.json') @{id=$instances[0].Id;run_id=$runId;project=$project}
                $recorded=$true
            }
        } catch { Write-Warning 'Could not record Sandbox ID yet; bootstrap reports remain authoritative.' }
    }
    if ($cli -and $recorded -and $r.restart -and !$r.restart.after_boot -and (Get-Date) -ge $resumeProbe) {
        try {
            $identity=Read-Json (Join-Path $run 'sandbox-instance.json')
            Invoke-SandboxCli ('exec --id '+$identity.id+' --run-as ExistingLogin --command "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\VD-Acceptance\Resume-Acceptance.ps1"') 'wsb-resume' | Out-Null
        } catch { Write-Warning 'Guest reboot/login is still pending; no additional reboot was requested.' }
        $resumeProbe=(Get-Date).AddSeconds(15)
    }
    if ($r.status -notin @('PREPARED','RUNNING')) { $r.stages | Format-Table name,status,reason; Write-Output "Result: $($r.status)"; if ($r.status -ne 'PASS') { exit 2 }; return }
} while ((Get-Date) -lt $deadline)
# Never stop a different Sandbox or pretend guest-local state survived disappearance.
Write-Json (Join-Path $reports 'host-timeout.json') @{run_id=$runId;timeout_seconds=$TimeoutSeconds;timestamp=(Get-Date).ToUniversalTime().ToString('o');reason='Host deadline expired'}
$r.status='BLOCKED'; $r | Add-Member -Force -NotePropertyName host_error -NotePropertyValue 'Guest did not finish before deadline; guest may have been destroyed. No automatic relaunch.'
$r | Add-Member -Force -NotePropertyName finished_at -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o')
foreach ($s in $r.stages) { if ($s.status -eq 'NOT_TESTED') { $s.status='BLOCKED';$s.reason=$r.host_error } }
Write-Json (Join-Path $reports 'report.json') $r
exit 2
