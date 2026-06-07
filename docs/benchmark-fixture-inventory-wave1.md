# Wave 1 Fixture Inventory and Allowlist

## Purpose
This document is the explicit allowlist confirmation for curated real smoke fixtures used in Wave 1.

## Canonical Curated Fixture Classes
- Input fixtures: versioned PDFs and images used by benchmark manifests.
- Reference fixtures: versioned MusicXML files used as comparison targets.

## Current Wave 1 Curated Allowlist
### Inputs
- notebooks/scans/Boże_mój.png
- notebooks/scans/Więzień_w_czyśćcu_zatrzymany.pdf
- notebooks/scans/Zapada zmrok.pdf
- notebooks/scans/[WzH 113] Niech z serca płynie pieśń.pdf

### References
- notebooks/data/reference_scores/Boże_mój.musicxml
- notebooks/data/reference_scores/Więzień_w_czyśćcu_zatrzymany.musicxml
- notebooks/data/reference_scores/Zapada zmrok.musicxml
- notebooks/data/reference_scores/[WzH 113] Niech z serca płynie pieśń.musicxml

## Manifest Mapping
Source manifest: data/benchmarks/real_smoke_manifest.json

1. boze_moj_scan
- input_path: notebooks/scans/Boże_mój.png
- reference_path: notebooks/data/reference_scores/Boże_mój.musicxml
- qa_status: reviewed
- license_status: cleared-for-dev

2. wiezien_w_czysccu_zatrzymany_scan
- input_path: notebooks/scans/Więzień_w_czyśćcu_zatrzymany.pdf
- reference_path: notebooks/data/reference_scores/Więzień_w_czyśćcu_zatrzymany.musicxml
- qa_status: reviewed
- license_status: cleared-for-dev

3. zapada_zmrok_scan
- input_path: notebooks/scans/Zapada zmrok.pdf
- reference_path: notebooks/data/reference_scores/Zapada zmrok.musicxml
- qa_status: reviewed
- license_status: cleared-for-dev

4. wzh_113_niech_z_serca_plynie_piesn_scan
- input_path: notebooks/scans/[WzH 113] Niech z serca płynie pieśń.pdf
- reference_path: notebooks/data/reference_scores/[WzH 113] Niech z serca płynie pieśń.musicxml
- qa_status: reviewed
- license_status: cleared-for-dev

## Policy Notes
- Generated outputs are non-curated and must not be tracked:
- agent/reports/**
- notebook checkpoints
- data/processed/**

- Curated fixtures above remain tracked as source_of_truth for real smoke benchmark.

## Wave 1 Validation Checklist
1. Confirm all manifest cases resolve to an allowlisted input and reference fixture.
2. Confirm no generated report paths are staged after benchmark operations.
3. Confirm benchmark manifest remains tracked and unchanged except intentional edits.
