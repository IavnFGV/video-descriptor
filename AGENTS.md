# Video Descriptor: agent entry point

Video Descriptor turns local video/audio into editable transcripts, subtitles,
translations, notes and articles. Windows uses a native WinForms/WebView2 shell
and a local Python HTTP backend; CLI/web and container paths also exist.
Python 3.11+, Pydantic, Requests, FFmpeg/PyAV, OpenVINO/Whisper and plain HTML/CSS/JS
are the main technologies. Pyannote runs in a separate managed environment.

Read [owner constraints](docs/development/safety.md) before making changes.
They retain the machine, data, model, audit and publication requirements from
this file's former working-context notes. Current user instructions take priority.

## Find the right code

| Area | Entry points and guidance |
| --- | --- |
| Pipeline, API, persistence and editor | [video_descriptor/AGENTS.md](video_descriptor/AGENTS.md) |
| Windows launcher, workers, setup and packaging | [windows-app/AGENTS.md](windows-app/AGENTS.md) |
| Native UI | [windows-app/ui/AGENTS.md](windows-app/ui/AGENTS.md) |
| Component and data-flow map | [docs/architecture/README.md](docs/architecture/README.md) |
| Setup, checks, debugging, Git and releases | [docs/development/README.md](docs/development/README.md) |
| Agent discovery and reusable workflows | [docs/development/agents.md](docs/development/agents.md) |

Read applicable nested AGENTS.md files before editing their scope; search for
additional instructions rather than assuming every assistant loads them.
The shared frontend is in `video_descriptor/assets/`, not just `windows-app/ui/`.

## Non-negotiable boundaries

- Preserve genuine model timestamps, completed checkpoints, original responses,
  manual edits, source IDs, revisions and dirty guards. Never manufacture an end
  for `end_ts=-1`, silently skip failed audio or silently substitute an explicit device.
- Speech Auto selects usable NPU → GPU → CPU backends. Diarization and translation
  have separate capability checks; detected hardware is not proof of model readiness.
- Use `video_descriptor.action_history.record` for structured operation events and
  the shared HTTP audit for mutations. Keep secrets, prompts and transcript content
  out of the general log; keep it outside portable recording folders.
- Runtime data, models, credentials and recordings stay out of Git. Inspect
  configuration structure without printing `.env*` or credential-bearing values.
- Before UI, library or generated-report changes, read
  [MASTER](design-system/MASTER.md), relevant page overrides and
  [CONTRACTS](design-system/CONTRACTS.md). Stage 0 is an audit and separate prototype;
  broad migration requires owner agreement. Preserve the native launcher and NPU path.

## Change and validation workflow

For routine implementation, choose the least expensive capable approach without
asking the owner to choose a model. Before delegating a tiny, self-contained task,
load `delegate-small-task` from `.opencode/skills/delegate-small-task/SKILL.md`.
Use the configured `executor-free` for free delegation; the working paid `executor`
is retained separately. Do not fall back from free quota/errors to paid calls
without owner authorization. Do not use a model override or primary-model switch.
Do complex/cross-cutting work directly when delegation would add more overhead.
These instructions do not enforce billing limits; never promise subscription-only
usage without a verified account-side control.

Inspect branch, worktrees, status and upstream before editing. Keep unrelated changes.
All development changes, including code, tests, documentation and agent/configuration
changes, must start on a dedicated task branch, never directly on main or detached
HEAD. Create the branch before editing; use a separate worktree for concurrent work.
Implement, run checks, inspect the diff and commit with a meaningful message on that
branch. Merge only verified commits into main, then delete the fully merged task
branch with safe deletion (`git branch -d`, never force deletion). If a worktree
still checks out that branch, preserve its files and switch a clean worktree to a
safe ref before deletion; never remove a dirty worktree to force cleanup. Remote
branch deletion requires authorized remote access and a confirmed merge. Leave
unrelated or unmerged branches untouched. Merge is not release authorization:
do not change version/BUILD, create tags or dispatch releases as a merge side effect.
For concurrent work use separate branches/worktrees and explicit file ownership;
do not share an index or runtime workspace blindly. Prefer `codex/` for new Codex
branches. Commit verified work locally with a meaningful message; push/publication
requires a user request. Do not automatically sync the preserved WSL source.

Run focused tests while developing and `python scripts/check-fast.py` for final
local verification (installed dev dependencies only). Documentation-only checks
can use `python scripts/check-fast.py --config-only`; see the
[testing guide](docs/development/testing.md) for coverage and limits.
Do not use Actions as an interactive debugger. Full Acceptance and Sandbox are
explicit integration/release checks, not a substitute for local UI validation.

Keep the root README concise: current product state, getting started and documentation
links. Add substantial development changes to
[history.md](docs/development/history.md), not the README. Release descriptions live
in GitHub Releases and versioned `docs/releases/`; prepare the notes of the next
Windows build in `docs/releases/next-build.md`. Update
[architecture-windows.md](docs/architecture-windows.md) when architecture/contracts
change. Do not claim hardware support from mocks or containers.

Only standard packages may be public. Domestic/cached offline packages are private;
a public artifact gate is mandatory before upload. Never create a tag or dispatch
release preparation as a harmless validation step: preparation commits BUILD,
pushes main and a tag, then dispatches a release. See the
[release guide](docs/development/releases.md).

11.11.2026: Ollama только внешний HTTP(S)-сервер, default 127.0.0.1:11434.
Не возвращать установку/запуск/остановку runtime, private ports, model downloads,
managed modes или каталог моделей. Inventory только из свежего /api/tags выбранного
endpoint; смена адреса сбрасывает выбор, stale async responses игнорируются.
Discovery и проверка генерации раздельны; перед генерацией проверить наличие модели.
Инструкции: docs/ollama-windows.md и docs/lmstudio-windows.md.
