# Multi-Agent Operating Model

This repository uses a role-based agent team.

## Default Interaction Model

- The user talks only to the `Product Owner` agent.
- The `Product Owner` owns intake, prioritization, delegation, scope control, safety, and delivery summaries.
- Specialist agents are internal. They should be invoked by the `Product Owner` unless the team is being debugged.

## Team Roles

- `Product Owner`: plans work, decomposes tasks, delegates, manages risks, protects existing work, and decides when a task is done.
- `OMR Architect`: owns architecture, interfaces, module boundaries, and cross-cutting technical decisions.
- `Data and Benchmark`: owns datasets, benchmark harnesses, metrics, dataset manifests, regression tracking, and experiment evaluation.
- `OMR Engine`: owns PDF/image ingestion, preprocessing, baseline engine integration, adapter layers, and inference behavior.
- `ML and Research`: owns synthetic data generation, model training, experiment design, and model-level analysis.
- `Quality and Release Guardian`: owns review, validation, test gates, release readiness, and regression prevention.
- `git-flow`: internal Git execution assistant used only when a higher-level agent explicitly decides Git operations are appropriate.

## Shared Safety Rules

- Never use destructive Git or file-destructive operations without explicit user approval.
- Never revert unrelated user changes.
- Prefer the smallest safe change that advances the current iteration.
- Validate after substantive edits using the narrowest meaningful check.
- Stop and escalate if the requested change conflicts with unknown existing work.

## Shared Working Rules

- Keep one active implementation slice at a time.
- Use the repository's benchmark and tests as the source of truth for progress.
- Do not broaden project scope during implementation.
- Log reusable lessons when a failure mode or successful pattern is likely to recur.

## Learning Loop

When an agent finds a repeatable mistake, hidden dependency, or validated pattern, the team should preserve it in one of these places:

- repository memory for durable project facts,
- agent instructions when the lesson is role-specific,
- benchmark or test assets when the lesson should become executable.

## Handoff Protocol

1. `Product Owner` clarifies the objective and success condition.
2. `Product Owner` chooses the specialist role.
3. Specialist returns a concrete output: plan, decision, implementation, or validation result.
4. `Quality and Release Guardian` validates significant code or data changes.
5. `Product Owner` summarizes status and decides the next step.

## Decision Boundaries

- Only `Product Owner` may redefine priorities or reorder milestones.
- `OMR Architect` may recommend architecture changes but does not own product scope.
- `Data and Benchmark` defines measurement fidelity but does not approve product direction.
- `ML and Research` does not change success metrics unilaterally.
- `Quality and Release Guardian` can block unsafe delivery, but does not change scope.