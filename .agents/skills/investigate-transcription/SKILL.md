---
name: investigate-transcription
description: Diagnose Video Descriptor transcription failures or interrupted recognition while protecting checkpoints, original responses and manual edits.
---

Read [root instructions](../../../AGENTS.md) and the
[debugging guide](../../../docs/development/debugging.md).
Use this for a failed/interrupted recording, not a general UI redesign.

Identify job/recording, engine/device, source revision and original audio offset
before retrying. Trace the selected path in `video_descriptor/speech.py`,
`speech_npu.py`, `whisper_http.py` or `local_backends.py`; native planning lives
in `windows-app/compute.py`. Distinguish availability/protocol/model identity from
content errors such as `end_ts=-1`, invalid timing or missing model labels.
Code paths in this paragraph are relative to the repository root.

Inspect checkpoint identity and completed intervals read-only. Keep valid blocks,
raw/invalid responses and transcript overlays. Do not erase caches, guess times,
skip failed intervals or restart protected workers. Prefer guarded UI/API recovery;
direct JSON edits under a running worker are unsafe.

For a code repair, reproduce using synthetic evidence and temporary storage.
Select existing tests from the [test map](../../../docs/development/testing.md),
then run `python scripts/check-fast.py` from the repository root with existing dev
dependencies. Check audit/UI error visibility for changed operations. Report cause,
preserved artifacts, recovery outcome and remaining hardware/model evidence needs.
Never copy private transcripts, prompts or credentials into shared logs or fixtures.
