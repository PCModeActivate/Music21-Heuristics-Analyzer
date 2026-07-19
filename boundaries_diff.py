#!/usr/bin/env python
"""
boundaries_diff.py -- compare two boundaries.json outputs.

v2 (2026-07-19): parameter check ignores ephemeral all_knobs keys and
skips GT reference files ('gt': True); measure/beat display is built
from the JSON files' own measure/beat fields (18/4 m.93 correct).

Answers "what did this change actually do?" after any pipeline commit:
per part, lists boundaries that were ADDED, REMOVED, or MOVED (paired
within a tolerance), plus a one-line count summary.

Usage:
    python boundaries_diff.py OLD/boundaries.json NEW/boundaries.json
    python boundaries_diff.py OLD/boundaries.json NEW/boundaries.json \
        --tolerance 1.0        # pair boundaries within 1.0 qn as "moved"
    python boundaries_diff.py OLD.json NEW.json --part 5   # one part only

Pairing: per part, old and new boundary lists are matched greedily by
smallest time distance; pairs within --tolerance count as MOVED (or
UNCHANGED if the distance is 0), leftovers are REMOVED/ADDED. Parts are
matched by index; a name mismatch at the same index is warned about.

Read-only. Exit code 0 if identical, 1 if any difference (usable in
scripts: run defaults, diff against the previous commit's output,
expect exit 0 for pure-diagnostic changes).
"""

import argparse
import json
import sys


def load(path):
    with open(path) as f:
        data = json.load(f)
    parts = {}
    for p in data.get('per_part', []):
        times = [b['time_quarter_notes'] for b in p.get('boundaries', [])]
        parts[p['index']] = {
            'name': p.get('name', 'part%d' % p['index']),
            'times': sorted(times),
        }
    return parts


_MB_STARTS = []   # [(start_qn, measure_number)], built from the inputs


def build_mb_map(*json_paths):
    """Harvest (measure -> start_qn) from boundary entries that carry
    numeric measure/beat fields. Barline instants are recorded as
    next-measure b1 by the pipeline, so they contribute exact starts."""
    starts = {}
    for path in json_paths:
        try:
            data = json.load(open(path))
        except Exception:
            continue
        for p in data.get('per_part', []):
            for b in p.get('boundaries', []):
                m, bt, t = b.get('measure'), b.get('beat'), \
                    b.get('time_quarter_notes')
                if isinstance(m, int) and isinstance(bt, (int, float)) \
                        and t is not None:
                    starts.setdefault(m, round(float(t) - (float(bt) - 1.0), 6))
    _MB_STARTS[:] = sorted((s, m) for m, s in starts.items())


def qn_to_mb(qn):
    """Display via the harvested measure map; 4/4 fallback for gaps.
    Barline instants render as 'm.N end' (project convention)."""
    if not _MB_STARTS:
        m = int(qn // 4) + 1
        return 'm.%d b%.3g' % (m, (qn % 4) + 1)
    prev = None
    for s, m in _MB_STARTS:
        if s > qn + 1e-6:
            break
        if abs(qn - s) <= 1e-6 and m > _MB_STARTS[0][1]:
            return 'm.%d end' % (m - 1)
        prev = (s, m)
    if prev is None:
        m = int(qn // 4) + 1
        return 'm.%d b%.3g' % (m, (qn % 4) + 1)
    s, m = prev
    off = qn - s
    nxt = next((sn for sn, _ in _MB_STARTS if sn > s + 1e-6), None)
    if nxt is None and off >= 4.0:
        # beyond the last harvested measure start: extrapolate 4/4
        skip = int(off // 4.0)
        m += skip
        off -= 4.0 * skip
    # if nxt exists, qn < nxt lies inside measure m's real span
    # (covers the 18/4 m.93 correctly: beats run 1..18)
    return 'm.%d b%.3g' % (m, off + 1.0)


def pair_greedy(old, new, tol):
    """Greedy nearest-distance pairing. Returns (pairs, removed, added):
    pairs = [(o, n)] with |o-n| <= tol."""
    old = list(old)
    new = list(new)
    cand = []
    for oi, o in enumerate(old):
        for ni, n in enumerate(new):
            d = abs(o - n)
            if d <= tol:
                cand.append((d, oi, ni))
    cand.sort()
    used_o, used_n, pairs = set(), set(), []
    for d, oi, ni in cand:
        if oi in used_o or ni in used_n:
            continue
        used_o.add(oi)
        used_n.add(ni)
        pairs.append((old[oi], new[ni]))
    removed = [o for i, o in enumerate(old) if i not in used_o]
    added = [n for i, n in enumerate(new) if i not in used_n]
    return pairs, removed, added

_EPHEMERAL_KNOBS = {'annotated_path', 'plot_path', 'output_dir', 'i',
                    'marker', 'n_flagged', 'n_hp', 'n_nat_ties',
                    'n_phrase', 'n_struct', 'n_tie_like', 'n_tuplets'}


def diff_parameters(old_json, new_json):
    po = json.load(open(old_json)).get('parameters', {})
    pn = json.load(open(new_json)).get('parameters', {})
    if po.get('gt') is True or pn.get('gt') is True:
        print('(GT reference file: parameter comparison skipped)')
        print()
        return False
    for _d in (po, pn):
        _ak = _d.get('all_knobs')
        if isinstance(_ak, dict):
            for _k in _EPHEMERAL_KNOBS:
                _ak.pop(_k, None)
    keys = sorted(set(po) | set(pn))
    diffs = [(k, po.get(k, '<absent>'), pn.get(k, '<absent>'))
             for k in keys if po.get(k) != pn.get(k)]
    if diffs:
        print('PARAMETER DIFFERENCES (runs are NOT apples-to-apples):')
        for k, a, b in diffs:
            print('  %s: %r -> %r' % (k, a, b))
        print()
    return bool(diffs)

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('old_json')
    ap.add_argument('new_json')
    ap.add_argument('--tolerance', type=float, default=1.0,
                    help='Max qn distance to pair old/new boundaries as '
                         'the "same, moved" (default 1.0)')
    ap.add_argument('--part', type=int, default=None,
                    help='Restrict to one part index')
    args = ap.parse_args()
    build_mb_map(args.old_json, args.new_json)
    diff_parameters(args.old_json, args.new_json)

    old = load(args.old_json)
    new = load(args.new_json)

    indices = sorted(set(old) | set(new))
    if args.part is not None:
        indices = [i for i in indices if i == args.part]

    tot_add = tot_rem = tot_mov = tot_same = 0
    any_diff = False

    for i in indices:
        o = old.get(i, {'name': '?', 'times': []})
        n = new.get(i, {'name': '?', 'times': []})
        name = n['name'] if i in new else o['name']
        if i in old and i in new and o['name'] != n['name']:
            print('WARNING: part %d name mismatch: %r vs %r'
                  % (i, o['name'], n['name']))

        pairs, removed, added = pair_greedy(o['times'], n['times'],
                                            args.tolerance)
        moved = [(a, b) for a, b in pairs if abs(a - b) > 1e-9]
        same = len(pairs) - len(moved)
        tot_add += len(added)
        tot_rem += len(removed)
        tot_mov += len(moved)
        tot_same += same

        if not (added or removed or moved):
            continue
        any_diff = True
        print('=== part %d %s: %d -> %d boundaries '
              '(%d unchanged, %d moved, %d removed, %d added) ==='
              % (i, name, len(o['times']), len(n['times']),
                 same, len(moved), len(removed), len(added)))
        for a, b in sorted(moved):
            print('  MOVED   qn %8.3f -> %8.3f  (%+.3f qn)   %s -> %s'
                  % (a, b, b - a, qn_to_mb(a), qn_to_mb(b)))
        for a in sorted(removed):
            print('  REMOVED qn %8.3f                        %s'
                  % (a, qn_to_mb(a)))
        for b in sorted(added):
            print('  ADDED   qn %8.3f                        %s'
                  % (b, qn_to_mb(b)))

    print()
    print('TOTAL: %d unchanged, %d moved, %d removed, %d added '
          '(pair tolerance %.2f qn)'
          % (tot_same, tot_mov, tot_rem, tot_add, args.tolerance))
    sys.exit(1 if any_diff else 0)


if __name__ == '__main__':
    main()
