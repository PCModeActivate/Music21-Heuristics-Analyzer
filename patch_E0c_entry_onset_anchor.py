#!/usr/bin/env python3
"""
patch_E0c_entry_onset_anchor.py

E0c (2026-07-15): extend the E0b release-anchor rule to entry-onset
boundaries, and drop the score-end suppression.

RATIONALE: Robert's hand-corrected GT v2 settled the entry-onset policy
empirically -- every entry-instant mark was moved to a real note
release, including the final chord (m.94 gets a required comma in six
parts; Oboe excluded by its tie). E0b's rule 4 ("entry-onsets
untouched") and rule 5 (score-end suppression) now contradict the GT.

The change: a boundary where a note STARTS (with arrival/gap evidence
> evidence_min) re-anchors to that note's chain release regardless of
whether anything releases at the boundary. Rest-seam boundaries
(release only) remain untouched. Same evidence gate, same records.

SIMULATED on output_v2_10_E0b/liz_seam vs gt_boundaries_v2:
  24 of the 26 entry-onset boundaries shift (2 lack evidence and stay);
  0 land on an existing boundary (no merges).
  vs GT: 14 disagreements become exact agreements (all six final-chord
  m.93-end -> m.94-end marks, Tpt m.20 b4.5 -> m.20 end, Cl1 m.69 end ->
  m.70 b4, Euph m.49/m.76/m.78/m.88 family, Harp m.46 end / m.68 b3);
  0 current agreements break. Predicted GT-diff totals:
  ~190 unchanged (was 176), moved ~13, removed ~73, added ~44.
  boundaries_diff vs the E0b run: ~24 boundaries moved/re-paired,
  0 added, 0 removed, final count unchanged (~243).
  Materially outside these bands: STOP.

Usage:
    cp sectioning_v2_10_E0b.py sectioning_v2_10_E0c.py
    python patch_E0c_entry_onset_anchor.py sectioning_v2_10_E0c.py
(No backups -- git handles versioning.)
"""

import sys
from pathlib import Path

# Branch condition: seam-only -> any starting note (entry-onset included)
ANCHOR_BRANCH = """        elif at_rel and k_on.size:
            f = min(max(int(round(bt * division)), 0), T - 1)
            ev = max(float(long_grid[f]), float(gap_grid[f]))
            if ev > evidence_min:
                new_bt = float(rels[k_on[0]])
                reason = 'seam_arrival_evidence'
"""
REPLACE_BRANCH = """        elif k_on.size:
            # E0c: applies at note-to-note seams AND entry onsets --
            # per GT v2, the breath follows the note the evidence
            # describes, even when it enters from silence.
            f = min(max(int(round(bt * division)), 0), T - 1)
            ev = max(float(long_grid[f]), float(gap_grid[f]))
            if ev > evidence_min:
                new_bt = float(rels[k_on[0]])
                reason = ('seam_arrival_evidence' if at_rel
                          else 'entry_onset_arrival_evidence')
"""

# Score-end suppression: removed (GT requires the final-chord comma)
ANCHOR_SUPPRESS = """        if reason is not None and score_end_qn is not None \\
                and new_bt >= float(score_end_qn) - eps:
            shifts.append({'from': bt, 'to': bt,
                           'reason': 'score_end_suppressed'})
            new_bt = bt
        elif reason is not None and abs(new_bt - bt) > eps:
"""
REPLACE_SUPPRESS = """        if reason is not None and abs(new_bt - bt) > eps:
"""


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    src = path.read_text()

    assert 'entry_onset_arrival_evidence' not in src, "already patched"
    n = src.count(ANCHOR_BRANCH)
    assert n == 1, (
        f"REFUSING: E0b seam branch anchor found {n} times (expected 1); "
        "inspect release_anchor_boundaries manually.")
    n = src.count(ANCHOR_SUPPRESS)
    assert n == 1, (
        f"REFUSING: score-end suppression anchor found {n} times "
        "(expected 1); inspect release_anchor_boundaries manually.")

    src = src.replace(ANCHOR_BRANCH, REPLACE_BRANCH, 1)
    src = src.replace(ANCHOR_SUPPRESS, REPLACE_SUPPRESS, 1)
    path.write_text(src)
    print(f"E0c applied to {path}.")
    print("Validate: run with --rest_seam_policy seam into a new dir; "
          "boundaries_diff vs the E0b run predicts ~24 moved / 0 added / "
          "0 removed; vs gt_boundaries_v2 predicts ~190 unchanged.")


if __name__ == '__main__':
    main()
