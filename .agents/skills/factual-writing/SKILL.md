---
name: factual-writing
description: Write factual documentation, changelogs, audit reports and task summaries without request attribution, approval narratives or bureaucratic wording.
---

# Factual writing

Use for documentation, development history, release notes, audits and task summaries.
Read the repository's documentation synchronization rules in [AGENTS.md](../../../AGENTS.md).

## Write the change, not the conversation

- State what changed, its effect, the evidence actually checked and remaining limits.
  Keep dates, versions, source revisions, artifact hashes and technical rationale.
- Do not explain who requested, approved, permitted or agreed to routine work.
  Omit phrases such as «по запросу владельца», «после согласования владельца»,
  «владелец разрешил», «по прямому поручению», «согласованное направление»,
  `owner-requested`, `owner-approved`, `with the owner's approval` and equivalents.
- Do not replace attribution with another empty preamble such as «в рамках
  согласованной задачи». Start directly with the result. Use plain technical language.
- Distinguish implemented, planned, statically reviewed, tested and unverified.
  Never turn a user-reported result into an independently executed test.
- In retrospective reports, describe actual scope rather than permission history:
  «SAC выключен только в одноразовой Sandbox; защита хоста не менялась».
  Do not imply that a historical run grants permission for future system changes.
- Preserve operative safety requirements, download/cloud consent, access control,
  licenses and publication restrictions. Technical terms such as file ownership,
  HTTP authorization and browser permissions are not bureaucratic attribution.
  Ask before actions that require a decision; do not remove that boundary for style.
- Do not rewrite frozen release notes, quotations, UI labels or raw evidence just
  to remove a matching word. Check context; update current prose and linked guidance.

## Examples

| Avoid | Use |
| --- | --- |
| «По запросу владельца настройки разделены на вкладки» | «Настройки разделены на вкладки» |
| «После согласования владельца синхронизированы инструкции» | «Инструкции синхронизированы с текущей реализацией» |
| `Owner authorized installing package X; the test now passes` | `Package X was installed in the dev environment; the test passes` |

Before delivery, scan changed prose for attribution and permission narratives.
Remove empty framing, check that technical facts and evidence limits survived, and
summarize changes without retelling the conversation. This is a writing rule, not
permission to change application behavior or bypass safety requirements.
