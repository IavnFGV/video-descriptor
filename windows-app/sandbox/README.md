# Windows Sandbox acceptance harness

Run from the repository root on Windows with Windows Sandbox already available.
The entry point works with Windows PowerShell 5.1 and does not require host Python,
Docker, model installation, security changes, or a host reboot. Existing
`Prepare-Sandbox.ps1` remains available for the historical release smoke test.

```powershell
# Standard security policy: verify unsigned installer rejection and diagnostics.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Security

# Complete functional plan in a separate disposable guest.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Functional -AllowGuestEvaluation

# Ollama alone does not depend on Whisper or download its 470 MiB model.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Functional -Stage ollama-inference -AllowGuestEvaluation

# A translation test adds only its actual dependencies.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Functional -Stage translation -AllowGuestEvaluation

# Retry failed/BLOCKED stages with required clean-guest provisioning.
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/sandbox/Run-Acceptance.ps1 -Profile Functional -FailedOnly -AllowGuestEvaluation

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

## SAC profiles and the actual environment limit

Security keeps the guest's standard protection policy. PASS requires the rejected
installer and a matching Code Integrity 3033/3077 event, not merely a nonzero exit.
Only `preflight`, `installer`, and `cleanup` run by default in this profile.
The Windows refusal message and raw event XML are retained.

Functional requires a currently enforced Microsoft
`VerifiedAndReputableDesktopEvaluation`, `...EvaluationAudit`, or
`...EvaluationAuditNoISG` policy reported by CiTool. `-AllowGuestEvaluation` records
owner authorization; it does **not** assert that this mode is available or turn off
SAC. The harness does not change protected file owners/ACLs, replace EFI policies,
disable Defender/Firewall, alter boot settings, or reboot Windows.

Microsoft's current [SAC testing procedure](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control)
requires recovery for forced mode switching; its audit setup requires ownership/ACL
or EFI changes. Those procedures are outside the constraints of this task. If the
guest does not already expose a supported Evaluation/Audit mode, Functional returns
BLOCKED with the policy snapshots and Code Integrity log. It never substitutes the
historical guest SAC-Off tests for this profile.

Observed 19 October 2026: stock guest build 26100 reports registry SAC state 1 and
blocks this unsigned preview (event 3033). `CiTool --list-policies --json` returns
`OperationResult: -2147009597` / `0x80073BC3`, including a separate System-context
diagnostic. Consequently Security PASS is based on correlated actual enforcement;
Functional is BLOCKED and its UI/Ollama stages have not been executed by this harness.

## Stages, evidence, and reuse

[`stage-contracts.json`](stage-contracts.json) defines each stage's inputs,
dependencies, method and PASS criteria; a copy is embedded in every guest report.
The stage DAG selects prerequisites automatically. No HTTP write substitutes for a
UI action: the UI driver uses the installed Start Menu shortcut, real WebView2,
pointer events, form fields and a native file input. API reads and saved files
collect evidence. `ollama-inference` is explicitly a diagnostic API generation;
translation/notes exercise the actual application UI. Ollama installation and model
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

Default: `windows-app/runtime/acceptance-cache`, outside the guest and ignored by
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
profile, OS, stages, reasons, elapsed times and linked evidence. Screenshots and UI
JSON are written after each executed stage, including failures. Code Integrity
EVTX and initial/final SAC/CiTool snapshots are written before final completion.

Checkpoint is saved before and after each stage. Re-running bootstrap in a
surviving guest is bounded to two attempts and reprovisions dependencies; a mutex
prevents concurrent guest runners. A guest-local identity is compared with the
host checkpoint. If that identity disappears, a reopened `.wsb` returns BLOCKED
instead of pretending the old installation survived. No automatic reboot is
currently needed or issued: the unsupported SAC transition stops before mutation.
No claim of reboot recovery is made without an actual surviving guest.

The WebView2 driver requires loopback DevTools port 9222, enabled only in this
disposable guest's application process tree. It has protocol/unit coverage but
its real functional execution is blocked by the policy condition above. Functional
acceptance and the requested Ollama → generation → translation → notes outcome
remain unverified until a permitted test environment is available. Unit tests do
not count as those acceptance results. This harness does not prove GPU/NPU support,
editor/export lifecycle, tray persistence or readiness for a public release.
