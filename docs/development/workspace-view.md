# Customizable Workspace / View menu

Implemented on `codex/customizable-workspace-view-menu`, based on main `917c4ed`.
No processing, release, installation or model changes.

## Existing regions and owners

| Menu item | Existing DOM / owner | Default |
| --- | --- | --- |
| Видео | `shared-player`, the single `process-video`; `recordingUI.seek/sync`, existing playback handlers | Visible |
| Расшифровка | `stage-speech`, `transcript-disclosure`, `speech-feed`; create.js and speech-edit.js | Visible |
| Участники | `recording-diarize`, `toggle-speaker-names`, `speaker-settings`, inline `.speaker-select`; existing assignment/rename handlers | Visible when available |
| Перевод | `translation-settings-panel` and `recording-translate`, subtitle mode, translated lines and translated exports; original controls relocated together | Hidden |
| Конспект | `material-tab-notes` and the existing `material-panel` when selected | Hidden |
| Статья / отчёт | `material-tab-article` and that same panel when selected | Hidden |
| Технические сведения и параметры | `source-details`, optional `recording-speech-settings`, `recording-processing`, `diagnostics`, auxiliary prompts | Hidden |

The shared report iframe is **not** two independent panels. Visibility does not
select a different material or bypass `selectMaterial`/`notesEditorDirty` guards.
If its current kind is hidden, the enabled tab remains keyboard-reachable and a
small hint asks the user to select it. Re-enable the hidden kind to recover its
unchanged draft. The existing material tab keyboard handler skips hidden tabs.

The View entry is a native disclosure inside the existing left navigation rail of
the recording workspace (`Записи`, `Настройки AI`, `Диагностика`). Its panel opens
beside the rail, or below the entry when the rail becomes a row in a narrow
window, and is clamped to the viewport. The library/settings shell has no
recording panels, so it carries no entry.

Selection/version controls, stop action, request/diarization progress, job errors,
retry/manual recovery, speech warnings and run-message remain outside hidden
regions. Speech settings remain in their original stage before a recording exists;
they move to the permanent controls only after a snapshot. Required speech settings
remain available without a ready transcript, and choosing a new speech version
explicitly reveals its parameters. An in-progress inline participant-name draft is
not hidden by the participant toggle, avoiding its blur/save behavior.

## Persistence and layout

`workspace-view.js` loads synchronously in both native index and `/create` heads.
`localStorage['video-descriptor:ui:workspace']` contains version 1, `layout`
(`side`/`stacked`) and boolean `panels`. It follows existing global UI preference
conventions and is scoped to WebView2/browser origin/profile, not recording folders.
It is not shared automatically between distinct ports or browser profiles.
Unknown versions use defaults; invalid fields are ignored; blocked storage falls
back to memory. Storage events synchronize other windows of the same origin.
Reset writes only this key. The old player position key is no longer read; the
existing expand-player button delegates to this same layout owner.

CSS Grid places video left/transcript right on wide windows, or video above speech
when stacked or at <=1000 px. Either primary panel alone fills the width; with both
hidden an inline reset remains. Enabled materials and translation use full-width
following rows. Source details are outside the player so technical information is
available even when video is hidden. Native topbar wraps without pushing application
or update menus beyond the narrow viewport.

## Changed implementation files

- `video_descriptor/assets/workspace-view.js` (new), `create.html`, `recording.js`.
- `video_descriptor/serve.py`: static asset allowlist only; no new API endpoints.
- `windows-app/ui/index.html`, `layout.css`: the shell loads no View entry, so the
  desktop bundle keeps only the shared layout.
- `design-system/components.css`, `surfaces.css`, `workspace.css`; regenerated
  `create.css`, `editor.css`, `windows-app/ui/app.css`. `surfaces.css` no longer
  stretches radio inputs to the full field width.
- `tests/test_workspace_view.py`, `tests/workspace_view.cjs` (new).
- `scripts/workspace_view_checks.py` (new), `verify-recording-ui.py`,
  `verify-updates-ui.py`: real asset route, updated geometry, and completion wait
  for the existing asynchronous participant assignment (not merely an added option).
- Contract/review documentation: `design-system/CONTRACTS.md`,
  `design-system/pages/workspace.md`, `design-system/migrations/main.json`,
  `docs/architecture-windows.md`, `docs/development/history.md`, this document.

## Local validation (12 November 2026)

- Existing Windows dev Python: `scripts/check-fast.py`: configuration **29 passed**;
  main suite **833 passed, 4 skipped**; Ruff, JS syntax, CSS generation and immutable
  DOM/API audit passed. Nothing installed. System Python initially lacked FFmpeg,
  faster-whisper, tokenization and Markdown dependencies and could not pass the full
  suite; the existing `.venv-windows` was used for final verification.
- Focused `test_workspace_view`, `test_updates`, `test_collapsible_sidebar`,
  `test_unresolved_navigation`: **53 passed** (included in the full suite).
- Real headless Edge/CDP fixture:
  `verify-recording-ui.py --workspace-view-only`: seven toggles, both layouts,
  reload/reset/invalid preferences, 360/760/1024/1440 px, video-only/text-only/empty,
  menu Escape/focus, intact DOM/player/frame, quick draft, report dirty guard/Undo,
  no visibility-triggered fetches, synthetic active/error snapshots, navigation.
- Existing browser scenarios: `--material-tabs-only`, `--material-tabs-empty`,
  `--unresolved-only`, `--speakers-only`: PASS; real temporary editor saves,
  participant rename/assignment, manual unresolved interval save and Undo/Redo.
- `verify-updates-ui.py`: PASS; badge, safe text, explicit check, external command,
  Escape/focus and 375–1440 px. New View menu included in real native markup.
- Screenshots reviewed for wide default and narrow stacked workspace. Local ignored
  evidence: `windows-app/runtime/zero-config/unified-recording/workspace-*.png`.

This is browser fixture validation, **not installed WebView2 acceptance**. Media
timing is simulated in the existing harness; actual codecs/playback, NPU/GPU/LLM
inference, Windows scaling and Narrator were not exercised. No live jobs or user
recordings were used or changed. No push, merge, tag or publication.
