---
name: delegate-small-task
description: Use before delegating a bounded implementation or review task to the project's executor; avoid delegation when context and review overhead exceed the benefit.
---

# Bounded Terra implementation

Use the [agent workflow](../../../docs/development/agents.md#luna-coordinator-and-terra-standard-worker-with-sol-advisor)
as the authoritative configuration and permission procedure.

## Scope before invoking

- Luna owns exploration, architecture, base SHA, invariants, acceptance criteria and
  the dedicated task branch. Sol can advise on architecture from supplied context
  only; it has no repository tools. Delegate at most two writable files; supply
  relevant contracts/excerpts and exact paths for any additional read-only inputs.
- Use the existing named `executor`: Terra Standard, eight steps, no model override
  or forced reasoning variant. The last step is a tools-disabled report, not an
  implementation step. Steps are not a token, spending or completion guarantee.
- Default-deny stays first. Luna temporarily appends only exact task-specific
  `read`/`edit` grants to `agents.executor.permissions` in `opencode.json`.
  No wildcards, directories, shell, glob/grep, network, external-directory access,
  further delegation or scope/config changes by the worker. Never grant edits to
  OpenCode configuration or agent/permission instructions; Luna maintains those.
  Verify the effective
  loaded agent at the task Location before generation; prompt-only scope is not
  enforcement. If the merged configuration is broader, stop and resolve it.
- Exclude credentials, runtime/model/recording data, protected machine paths and
  unrelated files. Luna supplies necessary instruction excerpts; do not grant broad
  repository access just to discover instructions.
- Keep writes serial: while Terra runs, Luna does not edit the owned files or change
  its grants. Concurrent mutations require separate worktrees and file ownership.

## Implement, review, close

1. Supply one bounded task, preferably under 6,000 characters of essential context.
   Terra reads, edits, inspects and revises through its allowed tools, then reports
   changed files, actual checks, uncertainties and blockers. No commands or Git.
2. Luna independently reviews the full diff, verifies file ownership and preservation
   invariants, and runs focused tests plus applicable final checks. Worker text is
   not validation evidence.
3. If review finds a bounded defect, permit at most one targeted correction handoff
   to the same child session, with the same permissions. It resets the step
   allowance and is another model call/cost, not a free retry. No automatic loops,
   budget escalation or silent takeover; report incomplete/blocked work explicitly.
4. Once the child is idle, Luna removes all temporary grants, verifies the effective
   default-deny policy, reviews/validates the result and commits verified work.
   Remove grants on failure/interruption too, after the child is stopped/idle.
   Never commit task grants or reuse them for a different task. Only one executor
   scope may be active per Location.

The worker cannot push, merge, release, install, start services or mutate protected
data. Luna's existing publication and host-safety boundaries remain unchanged.
The worker is a permission-scoped editor, not an OS sandbox.

## Free alternative and verification

`executor-free` remains an explicitly free, one-step, tool-less proposal agent.
Do not use it for multi-step implementation or silently fall back to paid calls
after free quota/errors. Keep the primary model unchanged.

Only run a paid generation smoke test when end-to-end verification is in scope.
Use synthetic fixtures: permitted read/edit/readback, a second permitted revision,
and single negative read/edit probes against an ungranted fixture. Verify tool
denials and unchanged bytes independently; unavailable tools are not executed
negative probes. Remove fixture grants afterwards. Report configuration checks,
actual tool behavior and token usage separately; never claim a local budget or
subscription-only guarantee without verified account-side controls.
