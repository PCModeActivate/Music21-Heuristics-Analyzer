#!/usr/bin/env python3
"""
drop_trace.py

Trace what happened to a boundary at a given part/time, through every stage
that can move or remove one.

The §1 invariant says every dropped boundary leaves a record, but the records
are scattered across several result.pkl keys with different shapes.  This walks
all of them and reports anything referencing a time near the target.

Usage:
    python drop_trace.py RUN_DIR PART QN [QN ...] [--window 3.0]

Example:
    python drop_trace.py output_v2_10_F1b/liz_seam_B3_all 9 26.5 134.0
"""

import argparse
import os
import pickle
import sys

try:
    import numpy as np
except ImportError:
    np = None

# keys that can explain a move or a removal, in pipeline order
STAGE_KEYS = [
    'per_part_candidate_diagnostics',
    'e0b_shift_info',
    'short_phrase_filter_info',
    'boundary_target_info',
    'phrase_material_per_part',
]


def is_num(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if np is not None and isinstance(v, (np.integer, np.floating)):
        return True
    return False


def part_slice(obj, part, nparts):
    """If obj is a per-part container, return just this part's entry."""
    if isinstance(obj, dict):
        for key in (part, str(part)):
            if key in obj:
                return obj[key], True
        return obj, False
    if isinstance(obj, (list, tuple)):
        if len(obj) in (nparts, nparts + 1) and part < len(obj):
            return obj[part], True
    return obj, False


def walk(obj, path, target, window, out, depth=0):
    """Collect dicts containing a numeric field within `window` of target."""
    if depth > 10:
        return
    if isinstance(obj, dict):
        hits = [(k, float(v)) for k, v in obj.items()
                if is_num(v) and abs(float(v) - target) <= window]
        if hits:
            out.append((path, obj, hits))
        for k, v in obj.items():
            walk(v, '%s[%r]' % (path, k), target, window, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        if len(obj) > 4000:
            return
        for i, v in enumerate(obj):
            if is_num(v):
                continue          # bare numeric arrays match everywhere
            walk(v, '%s[%d]' % (path, i), target, window, out, depth + 1)


def fmt(obj, limit=8):
    """One-line rendering of a record, long arrays elided."""
    if not isinstance(obj, dict):
        return repr(obj)[:200]
    bits = []
    for k, v in list(obj.items())[:limit]:
        if isinstance(v, (list, tuple)) and len(v) > 6:
            s = '<%d items>' % len(v)
        elif np is not None and isinstance(v, np.ndarray):
            s = '<array %s>' % (v.shape,)
        elif isinstance(v, float):
            s = '%.4f' % v
        else:
            s = repr(v)[:60]
        bits.append('%s=%s' % (k, s))
    if len(obj) > limit:
        bits.append('... +%d' % (len(obj) - limit))
    return '  '.join(bits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('part', type=int)
    ap.add_argument('qn', type=float, nargs='+')
    ap.add_argument('--window', type=float, default=3.0)
    args = ap.parse_args()

    pkl = args.run_dir
    if os.path.isdir(pkl):
        pkl = os.path.join(pkl, 'result.pkl')
    r = pickle.load(open(pkl, 'rb'))

    names = r.get('part_names') or []
    nparts = len(names) or 11
    pname = names[args.part] if args.part < len(names) else '?'

    final = r.get('per_part_boundaries')
    fb = []
    if final is not None:
        sl, _ = part_slice(final, args.part, nparts)
        if isinstance(sl, (list, tuple)) or (np is not None and hasattr(sl, 'tolist')):
            fb = [float(x) for x in sl if is_num(x)]

    print('run:  %s' % pkl)
    print('part: %d  %s   (%d final boundaries)' % (args.part, pname, len(fb)))
    print()

    for target in args.qn:
        print('=' * 74)
        print('TARGET  part %d  qn %.3f   window +/- %.2f qn'
              % (args.part, target, args.window))
        print('=' * 74)

        near = [b for b in fb if abs(b - target) <= args.window]
        if near:
            print('  FINAL: boundary present at %s' % ['%.3f' % b for b in near])
        else:
            nearest = min(fb, key=lambda b: abs(b - target)) if fb else None
            print('  FINAL: absent.  nearest %s'
                  % ('%.3f (%+.3f qn)' % (nearest, nearest - target)
                     if nearest is not None else 'n/a'))
        print()

        any_record = False
        for key in STAGE_KEYS:
            if key not in r:
                continue
            sliced, was_sliced = part_slice(r[key], args.part, nparts)
            out = []
            walk(sliced, key + ('[%d]' % args.part if was_sliced else ''),
                 target, args.window, out)
            if not out:
                continue
            any_record = True
            print('  --- %s%s ---' % (key, '' if was_sliced else '  (not part-sliced)'))
            for path, rec, hits in out[:25]:
                if not was_sliced:
                    pv = rec.get('part', rec.get('part_index'))
                    if pv is not None and int(pv) != args.part:
                        continue
                print('    %s' % path)
                print('        %s' % fmt(rec))
            print()

        if not any_record:
            print('  NO RECORD in any stage log.')
            print('  -> §1 invariant violation: a boundary vanished without a trace.')
            print()

    print('=' * 74)
    print('stage keys present: %s'
          % ', '.join(k for k in STAGE_KEYS if k in r))
    print('=' * 74)
    return 0


if __name__ == '__main__':
    sys.exit(main())
