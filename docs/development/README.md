# Development guide

Start with [AGENTS.md](../../AGENTS.md), the [architecture map](../architecture/README.md)
and [safety requirements](safety.md). This guide describes source development;
installed users run the packaged launcher and configure components in the app.

## Environment and launch

Use Windows x64 and Python 3.11+ (CI uses 3.12); Node is required for JS checks.
The desktop host also needs .NET tooling and WebView2. AI workers have separate
runtimes: never install development dependencies into the benchmark `.venv-npu`.

For a new source environment, inspect [Install-App.ps1](../../windows-app/Install-App.ps1)
and the [Windows README](../../windows-app/README.md). That script prepares
`.venv-windows` from `windows-app/requirements-lock.txt`; it installs dependencies.
Do not run it over a working environment just to validate documentation.
`requirements-ci.txt` pins check tooling; `requirements-dev.txt` has initial broad
ranges, not the release lock.

Do not confuse that launcher environment with local Fast checks: on Windows,
`scripts/check-fast.py` requires `.venv` in the checkout being checked, not
`.venv-windows` or an interpreter from another worktree. Use an existing populated
`.venv`; see [testing](testing.md). Creating environments or installing dependencies
is setup work, not a documentation validation step. The isolated local builder's
current conflict with this guard is documented in [local-build.md](../local-build.md).

With the source environment already prepared, from the repository root:

```powershell
.\windows-app\Start-App.ps1 -Doctor
.\windows-app\Start-App.ps1
```

Doctor inspects configuration/dependencies without starting recognition; the
second command opens the native desktop host. Model setup/download remains a
separate consented action. See [component setup](../ai-component-manager.md).

For the configured local source preview:

```powershell
.\scripts\Run-Dev.ps1 -Open
```

This requires `local-dev/config.json` under the Git **common directory** with an
existing dev Python, separate port, `development=true` and `records_directory`
pointing to an existing workspace containing `data` and `output`. The config is
machine-local. `scripts/run_dev.py` validates instance/workspace identity;
restart/stop refuse unrelated instances and active work. The preview can share
installed recordings: it is not disposable test storage.

The shared web server can run separately without the desktop host:

```powershell
python -X utf8 -m video_descriptor.serve --bind 127.0.0.1 --port 8000 --directory .
python -X utf8 -m video_descriptor --help
```

The explicit loopback bind avoids the web server's `0.0.0.0` default. This is the
legacy web/CLI path, not a replacement for native worker/configuration checks.
Do not start old queues containing Linux paths.

## Git and worktrees

Inspect before editing:

```powershell
git status --short
git branch --show-current
git worktree list
git log -5 --oneline
git fetch origin
git rev-list --left-right --count HEAD...origin/main
```

All development changes (code, tests, documentation, configuration and agent rules)
must use a dedicated task branch. Create it before editing; do not develop directly
on main or detached HEAD. Use the current agreed worktree and keep other agents'
changes untouched. For a separate checkout, choose a new unused path and branch:

```powershell
git worktree add ../video-descriptor-agent -b codex/task-name origin/main
```

Do not check out main in two worktrees or force-remove a worktree with data. Inspect
local hooks before merging: the configured post-merge can queue a local installer
build and restart its guarded preview. Coordinate those side effects with live work.

Run [focused checks](testing.md), inspect the diff and commit locally. Push, remote
merge and publication require a user request. Add substantial development changes
to [history.md](history.md), keeping the root README focused on current state and
links; maintain `docs/architecture-windows.md` for changed runtime contracts.

Complete each task as: **branch → changes → checks and diff review → commit →
merge verified commits → delete the merged task branch**. Prefer safe fast-forward
merges when possible. Use `git branch -d`, not forced deletion; first confirm the
task commits are ancestors of main. If a clean worktree still checks out the task
branch, detach it at the merged main revision before deleting the branch. Preserve
dirty worktrees and all unrelated/unmerged branches. Do not remove worktree files
just to delete a branch. Delete a remote task branch only after its merge is confirmed
and remote mutation is authorized.

Merging does not authorize a release: no automatic version/BUILD bump, tag, release
dispatch or publication. Explicitly authorized release automation follows the
[release procedure](releases.md) separately.

## Documentation with every change

Keep the affected guides, commands, configuration examples and links synchronized
in the same task as the implementation. Replace or remove obsolete passages rather
than leaving conflicting instructions under a newer dated note. History and release
notes do not replace updates to current guides. Preserve published notes, legal
notices and useful historical evidence with an explicit historical scope.
The authoritative checklist is [Keep documentation synchronized](../../AGENTS.md#keep-documentation-synchronized);
apply it to human and agent contributions. State validation limits and any blocked
documentation updates in the task report.

## Task routes and dependencies

- [Testing and CI](testing.md): commands, regression ownership and evidence limits.
- [Debugging](debugging.md): model errors, checkpoints, logs and manual edits.
- [Release procedure](releases.md): version source, BUILD and automatic tag handling.
- [Agent discovery](agents.md): portable workflows and assistant-specific entry points.
- [UI/UX Epic](../../design-system/UI-UX-EPIC.md): current backlog, dependencies and acceptance gates.
- [Documentation audit](documentation-audit.md): historical contradictions and gaps.

Dependency updates require intentional lock/input changes and packaging validation.
`pyproject.toml` does not pin Windows runtime bytes. Inspect
`windows-app/requirements-lock.txt`, `requirements-container.lock`,
`windows-app/release-inputs.json`, `windows-app/release-wheels.json` and the separate
component/diarization manifests before changing dependencies. Do not regenerate
locks or install AI components during ordinary local checks.
