# Coding-agent entry points and skills

The source of instruction truth is [AGENTS.md](../../AGENTS.md), with scoped files
for the Python package, Windows application and native UI. Read them explicitly
if your assistant does not load nested instructions. `CLAUDE.md` imports the root
file rather than duplicating policy. Configuration does not authorize publication,
driver changes or model installations.

## Portable workflows

- [Investigate transcription](../../.agents/skills/investigate-transcription/SKILL.md):
  classify failures and protect saved work during recovery.
- [Review release readiness](../../.agents/skills/review-release-readiness/SKILL.md):
  trace BUILD, accepted artifacts and public gates without publishing.

Backend/editor/test changes already have subsystem instructions and a test map;
separate skills would mostly repeat them and are deliberately omitted.

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
