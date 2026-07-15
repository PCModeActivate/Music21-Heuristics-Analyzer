#!/usr/bin/env python3
"""
patch_E0_annotation_release_target.py

E0 (2026-07-10): fix the attach-to-next annotation bug.

DIAGNOSIS (annotation_check v2 on liz_seam: 42 correct / 145 ATTACH-NEXT /
69 missing / 52 extra): resolve_breath_target_for_part() selects its
primary candidate by ONSET proximity to the boundary -- a v2.3/v2.5-era
convention from when boundaries sat at phrase-final-note onsets (LBDM
long-IOI). The pipeline now uses Mueller RELEASE instants, so at every
note-to-note seam the note STARTING at bt wins and the comma renders one
note late. Rest-followed boundaries hit the previous-note fallback and
render correctly, which is why eye tests approved exactly those.

FIX: annotation-only retarget in add_breath_marks_per_part(), applied
AFTER the resolver returns (the resolver is not touched -- the D-patch
seam_snap_to logic lives there). If the resolved target's offset equals
the boundary (i.e., the mark would attach to the note starting at bt),
redirect to the note whose release equals bt, provided that note has no
outgoing tie. Controlled by module flag _ANNOT_RELEASE_RETARGET
(shipped True: this is a bug fix restoring the documented convention,
not a new mechanism; flip to False to reproduce legacy rendering).

VALIDATION: boundaries.json must be byte-identical before/after (this
patch cannot change boundaries). The two-run diff for this change is
annotation_check output: expect ATTACH-NEXT ~145 -> ~0 and 'rendered
correctly' ~42 -> ~187+. Robert eye-checks a sample (Fl1 m.10 comma
moves from m.10-end back to after the note ending at qn 38; Fl1 m.27
commas move from 108 to 106 -- NOTE the m.27 GT says 108 is musically
right, so after this patch those boundaries must ALSO move per the GT;
that is the E0b onset-landing boundary fix, tracked separately).

Usage:
    python patch_E0_annotation_release_target.py sectioning_v2_10_D_patch.py
(Robert controls file naming; pass whichever file currently owns
add_breath_marks_per_part in the live pipeline. No backups are made --
git handles versioning.)
"""

import sys
from pathlib import Path

ANCHOR_LOOP = """        for bt in boundaries:
            rec, target = resolve_breath_target_for_part(
                part, bt, slur_info,
                structural_info=structural_info,
                natural_tie_info=natural_tie_info,
                onset_tolerance=onset_tolerance,
                structural_phrase_start_kinds=structural_phrase_start_kinds,
            )
            if not rec.get('valid', True) or target is None:
                continue
"""

REPLACEMENT = """        # E0 (2026-07-10): boundary times are RELEASE instants; build the
        # per-part release index once for annotation retargeting.
        _notes_rel = None
        if _ANNOT_RELEASE_RETARGET:
            _notes_rel = sorted(
                ((float(n.offset) + float(n.duration.quarterLength), n)
                 for n in part.flatten().notes),
                key=lambda x: x[0])

        for bt in boundaries:
            rec, target = resolve_breath_target_for_part(
                part, bt, slur_info,
                structural_info=structural_info,
                natural_tie_info=natural_tie_info,
                onset_tolerance=onset_tolerance,
                structural_phrase_start_kinds=structural_phrase_start_kinds,
            )
            if not rec.get('valid', True) or target is None:
                continue

            # E0: if the resolver attached to the note STARTING at bt
            # (onset-era convention), redirect to the note RELEASING at
            # bt so the comma renders where the boundary is.
            if _ANNOT_RELEASE_RETARGET:
                _t_off = rec.get('target_offset')
                if _t_off is not None and abs(float(_t_off) - float(bt)) <= 1e-3:
                    _repl = None
                    for _rel, _n in _notes_rel:
                        if _rel > bt + 1e-3:
                            break
                        if abs(_rel - bt) <= 1e-3:
                            _tie = getattr(_n, 'tie', None)
                            if _tie is None or _tie.type == 'stop':
                                _repl = _n
                    if _repl is not None:
                        target = _repl
                        rec['target_reason'] = 'E0_release_retarget'
"""

FLAG_ANCHOR = "def add_breath_marks_per_part("
FLAG_LINE = ("# E0: attach breath marks to the note RELEASING at the boundary\n"
             "# (True = fixed convention; False = legacy onset attachment).\n"
             "_ANNOT_RELEASE_RETARGET = True\n\n\n"
             "def add_breath_marks_per_part(")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    src = path.read_text()

    n = src.count(ANCHOR_LOOP)
    assert n == 1, (
        f"REFUSING: annotation loop anchor found {n} times (expected 1). "
        "The file may have drifted; do not apply blind -- inspect "
        "add_breath_marks_per_part manually.")
    n = src.count(FLAG_ANCHOR)
    assert n == 1, (
        f"REFUSING: found {n} definitions of add_breath_marks_per_part "
        "(expected 1).")
    assert '_ANNOT_RELEASE_RETARGET' not in src, "already patched"

    src = src.replace(ANCHOR_LOOP, REPLACEMENT)
    src = src.replace(FLAG_ANCHOR, FLAG_LINE, 1)
    path.write_text(src)
    print(f"E0 applied to {path}. Validate: (1) rerun pipeline; "
          f"(2) boundaries.json must be identical (boundaries_diff: 0/0/0); "
          f"(3) annotation_check: ATTACH-NEXT ~0; (4) eye-check a sample.")


if __name__ == '__main__':
    main()
