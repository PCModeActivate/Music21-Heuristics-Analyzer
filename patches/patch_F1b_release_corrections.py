#!/usr/bin/env python3
"""
patch_F1b_release_corrections.py — F1b: three corrections to the F1
expressive release channel.

Target: sectioning_v2_10_F1.py (pass path as argv[1] if renamed).
Strict verbatim anchors; any mismatch aborts with the file unchanged.
No backups (git holds history). Compile-checked before writing.

WHY (all three are defects F1 exposed, not new evidence)

  (1) SLUR DEFERRAL -- 13 of 82 injections sit strictly inside a slur,
      and one more (ASax fermata anchor 163.0, slur 160.5->163.0) sits on
      the LAST slurred note's onset, where in_slur_interior has already
      gone to 0 because the mask is half-open. A breath at either place
      splits a slur. Robert's ruling on the m.41 passage: all those parts
      carry a fermata on the b.3 note, some held to the barline, some with
      another note after, some with tied pickups -- and most END WHERE THE
      SLUR ENDS. So an F1 anchor covered by a slur DEFERS to that slur's
      chain-release rather than being masked away. Deferral is one step,
      not iterated (cascade was tested and rejected in E0b).

  (2) E0b SEAM SHIFT, CONDITIONED -- an F1 anchor is a release by
      construction, so E0b's "boundary sits at a note-to-note seam, push
      it to the next note's release" is not always right for it. Measured
      on liz_seam, 5/5: the shift is CORRECT when the shifted target is
      followed by a rest (p3 368->370 rest 16 qn; p4 163->164 rest 0.5;
      p5 163->164 rest 0.5 -- all GT) and WRONG when the music continues
      attacca (p7 108->112 and 116->120, both destroying GT points).
      F1 anchors therefore decline the seam shift when the target runs on
      attacca. Baseline (non-F1) boundaries are untouched.

  (3) MULTIPLIER ROUTING -- F1 was added to B_i AFTER the continuation
      multiplier, making it the only channel that ignores hairpin, slur
      and tuplet attenuation, and the only one exempt from the tie-like /
      natural-tie hard veto. Euph m.28: base attenuated 0.443 -> 0.221 by
      the hairpin, then +1.000 landed untouched. F1 now enters with the
      boosts, before the multipliers. A fermata at 1.0 halved by a hairpin
      is 0.5 and still clears the 0.30 gate, so this costs little and
      makes tie precedence structural: Robert's "if it clashes with a tie,
      the tie takes precedence" is now enforced by the same hard veto that
      governs every other channel, rather than by luck.

  Explain's identity line is updated to match (3): F1 now sits INSIDE the
  multiplied term, so the printed reconstruction is
  (B_raw + boost + F1) * mult = B_i.

KNOBS (serialized; all default True -- these are corrections to a shipped
mechanism, not new evidence, so they do not need a zero run. The flags
exist so the staged validation below is attributable.)
    --f1b_no_slur_deferral
    --f1b_no_seam_condition
    --f1b_no_multiplier_routing

STAGED VALIDATION (boundaries_diff after each; reference run is
output_v2_10_F1/liz_seam_F1, i.e. fermata 1.0 / dim 0.6)

  B1  --f1b_no_slur_deferral --f1b_no_multiplier_routing
      isolates (2). PREDICTED, exactly and only:
        part 7 Euphonium: ADDED 108.0, ADDED 116.0,
                          REMOVED 112.0, REMOVED 120.0
      Nothing else moves. e0b_shift_info[7] gains two records with reason
      'f1_seam_shift_declined_attacca'. vs GT: 191 -> 193 exact,
      misses 72 -> 70, extras 43 -> 41.
      ANY other part changing = out of band, stop.

  B2  --f1b_no_slur_deferral
      adds (3). Attenuation now applies to 82 injected frames. Expect a
      SMALL diff concentrated where in_hairpin/in_slur/in_tuplet is 1 at
      an anchor, plus any anchor inside a tie-like span dropping out
      entirely (hard veto). Direction is not predictable per-point; the
      band is "few changes, each traceable to a mask being 1 at the
      anchor". Check f1_events.json + explain for any surprise.

  B3  (no flags -- everything on)
      adds (1). 14 anchors move to their slur's release. Watch for
      collisions: several deferred anchors may land on the SAME release
      as another injection, which is fine (weights sum), and some may land
      within 2.5 qn of an existing boundary, where peak-group
      winner-take-all still applies -- that interaction is known and NOT
      fixed here.

  Then: audit_check.py and annotation_check.py on B3 before A/B2 (cresc).

NOT FIXED HERE (deliberately, one thing at a time)
  - peak-group winner-take-all suppressing GT points 2.5 qn apart
  - the short-phrase filter treating an all-rest span as a phrase
    fragment (Flute 2 qn 386)
  - fermatas on rests (the extractor still walks .notes only)
"""

import sys


def replace_once(src, old, new, label):
    n = src.count(old)
    if n != 1:
        raise SystemExit(
            "ABORT [%s]: anchor found %d times (need exactly 1). "
            "File unchanged." % (label, n))
    return src.replace(old, new, 1)


# ---------------------------------------------------------------------------
# G1: knobs + per-part anchor registry, beside the existing F1 weight dict.
# ---------------------------------------------------------------------------
OLD_G1 = """_F1_DIM_RE = re.compile(r'^(dim|decresc|dimin)', re.I)"""
NEW_G1 = """# F1b (2026-08-07): corrections to the F1 channel. See the patch
# docstring for the diagnosis behind each. All default True.
_F1B = {
    'slur_deferral': True,
    'seam_condition': True,
    'multiplier_routing': True,
}

# F1b: per-part sets of injected anchor times, so release_anchor_boundaries
# can tell an F1 anchor from a baseline boundary. Populated once per run by
# _f1_build_release_grids; module-level for the same reason
# _REST_SEAM_POLICY is (shared without threading a new argument through
# every call site).
_F1_ANCHOR_SETS = {}

_F1_DIM_RE = re.compile(r'^(dim|decresc|dimin)', re.I)"""


# ---------------------------------------------------------------------------
# G2: collect slur spans during the spanner sweep (they were skipped).
# ---------------------------------------------------------------------------
OLD_G2 = """        elif cls in ('Line', 'TextLine'):
            lines.append((f_off, last))
            continue
        else:
            continue
        anchor = _anchor_of(last)"""
NEW_G2 = """        elif cls in ('Line', 'TextLine'):
            lines.append((f_off, last))
            continue
        elif isinstance(sp, m21.spanner.Slur):
            slurs.append((f_off, last))
            continue
        else:
            continue  # everything else
        anchor = _anchor_of(last)"""

# ---------------------------------------------------------------------------
# G3: declare the slur list next to the line list.
# ---------------------------------------------------------------------------
OLD_G3 = """    lines = []
    for sp in part.recurse().getElementsByClass(m21.spanner.Spanner):"""
NEW_G3 = """    lines = []
    slurs = []
    for sp in part.recurse().getElementsByClass(m21.spanner.Spanner):"""


# ---------------------------------------------------------------------------
# G4: apply slur deferral to every extracted anchor, then return.
# ---------------------------------------------------------------------------
OLD_G4 = """            if n_at is None:
                rec['skipped'] = 'in_rest'
            ev.append(rec)
    return ev"""
NEW_G4 = """            if n_at is None:
                rec['skipped'] = 'in_rest'
            ev.append(rec)

    # F1b(1): an anchor covered by a slur defers to that slur's release.
    # "Covered" means slur_start < anchor < slur_release, which catches
    # both the interior and the last-slurred-note onset that
    # in_slur_interior misses. One step only, no cascade; where slurs
    # nest, the outermost (latest release) wins.
    if _F1B['slur_deferral'] and slurs:
        spans = []
        for f_off, last in slurs:
            rel = _rel(last) if getattr(last, 'pitches', None) else None
            if rel is not None and rel > f_off:
                spans.append((float(f_off), float(rel)))
        for e in ev:
            a = e.get('anchor_qn')
            if a is None:
                continue
            a = float(a)
            covering = [rel for s, rel in spans if s < a - 1e-6
                        and a < rel - 1e-6]
            if covering:
                new_a = max(covering)
                e['anchor_pre_slur_deferral'] = a
                e['anchor_qn'] = new_a
                e['slur_deferred'] = True
                e['detail'] = '%s [slur-deferred %g->%g]' % (
                    e.get('detail', ''), a, new_a)
    return ev"""


# ---------------------------------------------------------------------------
# G5: register per-part anchor sets as the grids are built.
# ---------------------------------------------------------------------------
OLD_G5 = """                idx = int(round(float(e['anchor_qn']) * division))
                if 0 <= idx < T:
                    g[idx] += w
                    e['fate'] = 'injected'
                else:
                    e['fate'] = 'off_grid'
            records.append(e)
        grids.append(g)
    return grids, records"""
NEW_G5 = """                idx = int(round(float(e['anchor_qn']) * division))
                if 0 <= idx < T:
                    g[idx] += w
                    e['fate'] = 'injected'
                    _F1_ANCHOR_SETS.setdefault(i, set()).add(
                        float(e['anchor_qn']))
                else:
                    e['fate'] = 'off_grid'
            records.append(e)
        grids.append(g)
    return grids, records"""


# ---------------------------------------------------------------------------
# G6: E0b signature gains f1_anchors.
# ---------------------------------------------------------------------------
OLD_G6 = """def release_anchor_boundaries(bdys, part_notes, long_grid, gap_grid,
                              division, enabled=True, evidence_min=0.3,
                              eps=0.02, score_end_qn=None):"""
NEW_G6 = """def release_anchor_boundaries(bdys, part_notes, long_grid, gap_grid,
                              division, enabled=True, evidence_min=0.3,
                              eps=0.02, score_end_qn=None,
                              f1_anchors=None):"""


# ---------------------------------------------------------------------------
# G7: condition the seam shift for F1 anchors on a following rest.
# ---------------------------------------------------------------------------
OLD_G7 = """        elif k_on.size:
            # E0c: applies at note-to-note seams AND entry onsets --
            # per GT v2, the breath follows the note the evidence
            # describes, even when it enters from silence.
            f = min(max(int(round(bt * division)), 0), T - 1)
            ev = max(float(long_grid[f]), float(gap_grid[f]))
            if ev > evidence_min:
                new_bt = float(rels[k_on[0]])
                reason = ('seam_arrival_evidence' if at_rel
                          else 'entry_onset_arrival_evidence')"""
NEW_G7 = """        elif k_on.size:
            # E0c: applies at note-to-note seams AND entry onsets --
            # per GT v2, the breath follows the note the evidence
            # describes, even when it enters from silence.
            f = min(max(int(round(bt * division)), 0), T - 1)
            ev = max(float(long_grid[f]), float(gap_grid[f]))
            if ev > evidence_min:
                _cand = float(rels[k_on[0]])
                # F1b(2): an F1 anchor is already a release. Pushing it
                # one note further is justified when that note completes
                # into silence, and not when the music runs on attacca --
                # the new target would just be another mid-stream instant.
                # 5/5 on liz_seam; baseline boundaries are unaffected.
                # (F1 anchors are always releases, so this can only bite
                # in the at_rel case; entry onsets are untouched.)
                _is_f1 = bool(
                    _F1B['seam_condition'] and f1_anchors
                    and any(abs(bt - float(a)) <= eps for a in f1_anchors))
                _attacca = bool(np.any(np.abs(onsets - _cand) <= eps))
                if _is_f1 and _attacca:
                    shifts.append(
                        {'from': bt, 'to': bt,
                         'reason': 'f1_seam_shift_declined_attacca'})
                else:
                    new_bt = _cand
                    reason = ('seam_arrival_evidence' if at_rel
                              else 'entry_onset_arrival_evidence')"""

# ---------------------------------------------------------------------------
# G8: pass the part's anchor set at the E0b call site.
# ---------------------------------------------------------------------------
OLD_G8 = """            eps=_E0B_RELEASE_ANCHOR['eps'],
            score_end_qn=_e0b_score_end)"""
NEW_G8 = """            eps=_E0B_RELEASE_ANCHOR['eps'],
            score_end_qn=_e0b_score_end,
            f1_anchors=_F1_ANCHOR_SETS.get(i))"""


# ---------------------------------------------------------------------------
# G9: signal function -- F1 joins the boosts, inside the multiplied term.
# ---------------------------------------------------------------------------
OLD_G9 = """    B_i = (B_raw + boosts) * hairpin_multiplier * slur_multiplier * tuplet_multiplier"""
NEW_G9 = """    if expressive_release_i is not None:
        # F1b(3): expressive release evidence enters WITH the boosts, so
        # hairpin/slur/tuplet attenuation and the tie-like and natural-tie
        # hard vetoes below apply to it exactly as to every other channel.
        boosts = boosts + expressive_release_i

    B_i = (B_raw + boosts) * hairpin_multiplier * slur_multiplier * tuplet_multiplier"""


# ---------------------------------------------------------------------------
# G10: main-loop call passes the grid in; the post-hoc addition is removed.
# ---------------------------------------------------------------------------
OLD_G10 = """            gamma=gamma, zeta=zeta
        )
        # F1: expressive release evidence, absolute weights at exact
        # release frames. Enters B_i so candidate_signal, selection_score,
        # and acceptance_score all see it; sub-gate weights support only.
        B_i = B_i + expressive_release_grids[i]
        per_part_signals.append((B_i, chroma_n, rhythm_n, lbdm_n, cross_n, B_raw))"""
NEW_G10 = """            gamma=gamma, zeta=zeta,
            expressive_release_i=(expressive_release_grids[i]
                                  if _F1B['multiplier_routing'] else None)
        )
        if not _F1B['multiplier_routing']:
            # Legacy F1 placement: added after the multiplier.
            B_i = B_i + expressive_release_grids[i]
        per_part_signals.append((B_i, chroma_n, rhythm_n, lbdm_n, cross_n, B_raw))"""


# ---------------------------------------------------------------------------
# G11: CLI flags.
# ---------------------------------------------------------------------------
OLD_G11 = """    args = parser.parse_args()
    _F1_EXPRESSIVE.update("""
NEW_G11 = """    parser.add_argument('--f1b_no_slur_deferral', action='store_true',
                        help='F1b: disable slur deferral of F1 anchors')
    parser.add_argument('--f1b_no_seam_condition', action='store_true',
                        help='F1b: disable the following-rest condition on '
                             'E0b seam shifts of F1 anchors')
    parser.add_argument('--f1b_no_multiplier_routing', action='store_true',
                        help='F1b: add F1 evidence after the continuation '
                             'multiplier (pre-F1b placement)')

    args = parser.parse_args()
    _F1B.update(
        slur_deferral=not args.f1b_no_slur_deferral,
        seam_condition=not args.f1b_no_seam_condition,
        multiplier_routing=not args.f1b_no_multiplier_routing,
    )
    _F1_EXPRESSIVE.update("""


# ---------------------------------------------------------------------------
# G12/G13: serialize the three flags in both parameters blocks.
# ---------------------------------------------------------------------------
OLD_G12 = """            'f1_text_start_weight': _F1_EXPRESSIVE['text_start_weight'],
            'all_knobs': _knobs,
        })"""
NEW_G12 = """            'f1_text_start_weight': _F1_EXPRESSIVE['text_start_weight'],
            'f1b_slur_deferral': _F1B['slur_deferral'],
            'f1b_seam_condition': _F1B['seam_condition'],
            'f1b_multiplier_routing': _F1B['multiplier_routing'],
            'all_knobs': _knobs,
        })"""

OLD_G13 = """            'f1_text_start_weight': _F1_EXPRESSIVE['text_start_weight'],
            'all_knobs': _knobs,
            'division': division,"""
NEW_G13 = """            'f1_text_start_weight': _F1_EXPRESSIVE['text_start_weight'],
            'f1b_slur_deferral': _F1B['slur_deferral'],
            'f1b_seam_condition': _F1B['seam_condition'],
            'f1b_multiplier_routing': _F1B['multiplier_routing'],
            'all_knobs': _knobs,
            'division': division,"""


# ---------------------------------------------------------------------------
# G14: explain -- F1 now sits inside the multiplied term.
# ---------------------------------------------------------------------------
OLD_G14 = """    _f1_base = (B_raw_v + boost_total) * effective_mult
    print(f"  (B_raw + boost) * effective continuation multiplier")
    print(f"  = ({B_raw_v:.3f} + {boost_total:.3f}) * {effective_mult:.2f}")
    print(f"  = {_f1_base:.3f}")
    _f1_here = _f1_explain_block(result, part_idx, actual_t, idx,
                                 division, window_qn)
    if abs(_f1_here) > 1e-9:
        print(f"  + F1 expressive release evidence: {_f1_here:+.3f}")
    print(f"  = B_i {B_i_v:.3f}")"""
NEW_G14 = """    _f1_here = _f1_explain_block(result, part_idx, actual_t, idx,
                                 division, window_qn)
    _f1_routed = bool(params.get('f1b_multiplier_routing', False))
    if _f1_routed:
        _f1_base = (B_raw_v + boost_total + _f1_here) * effective_mult
        print(f"  (B_raw + boost + F1) * effective continuation multiplier")
        print(f"  = ({B_raw_v:.3f} + {boost_total:.3f} + {_f1_here:.3f})"
              f" * {effective_mult:.2f}")
        _f1_total = _f1_base
    else:
        _f1_base = (B_raw_v + boost_total) * effective_mult
        print(f"  (B_raw + boost) * effective continuation multiplier")
        print(f"  = ({B_raw_v:.3f} + {boost_total:.3f})"
              f" * {effective_mult:.2f}")
        if abs(_f1_here) > 1e-9:
            print(f"  + F1 expressive release evidence (post-multiplier):"
                  f" {_f1_here:+.3f}")
        _f1_total = _f1_base + _f1_here
    print(f"  = B_i {B_i_v:.3f}")
    _f1_base, _f1_here = _f1_total, 0.0"""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'sectioning_v2_10_F1.py'
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()

    if '_F1B' in src:
        raise SystemExit("ABORT: %s already contains _F1B (already "
                         "patched?). File unchanged." % path)

    for old, new, label in (
            (OLD_G1, NEW_G1, 'G1 F1b knobs + anchor registry'),
            (OLD_G3, NEW_G3, 'G3 slur list declaration'),
            (OLD_G2, NEW_G2, 'G2 slur span collection'),
            (OLD_G4, NEW_G4, 'G4 slur deferral'),
            (OLD_G5, NEW_G5, 'G5 anchor set registration'),
            (OLD_G6, NEW_G6, 'G6 E0b signature'),
            (OLD_G7, NEW_G7, 'G7 seam condition'),
            (OLD_G8, NEW_G8, 'G8 E0b call site'),
            (OLD_G9, NEW_G9, 'G9 signal function routing'),
            (OLD_G10, NEW_G10, 'G10 main-loop call'),
            (OLD_G11, NEW_G11, 'G11 CLI flags'),
            (OLD_G12, NEW_G12, 'G12 summary serialization'),
            (OLD_G13, NEW_G13, 'G13 pkl serialization'),
            (OLD_G14, NEW_G14, 'G14 explain identity line'),
    ):
        src = replace_once(src, old, new, label)

    # G15: compute_per_part_boundary_signal gains the keyword. Done
    # positionally rather than by verbatim anchor because the parameter
    # list has grown across versions; the assert keeps it honest.
    marker = 'def compute_per_part_boundary_signal('
    if src.count(marker) != 1:
        raise SystemExit("ABORT [G15]: found %d definitions of "
                         "compute_per_part_boundary_signal (need 1). "
                         "File unchanged." % src.count(marker))
    start = src.index(marker)
    close = src.index('):', start)
    src = (src[:close] + ',\n                                      '
           'expressive_release_i=None' + src[close:])

    try:
        compile(src, path, 'exec')
    except SyntaxError as e:
        raise SystemExit("ABORT: patched source fails to compile: %s. "
                         "File unchanged." % e)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print("Patched %s with F1b (slur deferral, conditioned E0b seam shift, "
          "multiplier routing). All three default ON.\n"
          "Run the staged validation B1/B2/B3 from the patch docstring; "
          "B1 has an exact prediction (Euphonium only: +108, +116, -112, "
          "-120)." % path)


if __name__ == '__main__':
    main()
