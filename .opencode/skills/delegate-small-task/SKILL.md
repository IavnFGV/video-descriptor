---
name: delegate-small-task
description: Use before delegating a tiny self-contained coding or review task to the project's cheap executor; avoid delegation when context and review overhead exceed the benefit.
---

# Cheap bounded delegation

The owner submits ordinary tasks, not model-routing commands. The primary agent
chooses the cheapest capable approach and owns correctness. Do not ask for model
approval for each task, and do not delegate just to demonstrate delegation.

## Decide

- Delegate only a mechanical change or precise question involving at most two files,
  with enough context already available. Examples: one small test, one replacement,
  a short documentation correction, or checking a supplied diff for one invariant.
- Work directly for repository exploration, architecture, release/installer changes,
  concurrency, persistence, or tasks whose review duplicates the implementation.
- Prefer local commands over LLM calls for searches, formatting, and deterministic checks.

## Delegate once

1. Read applicable repository instructions. For a proposed code change, identify
   base SHA, allowed paths, preserved behavior, acceptance criteria and focused tests.
2. Call `executor` by agent name, without overriding its configured model or variant.
   It is pinned to DeepSeek Flash via OpenRouter, with `steps: 1` and all tools denied.
   Keep the primary model unchanged. Never substitute a stronger paid worker silently.
3. Supply only the necessary source excerpts and contracts, preferably under 6,000
   characters total. Do not send secrets, local configuration, recordings or unrelated
   conversation history. Ask for a small patch or concise answer, not a long narrative.
4. One invocation per subtask; no automatic retries or follow-ups. On BLOCKED or an
   unusable proposal, finish directly or report a real blocker. A new call is another
   cost, not a free extension of the same step allowance.

## Review and apply

This lightweight executor has no filesystem access. It does NOT edit its own
worktree or run tests: it returns a proposal. Do not describe this as an isolated
filesystem-writing worker or claim a successful call before it has been tested.

The primary agent validates the proposed patch against the actual source. Before
applying an accepted change, create a dedicated branch/worktree at the base SHA;
parallel mutations must never share an index or runtime. Apply only allowed files,
inspect the full diff, run focused checks and the applicable final local checks.
Report real command results, limitations and the resulting commit when authorized.
An executor's report never replaces independent diff review or tests. Follow the
owner's current Git/release authorization; task delegation alone does not authorize
push, publication, release preparation, service startup or installations.

## Costs and limits

`steps` is a per-turn model-step limit, NOT a token or money cap. OpenRouter usage
is paid separately from the primary ChatGPT subscription. Account-side budgets,
credit-use settings and automatic reload are distinct; do not invent a local
"never use ChatGPT credits" configuration field or assume such a guard is active.

Do not make paid test calls just to validate configuration. Inspect the loaded
agent's model, steps and permissions without generation. Until an actual invocation
is observed, report configuration validation separately from end-to-end validation.
