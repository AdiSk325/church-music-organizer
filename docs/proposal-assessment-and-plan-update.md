# Proposal Assessment And Plan Update

## Why This Addendum Exists

This addendum incorporates three user proposals into the active project plan:

1. explicit visibility of manual or external inputs needed from outside the repo,
2. regular delivery of tangible work products that explain and demonstrate the system,
3. a synthetic roundtrip data stream based on generated MusicXML as auxiliary benchmark input.

The proposals are directionally strong, but they should not be adopted uncritically. This document records the recommended shape, limits, and immediate follow-up.

## Critical Assessment

### Proposal 1: Explicit Manual And External Inputs

Assessment: accept and make it operational.

Why:

- The current workflow depends on external tools that are not managed by Poetry.
- Benchmark progress is easy to misread when the environment is only partially configured.
- The project needs a clear boundary between repository-deliverable work and user-provided environment setup.

What should be treated as external or manual input today:

- Audiveris installation and CLI availability.
- Java runtime required by Audiveris.
- Tesseract installation for OCR fallback.
- Poppler for PDF rasterization through `pdf2image`.
- MuseScore or equivalent renderer for optional MusicXML to PDF export.
- Real-world licensed scan or PDF corpus for domain validation.

Decision:

- Every milestone that depends on external tooling should state that dependency explicitly.
- User-facing workflow assets should include a short prerequisites section.
- Benchmark acceptance should distinguish environment failure from code failure.

### Proposal 2: Tangible Work Products

Assessment: accept and make it a standing delivery rule.

Why:

- The project is easier to steer when each iteration yields a runnable or inspectable artifact.
- A notebook or script is a better handoff surface than a verbal summary alone.
- The benchmark-first roadmap benefits from demo artifacts that show the exact control path being measured.

Constraints:

- Demo assets must use the current code path, not a parallel toy path.
- They must state optional versus required dependencies.
- They must remain small and readable enough to function as inspection tools, not long-lived products on their own.

Decision:

- Add a documented notebook that walks through reference parsing, benchmark record creation, agent reporting, optional scan benchmarking, and synthetic data generation.
- Prefer step-by-step artifacts over large narrative documents when explaining current functionality.

### Proposal 3: Synthetic MusicXML -> PDF -> MusicXML Roundtrip Data

Assessment: accept as an auxiliary benchmark workstream, not as a substitute for real scans.

Why it is valuable:

- MusicXML generation is cheap and deterministic.
- It gives immediate ground truth for pipeline and benchmark validation.
- It is useful for stress-testing import, export, artifact bookkeeping, and regression detection.

Why it is not sufficient alone:

- Rendered PDF from pristine symbolic input is easier than real-world church prints and scans.
- It can overfit the pipeline to clean typography and ideal spacing.
- It does not replace domain gold sets, licensing work, or real scan failure analysis.

Decision:

- Add a synthetic SATB generator now.
- Keep synthetic cases clearly labeled in manifests.
- Use synthetic data for contract testing, regression testing, and benchmark harness validation.
- Do not use synthetic results alone as evidence of production readiness.

## Plan Changes

## New Standing Requirement: Deliverable Surface Per Iteration

Each meaningful iteration should produce at least one of:

- a runnable notebook,
- a smoke runner or CLI script,
- a manifest or report artifact,
- a validation-focused test slice.

## New Workstream: Workflow Assets

Add a lightweight documentation-and-demo stream parallel to implementation.

Immediate deliverables:

- a notebook walkthrough for the main project flow,
- explicit prerequisite listing,
- one example report path and one example synthetic-data path.

## New Workstream: Synthetic Roundtrip Benchmarking

Add a synthetic-data stream with the following order:

1. Generate structurally valid synthetic SATB MusicXML.
2. Persist a manifest linking case id, seed, and ground truth file.
3. Optionally render MusicXML to PDF when a renderer is available.
4. Feed rendered PDF back into the benchmark pipeline.
5. Track synthetic results separately from real scan results.

## Updated Near-Term Backlog

### Immediate

1. Keep the raw-engine benchmark contract as the default scored path.
2. Provide a notebook demonstrating the current benchmarkable workflow.
3. Provide a synthetic SATB MusicXML generator with manifest output.

### Next

1. Add a manifest-driven smoke benchmark runner for real scan or PDF cases.
2. Add optional synthetic PDF rendering using external renderer configuration.
3. Separate synthetic and real benchmark series in reporting.

### Later

1. Add richer synthetic controls: lyrics, repeats, dotted notes, chord density, and staff grouping variants.
2. Compare synthetic roundtrip results against real scan results to detect overfitting to clean renders.
3. Extend synthetic generation only after the real benchmark harness is stable.

## Manual Or External Inputs Needed From The User

The project can continue without all of these at once, but they are the main outside-the-repo needs:

1. Audiveris installed and callable from CLI, or a confirmed path for `AUDIVERIS_PATH`.
2. Tesseract installed if OCR fallback should be exercised locally.
3. Poppler installed if PDF rasterization should be exercised locally.
4. MuseScore path if you want automated MusicXML -> PDF rendering in the synthetic loop.
5. Additional licensed real scan or PDF examples once we move beyond the current smoke sample.

## Immediate Follow-Up Triggered By This Addendum

This addendum authorizes three concrete artifacts in the repo:

- a workflow notebook,
- a synthetic SATB MusicXML generator,
- plan updates that keep external prerequisites visible.