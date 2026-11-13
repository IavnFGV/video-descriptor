# Coding-agent entry points and skills

The source of instruction truth is [AGENTS.md](../../AGENTS.md), with scoped files
for the Python package, Windows application and native UI. Read them explicitly
if your assistant does not load nested instructions. `CLAUDE.md` imports the root
file rather than duplicating policy. Configuration does not authorize publication,
driver changes or model installations.

## Portable workflows

- [Factual writing](../../.agents/skills/factual-writing/SKILL.md): use for
  documentation, history and task summaries.
- [Investigate transcription](../../.agents/skills/investigate-transcription/SKILL.md):
  classify failures and protect saved work during recovery.
- [Review release readiness](../../.agents/skills/review-release-readiness/SKILL.md):
  trace BUILD, accepted artifacts and public gates without publishing.
- [Prepare release notes](../../.agents/skills/prepare-release-notes/SKILL.md):
  carry forward applicable changes from unpublished Windows builds.

Backend/editor/test changes already have subsystem instructions and a test map.

## Terra primary and Sol advisor

The existing [opencode.json](../../opencode.json) configures `build` as the primary
agent with `openai/gpt-6.1-terra` (Standard, without a forced variant). It retains
the built-in coding prompt and normal project development tools. Terra investigates,
edits, runs tests, reviews and integrates work under the project safety and approval
rules; routine work does not require delegation or temporary permission grants.

The existing `architecture-advisor` uses `openai/gpt-6.1-sol` for genuinely complex
architecture or debugging decisions, or when Terra is blocked. It has default-deny
tool permissions and receives only supplied context; it cannot inspect the checkout,
execute commands or make changes. Terra remains responsible for decisions and
verification. `build` can invoke this advisor but not other subagents.

The project model is a default, not a lock: existing sessions retain their selected
model independently of the configuration. Check the session model when necessary;
changing the default does not switch an existing session. Configuration reloads
without restarting OpenCode; `/reload` forces a refresh. Static configuration
checks do not prove model generation or effective permissions under merged global,
project and managed settings. Pricing is not an account-side spending control.

| Client | Repository discovery |
| --- | --- |
| Codex | AGENTS.md hierarchy and repository `.agents/skills`. Check the available skill list; reload if new skills are absent. |
| OpenCode | Root AGENTS.md; current skill docs include `.agents/skills` as a project compatibility path. Check installed-version behavior and permissions. |
| Claude Code | `CLAUDE.md` imports AGENTS.md. Native project skills use `.claude/skills`; shared sources are not duplicated there. Ask Claude to read the exact portable SKILL.md path. |
| Other assistants | Explicitly load root/scoped instructions and the selected skill; automatic discovery is not assumed. |

[opencode.json](../../opencode.json) enables built-in LSP with `lsp: true`.
Availability depends on installed tooling/client version; the setting does not
install or prove a working Python/C# language server. Keep personal provider
configuration and credentials out of this tracked file.
