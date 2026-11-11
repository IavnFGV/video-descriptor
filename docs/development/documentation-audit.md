# Documentation audit: 2026-11-11

The [architecture map](../architecture/README.md) and [development guide](README.md)
route readers to sources and detailed pages. Root owner requirements were moved
to [safety.md](safety.md), not discarded. No runtime contracts change in this task.

| Existing ambiguity | Resolution |
| --- | --- |
| Root context names the original E: copy while work uses D: worktrees | Follow current task/worktree and `git worktree list`; preserve historical/protected paths in safety.md. |
| Migration START-HERE lists unimplemented Windows blockers | It already labels its historical snapshot; use current sources and architecture map. |
| Windows README includes 0.4/0.7 prototype requirements and installation limits | Treat these as dated evidence; current development/release routes point to scripts and versioned acceptance. |
| CI policy says five workflows and describes combined automatic container releases | Current YAML contains additional workflows; container release is manual, Windows tags use windows-release.yml. |
| Windows release notes describe both run/attempt numbers and tracked BUILD | Tracked BUILD is current; earlier run/attempt numbering is superseded. |
| Whisper HTTP defaults differ (8765/8766) | Legacy lecture and multilingual speech paths differ; native config supplies loopback URLs. |
| Recognition chunks resemble notes chunks | Architecture map separates audio checkpoints from LLM grouping. |
| Agent configuration | Root/native UI AGENTS.md existed; no tracked portable skills or Claude adapter were present. User-provided opencode.json is now shared. |

Dated documents remain historical evidence rather than being wholesale rewritten.
Short notices there point to current routes. New instruction/development pages are
English. Existing UI rules remain. No extra AGENTS.md was added to scripts, tests
or .github: common testing/release pages cover their workflows without more policy copies.

## Remaining gaps

- Long-form historical documents are largely Russian and interleave dated decisions.
  Future translation/archival work should preserve versioned evidence.
- No single OpenAPI/schema page describes all native/shared endpoints. Handlers,
  API tests and UI contracts remain authoritative; this map does not freeze formats.
- Hardware claims still need matching real-machine evidence. CPU acceptance, mocks
  and Sandbox do not establish NPU/GPU compatibility or LLM quality.
- The standard artifact gate does not prove transitive runtime license readiness.
- Client discovery/configuration was checked against official docs; live skill/LSP
  execution requires those clients and installed language servers.
- No dedicated Markdown-link checker exists. Check new local links directly;
  configuration/Fast checks do not validate prose or links.

## Change inventory

Created: `CLAUDE.md`, `opencode.json`, `video_descriptor/AGENTS.md`,
`windows-app/AGENTS.md`, `docs/architecture/README.md`, and these development pages:
`README.md`, `agents.md`, `debugging.md`, `documentation-audit.md`, `releases.md`,
`safety.md`, `testing.md`. Added two workflow sources under `.agents/skills/`:
`investigate-transcription/SKILL.md` and `review-release-readiness/SKILL.md`.

Modified: root `AGENTS.md` and `README.md`, `docs/architecture-windows.md`,
`docs/ci-policy.md`, `docs/windows-release.md`, `windows-app/README.md`.
Existing `windows-app/ui/AGENTS.md` is unchanged: it remains the narrow UI contract.
Root instructions route all agents; package instructions cover shared pipeline/API/
edit persistence; Windows instructions cover native runtime/setup/packaging.

## Validation

- Checked 145 local Markdown links in new pages and added notices; all targets exist.
  Test names in the test map were checked against the actual suite.
- Both portable skills pass the skill-creator frontmatter/structure validator.
- `git diff --check` passes; only Markdown/instruction files and the authorized
  `opencode.json` changed. No application, test, dependency, CI or release-input edits.
- Full `scripts/check-fast.py` passes using the existing Windows dev Python:
  25 configuration tests plus 630 suite tests, 3 skips; Ruff, shared UI/CSS audit
  and JavaScript syntax checks pass. The system Python lacks pytest; no packages
  were installed to work around it.
- Both documented CLI help commands execute successfully with explicit `-X utf8`.
- OpenCode JSON parses and `lsp: true` matches the boolean option in the official
  schema viewed through the web tool. A direct urllib schema fetch returned HTTP
  403; no automated remote-schema validator or live LSP invocation is claimed.

No release workflow, tag, upload or push was performed. The initial fast-forward
of main invoked the existing post-merge hook (local build/preview); the final
local documentation merge bypasses that hook for one invocation to avoid an
unnecessary installer build/preview restart. Persistent hook settings are unchanged.
