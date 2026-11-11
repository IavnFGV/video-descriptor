# Owner constraints and machine context

These standing requirements were consolidated from the root working context on
2026-11-11. This document is mandatory through the root AGENTS.md; dated migration
notes describe historical states, not instructions to regress the product.

## Host and authorization boundaries

The original Windows working copy is `E:\LocalAI\video desriptor` (intentional
spelling). Other Git worktrees now exist: use `git worktree list` and the current
user-selected checkout rather than copying changes to that historical path.
The original Ubuntu WSL project is `/home/ivand/projects/video-descriptor`:
do not delete it or automatically synchronize back. `.devcontainer/` is retained
and some settings still use that directory; it does not require VS Code or WSL.
The owner works from Codex without switching to VS Code/devcontainer.

The owner authorized autonomous investigation and agreed implementation on
2026-10-16; do not repeatedly seek authorization for those steps. Major application
implementation still starts with investigation, an architectural proposal and a
scope estimate. This does not authorize unrelated system installations/downloads.
First read [START-HERE](../../windows-migration/START-HERE.md) and the
[original migration request](../../windows-migration/ORIGINAL-REQUEST.txt) when
first orienting in this repository, then follow newer decisions in
[release readiness](../release-readiness.md).

The 2026-10-17 decision prioritizes a usable installer and end-to-end product over
stack uniformity. Preserve proven native UI/launcher and NPU integration. Use
Docker/Compose where it simplifies delivery; do not rewrite for a single stack.
Model/service setup and the installed user flow precede backend expansion.

Do not install system components or download large models without agreement.
The 2026-10-17 authorization covers enabling Windows Sandbox
`Containers-DisposableClientVM` with dependencies using `NoRestart`, not an automatic
host reboot, driver changes or other system components. Follow the applicable
Sandbox skill for guest-only Smart App Control changes; this is not host permission.

## Working models, devices and data

The protected benchmark directory is
`C:\Users\ivand\Downloads\windows-benchmark`. Do not modify its `.venv-npu`,
or stop/restart live services/jobs without need. The established profile is
Whisper small FP16 OpenVINO on NPU, `STATIC_PIPELINE=True`, `num_beams=1`, port 8766.
Do not enable word timestamps. `end_ts=-1` is missing timing, never a guessed end.
Do not promise native GPU diarization without a real verification.

Device settings must support explicit selection and Auto with NPU â†’ GPU â†’ CPU
priority for recognition. Check backend/model functionality, not mere detection.
Never silently replace an explicit choice. Check diarization and translation
capabilities separately; NPU support is not transferable between models.
See [device and release policy](../device-policy-and-release.md).

Diarization readiness (2026-11-09) survives runs and UI updates only for matching
model, Python/package metadata, lockfile, worker and device/driver inputs. Without
proof, do not report readiness. Unchanged verified inputs need no repeated inference,
HF token, HF access or manual verification; failures invalidate the cache. Request
HF access only when a necessary model download needs it.

Never print `.env*`, tokens or credentials. Keep local models, recordings, output,
queues and generated runtime data out of commits. Existing jobs/results can contain
Linux paths: never auto-run the old queue; conversion needs an explicit path/state
migration design. Preserve persisted recordings, checkpoints and user edits.

## Structured audit requirement (2026-11-09)

All mutating APIs go through the common HTTP audit. Worker/model interactions,
verification and result saves use `video_descriptor.action_history.record` as the
single structured event entry point. Record start, success and failure with
operation/job/request identifiers, stage and status. Do not replace it with a
separate logger. General events exclude keys, credentials, request bodies, prompts
and transcript content. Per-recording events live beside their artifacts; general
ones use `VIDEO_DESCRIPTOR_EVENTS` (Windows `application_log_directory` or
`runtime/logs/events.jsonl`) outside portable recording folders so logging cannot
invalidate folder checksums. Check events and UI visibility for each new endpoint
or background operation. Legacy `run.log` and `construction.log` are supplemental.

## Validation and release boundaries

Run available local checks with `python scripts/check-fast.py` before any authorized
push. It uses installed development dependencies and does not install AI components.
Fast CI runs for PR/main; Full Acceptance is explicit or pre-release. Sandbox tests
installation/environment; ordinary UI/infrastructure fixes are checked locally.
See [CI policy](../ci-policy.md). Commit verified changes locally; do not publish or
push without a user request. Substantial development changes go to
[history.md](history.md); keep the root README focused on current state and
documentation links. Release descriptions live in GitHub Releases and versioned
release notes. Architecture/contracts require
[architecture-windows.md](../architecture-windows.md).

Final delivery needs reproducible ZIP/Windows installer and clean Windows VM/runner
smoke, install, upgrade and uninstall checks. NPU/GPU support needs separate real
hardware verification; simulations and Windows containers are not hardware evidence.

Only standard packages go to GitHub Releases (2026-11-09). Domestic and cached full
offline installers with models are personal/private. Enforce the public artifact
gate regardless of filename. Users obtain Whisper/community-1/LLMs from official
sources with consent/access; a suitable local model avoids duplicate download and
unnecessary HF credentials. Bundled dependency assets require license/notices review
and pinned bytes. Excluding Domestic alone does not establish legal readiness of
the entire runtime. See [THIRD-PARTY](../../windows-app/THIRD-PARTY.md).
