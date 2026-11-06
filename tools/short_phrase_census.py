#!/usr/bin/env python3
"""
short_phrase_census.py  (v2, 2026-09-02)

Census of boundaries removed by the short-phrase filter, scored against GT.

v1 was wrong three ways and this rewrite exists to not repeat them:

  * The GT loader looked for a 'parts' key; the file uses 'per_part'.  Every
    row reported "not a GT point".  v2 asserts a non-empty GT and dies loudly
    rather than reporting zeros.
  * v1 recomputed segment material itself and disagreed with the pipeline's
    own numbers for the same instant.  It no longer computes anything --
    note_count / sounding_seconds / elapsed_qn are read straight from the
    record.
  * A removed boundary can be reinstated by release_anchor_boundaries, which
    runs AFTER the filter (line ~3162 vs ~3182).  A removal only costs a GT
    point if that point is ALSO missing from the final output.  v1 never
    checked, so it would have scored reinstated boundaries as losses.

Known limitation, stated rather than papered over: `postprocess_short_phrases`
records the removed time plus the material of the flagged segment (prev, cur),
but not which endpoint was removed.  The segment cannot be reconstructed from
the log.  That is a §1 provenance gap, not a bug in this tool.

Usage:
    python short_phrase_census.py RUN_DIR [--gt gt_boundaries_v2.json]
                                          [--tol 0.1]
"""

import argparse
import json
import os
import pickle
import sys

try:
    import numpy as np
except ImportError:
    np = None


def is_num(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if np is not None and isinstance(v, (np.integer, np.floating)):
        return True
    return False


def to_floats(obj):
    if obj is None:
        return []
    if np is not None and hasattr(obj, 'tolist'):
        obj = obj.tolist()
    out = []
    if isinstance(obj, (list, tuple)):
        for v in obj:
            if is_num(v):
                out.append(float(v))
            elif isinstance(v, dict) and is_num(v.get('time_quarter_notes')):
                out.append(float(v['time_quarter_notes']))
    return out


def note_fields(n):
    """-> (offset, duration) from a note record of unknown shape."""
    if isinstance(n, dict):
        off = dur = None
        for k in ('offset', 'offset_qn', 'start', 'start_qn', 'boundary_offset'):
            if k in n and is_num(n[k]):
                off = float(n[k])
                break
        for k in ('duration', 'duration_qn', 'dur', 'quarterLength', 'ql'):
            if k in n and is_num(n[k]):
                dur = float(n[k])
                break
        if off is not None and dur is not None:
            return off, dur
    if isinstance(n, (list, tuple)) and len(n) >= 2 \
            and is_num(n[0]) and is_num(n[1]):
        return float(n[0]), float(n[1])
    return None, None


def anchored(t, notes, eps=0.02):
    """E0b case 1: a boundary strictly inside a note retargets to its release.

    This is the ONLY thing v3 recomputes.  Segment material still comes from
    the pipeline's own record -- v1's mistake was recomputing that too.
    """
    for n in notes:
        off, dur = note_fields(n)
        if off is None:
            continue
        if off + eps < t < off + dur - eps:
            return off + dur
    return t


def load_gt(path):
    """gt_boundaries_v2.json -> {part: [(qn, 'm.x by'), ...]}"""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    per_part = data.get('per_part') if isinstance(data, dict) else data
    if not isinstance(per_part, list):
        raise SystemExit('GT SHAPE UNRECOGNISED: top-level keys %s'
                         % (list(data) if isinstance(data, dict) else type(data)))
    gt = {}
    for i, entry in enumerate(per_part):
        idx = int(entry.get('index', i)) if isinstance(entry, dict) else i
        rows = []
        for b in (entry.get('boundaries') or []):
            if isinstance(b, dict) and is_num(b.get('time_quarter_notes')):
                rows.append((float(b['time_quarter_notes']),
                             b.get('measure_beat', '')))
        gt[idx] = rows
    total = sum(len(v) for v in gt.values())
    if total == 0:
        raise SystemExit('GT LOADED BUT EMPTY -- the loader is wrong, not the data.')
    print('GT: %d points across %d parts\n' % (total, len(gt)))
    return gt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--gt', default='gt_boundaries_v2.json')
    ap.add_argument('--tol', type=float, default=0.1)
    args = ap.parse_args()

    pkl = args.run_dir
    if os.path.isdir(pkl):
        pkl = os.path.join(pkl, 'result.pkl')
    r = pickle.load(open(pkl, 'rb'))

    names = r.get('part_names') or []
    spf = r.get('short_phrase_filter_info') or []
    finals = r.get('per_part_boundaries') or []
    notes_all = r.get('notes_per_part') or []
    gt = load_gt(args.gt)

    probe = None
    for pn in notes_all:
        if pn:
            probe = pn[0]
            break
    if probe is not None and note_fields(probe)[0] is None:
        print('NOTE-SCHEMA PROBE FAILED -- anchored columns are unreliable.')
        print('  first record: %r\n' % (probe,))

    print('=' * 86)
    print('SHORT-PHRASE FILTER CENSUS v2   run=%s   tol=%.2f qn' % (pkl, args.tol))
    print('=' * 86)

    T = dict(rem=0, fm3=0, fm3_if=0, on_gt=0, via_anchor=0, lost=0,
             lost_fm3=0, lost_fm3_if=0)
    lost_rows = []

    for i in range(len(spf)):
        recs = spf[i] or []
        if not recs:
            continue
        gtp = gt.get(i, [])
        fin = to_floats(finals[i] if i < len(finals) else None)
        notes = notes_all[i] if i < len(notes_all) else []
        pname = names[i] if i < len(names) else '?'

        print('\n--- part %d  %s   (%d removal(s), %d final boundaries) ---'
              % (i, pname, len(recs), len(fin)))
        print('    %-9s %-9s %4s %8s  %-12s %-9s %s'
              % ('removed', 'anchored', 'cnt', 'sound_qn', 'GT?', 'in final?',
                 'verdict'))

        for rec in recs:
            if not isinstance(rec, dict) or not is_num(rec.get('time_quarter_notes')):
                continue
            t = float(rec['time_quarter_notes'])
            cnt = rec.get('note_count')
            ss = rec.get('sounding_seconds')
            sq = rec.get('sounding_qn')
            a = anchored(t, notes)

            fm3 = (cnt == 0 and is_num(ss) and float(ss) <= 1e-9)

            # Would the flagged segment become all-rest if anchoring ran first?
            # Exact test: the boundary sat inside a note whose remaining
            # fragment (a - t) accounts for ALL the segment's sounding time,
            # so anchoring past it leaves zero sounding material.
            fm3_if = False
            if not fm3 and a > t + 1e-9 and cnt == 1 and is_num(sq):
                fm3_if = abs(float(sq) - (a - t)) <= 1e-6

            # GT membership at either position; anchoring is what the boundary
            # would have become had the stages run in the correct order.
            m_raw = [(g, mb) for g, mb in gtp if abs(g - t) <= args.tol]
            m_anc = [(g, mb) for g, mb in gtp if abs(g - a) <= args.tol]
            match = m_raw or m_anc
            via_anchor = (not m_raw) and bool(m_anc)

            gpt = match[0][0] if match else None
            in_final = (gpt is not None
                        and any(abs(b - gpt) <= args.tol for b in fin))
            lost = bool(match) and not in_final

            v = []
            if fm3:
                v.append('FM3 all-rest')
            elif fm3_if:
                v.append('FM3 ONLY IF ANCHORED')
            if lost:
                v.append('*** COSTS GT ***')
            elif match:
                v.append('reinstated by anchoring')

            print('    %-9.3f %-9.3f %4s %8s  %-12s %-9s %s'
                  % (t, a, cnt, ('%.3f' % sq) if is_num(sq) else '-',
                     ((match[0][1] or '%.3f' % match[0][0])
                      + ('*' if via_anchor else '')) if match else 'no',
                     'yes' if in_final else 'no',
                     ', '.join(v) or '-'))

            T['rem'] += 1
            T['fm3'] += int(fm3)
            T['fm3_if'] += int(fm3_if)
            T['on_gt'] += int(bool(match))
            T['via_anchor'] += int(via_anchor)
            T['lost'] += int(lost)
            T['lost_fm3'] += int(lost and fm3)
            T['lost_fm3_if'] += int(lost and fm3_if)
            if lost:
                lost_rows.append((i, pname, t, a,
                                  match[0][1] or '%.3f' % match[0][0],
                                  'FM3' if fm3 else
                                  ('FM3-if-anchored' if fm3_if else 'fragment')))

    print('\n' + '=' * 92)
    print('TOTALS')
    print('  removals by the short-phrase filter            %4d' % T['rem'])
    print('  segments all-rest AS THE FILTER SEES THEM      %4d   (FM3 firing now)'
          % T['fm3'])
    print('  segments all-rest ONLY IF ANCHORED FIRST       %4d   (order bug)'
          % T['fm3_if'])
    print('  removed at a GT point (either position)        %4d' % T['on_gt'])
    print('    ... of which found only via anchoring        %4d' % T['via_anchor'])
    print('  ... and the GT point is absent from final      %4d   <- real cost'
          % T['lost'])
    print('    ... FM3 now                                  %4d' % T['lost_fm3'])
    print('    ... FM3 only after the order swap            %4d' % T['lost_fm3_if'])

    if lost_rows:
        print('\n  GT points lost to the filter:')
        for i, pname, t, a, mb, kind in lost_rows:
            print('    part %-2d %-20s %-12s removed %8.3f -> anchored %8.3f   %s'
                  % (i, pname[:20], mb, t, a, kind))

    print('\n  PRE-REGISTERED BANDS')
    print('    FM3 guard alone      : GT recovered = %d, boundaries reinstated <= %d'
          % (T['lost_fm3'], T['fm3']))
    print('    order swap + guard   : GT recovered = %d, boundaries reinstated <= %d'
          % (T['lost_fm3'] + T['lost_fm3_if'], T['fm3'] + T['fm3_if']))
    print('  The order swap also reshuffles which endpoint is weaker, which')
    print('  cannot be modelled statically -- the reinstated counts are ceilings.')
    print('=' * 92)
    return 0


if __name__ == '__main__':
    sys.exit(main())
