#!/usr/bin/env python3
"""
slur_release_probe.py

Pre-registration band for two related changes:

  (A) project SlurEnd_i at the slur's chain release instead of the last
      slurred note's onset      -- the positive fix
  (B) F1c-right: extend in_slur_interior to the chain release
      -- the suppressive fix

Both push a boundary from  onset(last slurred note)  to  rel(last slurred note).
This counts how many current boundaries sit in that window, and how many of
them are at, or would move onto, a GT point.

Schema is DUMPED FIRST, unconditionally, so a shape mismatch is diagnosable
from the same run rather than costing another round trip.

Usage:
    python slur_release_probe.py RUN_DIR [--gt gt_boundaries_v2.json] [--tol 0.1]
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


def shape(o, depth=0, maxd=3):
    """Compact structural description of an unknown object."""
    pad = '  ' * depth
    if np is not None and isinstance(o, np.ndarray):
        return '%sndarray%s' % (pad, (o.shape,))
    if isinstance(o, dict):
        if depth >= maxd:
            return '%sdict(%d keys)' % (pad, len(o))
        ks = list(o)[:10]
        out = ['%sdict keys=%s' % (pad, ks)]
        for k in ks[:4]:
            out.append('%s  %r -> %s' % (pad, k, type(o[k]).__name__))
        return '\n'.join(out)
    if isinstance(o, (list, tuple)):
        if not o:
            return '%s%s(empty)' % (pad, type(o).__name__)
        if depth >= maxd:
            return '%s%s(len %d)' % (pad, type(o).__name__, len(o))
        return '%s%s(len %d) first ->\n%s' % (
            pad, type(o).__name__, len(o), shape(o[0], depth + 1, maxd))
    return '%s%s %r' % (pad, type(o).__name__, o)


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
    if isinstance(n, dict):
        off = dur = None
        for k in ('offset', 'offset_qn', 'start', 'start_qn'):
            if k in n and is_num(n[k]):
                off = float(n[k])
                break
        for k in ('duration', 'duration_qn', 'dur', 'quarterLength', 'ql'):
            if k in n and is_num(n[k]):
                dur = float(n[k])
                break
        if off is not None and dur is not None:
            return off, dur
    if isinstance(n, (list, tuple)) and len(n) >= 2 and is_num(n[0]) and is_num(n[1]):
        return float(n[0]), float(n[1])
    return None, None

def slur_ends_of(entry):
    """slur_ends only. starts and ends are NOT index-parallel (see line 941)."""
    if not isinstance(entry, dict):
        return []
    e = entry.get('slur_ends')
    if e is None:
        return []
    if np is not None and hasattr(e, 'tolist'):
        e = e.tolist()
    return [float(x) for x in e if is_num(x)]

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

    print('=' * 84)
    print('SCHEMA DUMP (printed unconditionally)')
    print('=' * 84)
    for k in ('slur_info', 'notes_per_part', 'per_part_boundaries'):
        print('\n--- %s ---' % k)
        print(shape(r.get(k)))
    print()

    gt = {}
    if os.path.exists(args.gt):
        d = json.load(open(args.gt, encoding='utf-8'))
        for i, e in enumerate(d.get('per_part', [])):
            idx = int(e.get('index', i))
            gt[idx] = [float(b['time_quarter_notes'])
                       for b in (e.get('boundaries') or [])
                       if is_num(b.get('time_quarter_notes'))]
    print('GT: %d points\n' % sum(len(v) for v in gt.values()))

    names = r.get('part_names') or []
    notes_all = r.get('notes_per_part') or []
    finals = r.get('per_part_boundaries') or []
    slurs_all = r.get('slur_info') or []

    print('=' * 84)
    print('BOUNDARIES AT A SLUR LAST-NOTE ONSET   tol=%.2f qn' % args.tol)
    print('=' * 84)

    tot = dict(n=0, gt_at_rel=0, gt_at_onset=0, neither=0)
    for i in range(len(finals)):
        fin = to_floats(finals[i])
        notes = notes_all[i] if i < len(notes_all) else []
        spans = slur_ends_of(slurs_all[i]) if i < len(slurs_all) else []
        if not spans:
            continue
        gtp = gt.get(i, [])
        rows = []
        for b in fin:
            for last in spans:
                if abs(b - last) > 1e-6:
                    continue
                rel = b
                for n in notes:
                    off, dur = note_fields(n)
                    if off is not None and abs(off - b) <= 1e-6:
                        rel = off + dur
                        break
                at_rel = any(abs(g - rel) <= args.tol for g in gtp)
                at_on = any(abs(g - b) <= args.tol for g in gtp)
                rows.append((b, rel, at_on, at_rel))
                break
        if not rows:
            continue
        print('\n--- part %d  %s ---' % (i, names[i] if i < len(names) else '?'))
        for b, rel, at_on, at_rel in rows:
            verdict = ('GT AT RELEASE -> gain' if at_rel and not at_on else
                       'GT at onset -> would LOSE' if at_on and not at_rel else
                       'both' if at_on else 'neither GT')
            print('    onset %8.3f  ->  release %8.3f   %s' % (b, rel, verdict))
            tot['n'] += 1
            tot['gt_at_rel'] += int(at_rel and not at_on)
            tot['gt_at_onset'] += int(at_on and not at_rel)
            tot['neither'] += int(not at_on and not at_rel)

    print('\n' + '=' * 84)
    print('BAND')
    print('  boundaries at a slur last-note onset   %4d' % tot['n'])
    print('  GT sits at the RELEASE (gain)          %4d   <- expected recovery'
          % tot['gt_at_rel'])
    print('  GT sits at the ONSET  (loss)           %4d   <- expected cost'
          % tot['gt_at_onset'])
    print('  neither position is GT                 %4d   <- churn' % tot['neither'])
    print('=' * 84)
    return 0


if __name__ == '__main__':
    sys.exit(main())
