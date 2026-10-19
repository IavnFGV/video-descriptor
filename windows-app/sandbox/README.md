# Windows Sandbox acceptance harness

Run from the repository root on Windows with Windows Sandbox already available.
The entry point works with Windows PowerShell 5.1 and does not require host Python,
Docker, model installation, security changes, or a host reboot. Existing
`Prepare-Sandbox.ps1` remains available for the historical release smoke test.

```powershell
# Standard security policy: verify unsigned installer rejection and diagnostics.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Security

# Complete functional plan in a separate disposable guest.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Functional -GuestSacMode Off -Interaction Api -OllamaModel qwen3.5:0.8b

# Ollama alone does not depend on Whisper or download its 470 MiB model.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Functional -Stage ollama-inference -OllamaModel qwen3.5:0.8b

# A translation test adds only its actual dependencies.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Functional -Stage translation -OllamaModel qwen3.5:0.8b

# Retry failed/BLOCKED stages with required clean-guest provisioning.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Functional -FailedOnly -OllamaModel qwen3.5:0.8b

powershell -NoProfile -File windows-app/sandbox/Run-Acceptance.ps1 -Action Status -Profile Functional
powershell -NoProfile -File windows-app/sandbox/Run-Acceptance.ps1 -Action Report -Profile Functional
powershell -NoProfile -File windows-app/sandbox/Run-Acceptance.ps1 -Action Clean
```

`-PrepareOnly` creates the input snapshot, plan, early report, and official `.wsb`
without launching. Open that `.wsb` later to execute its `<LogonCommand>`.
`-TimeoutSeconds` bounds the host wait (default 1800, range 60–14400);
exit code 0 means PASS, 2 means FAIL/BLOCKED. Preparation errors return a nonzero
PowerShell exit code. No missing report is accepted as success. The guest remains
visible after completion; closing it destroys guest files. On the next invocation,
`wsb` CLI identifies and disposes only a completed guest recorded by this harness
before creating a fresh one. Active runs, unrelated and untracked guests cause
BLOCKED; they are not stopped. This prevents the native single-instance Sandbox
launcher from silently reusing the previous guest. Without `wsb`, an existing guest
must first be closed. `Clean` removes only input snapshots of completed runs for the
selected profile; it preserves reports, cache, and PREPARED/RUNNING inputs and
refuses links/junctions.

## SAC profiles and guest restart

Security keeps the guest's standard protection policy. PASS requires the rejected
installer and a matching Code Integrity 3033/3077 event, not merely a nonzero exit.
Only `preflight`, `installer`, and `cleanup` run by default in this profile.
The Windows refusal message and raw event XML are retained.

Functional defaults to `-GuestSacMode Off` under Ivan's explicit authorization.
The bootstrap verifies WDAGUtilityAccount, Hyper-V VM and CExecSvc. It records the
initial state, sets only guest SAC to Off, saves a host checkpoint and registers a
guest RunOnce continuation. It reboots that Sandbox at most once. The host also
has an idempotent CLI resume fallback. Guest identity and boot times must survive;
a lost guest or failed setting becomes BLOCKED, with no repeated reboot loop.
Actual installer execution and inference verify functionality; registry state alone
is not a functional PASS. Host Windows, Defender, firewall, ACL/ownership and boot
policies are not changed. The host is never rebooted.

Microsoft's current [SAC testing procedure](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control)
requires recovery for forced mode switching; its audit setup requires ownership/ACL
or EFI changes. Those procedures are outside the constraints of this task. If the
guest does not already expose a supported Evaluation/Audit mode, the separately
selected `-GuestSacMode Evaluation` still returns BLOCKED. Mode and fingerprints
distinguish this stricter profile from authorized guest SAC Off and default Security.

Observed 19 October 2026: stock guest build 26100 reports registry SAC state 1 and
blocks this unsigned preview (event 3033). `CiTool --list-policies --json` returns
`OperationResult: -2147009597` / `0x80073BC3`, including a separate System-context
diagnostic. The historical Evaluation-only run was BLOCKED. The later guest-Off API
run passed automatic SAC preparation, same-guest reboot/resume, installation, model
detection and real CPU transcription. Historical reports are preserved separately.

## Stages, evidence, and reuse

[`stage-contracts.json`](stage-contracts.json) defines each stage's inputs,
dependencies, method and PASS criteria; a copy is embedded in every guest report.
The stage DAG selects prerequisites automatically. `-Interaction Api` is the default
for scripts: it uses the installed application's real API, worker and saved files
and does not claim UI coverage. `-Interaction UI` uses real WinForms/WebView2
pointer/form actions, the installed shortcut target and a native file input.
`ollama-inference` is explicitly an API generation diagnostic. Ollama installation and model
provisioning use CLI preparation, not an assertion that the product has installer
or model-download buttons (the current product has only model selection controls).

Reports distinguish PASS, CACHED_PASS, FAIL, BLOCKED and NOT_TESTED. Dependencies
blocked by a prerequisite carry its stage name. Unselected stages stay NOT_TESTED.
Every new guest physically installs the preview and dependencies. A PASS in another
guest never establishes their presence. The existing installer provisions WebView2;
this harness does not reimplement that behavior.

Reuse requires the same artifact SHA256s, Git SHA, harness/contract hashes, cache
manifests, profile, model selection, OS and policy fingerprint. `-Force` disables
reuse. A previous full installer lifecycle proof can yield CACHED_PASS after a
fresh guest install and presence checks. A prior short Whisper WAV probe may be
skipped, but CPU preparation and the real bundled MP4 UI transcription still run
and receive PASS with an explicit probe-skip reason. Installer lifecycle is not run
when `installer` is merely a dependency of an Ollama/UI stage. Ordinary UI and
generation tests always run. The separate synthetic WAV is not played repeatedly
when its exact proof applies. Lifecycle verification of thousands of ZIP members
runs only when explicitly selected and not reusable; artifact/model integrity
checks still run before use.

## Verified external cache

Default: `windows-app/runtime/acceptance-cache-v2`, outside the guest and ignored by
Git. `-CacheDirectory` selects a different dedicated test cache. `-Cache None`
omits it. `-NetworkDownload` explicitly exercises real model download/pull, omits
model cache objects and disables result reuse; a pinned installer may still be
used as it is not the model-download subject. Without model cache or this opt-in,
the model-dependent stage reports BLOCKED.

Register **only dedicated public test assets**, never a user's entire model store:

```powershell
powershell -NoProfile -File windows-app/sandbox/Register-TestCache.ps1 `
  -SourcePath C:\public-test-assets\whisper-small `
  -Component whisper-model -Version 2410d022171ca8a97343182f88eec8807a324db9 `
  -Source https://huggingface.co/OpenVINO/whisper-small-fp16-ov

powershell -NoProfile -File windows-app/sandbox/Register-TestCache.ps1 `
  -SourcePath C:\public-test-assets\OllamaSetup.exe `
  -Component ollama-installer -Version '<pinned release>' `
  -Source 'https://github.com/ollama/ollama/releases/download/<release>/OllamaSetup.exe'

powershell -NoProfile -File windows-app/sandbox/Register-TestCache.ps1 `
  -SourcePath C:\public-test-assets\ollama-test-models `
  -Component ollama-model -Version 'qwen3.5:9b' `
  -Source https://ollama.com/library/qwen3.5
```

Object bytes live in `payload/`, separately from their metadata JSON. This prevents
cache metadata from contaminating Whisper's model digest. Re-register old flat
cache objects into v2; do not put their metadata inside a model directory.
Each object records component, version, HTTPS upstream, acquisition time, total
size and each file's SHA256/size. Registration copies and verifies the chosen
assets; it records provenance, not independent proof of upstream authenticity.
Use the pinned component manifest for official Whisper provenance. Ollama installer
execution additionally requires valid Ollama Authenticode. An Ollama model object
must contain only the selected test model's `manifests/` and referenced `blobs/`,
with blob filenames matching Ollama's content digests. The selected tag must match
the cache object's version; the guest records the actual `/api/tags` digest.
`-OllamaModel` selects a model; default `qwen3.5:9b` matches the existing application's
configuration. This new harness has not validated that model in a functional guest.

Keep one object per component in a selected cache directory. The guest receives
the cache read-only and verifies every selected file before use. Ollama's service
uses a guest-local copy because it requires a writable model directory. Downloaded
models are guest-local; there is no automatic publication of arbitrary guest
downloads into the host's trusted cache. To persist new downloads, explicitly
export only public test artifacts before destroying the guest, then register them.

## Checkpoints, logs and limitations

Default runs: `windows-app/runtime/acceptance/<run-id>/`. Only the frozen input
snapshot (read-only), optional cache (read-only), and run-specific reports
(writable) are mapped. The checkout, `.env` files and private model stores are not
shared. The report records Git SHA/dirty flag, exact artifact identity, contracts,
profile, OS, stages, reasons, elapsed times and linked evidence. The UI driver writes
screenshots and UI JSON; the API driver writes JSON and exported results. Code Integrity
EVTX and initial/final SAC/CiTool snapshots are written before final completion.

Checkpoint is saved before and after each stage. Re-running bootstrap in a
surviving guest is bounded to two attempts and reprovisions dependencies; a mutex
prevents concurrent guest runners. A guest-local identity is compared with the
host checkpoint. If that identity disappears, a reopened `.wsb` returns BLOCKED
instead of pretending the old installation survived. Guest SAC Off requests at most
one guest reboot; successful resume records the same guest ID and different boot
times. Closing the Sandbox still destroys its local state.

The WebView2 driver requires loopback DevTools port 9222, enabled only in this
disposable guest's application process tree. The initial UI attempt found a shortcut
environment-inheritance problem; the launcher now starts the shortcut target with
the explicit test environment. API PASS does not establish that this UI path works.
Unit tests are not acceptance evidence. This harness does not prove GPU/NPU support,
editor/tray persistence, language-model quality or readiness for a public release.

## Installed API checks and CI

`windows-app/verify_installed.py --installer <setup.exe> --zip <matching.zip>
--model <public-Whisper-fixture> --output <report.json>` installs into a fresh test
directory, verifies the release manifest and critical file hashes, starts the
installed Python/backend on isolated loopback ports, detects the model and performs
real CPU transcription of the bundled MP4. It validates text/timestamps and stops
only that test copy's processes, then uninstalls the test copy. It refuses an
existing registered application so it cannot overwrite a developer installation.
`--with-ollama --ollama-url <loopback> --ollama-model <tag>` adds real generation,
translation, saved notes/chapters/report and API subtitle export checks.

Windows CI already had unit/API tests, WebView2 smoke, reproducible ZIP and installer
lifecycle. It now also caches/verifies the pinned public Whisper fixture and runs
the installed-build CPU API check on every normal Windows job. Real Ollama checks
are opt-in via workflow_dispatch `test_ollama=true`; they download a SHA256-pinned,
signed public Ollama installer and the explicitly selected public model into CI-only
directories. Reports and failure evidence are uploaded with `if: always()`.
No SAC changes are made on hosted CI runners, and Sandbox/nested virtualization is
not required there. CI changes still need push/dispatch before a remote run exists.

[`Acceptance.template.wsb`](Acceptance.template.wsb) is the committed source of
generated run configurations. The repository root [`sandbox.wsb`](../../sandbox.wsb)
is also committed as the owner's historical manual configuration, with its original
machine-specific read-only mappings; it is not the automatic harness entry point.


## Automatic production workspace UI acceptance

Windows CI now calls verify_installed.py --ui after building the exact installer.
A fresh marked installation runs real CPU inference via its embedded Python,
then launches its real WebView2 and uploads the bundled MP4 through the file input.
The driver edits and saves a reply, checks revision/timestamps/dirty Escape,
Back/Forward and AI round trips, independent prompt drafts, keyboard stage focus,
actual SRT/VTT/TXT downloads, four viewports and a labelled visual stress fixture.
Optional --with-ollama adds real UI translation/notes and Markdown/HTML export.
Reports and screenshots are included in the normal CI artifact. No manual clicks
or public GitHub Release are needed. Existing scheduled dispatch options remain.
The same verifier is included in Sandbox UI whisper/notes stages. API and UI
results remain separate, and transport failures are not counted as application PASS.

PnP visibility is not inference capability: in the 19 October UI guest Windows
listed Intel AI Boost and Arc 140V, while OpenVINO exposed only CPU. That guest
does not establish NPU/GPU support; diagnostics explicitly distinguish the layers.

The Windows workflow also runs on a published release event. On that event the
cached public qwen3.5:0.8b Ollama scenario is enabled automatically, including API
and actual installed UI generation, translation, notes and exports. PR/main runs
always perform CPU/UI acceptance; manual dispatch can request the same full AI
suite. This configures verification, and does not create or publish a release.

Elevated WebView2 ignores WEBVIEW2_* environment overrides (Microsoft security
behavior). The driver therefore uses --ui-test-port=9222 with the installed host;
a .acceptance-installation.json marker is required. The host validates the port
and passes loopback-only flags through SDK environment options. Normal launches
leave this disabled. The fresh-guest bootstrap creates the marker only after
installation. No HKCU/HKLM policy or host setting is changed.
