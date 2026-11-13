# Coding-agent entry points and skills

The source of instruction truth is [AGENTS.md](../../AGENTS.md), with scoped files
for the Python package, Windows application and native UI. Read them explicitly
if your assistant does not load nested instructions. `CLAUDE.md` imports the root
file rather than duplicating policy. Configuration does not authorize publication,
driver changes or model installations.

## Portable workflows

- [Factual writing](../../.agents/skills/factual-writing/SKILL.md): mandatory for
  documentation, history and task summaries. Describe changes and evidence, not
  who requested or approved the work. Root instructions require explicit loading
  even when the client has not discovered the new skill automatically.

- [Cheap bounded delegation](../../.opencode/skills/delegate-small-task/SKILL.md):
  OpenCode reuses `build` as the Sol architect and `executor` as the Terra Standard
  worker. The architect supplies a bounded task, reviews the proposed patch, applies
  it on a dedicated task branch (separate worktree for concurrent mutations), and
  runs checks. The worker has no tools or filesystem access; it is not an autonomous
  implementation agent. Use `executor-free` for explicitly free work; free quota
  errors never authorize paid fallback. See the workflow below for model selection.

- [Investigate transcription](../../.agents/skills/investigate-transcription/SKILL.md):
  classify failures and protect saved work during recovery.
- [Review release readiness](../../.agents/skills/review-release-readiness/SKILL.md):
  trace BUILD, accepted artifacts and public gates without publishing.
- [Prepare release notes](../../.agents/skills/prepare-release-notes/SKILL.md):
  carry forward applicable changes from unpublished Windows builds.

Backend/editor/test changes already have subsystem instructions and a test map;
separate skills would mostly repeat them and are deliberately omitted.

## Sol architect + Terra Standard worker

The existing [opencode.json](../../opencode.json) is the configuration source:

| Role | Agent | Model | Responsibility |
| --- | --- | --- | --- |
| Architect | `build` | Project default `openai/gpt-6.1-sol` | Explore, scope, delegate, review, apply and validate |
| Worker | `executor` | `openai/gpt-6.1-terra` | One small proposal from supplied excerpts |
| Free alternative | `executor-free` | `opencode/minimax-m3.1-flash-free#low` | Explicitly free, bounded proposals |

Terra Standard means the non-Fast model; no reasoning variant is forced. Both
workers retain one step and deny all tools. No extra architect agent, command,
plugin or orchestration script is needed. The built-in Build prompt stays intact.

For a bounded task, ask the primary agent to use `executor`. Supply the base SHA,
allowed paths (at most two), relevant excerpts, invariants, acceptance criteria and
focused tests. Invoke the named agent without a model override. The architect
checks the proposal against the actual source before applying it; worker output
never substitutes for tests. UI tasks still read MASTER, CONTRACTS and page overrides.

The project model is a default, not a lock: an existing session's selected model
is independent. Check that the primary session is using Sol; do not switch it
silently. Configuration reloads without restarting OpenCode; `/reload` forces a
refresh. Inspect loaded models/permissions first, and run one tiny smoke delegation
only when end-to-end verification is in scope. Configuration checks alone do not
prove generation works. Listed pricing is not an account-side spending control;
no subscription-only or fixed-cost guarantee is implied.

| Client | Repository discovery |
| --- | --- |
| Codex | AGENTS.md hierarchy and repository `.agents/skills`. Check the available skill list; reload if new skills are absent. |
| OpenCode | Root AGENTS.md; current skill docs include `.agents/skills` as a project compatibility path. Check installed-version behavior and permissions. |
| Claude Code | `CLAUDE.md` imports AGENTS.md. Native project skills use `.claude/skills`; shared sources are not duplicated there. Ask Claude to read the exact portable SKILL.md path. |
| Other assistants | Explicitly load root/scoped instructions and the selected skill; automatic discovery is not assumed. |

Sources checked on 2026-11-11: [OpenAI skills](https://learn.chatgpt.com/docs/build-skills),
[OpenCode skills](https://opencode.ai/docs/skills/),
[Claude memory imports](https://code.claude.com/docs/en/memory) and
[Claude skills](https://code.claude.com/docs/en/skills).
This does not mean every client was executed locally.

[opencode.json](../../opencode.json) enables built-in LSP with `lsp: true`, supported
by the current [official schema](https://opencode.ai/config.json). Availability
still depends on installed tooling/client version; the setting does not install
or prove a working Python/C# language server. Keep personal provider configuration
and credentials out of this tracked file.
