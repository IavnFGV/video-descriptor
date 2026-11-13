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
  worker. Sol scopes a task and exact read/edit permissions; Terra implements on
  the dedicated task branch with eight steps. Sol reviews and runs validation;
  concurrent mutations use separate worktrees. No shell or broad filesystem access
  is granted to Terra. Use `executor-free` for explicitly free work; free quota
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
| Architect | `build` | Project default `openai/gpt-6.1-sol` | Architecture, task/permission scope, review, validation and commits |
| Worker | `executor` | `openai/gpt-6.1-terra` | Bounded read/edit/inspect/revise implementation; eight steps |
| Free alternative | `executor-free` | `opencode/minimax-m3.1-flash-free#low` | Explicitly free, bounded proposals |

Terra Standard means the non-Fast model; no reasoning variant is forced. The
committed executor policy denies everything, with no standing task grants. Eight
steps permit a bounded working loop; OpenCode reserves the last step for a
tools-disabled report. `steps: 1` therefore starts in terminal-report mode and is
not suitable for implementation. `executor-free` retains its one-step/tool-less
proposal role. No extra agent, command, plugin or orchestration script is needed.
The built-in Build prompt stays intact.

### Task-specific permissions

1. Sol inspects the branch/worktrees, creates the dedicated task branch, and defines
   the base SHA, at most two writable files, any exact read-only inputs, invariants,
   acceptance criteria and focused tests. Supply required instruction excerpts;
   do not grant repository-wide discovery access. UI tasks still read MASTER,
   CONTRACTS and page overrides.
2. In that Location's `opencode.json`, temporarily replace only
   `agents.executor.permissions` with the deny rule followed by exact path grants.
   For example, a synthetic fixture task can use:

   ```json
   [
     { "action": "*", "resource": "*", "effect": "deny" },
     { "action": "read", "resource": "tests/fixtures/executor-smoke/allowed.txt", "effect": "allow" },
     { "action": "edit", "resource": "tests/fixtures/executor-smoke/allowed.txt", "effect": "allow" },
     { "action": "read", "resource": "tests/fixtures/executor-smoke/read-only.txt", "effect": "allow" }
   ]
   ```

   These are task-relative files, not directory or wildcard grants. An edit grant
   does not imply read access; grant both when required. Read-only inputs receive
   no edit grant. Never grant shell, network, glob/grep, external-directory access,
   further delegation, secrets or protected runtime/model/recording data. The child
   cannot change its own scope or configuration: never grant edits to OpenCode
   configuration or agent/permission instructions; Sol maintains those. This is
   tool permission scoping, not an OS sandbox.
3. Inspect the **effective** loaded executor at the task Location before invocation:
   `GET /api/agent/executor?location[directory]=<URL-encoded absolute task directory>`
   through `opencode api`. Omitting Location can inspect the CLI's home Location
   instead of the checkout. Check Terra's model, eight steps, and last-match
   read/edit rules; all other actions/paths must resolve to deny. Account for merged
   global/nested config and later rules. Stop if effective permissions are broader
   than intended; task text and worktree separation are not permission enforcement.
4. Invoke named `executor`, without a model override, with the bounded assignment.
   Keep writes serial: Sol does not mutate worker-owned files or its grants while
   the child runs. For concurrent mutations, use separate worktrees/Locations and
   explicit file ownership. Only one executor scope may be active per Location.
5. Terra reads, edits, inspects and revises, then reports actual changes, checks,
   uncertainties and blockers. Sol independently reviews the full diff and runs
   focused tests, UI checks where applicable, and final local verification. Terra
   cannot run commands, Git, services or installations; worker output is not proof
   that tests passed.
6. Allow at most one targeted correction handoff to the same child session, with
   the same scope. New input resets its step allowance and incurs another model
   call. No automatic retries, model/budget escalation or silent Sol takeover.
   Report incomplete/blocked work explicitly.
7. After the child is idle (or stopped following failure/interruption), remove all
   temporary grants and recheck the effective default-deny policy. Do not reuse
   stale grants or commit them. Sol reviews/validates and commits verified work;
   push, merge and release remain separate operations under the existing rules.

The configuration regression test requires the committed permission list to be
deny-only; it intentionally fails while temporary task grants remain. When testing
the policy end to end, use synthetic files, permitted read/edit/readback and a
second revision; attempt each negative fixture read/edit only once, then check
tool denials and unchanged bytes independently. A tool absent from the catalog is
unavailable, not an executed negative probe. Do not use real secrets as probes.

The project model is a default, not a lock: an existing session's selected model
is independent. Check that the primary session is using Sol; do not switch it
silently. Configuration reloads without restarting OpenCode; `/reload` forces a
refresh. Inspect loaded models/permissions first, and run one tiny smoke delegation
only when end-to-end verification is in scope. Configuration checks alone do not
prove generation or permission enforcement works. Listed pricing is not an account-side spending control;
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

Executor steps and last-match path permissions checked on 2026-11-13 against
[OpenCode agents](https://opencode.ai/docs/agents#steps) and
[permissions](https://opencode.ai/docs/permissions). Effective loading and the
synthetic read/edit denial smoke were verified on OpenCode 2.2.7.

[opencode.json](../../opencode.json) enables built-in LSP with `lsp: true`, supported
by the current [official schema](https://opencode.ai/config.json). Availability
still depends on installed tooling/client version; the setting does not install
or prove a working Python/C# language server. Keep personal provider configuration
and credentials out of this tracked file.
