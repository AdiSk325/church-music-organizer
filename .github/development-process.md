# Development Process — TDD & Metrics-Driven OMR Pipeline

> How to develop the Church Music Organizer project using a human-in-the-loop,
> test-driven, metrics-driven approach.
>
> Audience: Human developers + AI agents (Copilot, Claude, etc.)
> Last updated: 2026-02-17

---

## 1. Core Principles

| # | Principle | Why |
|---|-----------|-----|
| 1 | **Each pipeline step is an independent, testable unit** | Isolate errors, enable per-step debugging |
| 2 | **Every step saves inspectable artifacts** | Human can verify intermediate results |
| 3 | **Test cases define truth, code implements it** | TDD — write expected output first, then code to match |
| 4 | **Metrics are computed and stored, not eyeballed** | Regression detection, progress tracking |
| 5 | **Refactor before features** | Clean architecture enables faster iteration |

---

## 2. Pipeline Steps — Executable Contracts

Each pipeline step has a **strict contract**: typed input, typed output, validation
criteria, and saved artifacts. Steps are independently runnable.

### Step Registry

| Step | Module | Input Type | Output Type | Artifact Saved |
|------|--------|-----------|-------------|----------------|
| 1. Ingestion | `preprocessing.py` | `Path` (PDF/PNG) | `IngestionResult` | `{run}/step_01_pages/*.png` |
| 2. Preprocessing | `preprocessing.py` | `List[PageImage]` | `List[PreprocessedImage]` | `{run}/step_02_preprocessed/*.png` |
| 3. Text Classification | `text_classifier.py` | `Path` (PDF) | `ClassifiedText` | `{run}/step_03_text.json` |
| 4. Staff Detection | `staff_detector.py` | `PreprocessedImage` | `StaffLayout` | `{run}/step_04_layout.json` + debug image |
| 5. Staff Splitting | `staff_splitter.py` | `PreprocessedImage` + `StaffLayout` | `List[StaffImage]` | `{run}/step_05_staves/*.png` |
| 6. OMR per Staff | `engines/*.py` | `StaffImage` | `OMRResult` | `{run}/step_06_omr/*.musicxml` |
| 7. Score Assembly | `score_builder.py` | `List[OMRResult]` + `StaffLayout` + `ClassifiedText` | `ScoreXML` | `{run}/step_07_assembled.musicxml` |
| 8. Lyrics Alignment | `lyrics_aligner.py` | `ScoreXML` + `ClassifiedText` | `ScoreXML` | `{run}/step_08_lyrics.musicxml` |
| 9. Validation | `musicxml_validator.py` | `ScoreXML` | `ValidationReport` + `ScoreXML` | `{run}/step_09_validated.musicxml` + `report.json` |
| 10. Output | orchestrator | `ScoreXML` | Final `.musicxml` | `{run}/step_10_final.musicxml` |

### Artifact Directory Structure

Each pipeline run produces a timestamped artifact directory:

```
data/processed/runs/
└── 2026-02-17_143052_Alleluja/
    ├── run_metadata.json          # Input path, engine, parameters, git SHA
    ├── step_01_pages/
    │   ├── page_001.png
    │   └── page_002.png
    ├── step_02_preprocessed/
    │   ├── page_001_preprocessed.png
    │   └── page_002_preprocessed.png
    ├── step_03_text.json          # ClassifiedText serialized
    ├── step_04_layout.json        # StaffLayout serialized per page
    ├── step_04_debug.png          # Staff detection overlay (visual)
    ├── step_05_staves/
    │   ├── page_001_staff_0.png
    │   ├── page_001_staff_1.png
    │   └── page_001_staff_2_3.png  # grand staff
    ├── step_06_omr/
    │   ├── staff_0.musicxml
    │   ├── staff_1.musicxml
    │   └── staff_2_3.musicxml
    ├── step_07_assembled.musicxml
    ├── step_08_lyrics.musicxml
    ├── step_09_validated.musicxml
    ├── step_09_report.json        # Validation issues
    ├── step_10_final.musicxml
    └── metrics.json               # All computed metrics for this run
```

---

## 3. Test Case Structure

### 3.1 Directory Layout

```
tests/
├── __init__.py
├── conftest.py                    # Shared pytest fixtures
├── test_database.py               # Database unit tests
│
├── pipeline/                      # Per-step unit tests
│   ├── __init__.py
│   ├── test_step_01_ingestion.py
│   ├── test_step_02_preprocessing.py
│   ├── test_step_03_text_classifier.py
│   ├── test_step_04_staff_detector.py
│   ├── test_step_05_staff_splitter.py
│   ├── test_step_06_omr_engine.py
│   ├── test_step_07_score_builder.py
│   ├── test_step_08_lyrics_aligner.py
│   ├── test_step_09_validator.py
│   └── test_step_10_integration.py
│
├── metrics/                       # Metrics computation and regression
│   ├── __init__.py
│   ├── test_metrics_computation.py
│   └── test_metrics_regression.py
│
└── fixtures/                      # Test data (ground truth)
    ├── manifest.yaml              # Master list of all test cases
    │
    ├── Alleluja_werset_sw_Anna/   # One directory per test piece
    │   ├── case.yaml              # Test case metadata & expected values
    │   ├── input.pdf              # Source file
    │   ├── expected_final.musicxml
    │   ├── expected_step_03_text.json
    │   ├── expected_step_04_layout.json
    │   └── expected_step_06_omr/
    │       ├── staff_0.json       # Expected note count, pitch range, measures
    │       └── staff_1.json
    │
    ├── Boze_moj/
    │   ├── case.yaml
    │   ├── input.png
    │   ├── expected_final.musicxml
    │   └── ...
    │
    └── do_Jana_Kantego/
        ├── case.yaml
        ├── input.pdf
        ├── expected_final.musicxml
        └── ...
```

### 3.2 Test Case YAML Schema — `case.yaml`

This is the **core artifact that the human prepares**. It defines what
the pipeline SHOULD produce for this input.

```yaml
# tests/fixtures/Alleluja_werset_sw_Anna/case.yaml

id: "alleluja_sw_anna"
title: "Alleluja - werset św. Anna"
source: "input.pdf"
difficulty: "medium"         # easy | medium | hard | extreme
tags: ["satb", "organ", "single_page", "polish_text"]
notes: "SATB + Organo, recto tono section, 1 page"

# ── Step 1: Ingestion ──────────────────────────────
step_01_ingestion:
  expected_pages: 1
  expected_dpi: 300
  has_text_layer: true
  page_dimensions_mm: [210, 297]  # A4 approximate

# ── Step 2: Preprocessing ──────────────────────────
step_02_preprocessing:
  expected_pages: 1
  # Metrics computed automatically:
  # - deskew_angle (should be < 0.5°)
  # - laplacian_variance (should be > 100)
  # - black_pixel_ratio (expected range)

# ── Step 3: Text Classification ────────────────────
step_03_text:
  title: "Alleluja"
  composer: null              # or "Jan Kowalski"
  arranger: null
  part_names: ["S", "A", "T", "B", "Org."]
  has_lyrics: true
  lyrics_snippet: "Al-le-lu-ja"  # First few syllables for verification
  tempo: null

# ── Step 4: Staff Detection ───────────────────────
step_04_layout:
  pages:
    - page: 1
      staff_count: 4
      groups:
        - type: "bracket"
          staff_indices: [0, 1]
          label: "SA+TB"
        - type: "brace"
          staff_indices: [2, 3]
          label: "Organo"
      systems: 1

# ── Step 5: Staff Splitting ───────────────────────
step_05_splitting:
  expected_images: 3         # SA, TB, Org (grand staff)
  splits:
    - staff_indices: [0]
      group_type: "bracket"
      label: "SA"
    - staff_indices: [1]
      group_type: "bracket"
      label: "TB"
    - staff_indices: [2, 3]
      group_type: "brace"
      label: "Organo"

# ── Step 6: OMR per Staff ─────────────────────────
step_06_omr:
  staves:
    - label: "SA"
      clef: "G"
      key_signature: 0       # 0 = C major / A minor, -1 = F major, etc.
      time_signature: "4/4"
      expected_measures: 6
      expected_note_count: [20, 30]  # range [min, max]
      pitch_range_midi: [60, 72]     # C4 to C5
    - label: "TB"
      clef: "F"
      key_signature: 0
      time_signature: "4/4"
      expected_measures: 6
      expected_note_count: [20, 30]
      pitch_range_midi: [48, 60]
    - label: "Organo"
      clef: ["G", "F"]       # grand staff
      key_signature: 0
      time_signature: "4/4"
      expected_measures: 6
      expected_note_count: [30, 50]
      pitch_range_midi: [41, 72]

# ── Step 7: Score Assembly ────────────────────────
step_07_assembly:
  expected_parts: 3
  part_names: ["S A", "T B", "Organo"]
  grouping:
    - type: "bracket"
      parts: ["S A", "T B"]
    - type: "brace"
      parts: ["Organo"]
  total_measures: 6
  beats_per_measure: 4.0

# ── Step 8: Lyrics ────────────────────────────────
step_08_lyrics:
  vocal_parts: ["S A", "T B"]
  non_vocal_parts: ["Organo"]
  expected_syllable_count: [10, 20]  # range

# ── Step 9: Validation ───────────────────────────
step_09_validation:
  max_beat_errors: 0
  max_ambitus_warnings: 2
  expected_key_consistency: true
  expected_part_length_match: true

# ── Step 10: Final Output ────────────────────────
step_10_final:
  ground_truth_file: "expected_final.musicxml"
  # End-to-end metrics thresholds:
  min_pitch_accuracy: 0.80
  min_duration_accuracy: 0.80
  min_measure_count_accuracy: 1.0
  min_part_count_accuracy: 1.0
```

### 3.3 Manifest — `manifest.yaml`

```yaml
# tests/fixtures/manifest.yaml
# Master registry of all test cases.
# Human maintains this file.

test_cases:
  - id: "alleluja_sw_anna"
    path: "Alleluja_werset_sw_Anna"
    status: "active"        # active | wip | disabled
    priority: 1             # 1 = must pass, 2 = should pass, 3 = aspirational

  - id: "boze_moj"
    path: "Boze_moj"
    status: "active"
    priority: 1

  - id: "do_jana_kantego"
    path: "do_Jana_Kantego"
    status: "active"
    priority: 2             # multi-page, harder

  - id: "psalm_adwent"
    path: "psalm_adwent"
    status: "wip"
    priority: 2
```

---

## 4. Metrics Framework

### 4.1 Per-Step Metrics

Each step computes metrics automatically. Metrics are stored in
`metrics.json` per run and aggregated in the metrics database.

| Step | Metric Name | Type | How Computed |
|------|-------------|------|-------------|
| 1 | `pages_count` | int | Count of rendered pages |
| 1 | `dpi` | int | From image metadata |
| 1 | `has_text_layer` | bool | PyMuPDF text extraction check |
| 2 | `deskew_angle` | float | Measured correction angle |
| 2 | `laplacian_variance` | float | cv2.Laplacian variance (sharpness) |
| 2 | `black_pixel_ratio` | float | Black pixels / total pixels |
| 3 | `title_match` | bool | Extracted title == expected title |
| 3 | `part_names_match` | bool | Exact set match |
| 3 | `lyrics_recall` | float | Expected snippet found in extracted lyrics |
| 4 | `staff_count` | int | Detected staves |
| 4 | `staff_count_accuracy` | float | actual == expected ? 1.0 : 0.0 |
| 4 | `group_accuracy` | float | Groups match expected |
| 5 | `split_count` | int | Number of staff images produced |
| 5 | `split_count_accuracy` | float | actual == expected ? 1.0 : 0.0 |
| 6 | `measures_detected` | int | Per staff |
| 6 | `measure_count_accuracy` | float | Per staff, actual/expected |
| 6 | `clef_accuracy` | float | Per staff |
| 6 | `time_sig_accuracy` | float | Per staff |
| 6 | `note_count_in_range` | bool | Per staff, within [min, max] |
| 6 | `pitch_range_ok` | bool | Per staff, within expected MIDI range |
| 7 | `part_count_accuracy` | float | Actual parts == expected parts |
| 7 | `part_names_accuracy` | float | Name match ratio |
| 7 | `grouping_accuracy` | float | Bracket/brace correct |
| 7 | `total_measures_accuracy` | float | Measure count match |
| 8 | `lyrics_attached` | bool | At least some lyrics on vocal parts |
| 8 | `syllable_count_in_range` | bool | Within expected range |
| 9 | `beat_errors` | int | Measures with wrong beat count |
| 9 | `ambitus_warnings` | int | Notes outside expected range |
| 9 | `validation_pass` | bool | All critical checks passed |
| 10 | `pitch_accuracy` | float | Note-by-note pitch match vs ground truth |
| 10 | `duration_accuracy` | float | Note-by-note duration match |
| 10 | `note_accuracy` | float | Both pitch AND duration correct |
| 10 | `measure_accuracy` | float | % measures identical to ground truth |
| 10 | `overall_score` | float | Weighted composite of all step metrics |

### 4.2 Metrics Storage

Metrics are stored in SQLite for regression tracking:

```
data/metrics.db

Tables:
  runs:
    - run_id (UUID)
    - timestamp
    - git_sha
    - test_case_id
    - engine_name
    - pipeline_version

  step_metrics:
    - run_id (FK)
    - step_number (1-10)
    - metric_name
    - metric_value (float)
    - metric_type (accuracy | count | bool | float)

  regression_baselines:
    - test_case_id
    - step_number
    - metric_name
    - baseline_value
    - baseline_date
    - baseline_run_id
```

### 4.3 Regression Detection

After each run, compare metrics against the baseline:

```
🟢 IMPROVED: pitch_accuracy 0.42 → 0.68 (+0.26)
⚪ UNCHANGED: staff_count_accuracy 1.0 → 1.0
🔴 REGRESSED: measure_count_accuracy 1.0 → 0.67 (-0.33)
```

Rule: **No merge is allowed if any priority-1 test case has a regression
on critical metrics** (staff_count, part_count, measure_count).

---

## 5. Human Responsibilities — What YOU Prepare

### Per Test Case (one-time effort)

| # | What to Prepare | How | Estimated Time |
|---|-----------------|-----|----------------|
| 1 | **Source PDF/PNG** | Scan or download the sheet music | 5 min |
| 2 | **Ground truth MusicXML** | Manually create in MuseScore, export as MusicXML | 30-120 min |
| 3 | **`case.yaml`** | Fill in the template with expected values per step | 15-30 min |
| 4 | **Visual verification** | Open ground truth in MuseScore, confirm correctness | 10 min |

### Per Development Cycle

| # | What to Do | When |
|---|-----------|------|
| 1 | **Review metrics report** | After agent completes a task |
| 2 | **Verify MuseScore output** | Open `_final.musicxml` in MuseScore, compare visually with PDF |
| 3 | **Update `case.yaml` if needed** | When expected values change (e.g., you realize the key is different) |
| 4 | **Approve/reject PR** | Based on metrics regression report |

### What the Agent Provides to You

| # | Artifact | Purpose |
|---|----------|---------|
| 1 | **Per-step artifact directory** | Inspect intermediate outputs |
| 2 | **Metrics JSON** | Machine-readable results |
| 3 | **Regression report** | What improved, what regressed |
| 4 | **Test report** (markdown) | Human-readable summary using the existing template |

---

## 6. Agent Responsibilities — How AI Agents Work

### Before Writing Code

1. Read `case.yaml` for the test cases you're targeting
2. Run existing tests: `poetry run pytest tests/ -v`
3. Run pipeline on target test case, capture metrics baseline
4. Create a feature branch following gitflow convention

### Writing Code

1. Write/update failing test in `tests/pipeline/test_step_NN_*.py` first (TDD)
2. Implement the feature/fix in the relevant module
3. Keep modules under **400 lines** — split if exceeding
4. Use type hints, Google docstrings, `logging.getLogger(__name__)`
5. Use `pathlib.Path`, not string paths
6. Use `poetry add` to add dependencies, never `pip install`

### After Writing Code

1. Run `poetry run pytest tests/ -v` — all tests must pass
2. Run pipeline on all priority-1 test cases
3. Compute metrics and compare against baseline
4. Generate regression report
5. If regressions on critical metrics: fix before commit
6. Commit with conventional message: `feat:`, `fix:`, `refactor:`, `test:`

### Module Size Limits

| Threshold | Action |
|-----------|--------|
| < 200 lines | Fine |
| 200-400 lines | Monitor, consider splitting |
| > 400 lines | **Must split** before adding features |

---

## 7. Development Workflow — Step by Step

### Adding a New Test Case

```
Human:
  1. Scan/obtain the PDF or PNG
  2. Create ground truth MusicXML in MuseScore
  3. Create case.yaml using the template (section 3.2)
  4. Place files in tests/fixtures/{name}/
  5. Add entry to tests/fixtures/manifest.yaml
  6. Commit: "test: add {name} test fixture"

Agent (optional, on request):
  7. Generate expected_step_03_text.json by running TextClassifier
  8. Generate expected_step_04_layout.json by running StaffDetector
  9. Human reviews and corrects these generated expectations
```

### Fixing a Bug

```
1. Identify failing test case and failing step
2. Agent: write a specific failing test in tests/pipeline/test_step_NN_*.py
3. Agent: fix the bug in the relevant module
4. Agent: run full test suite, compute metrics
5. Agent: generate regression report
6. Human: review metrics, approve merge
```

### Adding a Feature

```
1. Human: describe the feature
2. Agent: update case.yaml with new expected values (if applicable)
3. Agent: write failing tests
4. Agent: implement feature
5. Agent: run full test suite, compute metrics
6. Human: review, test in MuseScore, approve
```

---

## 8. Running Tests

### Quick Test (per-step, fast)

```bash
# Run all pipeline step tests
poetry run pytest tests/pipeline/ -v

# Run tests for a specific step
poetry run pytest tests/pipeline/test_step_04_staff_detector.py -v

# Run tests for a specific test case
poetry run pytest tests/pipeline/ -v -k "alleluja"
```

### Full Integration Test (slow, runs OMR)

```bash
# Run integration tests (requires OMR engine, may take minutes)
poetry run pytest tests/pipeline/test_step_10_integration.py -v --timeout=300

# Run with metrics collection
poetry run pytest tests/pipeline/ -v --metrics
```

### Metrics Report

```bash
# Generate metrics report for all active test cases
poetry run python -m tests.metrics.run_metrics_report

# Compare against baseline
poetry run python -m tests.metrics.regression_check
```

---

## 9. Definition of Done

A task is "done" when:

- [ ] All priority-1 test cases pass on changed steps
- [ ] No regression on critical metrics (staff_count, part_count, measure_count)
- [ ] New code has type hints and Google-style docstrings
- [ ] No module exceeds 400 lines
- [ ] `poetry run pytest tests/ -v` passes
- [ ] Conventional commit message used
- [ ] Metrics report generated and reviewed by human

---

## 11. File Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Test fixture directory | ASCII, underscores, no spaces | `Alleluja_werset_sw_Anna/` |
| Test case ID | lowercase, underscores | `alleluja_sw_anna` |
| Source input | `input.{pdf\|png}` | `input.pdf` |
| Ground truth | `expected_final.musicxml` | |
| Per-step expected | `expected_step_NN_*.{json\|musicxml}` | `expected_step_03_text.json` |
| Case metadata | `case.yaml` | |
| Report | `report.md` | |
| Pipeline artifact | `step_NN_*.{png\|json\|musicxml}` | `step_04_layout.json` |

---

## 12. Communication Protocol — Human ↔ Agent

### Human → Agent (task request)

Include:
1. **Which test case(s)** to focus on (or "all priority-1")
2. **Which step(s)** are failing or need improvement
3. **Desired outcome** (e.g., "Step 4 should detect 4 staves, currently detects 3")
4. **Constraints** (e.g., "don't change the OMR engine, only post-processing")

### Agent → Human (completion report)

Include:
1. **What changed** (files modified, lines changed)
2. **Test results** (pass/fail)
3. **Metrics before/after** (regression report)
4. **What to verify** (e.g., "open data/processed/runs/.../step_10_final.musicxml in MuseScore")
5. **Open questions** (if any)

---

## Appendix A: `case.yaml` Template

Copy this template when adding a new test case:

```yaml
# tests/fixtures/{name}/case.yaml

id: "{unique_id}"
title: "{Full Title}"
source: "input.pdf"          # or input.png
difficulty: "medium"         # easy | medium | hard | extreme
tags: []                     # e.g. ["satb", "organ", "multi_page", "recto_tono"]
notes: ""

step_01_ingestion:
  expected_pages: 1
  expected_dpi: 300
  has_text_layer: true

step_02_preprocessing:
  expected_pages: 1

step_03_text:
  title: ""
  composer: null
  arranger: null
  part_names: []
  has_lyrics: false
  lyrics_snippet: ""
  tempo: null

step_04_layout:
  pages:
    - page: 1
      staff_count: 0
      groups: []
      systems: 1

step_05_splitting:
  expected_images: 0
  splits: []

step_06_omr:
  staves: []

step_07_assembly:
  expected_parts: 0
  part_names: []
  grouping: []
  total_measures: 0
  beats_per_measure: 4.0

step_08_lyrics:
  vocal_parts: []
  non_vocal_parts: []
  expected_syllable_count: [0, 0]

step_09_validation:
  max_beat_errors: 0
  max_ambitus_warnings: 5
  expected_key_consistency: true
  expected_part_length_match: true

step_10_final:
  ground_truth_file: "expected_final.musicxml"
  min_pitch_accuracy: 0.80
  min_duration_accuracy: 0.80
  min_measure_count_accuracy: 1.0
  min_part_count_accuracy: 1.0
```
