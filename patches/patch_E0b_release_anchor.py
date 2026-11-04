#!/usr/bin/env python3
"""
patch_E0b_release_anchor.py

E0b (2026-07-15): re-anchor onset-landed boundaries to note releases.

DIAGNOSIS (result.pkl of output_v2_10_E0/liz_seam, Fl1 m.7-8 probe):
Every note-level evidence channel is projected at note ONSETS: the
long-note arrival grid, the following-gap grid ("this note is followed
by a rest"), slur endpoint bumps, and LBDM long-IOI all vote at the
attack of the phrase-final note. At Fl1 m.8 (whole note, rest after):
long_grid=1.0, gap_grid=1.0, selection=1.44 at the ATTACK (m.7 end);
0.0/0.0/0.26 at the RELEASE (m.8 end) -- below the 0.30 acceptance
gate. So boundaries land one note early at every phrase ending on a
long note. The x.875/x.125 values were the visible members; integer
seam values (m.7 end, m.10 b3, ...) are the same disease, masked
because the onset coincides with the previous note's release.

Pre-E0, the attach-to-next annotation bug shifted these commas one note
late, cancelling the error; months of eye approvals approved the
doubly-wrong-therefore-right renders. E0 removed the compensation; E0b
moves the correction into the boundary values, where it is principled
and recorded.

RULE (per Robert 2026-07-15, reproduces his m.8 and m.93-unison
rulings):
  1. Boundary strictly inside a note (merged tie chain): re-anchor to
     that chain's release ('mid_note'). Covers the x.125 / x.625 /
     x.875 smears and mid-tie leaks (e.g. Euph m.11 end inside the
     tied D3).
  2. Boundary at a note-to-note seam (a note releases AND a note
     starts there): if the starting note carries arrival/gap evidence
     (max(long_grid, gap_grid) > evidence_min at the boundary frame),
     the evidence belongs to that note, so the breath follows it:
     re-anchor to its release ('seam_arrival_evidence'). Measured
     separation on liz_seam is clean: movers >= 0.3 (mostly 1.0),
     stayers <= 0.14; evidence_min = 0.3 sits in the gap.
  3. Rest-seam boundaries (release only): untouched -- already right.
  4. Entry-onset boundaries (onset only, rest before): untouched --
     separate species, print-policy pending. This also means the
     final-chord boundary at m.93 end stays put (no trailing comma).
  5. Any shift that would land at the score-final release is
     suppressed and recorded ('score_end_suppressed').
Every shift, merge, and suppression leaves a record (traceability
invariant): result['e0b_shift_info'][part] = list of
{'from', 'to', 'reason'}.

Shipped enabled=True: this completes the E0 bug fix (same convention,
boundary-value half). Disable via _E0B_RELEASE_ANCHOR['enabled'] to
reproduce pre-E0b values. The setting is mirrored into a local
(`release_anchor`) inside run_sectioning so S0's all_knobs serializes
it automatically.

VALIDATION (simulated on output_v2_10_E0/liz_seam -- these bands are a
falsifiable prediction, not a guess):
  179 of 256 boundaries shift (61 mid-note, 118 seam-with-evidence);
  15 seams stay (evidence 0.0-0.14); 26 entry-onsets untouched;
  13 post-shift duplicates merge -> final count ~243.
  boundaries_diff vs output_v2_10_E0/liz_seam (pair tolerance 1.0 qn
  reports long shifts as remove+add pairs):
    ~64 unchanged, ~59 moved, ~133 removed, ~120 added, total ~243.
  Numbers materially outside these bands = unmapped interaction: STOP.
  Sentinels: Fl1 m.7 end -> m.8 end (comma after the whole note);
  Fl1 m.92 end -> m.93 b3 (unison fermata breath); Fl1 m.27 / Tpt m.57
  GT double-bug points now PASS in audit_check.
  EXPECTED FALLOUT: audit_check against audit_cases_full_2026-07-10
  will FAIL en masse -- the GT encodes pre-E0b onset values for
  eye-approved marks. Do NOT gate on its exit code for this run; the
  GT itself is queued for render-and-re-judge (gt_render).

Usage:
    cp sectioning_v2_10_E0.py sectioning_v2_10_E0b.py
    python patch_E0b_release_anchor.py sectioning_v2_10_E0b.py
(No backups are made -- git handles versioning.)
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------- anchors

ANCHOR_DEF = ("def validate_boundaries_for_part(part, boundaries, slur_info, "
              "structural_info,")

INSERT_DEF = '''# E0b (2026-07-15): onset-landed boundaries are re-anchored to the
# release of the note whose arrival/gap evidence created them.
# 'enabled': False reproduces pre-E0b boundary values.
_E0B_RELEASE_ANCHOR = {'enabled': True, 'evidence_min': 0.3, 'eps': 0.02}


def release_anchor_boundaries(bdys, part_notes, long_grid, gap_grid,
                              division, enabled=True, evidence_min=0.3,
                              eps=0.02, score_end_qn=None):
    """E0b: map onset-landed boundary values to note releases.

    Returns (new_boundaries, shift_records). Rest-seam and entry-onset
    boundaries pass through untouched; every change is recorded.
    """
    shifts = []
    arr = np.asarray(bdys, dtype=float)
    if not enabled or arr.size == 0:
        return arr, shifts
    notes = sorted(part_notes, key=lambda n: float(n['offset']))
    if not notes:
        return arr, shifts
    onsets = np.array([float(n['offset']) for n in notes])
    rels = np.array([float(n['offset']) + float(n['duration'])
                     for n in notes])
    T = len(long_grid)
    mapped = []
    for bt in sorted(float(x) for x in arr):
        new_bt, reason = bt, None
        k_in = np.where((onsets + eps < bt) & (bt < rels - eps))[0]
        at_rel = bool(np.any(np.abs(rels - bt) <= eps))
        k_on = np.where(np.abs(onsets - bt) <= eps)[0]
        if k_in.size:
            new_bt, reason = float(rels[k_in[0]]), 'mid_note'
        elif at_rel and k_on.size:
            f = min(max(int(round(bt * division)), 0), T - 1)
            ev = max(float(long_grid[f]), float(gap_grid[f]))
            if ev > evidence_min:
                new_bt = float(rels[k_on[0]])
                reason = 'seam_arrival_evidence'
        if reason is not None and score_end_qn is not None \\
                and new_bt >= float(score_end_qn) - eps:
            shifts.append({'from': bt, 'to': bt,
                           'reason': 'score_end_suppressed'})
            new_bt = bt
        elif reason is not None and abs(new_bt - bt) > eps:
            shifts.append({'from': bt, 'to': new_bt, 'reason': reason})
        mapped.append(new_bt)
    out = []
    for v in sorted(mapped):
        if out and abs(v - out[-1]) <= eps:
            shifts.append({'from': v, 'to': out[-1],
                           'reason': 'merged_duplicate'})
            continue
        out.append(v)
    return np.array(out, dtype=float), shifts


''' + ANCHOR_DEF

ANCHOR_CALL = """        bdys, target_records = validate_boundaries_for_part(
            parts[i], bdys, slur_info[i], structural_info[i], natural_tie_info[i],
            reject_rest_boundaries=reject_rest_boundaries,
            reject_outgoing_ties=reject_outgoing_ties,
        )
"""

INSERT_CALL = """        # E0b: re-anchor onset-landed boundaries BEFORE validation, so
        # target records and seam handling see the final values.
        try:
            e0b_shift_info
        except NameError:
            e0b_shift_info = []
        try:
            _e0b_score_end = float(score_end_qn)
        except NameError:
            _e0b_score_end = None
        release_anchor = bool(_E0B_RELEASE_ANCHOR['enabled'])
        bdys, _e0b_shifts = release_anchor_boundaries(
            bdys, notes_per_part[i], long_note_grids[i],
            following_gap_grids[i], division,
            enabled=release_anchor,
            evidence_min=_E0B_RELEASE_ANCHOR['evidence_min'],
            eps=_E0B_RELEASE_ANCHOR['eps'],
            score_end_qn=_e0b_score_end)
        e0b_shift_info.append(_e0b_shifts)
""" + ANCHOR_CALL

ANCHOR_RESULT = "'boundary_target_info': boundary_target_info,"
INSERT_RESULT = ("'boundary_target_info': boundary_target_info,\n"
                 "        'e0b_shift_info': e0b_shift_info,")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    src = path.read_text()

    assert '_E0B_RELEASE_ANCHOR' not in src, "already patched"

    n = src.count(ANCHOR_DEF)
    assert n == 1, (
        f"REFUSING: validate_boundaries_for_part def anchor found {n} "
        "times (expected 1); inspect the file manually.")
    n = src.count(ANCHOR_CALL)
    assert n == 1, (
        f"REFUSING: validate call-site anchor found {n} times (expected "
        "1); the run_sectioning loop may have drifted.")
    n = src.count(ANCHOR_RESULT)
    assert n == 1, (
        f"REFUSING: result-dict anchor found {n} times (expected 1); "
        "add 'e0b_shift_info': e0b_shift_info to the result dict by hand "
        "after applying the other two edits.")

    src = src.replace(ANCHOR_DEF, INSERT_DEF, 1)
    src = src.replace(ANCHOR_CALL, INSERT_CALL, 1)
    src = src.replace(ANCHOR_RESULT, INSERT_RESULT, 1)
    path.write_text(src)
    print(f"E0b applied to {path}.")
    print("Validate: run with --rest_seam_policy seam into a NEW output "
          "dir, then boundaries_diff vs output_v2_10_E0/liz_seam.")
    print("Predicted (simulated): ~64 unchanged, ~59 moved, ~133 removed, "
          "~120 added, final count ~243. Outside these bands: STOP.")


if __name__ == '__main__':
    main()
