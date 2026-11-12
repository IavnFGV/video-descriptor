# Debugging transcription and recovery

Begin read-only. Identify recording/job, selected engine, source revision,
requested/resolved device and failure stage. Inspect relevant fields without dumping
settings, tokens, prompts or transcript content into shared output.

| Symptom | Investigate |
| --- | --- |
| Connection refused, occupied port, wrong instance | Native `/health`, `app.py`, `compute.py`, `local_backends.py`; compare configured URL and worker identity |
| Missing model/runtime or wrong protocol | Setup diagnostics and engine health, not hardware enumeration alone |
| Invalid time, `end_ts=-1`, missing labels, empty/truncated answer | Content validation and original model evidence; never fabricate content or mark the interval complete |
| Conflict or unsaved editor | Revision, active jobs and dirty guard; preserve user edits |
| Stuck running state | Worker lock/live process checks in `jobs.py`; do not kill a service just because state looks stale |

Relevant code: [speech_npu.py](../../video_descriptor/speech_npu.py),
[whisper_http.py](../../video_descriptor/whisper_http.py),
[media.py](../../video_descriptor/media.py), [speech.py](../../video_descriptor/speech.py),
[local_backends.py](../../video_descriptor/local_backends.py).

The NPU segment path rejects missing end times and nonfinite/out-of-range timestamps.
It keeps chunk/VAD-region responses; invalid region responses use
`invalid-response.json`. Trace the failed original audio offset and keep successful
chunks. The older HTTP client uses `transcript.partial.json` with identity and
`completed_until`, retries invalid-timestamp HTTP failures from the same offset
with smaller chunks and advances only after validating the response. These paths
have different cache formats; do not apply one recovery recipe to both.

Check audio/model identity and offsets before reusing checkpoints. Do not delete
completed cache, skip failed intervals, truncate speech or turn an infrastructure
outage into no speech. No speech requires evidence from the selected pipeline.

## Artifacts and logs

Native workspace selection is `records_directory`, otherwise `runtime/workspace`.
Its `output` contains jobs/results and `data` contains inputs. Use UI Diagnostics/
history first rather than hardcoding a developer's absolute paths.

- `speech.json`, `transcript.json`, `transcript-edits.json`, `translations.json`:
  retain original speech and user overlays; inspect status/identity/revision.
- Chunk request/response files and checkpoints: retain exact evidence locally.
  They can contain private text and are not public fixtures.
- `construction-result.md` and `construction-manual.json`: original model answer
  versus separately validated user recovery. See
  [construction_recovery.py](../../video_descriptor/construction_recovery.py).
- General events: `VIDEO_DESCRIPTOR_EVENTS`; Windows uses
  `application_log_directory` or `runtime/logs/events.jsonl`, outside recording
  checksum scope. Per-recording events are beside artifacts. `run.log` and
  `construction.log` supplement structured history. Model payloads stay out of
  the general event log.
- Source preview: `local-dev/stdout.log`, `stderr.log`, `status.json` under the Git
  common directory. Build logs: [local-build.md](../local-build.md).

## Publishing artifacts on Windows

Artifacts are published atomically through `video_descriptor/atomic_file.py`: a
unique temporary file is replaced by `ReplaceFileW`, readers open files with
`FILE_SHARE_DELETE`, and a holder that forbids deletion (antivirus, file
browser) is waited out with a bounded retry. A failed publication keeps the
previous artifact and removes the temporary file.

Recognition progress is advisory: a locked progress snapshot is reported as
`speech_progress_save_failed` and never stops recognition. The final result is
mandatory: when it cannot be published the job fails with the original cause
(`speech_result_save_failed` in the journal) instead of reporting a saved
result. Inspect `run.log` and the journal before repeating a job.

## Safe repair

Prefer existing UI/API recovery with revision/active-job guards. Report recovery
validates a separate user answer and resumes the existing job, preserving the
original response. Transcript editing uses `speech.editable_result()` and its
revision over saved speech/translations. Choosing a report must not switch speech.
Never edit persisted JSON under a running worker.

For a code fix, reproduce with synthetic audio/HTTP evidence in temporary storage,
add a meaningful regression and run the [relevant suite](testing.md). Verify audit
start/result/error events and UI visibility for new operations. Do not restart
protected benchmark services or rerun verified diarization just to refresh the UI.
