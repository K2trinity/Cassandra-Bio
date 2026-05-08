# Investigation UI Workflow Design

## Context

The Investigation surface is the primary disease and drug research workflow in the Flask app. The Neo4j graph surface and captured-image preview surface have been removed from the product boundary. The remaining page should focus on query entry, optional PDF evidence, live execution state, and final report actions.

The K-line experience is out of scope. This work stays on the `investigation-ui-workflow-optimization` branch and must merge back to `main` after verification.

## Goals

- Make the Investigation page feel like an operational research workspace instead of a large hero page.
- Keep the existing Flask, Jinja, Tailwind runtime, Socket.IO, and endpoint contracts.
- Preserve existing element IDs used by JavaScript and tests: `queryForm`, `queryInput`, `analyzeBtn`, `cancelBtn`, `dropZone`, `fileInput`, `fileList`, `progressSection`, `logContainer`, `resultsSection`, `completionMessage`, and `downloadBtn`.
- Remove remaining graph and captured-image UI references from the Investigation frontend.
- Add stable semantic hooks so the page can be regression-tested without depending on decorative class names.

## Non-Goals

- No K-line UI changes.
- No new frontend build system.
- No Neo4j, graph canvas, image capture, or figure preview return path.
- No large app-wide design-system migration.

## Proposed Approach

Use a focused in-place Jinja refactor. The page keeps the current backend and JavaScript event model, but the visible structure becomes a two-column workbench:

- Left column: research query, quick examples, and optional evidence upload.
- Right column: workflow status, progress timeline, live terminal, and result actions.

The design replaces the old hero-gradient composition with restrained panels, compact controls, clear stage labels, and stable `data-testid` attributes. JavaScript receives a small state helper so submit, completion, error, and reset all update one status surface.

## Component Boundaries

- `analysis-input-panel`: query entry, examples, upload affordance, and selected PDFs.
- `workflow-summary-panel`: current run status, stage badges, progress percentage, and elapsed time.
- `workflow-timeline`: existing harvest, handoff, and writing steps with stable stage IDs.
- `live-log-panel`: terminal log stream with clear action.
- `result-summary-panel`: completion message, report preview toggle, and report actions.

## Data Flow

The page still submits `FormData` to `/api/analyze`, listens to Socket.IO `progress`, `step`, `analysis_complete`, and `analysis_error`, and uses `/api/status` as the polling fallback. The new status panel mirrors the existing values instead of introducing new API fields.

## Error Handling

Errors keep the existing retry affordance in the log panel. The status summary switches to an error tone, the progress message shows the error, and the run button returns to the ready state.

## Testing

Add a Flask-rendered UI regression test that loads `/investigation` and asserts:

- The new semantic workbench regions exist.
- The expected workflow stages are present.
- Removed graph and captured-image remnants are absent.
- The old hero copy no longer dominates the page.

Existing report and PDF tests remain part of final verification.
