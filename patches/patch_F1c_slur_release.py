#!/usr/bin/env python3
"""
patch_F1c_slur_release.py

sectioning_v2_10_F1b.py  ->  sectioning_v2_10_F1c.py

Two changes.  One is a latent correctness bug with no output effect; the other
is an output-affecting fix that ships default-off.

---------------------------------------------------------------------------
(1) phrase_spans -- ALWAYS ON, diagnostics only, no output change
---------------------------------------------------------------------------
`extract_slur_indicators` appends to `slur_starts` under `not start_nested`
and to `slur_ends` under `not end_nested` -- two independent conditions -- then
returns both `sorted()` independently.  The lists are therefore NOT
index-parallel, yet two callsites zip them:

    line ~2102  _f1_explain_slur_status   "AT LAST-SLURRED-NOTE ONSET (slur a->b)"
    line ~3899  explain                   "Currently INSIDE slur(s)"

Both pair one slur's start with an unrelated slur's end, and `zip` silently
truncates to the shorter list so tail entries vanish.  This is the actual cause
of the ALGORITHM.md §15b finding that explain contradicted the pipeline at
Oboe m.93 b9 and Cl2 m.18 end -- not a convention mismatch.

Fix: keep the real pairs in `phrase_spans` as (start_off, end_off, release_off)
triples and have both callsites read that.  `slur_starts` / `slur_ends` are
left alone; line ~1862's breath-target logic depends on them as onsets.

---------------------------------------------------------------------------
(2) slur-end bump at the chain RELEASE -- DEFAULT OFF, --slur_end_release
---------------------------------------------------------------------------
`endpoints_raw[end_idx]` places the bump at the last slurred note's ONSET.
The breath goes after that note.  Third instance of the E0 family: §7's box
already records that Long, Gap, Lambda and the slur bumps all fire one
note-duration early.  E0 repaired boundaries downstream via anchoring, but
§13 case 2 requires `max(Long, Gap) > ev_min`, and a phrase ending on a short
slurred note has Long = 0 (dur < d_min) and Gap = 0 (attacca), so the shift is
declined and the boundary is stranded at the onset.

Confirmed 6/6 by explain on B3: Fl1 147, Fl2 203.5, Ob 147, Ob 295.75,
Ob 319.75, ASax 171 -- every one at the onset of a note carrying slur_end,
with GT at that note's release.

F1b(a) already defers F1 anchors to the chain release.  This applies the same
predicate to the baseline slur channel, which is why `_slur_chain_release`
below mirrors `_rel` in `_f1_extract_part_events` rather than inventing a
second definition.

PRE-REGISTERED BAND (from slur_release_probe.py on liz_seam_B3_all, before the
GT correction at Oboe m.86 b4.75, and before the probe's zip-truncation fix):

    boundaries at a slur last-note onset   13   (undercount; expect more)
    GT sits at the RELEASE -- gain          6
    GT sits at the ONSET   -- loss          1   (Ob 343.75; being deleted from GT)
    neither position is GT                  6

    expected: +6 required, +6 banned = ~12 audit points; +5 exact
    Materially outside this band -> STOP.

Usage:
    python patch_F1c_slur_release.py
    python patch_F1c_slur_release.py --in sectioning_v2_10_F1b.py \
                                     --out sectioning_v2_10_F1c.py
"""

import argparse
import io
import os
import re
import sys

DEFAULT_IN = 'sectioning_v2_10_F1b.py'
DEFAULT_OUT = 'sectioning_v2_10_F1c.py'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', default=DEFAULT_IN)
    ap.add_argument('--out', dest='dst', default=DEFAULT_OUT)
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    if not os.path.exists(args.src):
        sys.exit('ABORT: %s not found' % args.src)
    src = io.open(args.src, encoding='utf-8').read()

    if '_SLUR_END_RELEASE' in src:
        sys.exit('ABORT: %s already contains _SLUR_END_RELEASE.' % args.src)
    if os.path.exists(args.dst) and not args.force:
        sys.exit('ABORT: %s exists. Use --force to overwrite.' % args.dst)

    applied = []

    def rep(tag, old, new, count=1):
        nonlocal src
        n = src.count(old)
        if n != count:
            sys.exit('ABORT [%s]: expected %d occurrence(s), found %d.\n'
                     'The source has drifted from what this patch was written '
                     'against. Nothing written.' % (tag, count, n))
        src = src.replace(old, new)
        applied.append(tag)

    # -- H1: module-level flag, beside the other shared globals -------------
    rep('H1 flag',
        "_F1_ANCHOR_SETS = {}",
        """_F1_ANCHOR_SETS = {}

# F1c (2026-09-02): project the slur endpoint bump at the last slurred note's
# tie-chain RELEASE rather than its onset. Default off for one validation run
# per the §1 default-off invariant. Module-level for the same reason
# _REST_SEAM_POLICY and _F1_ANCHOR_SETS are.
_SLUR_END_RELEASE = False""")

    # -- H2: chain-release helper, mirroring _rel() -------------------------
    rep('H2 helper',
        "def extract_slur_indicators(part, num_frames, division,",
        '''def _slur_chain_release(end_off, flat_notes, eps=1e-3):
    """Tie-chain release of the note starting at end_off.

    Deliberately mirrors _rel() inside _f1_extract_part_events. The slur-end
    bump, the F1 slur deferral, and (later) the interior mask must agree on
    one definition of "where does this slur actually stop sounding"; three
    private copies is how the explain/pipeline disagreement in §15b happened.

    flat_notes must be sorted by global offset.
    """
    cur = None
    for c in flat_notes:
        if abs(float(c.offset) - end_off) <= eps:
            cur = c
            break
    if cur is None:
        return end_off
    guard = 0
    while guard < 500:
        guard += 1
        rel = float(cur.offset) + float(cur.duration.quarterLength)
        tie = getattr(cur, 'tie', None)
        if tie is None or tie.type == 'stop':
            return rel
        pset = {p.nameWithOctave for p in cur.pitches}
        nxt = None
        for c in flat_notes:
            if abs(float(c.offset) - rel) <= eps and \\
                    pset & {p.nameWithOctave for p in c.pitches}:
                ct = getattr(c, 'tie', None)
                if ct is not None and ct.type in ('continue', 'stop'):
                    nxt = c
                    break
        if nxt is None:
            return rel
        cur = nxt
    return float(cur.offset) + float(cur.duration.quarterLength)


def extract_slur_indicators(part, num_frames, division,''')

    # -- H3: locals -- phrase_spans list and a flattened note list ----------
    rep('H3 locals',
        """    slur_starts = []
    slur_ends = []
    tie_like_spans = []

    note_events = _note_like_events(part)""",
        """    slur_starts = []
    slur_ends = []
    phrase_spans = []
    tie_like_spans = []

    note_events = _note_like_events(part)
    try:
        _flat_notes = sorted(part.flatten().notes,
                             key=lambda n: float(n.offset))
    except Exception:
        _flat_notes = []""")

    # -- H4: record the real pair, and place the bump -----------------------
    rep('H4 bump',
        """        if not end_nested:
            slur_ends.append(end_off)
            if 0 <= end_idx < num_frames:
                endpoints_raw[end_idx] = max(endpoints_raw[end_idx], 1.0)""",
        """        _release_off = _slur_chain_release(end_off, _flat_notes)
        phrase_spans.append((start_off, end_off, _release_off))

        if not end_nested:
            slur_ends.append(end_off)
            if _SLUR_END_RELEASE:
                _bump_idx = min(int(round(_release_off * division)),
                                num_frames - 1)
            else:
                _bump_idx = end_idx
            if 0 <= _bump_idx < num_frames:
                endpoints_raw[_bump_idx] = max(endpoints_raw[_bump_idx], 1.0)""")

    # -- H5: return it ------------------------------------------------------
    rep('H5 return',
        """        'slur_starts': sorted(slur_starts),
        'slur_ends': sorted(slur_ends),
        'tie_like_spans': tie_like_spans,""",
        """        'slur_starts': sorted(slur_starts),
        'slur_ends': sorted(slur_ends),
        'phrase_spans': phrase_spans,
        'tie_like_spans': tie_like_spans,""")

    # -- H6: tacet stub -----------------------------------------------------
    rep('H6 tacet',
        """                'slur_starts': [],
                'slur_ends': [],
                'tie_like_spans': [],""",
        """                'slur_starts': [],
                'slur_ends': [],
                'phrase_spans': [],
                'tie_like_spans': [],""")

    # -- H7: _f1_explain_slur_status -- stop zipping -------------------------
    rep('H7 explain-f1',
        """        for s, e in zip(slur_info_i.get('slur_starts', []),
                        slur_info_i.get('slur_ends', [])):
            if abs(float(e) - anchor) <= 1e-6 and float(s) < anchor:""",
        """        for _sp in slur_info_i.get('phrase_spans', []):
            s, e = float(_sp[0]), float(_sp[1])
            if abs(float(e) - anchor) <= 1e-6 and float(s) < anchor:""")

    # -- H8: explain 'Currently INSIDE slur(s)' -- stop zipping --------------
    rep('H8 explain-cover',
        """        for s, e in zip(slur_starts, slur_ends):
            if s < actual_t < e:
                covering.append((s, e))""",
        """        for _sp in si.get('phrase_spans', []):
            s, e = float(_sp[0]), float(_sp[1])
            if s < actual_t < e:
                covering.append((s, e))""")

    # -- H9: CLI flag --------------------------------------------------------
    rep('H9 cli',
        "    parser.add_argument('--disable_short_phrase_filter', action='store_true',",
        """    parser.add_argument('--slur_end_release', action='store_true',
                        help='F1c: project the slur endpoint bump at the last '
                             'slurred note tie-chain release instead of its '
                             'onset. Default off (one validation run).')
    parser.add_argument('--disable_short_phrase_filter', action='store_true',""")

    # -- H10: set the global before the run ----------------------------------
    rep('H10 main',
        """    run_sectioning(
        args.input,""",
        """    global _SLUR_END_RELEASE
    _SLUR_END_RELEASE = bool(args.slur_end_release)

    run_sectioning(
        args.input,""")

    # -- H11: serialize the knob in every parameters block -------------------
    pat = re.compile(r"^([ \t]*)'f1b_multiplier_routing':[^\n]*\n", re.M)
    hits = pat.findall(src)
    if len(hits) < 1:
        sys.exit("ABORT [H11]: no 'f1b_multiplier_routing' serialization line "
                 "found. Every output-affecting knob must be serialized (§1); "
                 "nothing written.")
    src = pat.sub(lambda m: m.group(0) + "%s'slur_end_release': bool(_SLUR_END_RELEASE),\n"
                  % m.group(1), src)
    applied.append('H11 serialize x%d' % len(hits))

    io.open(args.dst, 'w', encoding='utf-8').write(src)

    print('wrote %s' % args.dst)
    for t in applied:
        print('  applied %s' % t)
    print("""
NEXT
  1. Re-baseline first if the Oboe m.86 b4.75 GT correction has landed.

  2. Control run -- flag OFF. MUST be identical to liz_seam_B3_all except
     for the new serialized key:

     python %s Liz_and_the_Blue_Bird_III-1.2_colored.mxl \\
       -o output_v2_10_F1c/liz_seam_C0_control \\
       --rest_seam_policy seam --f1_fermata_weight 1.0 --f1_dim_end_weight 0.6
     python boundaries_diff.py output_v2_10_F1b/liz_seam_B3_all/boundaries.json \\
       output_v2_10_F1c/liz_seam_C0_control/boundaries.json

     Any boundary change here means phrase_spans altered behaviour it should
     not have. Stop and investigate.

  3. Treatment run -- flag ON:

     python %s Liz_and_the_Blue_Bird_III-1.2_colored.mxl \\
       -o output_v2_10_F1c/liz_seam_C1_slur_release \\
       --rest_seam_policy seam --f1_fermata_weight 1.0 --f1_dim_end_weight 0.6 \\
       --slur_end_release
     python boundaries_diff.py output_v2_10_F1c/liz_seam_C0_control/boundaries.json \\
       output_v2_10_F1c/liz_seam_C1_slur_release/boundaries.json

  4. Score it:
     python boundaries_diff.py gt_boundaries_v2.json \\
       output_v2_10_F1c/liz_seam_C1_slur_release/boundaries.json
     python audit_check.py --audit <audit cases> \\
       output_v2_10_F1c/liz_seam_C1_slur_release/boundaries.json \\
       --musicxml gt_rendered.musicxml

  5. explain.py imports the pipeline BY NAME. Update its import to
     sectioning_v2_10_F1c or every explain will read the old module.
""" % (args.dst, args.dst))
    return 0


if __name__ == '__main__':
    sys.exit(main())
