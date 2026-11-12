# Cohesive desktop UI — 12 November 2026

Task branch: `codex/cohesive-desktop-ui`, based on main **8e643c0** (the preceding
View/sidebar task is already merged and pushed). This task does **not** authorize
merge, push, tags, build/version changes, installation or release.

## Audit before implementation

The native index (`windows-app/ui/index.html`) owns library/import/settings and
diagnostics. `/create` uses `studio.js`, `create.js`, `recording.js` and the shared
speech editor. The recording module moves the single video and transcript into its
grid and keeps versions, actions and errors above it. Notes/article share one guarded
iframe; the generated standalone report uses the same editor. `/output/` is also an
existing library, not a new route. DOM/API manifests and scoped AGENTS were reviewed.

The actual 1200×800/1440×900 screenshots showed:

1. Workspace lacked the native application's command header and used different
   branding, link styles, title offsets and panel treatments.
2. A full-width version picker and a separate action row pushed the primary panels
   down to about **327 px** on the laptop-sized window. The transcript toolbar then
   consumed another large block; little speech was visible without page scrolling.
3. Settings opened with a long preparation form, hiding the actual configuration
   sections below the fold. Diagnostic labels and status values were stacked into
   oversized rows. Readiness occupied an entire separate card even for a short line.
4. Layout/menu controls appeared in navigation, mixing navigation with commands.
   Updates, connections and application commands belonged to different menu owners.
5. Report, import and reply editing reused base components but had inconsistent
   density and no common document/chrome hierarchy.

This is why changing colors or rounding alone would not solve the problem.

## Architecture and intentional changes

### One shell; existing feature owners

`video_descriptor/assets/desktop-shell.js` composes a **44 px shared command bar**
using native `details/summary` (no false ARIA menubar role). File, View, Tools and
Help are available where meaningful. Native index reuses its topbar; shared pages
receive the same header. The sidebar contains only screen navigation.

Existing controls are **reparented**, not cloned: `sidebar-toggle`,
`workspace-view-menu`, `stop`, `updates-check`, `open-connections`, `new-record-open`.
The old application menu node remains hidden after its actions move. IDs and direct
handler assignments remain in place. File links and shared navigation respect the
existing quick-reply and report dirty owners; no editor/frame is reconstructed.
Menus support Tab/Enter/Space, Escape with focus return, mutual exclusion and
Left/Right between summaries. Help is a local read-only dialog, not an external URL.
Update commands/badge retain their existing native-page lifecycle and API.

The earlier request to place View in the sidebar is intentionally superseded by
this task's command/navigation separation. **The same View controller**, version-1
storage key and layout modes are retained; no second settings owner is introduced.
Library/settings View contains only relevant navigation commands and explains where
recording panel controls appear. Embedded report pages skip shell initialization.

### Document and workspace

- 22 px document title, short processing/status lines, inline version/actions row.
- Side-by-side video/transcript proportions about **40/60**, minima **300/420 px**.
  At <=1000 px or explicit stacked preference, panels use one column.
- The transcript retains its existing scroller and DOM. A ResizeObserver sizes its
  maximum height from the actual toolbar/header geometry. At 1200×800 both primary
  columns begin above 260 px and the transcript scroller fits the viewport.
- One hidden primary panel lets the other fill the width; both hidden retain reset.
- Time links, participant assignment, Undo/Redo and exports remain at the text.
  An explicit **Copy** command copies rendered original utterances on user action;
  unresolved gaps and toolbar text are excluded. Active editing blocks copying;
  unavailable clipboard gives a TXT/selection fallback explanation, not data loss.
- Notes and article remain optional, full-width lower materials in the same iframe.
  The video is deliberately **not sticky** over those rows. Report editor actions
  share the 32 px toolbar density; model responses and original artifacts remain.

### Settings, diagnostics, import, reports

Settings have a local section index which opens/focuses existing disclosures without
changing routes or closing another dirty form. Once initial readiness is known, the
optional preparation controls may collapse; focused controls are never collapsed
by polling. Preparation status and the stop button are outside that disclosure.
Consent, credentials, selected devices and all existing forms stay intact.

Diagnostics use label/value rows, with separate readiness and hardware capability
semantics retained. Import, library, standalone reports and native dialogs share
typography, control heights, borders and spacing. Only historical UI descriptions
of managed Ollama were corrected: it remains external HTTP(S), with no runtime or
model lifecycle added. No device or processing code changes.

### Design sources

`design-system/desktop.css` is the common final presentation layer in all three
bundles. Shared colors/type/spacing remain; new named tokens are the 44 px menu
height, 8 px desktop panel radius, desktop gap and reading size. Forms remain 40 px,
toolbars 32 px. `scripts/build-ui-css.py` generates the bundles; baseline unchanged.
`prototype/desktop-shell.html` is an isolated, API-free layout reference.

## Visual verification and iteration

Real headless Microsoft Edge/CDP captures were produced from real HTML/CSS/JS with
disposable recording/API fixtures, not a hand-drawn mock. Windows/WebView2 host was
not rebuilt or installed. Media timing is simulated by the existing harness; the
grey video in evidence is fixture media, **not proof of actual codec playback**.

Reviewed initial and repeated captures at **1200×800**, **1440×900**, plus narrow
760/375 px. Checks cover visible alignment, wrapping, menu bounds, font/control sizes,
report scrolling and dialog layout. Problems found and fixed during iteration:

- transcript extending below the laptop viewport → geometry-based scroller sizing;
- sticky video obscuring report controls → non-sticky media across material rows;
- programmatic page-heading black outlines → noninteractive heading focus styling,
  while all interactive keyboard focus rings remain;
- settings form scrolled under chrome → scroll padding/margins for the command bar;
- article captured before its asynchronous editor loaded → wait for actual report
  document, rendered text and editor, not just iframe `src`;
- native brand lost its space at the old `<br>` → unified text branding.

Selected fixture-only captures are retained in `evidence/desktop-cohesion/`:

| Screen | Before | After |
| --- | --- | --- |
| Recording, 1200×800 | [before](evidence/desktop-cohesion/before/recording-1200x800.png) | [after](evidence/desktop-cohesion/after/recording-1200x800.png) |
| Settings, 1200×800 | [before](evidence/desktop-cohesion/before/settings-1200x800.png) | [after](evidence/desktop-cohesion/after/settings-1200x800.png) |
| Diagnostics, 1440×900 | [before](evidence/desktop-cohesion/before/diagnostics-1440x900.png) | [after](evidence/desktop-cohesion/after/diagnostics-1440x900.png) |

Additional after evidence includes the View menu, report editor, connections dialog,
and 375 px workspace. Full local captures/metrics live under ignored
`windows-app/runtime/zero-config/desktop-design/{before,after}/`. Initial baseline
captures were made on 8e643c0 before production edits. Running `--before` on a changed
checkout labels captures; it does not restore old source. To recreate old visuals,
use an isolated checkout of the base with the fixture harness, not production data.

Reproduce current capture/assertion run:

```powershell
python -X utf8 scripts/verify-recording-ui.py --desktop-design
python -X utf8 scripts/verify-recording-ui.py --workspace-view-only
python -X utf8 scripts/verify-updates-ui.py
```

The visual harness also checks original speech copying with a test clipboard, one
shell, laptop minimum widths and scroll bounds, zero UI exceptions/horizontal
overflow, no video overlay over reports, actual report dirty/Undo preservation and
blocked navigation through the new File menu. Existing material-tab, participant and
unresolved-interval fixtures exercise real temporary API saves, not inference.

## Executed checks

| Check | Result |
| --- | --- |
| `scripts/check-fast.py`, existing Windows dev Python | **836 passed, 4 skipped**, plus **29** configuration tests; Ruff/JS syntax/immutable audit/CSS consistency PASS |
| Focused design/workspace/sidebar/update/unresolved tests | **56 passed** (also included above) |
| Edge `--desktop-design` | PASS: real captures, geometry, copy, dirty navigation, help/connection focus, source/settings/diagnostics/library/materials |
| Edge `--workspace-view-only` | PASS: all seven panels, storage/reset/invalid values, layouts, primary-only/empty, state/dirty/Undo, progress/errors |
| Edge `--material-tabs-only`, `--speakers-only`, `--unresolved-only` | PASS: temporary real saves and preserved editor/selection behavior |
| Edge `--spacing-only` | PASS: related controls 8 px, groups/tab content 16 px |
| `scripts/verify-updates-ui.py` | PASS: update badge, text safety, manual check, fixed external command, Escape/focus, 375–1440 px |

An initial full run failed two CSS consistency checks while source CSS was still
being refined. Bundles were rebuilt; the full run above passed. No dependencies
were installed, no Actions jobs were used to debug, and no live recording was used.

## Remaining limits

- No installed WebView2 acceptance, Windows scaling/Narrator or real NPU/GPU/LLM run.
- Generated standalone reports receive shared chrome on generation; older server
  report URLs still open `/create` and receive the current shared editor/styles.
- Existing model/provider/cloud confirmation and error behavior are unchanged.
- Copy requires browser clipboard permission; TXT/select-and-copy remains available.
- The requested MiniMax Flash Free review could not start because the provider
  returned its free-usage limit. No paid fallback or model change was made; primary
  review and actual tests remain the validation, not a claimed subagent review.
