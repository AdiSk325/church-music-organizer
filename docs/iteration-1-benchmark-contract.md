# Iteration 1 Benchmark Contract

## Purpose

This document freezes the benchmark contract for iteration 1 of the PDF or scan to MusicXML OMR work.

The goal of iteration 1 is not to solve OMR quality. The goal is to establish a leak-resistant, reproducible benchmark path for one real baseline engine, using `ScoreGraph` as the canonical intermediate representation.

This contract exists to prevent false progress. A run may not be counted as a benchmark success unless it follows the rules below.

## Scope

Iteration 1 covers:

- one real baseline engine path,
- one smoke-set benchmark mode,
- one canonical normalization path into `ScoreGraph`,
- one benchmark record format,
- one minimal set of executable quality gates.

Iteration 1 does not cover:

- ensemble selection,
- model training or fine-tuning,
- confidence calibration,
- production-grade multi-page PDF orchestration,
- production-grade release thresholds,
- a full experiment tracker.

## Benchmark Mode Rules

The primary benchmark mode for iteration 1 must evaluate raw engine output only.

The following are forbidden in the scored benchmark path:

- reference-assisted mutation of the evaluated score,
- `ReferenceMatcher` enrichment,
- LLM repair,
- silent substitution of reference MusicXML for missing engine output,
- mixing assisted and unassisted runs in one baseline series.

If assisted modes are needed for diagnostics, they must be reported separately and must never be used as the headline benchmark result.

## Pipeline Contract

The benchmarked control path is:

1. Input ingestion
2. Engine execution
3. MusicXML normalization into `ScoreGraph`
4. Constraint validation
5. Benchmark scoring
6. Artifact and report persistence

Responsibilities are split as follows.

### Ingestion

Pipeline-owned.

- Detect input kind.
- Validate input path.
- Rasterize PDF only if the selected engine does not support PDF directly.
- Record both the original input path and the actual invocation input path.

### Engine Execution

Adapter-owned.

- Invoke the baseline engine.
- Return explicit status: `success`, `failed`, `timeout`, or `unsupported`.
- Persist raw engine artifacts.
- Return the engine-produced MusicXML or MXL path when available.

The engine adapter must not:

- construct `ScoreGraph`,
- run musical constraints,
- compute benchmark metrics,
- read or inject reference material into the scored run.

### Normalization

Pipeline-owned.

- Parse engine-produced MusicXML or MXL.
- Convert it into canonical `ScoreGraph`.
- Preserve structural fidelity as much as the current parser allows.

### Validation

Constraint-owned.

- Validate structural and musical consistency on normalized `ScoreGraph`.
- Report violations.
- Do not overwrite benchmark input with repaired content in the primary benchmark mode.

### Reporting

Benchmark-owned.

- Build one durable benchmark record per case.
- Persist artifact paths, engine metadata, and score metrics.
- Mark a run as non-comparable when output is missing or normalization fails.

## Canonical IR Decision

`ScoreGraph` remains the canonical intermediate representation for iteration 1.

No schema expansion is mandatory before the first adapter lands. The known limitation is current normalization fidelity for internal voices. That limitation must be documented in reports, not solved by widening scope before the first benchmarkable baseline exists.

## Required Data Contracts

### EngineRunResult

Minimal required fields:

- `engine_id`
- `engine_version`
- `input_path`
- `invocation_input_path`
- `input_kind`
- `status`
- `musicxml_path`
- `engine_artifact_paths`
- `elapsed_ms`
- `error_message`
- `stderr_excerpt`
- `pages_processed`
- `metadata`

Notes:

- `musicxml_path` is present only when the engine produced parseable MusicXML or MXL.
- `pages_processed` is required because the current PDF path is not yet full-document safe.

### BenchmarkRecord

Minimal required fields:

- `run_id`
- `timestamp`
- `input_path`
- `reference_path`
- `engine_run`
- `comparable`
- `non_comparable_reason`
- `normalization_status`
- `score_summary`
- `validation_violation_count`
- `validation_violations`
- `accuracy`
- `structural_metrics`
- `exported_musicxml_path`
- `alignment_strategy`

Notes:

- `engine_run` embeds `EngineRunResult`.
- `alignment_strategy` is required because current score comparison remains heuristic in iteration 1.

## Smoke Set Contract

Iteration 1 uses a manifest-driven smoke set.

Each manifest entry must define:

- document id,
- input path,
- input type,
- expected page count,
- notation profile,
- QA status,
- license status,
- reference path,
- reference scope,
- page-level records when needed.

Recommended status enums:

- QA: `candidate`, `reviewed`, `gold`
- license: `unknown`, `internal-only`, `cleared-for-dev`, `redistributable`

Minimum runnable smoke set for iteration 1:

- one checked-in scan or PDF case with checked-in reference MusicXML,
- one deterministic benchmark config,
- one report snapshot per run.

## Iteration 1 Headline Metrics

Only the following metrics are allowed to be headline iteration 1 metrics:

- end-to-end run success rate,
- valid MusicXML rate,
- page coverage accuracy,
- measure count accuracy,
- pitch accuracy,
- rhythm accuracy.

The following may be reported as diagnostic or provisional but are not release-defining in iteration 1:

- voice assignment accuracy,
- lyrics recall,
- chord recall,
- dotted note recall,
- metadata quality,
- trend deltas across engines.

## Quality Gates

### Entry Gates Before Adapter Implementation

The following must be true before the first engine adapter PR is considered valid:

1. Benchmark mode is explicitly defined as raw-engine only.
2. Assisted modes are separated from scored benchmark mode.
3. Smoke set input and reference assets are fixed and named.
4. Benchmark record schema is fixed.
5. Artifact layout for one run is fixed.

### Exit Gates For Iteration 1

The following must be true before iteration 1 can be closed:

1. One real engine adapter runs end to end through the benchmark path.
2. One smoke-set case produces persisted artifacts and a benchmark record.
3. A run that falls back to metadata-only extraction or stub score output is reported as failure for the primary benchmark mode.
4. A benchmark report clearly states whether the run is comparable.
5. Results are reproducible under the same config and input.

## Known Limitations Accepted In Iteration 1

- PDF handling may still be first-page only.
- Internal voice fidelity may remain incomplete in the normalization layer.
- Current alignment is heuristic and must be labeled as such.
- Benchmarking is smoke-grade, not release-grade.

These limitations are acceptable only if they are visible in reports and are not hidden behind optimistic aggregate scores.

## First Implementation Slice

The first implementation slice after this contract is accepted is:

1. Add `EngineRunResult` and one minimal engine adapter contract.
2. Wrap the current Audiveris execution path in that adapter.
3. Expose a detailed pipeline run result without breaking existing callers.
4. Build one benchmark record from that result.
5. Validate one smoke-set case in raw-engine mode.

## Out Of Scope Decisions Deferred

The following decisions are explicitly deferred beyond iteration 1:

- engine registry or plugin loading,
- baseline arbitration across multiple engines,
- confidence scoring,
- full release thresholds,
- dataset tracker infrastructure,
- model training roadmap details,
- rich provenance fields inside `ScoreGraph`.

## Ownership

- `Product Owner`: approves the benchmark contract and implementation order.
- `OMR Architect`: owns adapter and pipeline contract decisions.
- `Data and Benchmark`: owns manifest, metrics, and benchmark record shape.
- `OMR Engine`: owns the first real adapter implementation.
- `Quality and Release Guardian`: enforces the gates in this document.