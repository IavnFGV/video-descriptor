# Python pipeline, shared API and frontend

Scope: this package; root instructions still apply.
Read the [architecture map](../docs/architecture/README.md) for ownership and
[recovery guide](../docs/development/debugging.md) before repairing persisted work.

- `serve.py` hosts the shared web API; `jobs.py` owns filesystem jobs/worker lifecycle.
  Windows `app.py` wraps this backend, not a replacement persistence layer.
- `speech.py` owns editable speech and its revision/EDIT_LOCK contract.
  `editor.py` handles report edits. `recording.py` and `versions.py` join stored
  variants; choosing a report must not silently switch the selected transcript.
- `media.py`, `speech_npu.py`, `whisper_http.py` and `local_backends.py` use different
  recognition paths. Check which engine the job actually selected before fixing one.
  Do not equate notes chunking (`chunks.py`) with Whisper audio checkpointing.
- Preserve source IDs, absolute audio offsets, valid completed blocks, raw failure
  evidence and original model answers. Do not mark an invalid/unfinished interval done.
  Manual transcript overlays and report edits must survive regeneration/recovery.
- Mutations retain the shared audit, job/instance guards, revision conflicts and
  dirty-client protection. Use `action_history.record`, not a new event format.
- For assets, library UI or generated reports read the design system and relevant
  page overrides first. `assets/` is shared by native and web surfaces; do not break
  DOM IDs, handler wiring or HTTP payload/header contracts.

Locate relevant `tests/test_<module>.py`; see the
[test map](../docs/development/testing.md). Keep ordinary tests offline and use
existing fixtures for model/HTTP boundaries; mocks are not hardware/model proof.
