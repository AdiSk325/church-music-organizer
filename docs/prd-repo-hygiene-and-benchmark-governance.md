# PRD: Repo Hygiene and Benchmark Governance

## 1. Context and Problem Statement
The project made strong progress on benchmark-first OMR work (manifest-driven smoke benchmark, synthetic SATB generator, workflow notebook), but the repository currently mixes:

- source code and long-lived configuration,
- generated benchmark outputs and notebook execution artifacts,
- large binary inputs used for local experiments.

This lowers review quality, increases merge friction, obscures real regressions, and creates release risk.

## 2. Product Goal
Establish a stable, auditable, benchmark-first development baseline where:

- repository history stays focused on code and intentional benchmark contracts,
- generated artifacts are isolated from tracked source,
- benchmark runs are reproducible and comparable,
- acceptance decisions are supported by machine-readable summaries.

## 3. Success Metrics
Primary metrics:

- `git status` cleanliness after standard local runs: no unintended tracked artifacts.
- PR signal quality: no generated report churn in feature PRs by default.
- Benchmark comparability rate for smoke set: >= 80% cases comparable once dependencies are present.
- Benchmark run success rate in smoke harness: >= 95% for manifest-valid cases.

Operational metrics:

- Time-to-review for benchmark-related PRs reduced by at least 30% (team-estimated).
- Zero accidental commits of notebook outputs and local report directories over next 3 iterations.

## 4. Scope
### In scope
- Artifact governance policy and path conventions.
- `.gitignore` hardening for generated benchmark/report/notebook artifacts.
- Lightweight benchmark contract doc updates and runbook standardization.
- Validation gates for manifest schema and smoke summary integrity.
- Separation of real vs synthetic benchmark reporting channels.

### Out of scope
- Rewriting core OMR extraction architecture.
- Replacing Audiveris or introducing a new baseline engine in this PRD.
- Full CI redesign.

## 5. Personas and Stakeholders
- Product Owner: prioritization, acceptance gates.
- OMR Engine developer: pipeline and benchmark execution reliability.
- Data and Benchmark owner: manifest quality, metrics integrity, reporting taxonomy.
- Quality and Release owner: regression prevention, release readiness checks.

## 6. Requirements
### Functional requirements
1. Define canonical artifact classes:
- `source_of_truth`: code, manifests, benchmark contracts, curated references.
- `generated_ephemeral`: report runs, temporary pipeline outputs, notebook execution outputs.
- `curated_inputs`: intentionally versioned PDFs/scans used in benchmark manifests.

2. Enforce repository hygiene:
- Ignore generated report outputs by default.
- Keep benchmark manifests tracked.
- Keep curated test fixtures tracked only in designated paths.

3. Benchmark governance:
- Smoke manifest must be schema-valid before execution.
- Smoke run must emit aggregate summary JSON with fixed headline metrics.
- Real and synthetic result series must be clearly separated in output paths.

4. Runbook clarity:
- One documented happy-path for running smoke benchmark locally.
- One documented troubleshooting section for missing external dependencies.

### Non-functional requirements
- No destructive history rewrite.
- Minimal disruption to current developer workflow.
- Deterministic script behavior with explicit seeds and manifest IDs.

## 7. Constraints and Assumptions
- External tools (Audiveris, Java, Poppler, Tesseract, optional MuseScore) may be missing on some machines.
- Repository already contains useful benchmark assets mixed with generated artifacts.
- Changes must preserve current smoke benchmark utility.

## 8. Delivery Plan (Milestones)
## Milestone A: Hygiene Baseline
- Harden `.gitignore` for generated benchmark and notebook outputs.
- Define and document allowed tracked binary fixture locations.
- Produce migration checklist for existing tracked artifacts.

Acceptance criteria:
- Fresh local benchmark run does not produce staged/unstaged noise from generated dirs.
- Reviewed list of intentionally tracked binary inputs is explicit.

## Milestone B: Benchmark Contract Stabilization
- Normalize manifest expectations and validation messaging.
- Standardize summary JSON fields and semantic meanings.
- Separate output namespaces for `real_smoke` and `synthetic_roundtrip`.

Acceptance criteria:
- Two independent runs produce parseable summaries with stable keys.
- Contract doc aligns with script outputs and examples.

## Milestone C: Release Safety Gate
- Add validation checklist for benchmark-related PRs.
- Add minimum evidence requirement for acceptance (summary JSON + key deltas).
- Define rollback trigger conditions.

Acceptance criteria:
- Quality review can approve/reject from documented evidence without manual digging in temp dirs.

## 9. Risks and Mitigations
Risk: Over-ignoring files and losing curated fixtures.
Mitigation: explicit allowlist paths and pre-merge fixture inventory review.

Risk: Developers bypass runbook and reintroduce artifact churn.
Mitigation: short PR template checklist + quality gate review.

Risk: Dependency absence interpreted as benchmark regressions.
Mitigation: explicit non-comparable reasons and dependency diagnostics in summary.

## 10. Validation Strategy
- Dry-run validation on current smoke manifest.
- Confirm summary JSON headline metrics are present and typed.
- Verify git cleanliness before/after benchmark execution.
- Quality gate review against checklist.

## 11. Workstream Ownership (Delegation Map)
- OMR Architect:
  - Define artifact taxonomy boundaries and canonical folder contract.
  - Propose low-risk refactor boundaries for benchmark interfaces.
- Data and Benchmark:
  - Own manifest contract, metric semantics, summary schema stability.
  - Define real vs synthetic reporting taxonomy.
- OMR Engine:
  - Implement script/path behavior changes and guardrails in benchmark runners.
  - Ensure robust behavior under missing dependencies.
- Quality and Release Guardian:
  - Build release/hygiene gate checklist and regression audit.
  - Validate final readiness evidence.

## 12. Rollout
Phase 1: merge hygiene and docs updates.
Phase 2: merge benchmark contract consistency updates.
Phase 3: enforce quality gate for benchmark PRs.

## 13. Definition of Done
- Approved policy and runbook docs.
- Implemented ignore and path governance changes.
- Smoke benchmark outputs conform to contract.
- Quality gate checklist used in at least one end-to-end validation cycle.

## 14. Delegated Execution Packages (Accepted)
This PRD has been delegated to specialized workstreams and converted into actionable execution packages.

### Workstream A: OMR Architect
- Define canonical folder contract for tracked vs generated artifacts.
- Keep low-risk boundaries around existing smoke orchestration and agent execution.
- Introduce optional output series namespace without breaking current defaults.
- Add acceptance checks for Milestone A and B with explicit architectural risks.

### Workstream B: Data and Benchmark
- Harden manifest contract with explicit required fields, enums, and validation semantics.
- Freeze headline metrics contract for summary JSON including nullability rules.
- Enforce taxonomy split for `real_smoke` and `synthetic_roundtrip`.
- Define minimal baseline-delta strategy for regression detection.

### Workstream C: OMR Engine
- Implement path safety and output namespace behavior in smoke runner.
- Normalize non-comparable reasons and dependency diagnostics.
- Keep backward compatibility for existing runner and summary fields.
- Deliver runbook-level command flow for happy path and failure path.

### Workstream D: Quality and Release Guardian
- Define benchmark PR quality gate and acceptance evidence contract.
- Enforce lightweight but strict regression and hygiene checks.
- Add rollback criteria and playbooks per milestone.
- Validate release-readiness against this PRD Definition of Done.

## 15. Wave Plan (Execution Order)
### Wave 1 (Hygiene Baseline)
- `.gitignore` and artifact policy hardening.
- Fixture inventory and explicit allowlist confirmation.
- Git-cleanliness validation after smoke run.

Exit criteria:
- No unintended tracked artifact churn after local benchmark execution.

### Wave 2 (Contract Stabilization)
- Manifest validation hardening with compatibility mode.
- Stable summary schema keys and metric semantics.
- Real vs synthetic output namespace separation.

Exit criteria:
- Two independent runs produce parseable, schema-stable summaries.

### Wave 3 (Quality Gate Enforcement)
- Benchmark PR checklist and required evidence bundle.
- Delta-based regression decision policy.
- One end-to-end rehearsal review on a benchmark-impacting PR.

Exit criteria:
- Quality team can approve or reject using only structured evidence.

## 16. Immediate Next 72h Backlog
1. Finalize and merge hygiene policy update with fixture allowlist.
2. Add series separation and contract metadata in smoke summary output.
3. Add/extend tests for manifest validation and summary schema stability.
4. Publish benchmark PR evidence template and run one gate rehearsal.
