# AI Component Manager — Windows

AI Settings retains the existing Whisper controls and adds external Ollama connection checks,
pyannote preparation, per-component checks, cancellation, retries, a readiness summary and
managed-environment removal with confirmation. Optional components do not block transcription.

## Runtime and model provenance

- Whisper: existing pinned OpenVINO small FP16 manifest, per-file SHA256, engine digest,
  built-in speech WAV and existing Auto NPU → GPU → CPU selection.
- Ollama: external HTTP API only. No runtime is included or managed by Video Descriptor.
  See [Windows setup guide](ollama-windows.md).
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

## External Ollama connection

Configure `ollama_url` (default `http://127.0.0.1:11434`), check `/api/version`,
refresh `/api/tags`, explicitly select an installed model and test generation.
HTTP and HTTPS endpoints may be local or remote; credentials, paths and query
parameters are rejected. No discovery cache or model catalog supplies the selector.
Endpoint edits invalidate the inventory and selection; request identity prevents
late responses from overwriting a newer server's inventory. Empty and unavailable
servers have distinct messages. No model is selected implicitly.

The workspace connection pointer and immutable job environment keep notes and
translation on the configured endpoint. Before generation, fresh discovery checks
that the selected model still exists. Models need not be loaded in memory.
The small `Provider` protocol covers connection, model IDs/discovery and verification;
Ollama HTTP details live in `video_descriptor/ollama_provider.py`.

## Consent and credentials

Whisper/pyannote downloads and removal of their owned environments require explicit
confirmation. Ollama and its models are installed, updated and removed externally.
Discovery never generates; the explicit model test sends a small built-in prompt.

Hugging Face access/terms remain the user's responsibility. The UI opens fixed official
pages in the system browser. 401/403 explains authorization rather than a technical crash.
The read token is encrypted with Windows current-user DPAPI, never returned by GET or
included in acceptance evidence. No security bypass is built into the manager.

## Files, recovery, updates

Mutable files live under `%LOCALAPPDATA%\VideoDescriptor\ai-components`:
`state.json`, `downloads`, `models`, `community-1-<revision>`, `cpython-<version>`,
`pyannote-<device>-<unique-id>`, and `checks`.
Normal Windows user-profile inherited ACLs apply. Models/environments survive application
upgrade and managed runtime removal retains models. Existing external environments are
never deleted. Interrupted states become retryable errors; previous successful proof is
retained, and startup requests a new check rather than presenting stale proof as live readiness.

The downloader resumes interrupted archives with Range and verifies final size/hash.
Whisper/HF retries reuse completed verified files. pyannote candidates are never installed
into the active environment; failed candidates remain available for diagnosis. Venvs are
created at their final unique path, because moving a venv breaks absolute launcher paths.
Each candidate receives the installer's SHA256-verified Microsoft VC++ runtime DLLs in
its local `Library/bin`, which PyTorch adds to its DLL search path. No system-wide VC++
installation or administrator rights are needed. pip uses an explicit extended-length
installation prefix on Windows; size accounting and owned-runtime removal use the same
filesystem namespace. The app never enables a machine-wide long-path policy.
No active-job dependency update is allowed. Cross-process file locks serialize operations.
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


## Acceptance evidence

[verification-ai-components.json](verification-ai-components.json) retains the initial attempt
as history and records the follow-up separately. Real installed API and WebView2 translation,
notes, editing and exports passed after an explicit endpoint change from an unavailable
address to existing Ollama on 11434. The external service survived application exit and its
model names/digests were unchanged. Tests used an isolated fixture and an already cached
public model, without downloading model weights or changing the user's Ollama.

Fresh managed CPython 3.12.15, pyannote 4.0.7 and pinned PyTorch CPU/XPU environments both
performed real inference on the Windows host; XPU used Intel Arc 140V. Existing approved
community-1 weights matched the pinned checksums and were reused. Final installed component
UI acceptance passed on CPU and XPU, including real translation, notes and diarization.
A clean Sandbox also passed fresh managed CPython/pyannote CPU installation, real diarization,
existing Ollama reuse and historical runtime lifecycle checks. Those historical checks
do not describe the current external-only implementation. The guest used authorized SAC Off;
this is functional proof rather than standard-policy signing proof.
The initial notes-context error is fixed; actual model-context validation remains enabled.
Clean-guest checks additionally exposed missing VC++ libraries and PyTorch long-path limits;
both are handled app-locally without administrator rights or machine-policy changes.
Exact artifact/source hashes and CI results are retained in the report.
