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
```

`--config-only` checks workflow syntax/contracts and `test_ci_policy.py`, not
Markdown links. Full checks also run Ruff, shared UI/CSS auditing, `node --check`
for both JS directories and the remaining pytest suite. `--unit-only` omits repeated
static checks for OS-specific CI; `--skip-config` assumes configuration was checked.
Missing tools are an error, not permission to silently skip checks or install models.

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
