# UI changes

Before changing this interface, read `../../design-system/MASTER.md`, the relevant
`../../design-system/pages/*.md`, and `../../design-system/CONTRACTS.md`.
Use shared tokens and vd-* component contracts. Preserve existing DOM ids,
JavaScript handlers, API payloads/headers, job states, revision and dirty guards.
The owner approved the direction on 2026-10-19. Main/settings/diagnostics use the
shared system; see ../../design-system/IMPLEMENTATION.md. Prototype assets remain
reference only. Build app.css with scripts/build-ui-css.py; never edit the
generated bundle directly. Review migrations without replacing baseline.
Validate keyboard, empty/error/busy states and WebView2 constraints before commits.
