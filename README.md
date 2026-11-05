# Explainable symbolic-music phrase boundary detection (v2)

This branch contains ongoing research on **per-part phrase/breath boundary detection in polyphonic MusicXML scores**. It is part of a broader project on interpretable melody-role identification. The boundary detector is implemented and evaluated independently; **integration with the melody-role detector is future work**.

The historical 2024 melody-detection prototype is on [`main`](https://github.com/PCModeActivate/Music21-Heuristics-Analyzer/tree/main). The current sectioning entry point here is **`sectioning_v2_11_A.py`**, not the older `Sectioning.py` or `Sectioning.ipynb`.

## Method at a glance

For each instrumental part, the algorithm combines explicit symbolic-score evidence: pitch-class and rhythmic novelty (self-similarity matrices), LBDM, note durations and subsequent rests, slurs/ties and notated expressive events, with limited evidence from other parts. A deterministic candidate-selection and grouping procedure selects proposed phrase releases. Results are saved as MusicXML with breath marks and machine-readable boundary records. Individual decisions can be traced back to their feature evidence; no neural network is used.

- **[SECTIONING.md](SECTIONING.md)** — concise current method, evaluation, limitations, and commands
- **[ALGORITHM.md](ALGORITHM.md)** — full derivations, experiments, parameter choices, failure analysis and historical development
- **[HANDOVER_v2_11_A_2026-11-04.md](HANDOVER_v2_11_A_2026-11-04.md)** — current milestone, exact commands and open issues
- **`MelodyDetection.ipynb`** — historical melody extraction; **not yet coupled** to current phrase-boundary inference

## Quick start

Run from the root of the `v2` checkout using Python 3 and a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install music21==10.5.2 numpy scipy matplotlib
python sectioning_v2_11_A.py Liz_and_the_Blue_Bird_III-1.2_colored.mxl -o output_v2_11_A/liz_X7
```

The output directory contains `sectioned.musicxml` (annotated score), `boundaries.json` (per-part boundary instants), and `result.pkl` (feature/evidence traces). Open the MusicXML file in score notation software to inspect the breath marks.

```bash
python score_run.py output_v2_11_A/liz_X7
python violations_report.py output_v2_11_A/liz_X7
```

The historical settings can be restored with `--legacy_defaults`. See `SECTIONING.md` for explanations and additional inspection commands. The pip line above lists the **core direct dependencies** of the current CLI; a fully pinned environment and clean-room reproduction are not yet provided.

## Preliminary evaluation (development score)

On *Liz and the Blue Bird*, movement III (10 parts, 94 measures), the current X7 configuration matched **237 of 262** annotated phrase boundaries (within 0.1 quarter note) with **63 additional unmatched boundaries**. The repository's evaluation report lists roughly **90% recall** and **79% precision** against this hand-corrected, development-set annotation. Four annotated unison constraints were satisfied. These results are **not an estimate of generalization**; settings were adjusted based on this score, and some additional boundary decisions remain subjective.

The system also ran on a held-out excerpt of Dvořák's Symphony No. 9, movement IV, but that check is currently qualitative (no independent annotated ground truth). See `SECTIONING.md`, §5–6, for detailed errors and known limitations.

## Research status and limitations

- The independent sectioner is at an **implementation / preliminary-evaluation milestone**; the end-to-end section-aware melody-role algorithm is not yet implemented.
- Grouping thresholds and some ensemble rules were tuned on a single development piece.
- Ensemble-support counts depend on the number of parts, doubled lines are not fully handled, and some boundaries require finer release-time handling (especially nonstandard subdivisions).
- The repository contains earlier experimental scripts and patch history for reproducibility; `sectioning_v2_11_A.py` is the active CLI.

For research questions and collaboration, see the contact information in the project owner's GitHub profile.
