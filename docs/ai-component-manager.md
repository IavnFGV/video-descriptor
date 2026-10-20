# AI Component Manager — Windows

AI Settings retains the existing Whisper controls and adds Ollama installation/model pulls,
pyannote preparation, per-component checks, cancellation, retries, a readiness summary and
managed-environment removal with confirmation. Optional components do not block transcription.

## Runtime and model provenance

- Whisper: existing pinned OpenVINO small FP16 manifest, per-file SHA256, engine digest,
  built-in speech WAV and existing Auto NPU → GPU → CPU selection.
- Ollama: official standalone Windows ZIP, version 0.40.6, GitHub release asset SHA256
  pinned in component-manifest.json. Signed executables must have valid Authenticode;
  upstream unsigned executables are accepted only with the pinned archive hash.
  Existing HTTP services are reused. An existing executable may run as an app-owned
  instance; otherwise the official ZIP is staged and atomically renamed. A private
  loopback service uses a separate model directory. No Windows service/UAC is required.
- CPython: full 3.12.15 x64 python-build-standalone release 20261013 from Astral,
  upstream release asset SHA256 pinned. This is a third-party CPython distribution,
  not the embeddable runtime and not an official python.org installer. It supports venv.
- pyannote: distinct CPU/XPU environments with complete version locks captured from
  the verified native Windows environments. Existing diarization_worker performs real
  inference and validates turns before settings change. Explicit XPU cannot fall back;
  Auto tries XPU for Intel adapters, then actually tests CPU and records the reason.
- community-1: revision 3533c8cf8e369892e6b79ff1bf80f7b0286a54ee; model weights use
  upstream LFS SHA256 and config uses the pinned Git blob digest. No mutable main download.

Sources: [Ollama Windows](https://github.com/ollama/ollama/blob/main/docs/windows.mdx),
[Ollama release](https://github.com/ollama/ollama/releases/tag/v0.40.6),
[standalone CPython](https://github.com/astral-sh/python-build-standalone/releases/tag/20261013),
[community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).

## Consent and credentials

Downloads and managed removal require explicit UI confirmation. Model selection shows
approximate disk/RAM requirements and intended use; a small test model is described as
limited for long translations. `/api/pull` reports real streamed progress. A model is
selected for translation/notes only after tags, completion capability and real generation.

Hugging Face access/terms remain the user's responsibility. The UI opens fixed official
pages in the system browser. 401/403 explains authorization rather than a technical crash.
The read token is encrypted with Windows current-user DPAPI, never returned by GET or
included in acceptance evidence. No security bypass is built into the manager.

## Files, recovery, updates

Mutable files live under `%LOCALAPPDATA%\VideoDescriptor\ai-components`:
`state.json`, `downloads`, `models`, `community-1-<revision>`, `cpython-<version>`,
`pyannote-<device>-<unique-id>`, `ollama-<version>`, `ollama-models`, and `checks`.
Normal Windows user-profile inherited ACLs apply. Models/environments survive application
upgrade and managed runtime removal retains models. Existing external environments are
never deleted. Interrupted states become retryable errors; previous successful proof is
retained, and startup requests a new check rather than presenting stale proof as live readiness.

The downloader resumes interrupted archives with Range and verifies final size/hash.
Whisper/HF retries reuse completed verified files. pyannote candidates are never installed
into the active environment; failed candidates remain available for diagnosis. Venvs are
created at their final unique path, because moving a venv breaks absolute launcher paths.
A newer pinned Ollama is staged before switching to another private port; failure retains
the old endpoint. Only process objects launched by this manager may be terminated.
No active-job dependency update is allowed. Cross-process file locks serialize operations.

Limitations: no automatic provider-latest version polling; updates use reviewed profiles
shipped with the app. Old failed candidates are retained and can consume disk. The
language-model progress stream reports the current blob rather than inventing global ETA.
Cancellation closes the Ollama pull stream; Ollama owns partial blobs and resume behavior.
The small real-generation probe does not measure translation quality.

## Verification

Offline contracts are in `tests/test_component_manager.py`; `python scripts/check-fast.py`
continues to run without AI installs/downloads. `windows-app/verify_components.py` is an
explicit installed-Windows network acceptance runner, separate from normal push CI.
It strips system Python/PATH and inherited model caches, uses only built-in sample media,
and records versions, device, hashes, operation duration and real failures without tokens.
A Windows host with isolated PATH is labelled separately from a clean Sandbox and from
real WebView2 UI coverage. Actual results are recorded in the acceptance report accompanying
this change; incomplete scenarios must not be represented as passed.


## Acceptance outcome at handoff

See [verification-ai-components.json](verification-ai-components.json). The official Ollama ZIP
installed successfully after fixing inherited PowerShell module paths; model pull, generation
for both assignments and real translation passed. The notes pipeline failed its model-context
check. Clean-origin Sandbox installer/desktop and Whisper UI, editing and export passed after
correcting the test driver navigation race. New managed pyannote CPU/XPU installation E2E and
full final-artifact acceptance remain incomplete. This branch must not be merged on the basis
of unit-test success alone. No public release was published.
