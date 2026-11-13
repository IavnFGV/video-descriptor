# Testing and CI

Run from the repository root using an existing development environment. On local
Windows, `check-fast.py` requires this checkout's `.venv`; it refuses the system
Python instead of running an incomplete suite. GitHub Actions uses its separately
installed locked runner environment. Full checks
need installed pytest, Ruff, PyYAML, application dependencies and Node.
`scripts/check-actions.py` may fetch pinned actionlint if its verified cache is
missing; it does not install model components. Never use live recordings as test output.

```powershell
.\.venv\Scripts\python.exe scripts/check-fast.py --config-only
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_speech_npu.py tests/test_whisper_resume.py
.\.venv\Scripts\python.exe scripts/check-fast.py
.\.venv\Scripts\python.exe scripts/check-fast.py --workers 4
```

`--config-only` checks workflow syntax/contracts and `test_ci_policy.py`, not
Markdown links. Full checks also run Ruff, shared UI/CSS auditing, `node --check`
for both JS directories and the remaining pytest suite. `--unit-only` omits repeated
static checks for OS-specific CI; `--skip-config` assumes configuration was checked.
Missing tools are an error, not permission to silently skip checks or install models.

The default remains serial. `--workers N` opts into pytest-xdist (installed from
the development or CI requirements); N must be positive. Configuration tests remain
serial. The main suite runs in parallel except `test_desktop.py` and
`test_container_runtime.py`, which run once in a separate serial phase because they
select a port before starting a listener. This isolation cannot prevent interference
from other processes. The script removes inherited `PYTEST_ADDOPTS` from its child
processes so it cannot alter phase selection or parallelism. Other pytest invocations
are unaffected. Platform-dependent skips remain in effect.

## Find regression coverage

| Change | Starting tests under [tests/](../../tests/) |
| --- | --- |
| Timestamps, chunks and resume | `test_speech_npu.py`, `test_whisper_http.py`, `test_whisper_resume.py`, `test_chunks.py` |
| Device/setup | `test_device_policy.py`, `test_diarization_setup.py`, `test_component_manager.py` |
| Editors and variants | `test_speech.py`, `test_speech_undo.py`, `test_editor.py`, `test_recording.py`, `test_versions.py` |
| Queue and locks | `test_jobs_live.py`, `test_job_stop.py`, `test_progress_locking.py` |
| Recovery/model responses | `test_construction_recovery.py`, `test_translation_settings.py`, `test_lmstudio.py`, `test_model_behavior.py` |
| Audit | `test_action_journal.py`, `test_request_journal.py` |
| Windows and source preview | `test_windows_runtime.py`, `test_run_dev.py`, `test_desktop.py` |
| Packaging/public gates | `test_windows_release.py`, `test_release_packaging.py`, `test_public_release_policy.py`, `test_local_build.py` |

Inspect fixtures and platform skips before selecting tests. Cover observable
failures/data preservation rather than copying implementation strings. Use synthetic
data and temporary storage; never embed private transcripts or credentials.

## Workspace preferences and compatibility

[WORKSPACE-TABS](../../design-system/WORKSPACE-TABS.md#тестовая-матрица-task-7)
contains the authoritative compatibility matrix and the distinction between current
characterization and future production browser gates. Run the offline v1 harness:

```powershell
node tests/workspace_view.cjs
.\.venv\Scripts\python.exe -m pytest -q tests/test_workspace_view.py
```

It covers 256 panel/layout combinations, read-without-write, URL-neutral preference
loading, invalid/partial values, separate storage read/write failures, reset/reload,
storage events and embedded mode. It does not execute studio/recording routing,
workspace tabs, DOM geometry, editor guards or Back/Forward. Task 7 changed the
contract and characterization only; Task 8a adds the first production slice.

The isolated Edge fixture for the 8a tabs and existing workspace controls is:

```powershell
.\.venv\Scripts\python.exe scripts/verify-recording-ui.py --workspace-tabs-only
.\.venv\Scripts\python.exe scripts/verify-recording-ui.py --workspace-view-only
```

These checks do not establish guarded history, installed WebView2 or hardware acceptance.

## Workspace tabs prototype

Task 6 is a standalone [layout prototype](../../design-system/prototype/workspace-tabs.html),
not production workspace integration. Open the HTML directly for manual exploration.
With existing Edge and development dependencies on Windows:

```powershell
.\.venv\Scripts\python.exe scripts/verify-workspace-prototype.py
```

The driver starts a temporary loopback static server and isolated headless Edge,
then closes both. It uses no application backend, models or recordings. It checks
five viewport sizes, ready/empty/busy/error, three workspace areas, nested material
tabs, keyboard/focus, persistent DOM/draft and mock stop/recovery. Runtime traps
reject API, storage and history calls. Full-page screenshots and `result.json` go
to ignored `windows-app/runtime/zero-config/workspace-prototype/`; `--output` sets
an alternate evidence directory. Review captures as well as assertions. Forced
colors and a zoom-equivalent viewport are fixtures, not Windows scaling or
installed WebView2 acceptance. The media element has no source; actual playback,
iframe editing, independent versions and dirty/revision/Undo guards are outside
this prototype. Existing production material/workspace scenarios remain in
`scripts/verify-recording-ui.py`.

## CI and evidence

[ci.yml](../../.github/workflows/ci.yml) runs on PR/main push and routes changed paths
through [ci_changes.py](../../scripts/ci_changes.py). Markdown-only changes use
configuration/policy checks; `opencode.json` selects Fast because it is not Markdown.
Conditional Windows/container smoke is not evidence of NPU/GPU inference.

[Full Acceptance](../../.github/workflows/full-acceptance.yml) is explicit integration/
release validation. Windows release calls it with `windows_only=true`. Installed
checks include real CPU recognition, installer lifecycle and reproducibility. A
disposable LLM HTTP fixture checks integration, not inference or output quality.
Real model evaluation is separate: [model-behavior.yml](../../.github/workflows/model-behavior.yml)
and [model behavior](../model-behavior.md).

Use [Sandbox](../windows-sandbox.md) for clean-environment checks and
[device verification](../verification-devices.md) for hardware evidence. State the
version/machine/backend actually tested. Never dispatch release workflows to debug
local lint. The [CI policy](../ci-policy.md) contains dated audits; current YAML
defines actual triggers.
