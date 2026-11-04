#!/usr/bin/env python3
"""
patch_F1_expressive_release.py — F1: expressive release evidence channel.

Target: sectioning_v2_10_E0c.py (pass path as argv[1] if renamed).
Anchors are strict verbatim; any mismatch aborts with the file unchanged.
No backups (git is the safety net). Compile-checked before writing.

WHAT IT ADDS
  Typed expressive events anchored at tie-chain RELEASES enter B_i as
  exact frame deltas with ABSOLUTE weights (no gaussian smearing, no
  normalization, no zeta coupling):
    fermata_release  fermata note -> chain release
    dim_end          Diminuendo wedge (or dim-text + dashed Line) ->
                     last spanned note's chain release
    cresc_end        Crescendo wedge likewise
    text_start       bare dictionary text (rit./rall./dim./cresc./...) ->
                     release of the note sounding under it;
                     'a tempo' -> the PRECEDING release
  Ornaments (trill/tremolo/arpeggio/mordent/turn) and expressive-character
  words (marcato/dolce/espress./cantabile/legato) are extracted and
  RECORDED at weight 0.0 pending Robert's verdicts.
  Every event -> <output_dir>/f1_events.json with kind/raw/anchor/fate.
  Weights serialized into both parameters blocks (summary + pkl).
  All four weights DEFAULT 0.0 (wiring run must be 0/0/0 vs E0c).

VALIDATION PROTOCOL (staged; boundaries_diff after each)
  run 0: defaults            -> 0/0/0 vs output_v2_10_E0c/liz_seam
  A/B1: --f1_fermata_weight 1.0 --f1_dim_end_weight 0.6
        band: ADDED subset of {fermata,dim} anchors, ~13-15 GT misses
        recovered, extras <= 10 pre-validation; REMOVED ~0; MOVED ~0
  A/B2: + --f1_cresc_end_weight 0.25  (supporting-only; fires only with
        corroborating selection mass)
  A/B3: + --f1_text_start_weight 0.25
  Then audit_check + annotation_check v3 on the final candidate.
"""

import sys


def replace_once(src, old, new, label):
    n = src.count(old)
    if n != 1:
        raise SystemExit(
            f"ABORT [{label}]: anchor found {n} times (need exactly 1). "
            f"File unchanged.")
    return src.replace(old, new, 1)


# ---------------------------------------------------------------------------
# P1: module-level knobs + extraction helpers, inserted before the E0
# annotation-retarget comment (verbatim-confirmed unique).
# ---------------------------------------------------------------------------
OLD_P1 = """# E0: attach breath marks to the note RELEASING at the boundary"""
NEW_P1 = '''# ---------------------------------------------------------------------------
# F1 (2026-07-19): expressive release evidence.
# DIAGNOSIS: the exact-miss cluster sits at phrase-final releases where no
#   onset-projected channel fires (E0b finding). f_events.py dry run:
#   fermata claims 7 GT misses, dim_end 8, cresc_end 18 (42 novel),
#   including the Trumpet m.12-end sentinel and independent recovery of
#   the m.93 unison ruling.
# RULE: release-anchored typed events -> exact frame deltas with absolute
#   weights, added to B_i in the main per-part loop only (NOT local_B_pre:
#   injected evidence must not propagate via cross-rhythm support in v1).
#   Sub-gate weights (< 0.30) are supporting-only by construction.
#   Precedence: injected boundaries pass through the SAME validation as
#   every channel, so outgoing ties still veto fermata targets.
# RECORDS: every event -> f1_events.json; weights serialized explicitly
#   (module dict values are invisible to the locals() all_knobs sweep).
_F1_EXPRESSIVE = {
    'fermata_release_weight': 0.0,
    'dim_end_weight': 0.0,
    'cresc_end_weight': 0.0,
    'text_start_weight': 0.0,
}

_F1_DIM_RE = re.compile(r'^(dim|decresc|dimin)', re.I)
_F1_CRESC_RE = re.compile(r'^cresc', re.I)
_F1_WORD_RE = re.compile(r'^(marcato|dolce|espress|cantabile|legato)', re.I)


def _f1_extract_part_events(part):
    """F1: typed expressive events with tie-chain release anchors."""
    notes = sorted(part.flatten().notes, key=lambda n: float(n.offset))

    def _rel(n):
        cur, guard = n, 0
        while guard < 500:
            guard += 1
            rel = float(cur.offset) + float(cur.duration.quarterLength)
            tie = getattr(cur, 'tie', None)
            if tie is None or tie.type == 'stop':
                return rel
            pset = {p.nameWithOctave for p in cur.pitches}
            nxt = None
            for c in notes:
                if abs(float(c.offset) - rel) <= 1e-3 and \\
                        pset & {p.nameWithOctave for p in c.pitches}:
                    ct = getattr(c, 'tie', None)
                    if ct is not None and ct.type in ('continue', 'stop'):
                        nxt = c
                        break
            if nxt is None:
                return rel
            cur = nxt
        return float(cur.offset) + float(cur.duration.quarterLength)

    def _note_at(t):
        best = None
        for c in notes:
            o = float(c.offset)
            if o - 1e-3 <= t < o + float(c.duration.quarterLength) - 1e-3:
                best = c
        return best

    def _prev_release(t):
        best = None
        for c in notes:
            r = float(c.offset) + float(c.duration.quarterLength)
            if r <= t + 1e-3 and (best is None or r > best):
                best = r
        return best

    def _anchor_of(el):
        if hasattr(el, 'pitches') and el.pitches:
            return _rel(el)
        try:
            return float(el.getOffsetInHierarchy(part))
        except Exception:
            return None

    ev = []

    orn = (('trill', getattr(m21.expressions, 'Trill', None)),
           ('tremolo', getattr(m21.expressions, 'Tremolo', None)),
           ('arpeggio', getattr(m21.expressions, 'ArpeggioMark', None)),
           ('mordent', getattr(m21.expressions, 'Mordent', None)),
           ('turn', getattr(m21.expressions, 'Turn', None)))
    for n in notes:
        for e in n.expressions:
            if isinstance(e, m21.expressions.Fermata):
                ev.append(dict(kind='fermata_release',
                               raw_qn=float(n.offset), anchor_qn=_rel(n),
                               detail='fermata'))
                continue
            for kname, kcls in orn:
                if kcls is not None and isinstance(e, kcls):
                    ev.append(dict(kind='ornament_' + kname,
                                   raw_qn=float(n.offset),
                                   anchor_qn=_rel(n), detail=kname,
                                   zero_weight=True))
                    break

    lines = []
    for sp in part.recurse().getElementsByClass(m21.spanner.Spanner):
        first, last = sp.getFirst(), sp.getLast()
        if first is None or last is None:
            continue
        try:
            f_off = float(first.getOffsetInHierarchy(part))
        except Exception:
            continue
        cls = type(sp).__name__
        if isinstance(sp, m21.dynamics.Diminuendo):
            kind = 'dim_end'
        elif isinstance(sp, m21.dynamics.Crescendo):
            kind = 'cresc_end'
        elif isinstance(sp, m21.dynamics.DynamicWedge):
            kind = 'dim_end'    # untyped wedge: treat as dim, visible in detail
        elif cls in ('Line', 'TextLine'):
            lines.append((f_off, last))
            continue
        else:
            continue
        anchor = _anchor_of(last)
        if anchor is None:
            continue
        ev.append(dict(kind=kind, raw_qn=f_off, anchor_qn=anchor,
                       detail=cls))

    for te in part.recurse().getElementsByClass(
            m21.expressions.TextExpression):
        txt = (te.content or '').strip()
        if not txt:
            continue
        try:
            t_off = float(te.getOffsetInHierarchy(part))
        except Exception:
            continue
        tclass = _classify_tempo_or_expression_text(txt)
        is_dim = bool(_F1_DIM_RE.match(txt))
        is_cresc = bool(_F1_CRESC_RE.match(txt))
        is_word = bool(_F1_WORD_RE.match(txt))
        if not (tclass or is_dim or is_cresc or is_word):
            continue
        if is_word:
            n_at = _note_at(t_off)
            ev.append(dict(kind='expressive_word', raw_qn=t_off,
                           anchor_qn=(_rel(n_at) if n_at else None),
                           detail="'%s'" % txt, zero_weight=True))
            continue
        if tclass == 'tempo_text_a_tempo':
            pr = _prev_release(t_off)
            rec = dict(kind='text_start', raw_qn=t_off, anchor_qn=pr,
                       detail="a tempo '%s' -> preceding release" % txt)
            if pr is None:
                rec['skipped'] = 'no_prev_release'
            ev.append(rec)
            continue
        paired = None
        for f_off, last in lines:
            if abs(f_off - t_off) <= 1.0:
                paired = last
                break
        if paired is not None:
            kind = 'dim_end' if is_dim else (
                'cresc_end' if is_cresc else 'text_start')
            anchor = _anchor_of(paired)
            rec = dict(kind=kind, raw_qn=t_off, anchor_qn=anchor,
                       detail="'%s' + dashed line end" % txt)
            if anchor is None:
                rec['skipped'] = 'line_end_unresolvable'
            ev.append(rec)
        else:
            n_at = _note_at(t_off)
            rec = dict(kind='text_start', raw_qn=t_off,
                       anchor_qn=(_rel(n_at) if n_at else None),
                       detail="'%s' at note" % txt)
            if n_at is None:
                rec['skipped'] = 'in_rest'
            ev.append(rec)
    return ev


def _f1_build_release_grids(parts, is_tacet, T, division):
    """Per-part exact-frame delta grids + full event records."""
    wmap = {'fermata_release': _F1_EXPRESSIVE['fermata_release_weight'],
            'dim_end': _F1_EXPRESSIVE['dim_end_weight'],
            'cresc_end': _F1_EXPRESSIVE['cresc_end_weight'],
            'text_start': _F1_EXPRESSIVE['text_start_weight']}
    grids, records = [], []
    for i, part in enumerate(parts):
        g = np.zeros(T, dtype=float)
        if is_tacet[i]:
            grids.append(g)
            continue
        try:
            evs = _f1_extract_part_events(part)
        except Exception as _e:
            print("       WARNING: F1 extraction failed for part "
                  "%d: %s" % (i, _e))
            grids.append(g)
            continue
        for e in evs:
            e['part'] = i
            w = 0.0 if e.get('zero_weight') else wmap.get(e['kind'], 0.0)
            e['weight'] = w
            if e.get('anchor_qn') is None:
                e['fate'] = e.get('skipped', 'skipped')
            elif w <= 0.0:
                e['fate'] = 'zero_weight_recorded'
            else:
                idx = int(round(float(e['anchor_qn']) * division))
                if 0 <= idx < T:
                    g[idx] += w
                    e['fate'] = 'injected'
                else:
                    e['fate'] = 'off_grid'
            records.append(e)
        grids.append(g)
    return grids, records


# E0: attach breath marks to the note RELEASING at the boundary'''

# ---------------------------------------------------------------------------
# P2: build grids + write f1_events.json, just before the pre-loop.
# ---------------------------------------------------------------------------
OLD_P2 = """    local_B_pre = np.zeros((len(parts), T), dtype=float)"""
NEW_P2 = """    expressive_release_grids, _f1_records = _f1_build_release_grids(
        parts, is_tacet, T, division)
    try:
        with open(os.path.join(output_dir, 'f1_events.json'), 'w',
                  encoding='utf-8') as _f:
            json.dump({'weights': dict(_F1_EXPRESSIVE),
                       'events': _f1_records}, _f, indent=1)
    except Exception as _e:
        print("       WARNING: f1_events.json not written: %s" % _e)
    local_B_pre = np.zeros((len(parts), T), dtype=float)"""

# ---------------------------------------------------------------------------
# P3: injection into B_i in the MAIN loop only (the pre-loop call ends in
# 'local_B_pre[i] = B_pre', so this tail is unique to the main loop).
# ---------------------------------------------------------------------------
OLD_P3 = """            gamma=gamma, zeta=zeta
        )
        per_part_signals.append((B_i, chroma_n, rhythm_n, lbdm_n, cross_n, B_raw))"""
NEW_P3 = """            gamma=gamma, zeta=zeta
        )
        # F1: expressive release evidence, absolute weights at exact
        # release frames. Enters B_i so candidate_signal, selection_score,
        # and acceptance_score all see it; sub-gate weights support only.
        B_i = B_i + expressive_release_grids[i]
        per_part_signals.append((B_i, chroma_n, rhythm_n, lbdm_n, cross_n, B_raw))"""

# ---------------------------------------------------------------------------
# P4: CLI flags + module-dict setter around parse_args (anchor includes
# --breath_color to pin uniqueness).
# ---------------------------------------------------------------------------
OLD_P4 = """    parser.add_argument('--breath_color', default='#d62728')

    args = parser.parse_args()"""
NEW_P4 = """    parser.add_argument('--breath_color', default='#d62728')
    parser.add_argument('--f1_fermata_weight', type=float, default=0.0,
                        help='F1 fermata chain-release evidence weight '
                             '(proposed 1.0; >=0.30 fires alone)')
    parser.add_argument('--f1_dim_end_weight', type=float, default=0.0,
                        help='F1 diminuendo-end evidence weight '
                             '(proposed 0.6)')
    parser.add_argument('--f1_cresc_end_weight', type=float, default=0.0,
                        help='F1 crescendo-end evidence weight (proposed '
                             '0.25: sub-gate, supporting-only)')
    parser.add_argument('--f1_text_start_weight', type=float, default=0.0,
                        help='F1 bare dictionary-text weight (proposed '
                             '0.25: sub-gate, supporting-only)')

    args = parser.parse_args()
    _F1_EXPRESSIVE.update(
        fermata_release_weight=args.f1_fermata_weight,
        dim_end_weight=args.f1_dim_end_weight,
        cresc_end_weight=args.f1_cresc_end_weight,
        text_start_weight=args.f1_text_start_weight,
    )"""

# ---------------------------------------------------------------------------
# P5: serialization into the summary parameters block (S0-b site; tail
# '})' distinguishes it from the pkl block).
# ---------------------------------------------------------------------------
OLD_P5 = """            'rest_seam_policy': _REST_SEAM_POLICY['policy'],
            'rest_seam_snap_qn': _REST_SEAM_POLICY['snap_qn'],
            'all_knobs': _knobs,
        })"""
NEW_P5 = """            'rest_seam_policy': _REST_SEAM_POLICY['policy'],
            'rest_seam_snap_qn': _REST_SEAM_POLICY['snap_qn'],
            'f1_fermata_release_weight':
                _F1_EXPRESSIVE['fermata_release_weight'],
            'f1_dim_end_weight': _F1_EXPRESSIVE['dim_end_weight'],
            'f1_cresc_end_weight': _F1_EXPRESSIVE['cresc_end_weight'],
            'f1_text_start_weight': _F1_EXPRESSIVE['text_start_weight'],
            'all_knobs': _knobs,
        })"""

# ---------------------------------------------------------------------------
# P6: same fields into result['parameters'] (S0-c site; tail 'division').
# ---------------------------------------------------------------------------
OLD_P6 = """            'rest_seam_policy': _REST_SEAM_POLICY['policy'],
            'rest_seam_snap_qn': _REST_SEAM_POLICY['snap_qn'],
            'all_knobs': _knobs,
            'division': division,"""
NEW_P6 = """            'rest_seam_policy': _REST_SEAM_POLICY['policy'],
            'rest_seam_snap_qn': _REST_SEAM_POLICY['snap_qn'],
            'f1_fermata_release_weight':
                _F1_EXPRESSIVE['fermata_release_weight'],
            'f1_dim_end_weight': _F1_EXPRESSIVE['dim_end_weight'],
            'f1_cresc_end_weight': _F1_EXPRESSIVE['cresc_end_weight'],
            'f1_text_start_weight': _F1_EXPRESSIVE['text_start_weight'],
            'all_knobs': _knobs,
            'division': division,"""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'sectioning_v2_10_E0c.py'
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()

    src = replace_once(src, OLD_P1, NEW_P1, 'P1 helpers + knobs')
    src = replace_once(src, OLD_P2, NEW_P2, 'P2 grid build + records')
    src = replace_once(src, OLD_P3, NEW_P3, 'P3 B_i injection (main loop)')
    src = replace_once(src, OLD_P4, NEW_P4, 'P4 CLI wiring')
    src = replace_once(src, OLD_P5, NEW_P5, 'P5 summary serialization')
    src = replace_once(src, OLD_P6, NEW_P6, 'P6 pkl serialization')

    try:
        compile(src, path, 'exec')
    except SyntaxError as e:
        raise SystemExit("ABORT: patched source fails to compile: %s. "
                         "File unchanged." % e)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print("Patched %s: F1 expressive release channel installed, all four "
          "weights default 0.0.\n"
          "Run 0 (wiring): plain run, then boundaries_diff vs "
          "output_v2_10_E0c/liz_seam -> MUST be 0/0/0 (parameter check "
          "will flag the four new f1_* keys on the old run: expected).\n"
          "Then staged A/B per the patch docstring." % path)


if __name__ == '__main__':
    main()
