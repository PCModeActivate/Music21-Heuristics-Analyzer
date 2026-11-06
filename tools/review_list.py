#!/usr/bin/env python3
"""
review_list.py -- list the breaths a run adds that no GT pass has reviewed.

A boundary in NEW_RUN is listed when it is not a GT point, not a banned
position (removed_points), and not present in BASE_RUN. Such positions have
never been in front of the GT author, so neither the exact-match score nor
the audit can say whether they are acceptable. Output is a Markdown table
with an empty ok/no column to fill in.

Usage:
    python review_list.py BASE_RUN NEW_RUN [--title T] > review/NAME.md
        [--gt gt_boundaries_v2.json] [--gt_full gt_liz_v2_2026-09-02.json]
"""
import argparse
import json
import os
import pickle

HERE = os.path.dirname(os.path.abspath(__file__))
TOL = 0.1


def by_part(path):
    return {p['index']: p for p in json.load(open(path))['per_part']}


def times(p):
    return [float(x['time_quarter_notes']) for x in p['boundaries']]


def rest_after(run_dir, i, t):
    """qn of silence after t in part i (0 when the next note starts at t)."""
    try:
        r = pickle.load(open(os.path.join(run_dir, 'result.pkl'), 'rb'))
    except Exception:
        return None
    nxt = [n['offset'] for n in r['notes_per_part'][i] if n['offset'] >= t - 0.02]
    sounding = [n for n in r['notes_per_part'][i]
                if n['offset'] <= t + 0.02 < n['offset'] + n['duration']]
    if sounding:
        return 0.0
    return (min(nxt) - t) if nxt else None


def comma_on(run_dir, i, t):
    """'m.M bB PITCH' of the note releasing at t (the note carrying the
    comma), from result.pkl's merged notes and measure_offsets."""
    try:
        r = pickle.load(open(os.path.join(run_dir, 'result.pkl'), 'rb'))
    except Exception:
        return '?'
    mo = [(float(o), m) for o, m in r.get('measure_offsets', [])]
    cands = [n for n in r['notes_per_part'][i]
             if abs(n['offset'] + n['duration'] - t) <= 0.02]
    if not cands or not mo:
        return '(no note releases here)'
    n = cands[0]
    on = float(n['offset'])
    base, num = max((x for x in mo if x[0] <= on + 1e-6), key=lambda x: x[0])
    names = 'C C# D E- E F F# G G# A B- B'.split()
    p = n.get('pitch')
    pitch = ('%s%d' % (names[int(p) % 12], int(p) // 12 - 1)) if isinstance(p, (int, float)) else str(p)
    return 'm.%d b%g %s' % (num, round(on - base + 1, 3), pitch)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_run')
    ap.add_argument('new_run')
    ap.add_argument('--title', default=None)
    ap.add_argument('--gt', default=os.path.join(HERE, 'gt_boundaries_v2.json'))
    ap.add_argument('--gt_full', default=os.path.join(HERE, 'gt_liz_v2_2026-09-02.json'))
    a = ap.parse_args()
    G = {i: times(p) for i, p in by_part(a.gt).items()}
    L = {p['index']: [float(x['time_quarter_notes']) for x in p.get('removed_points', [])]
         for p in json.load(open(a.gt_full))['per_part']}
    base = {i: times(p) for i, p in by_part(os.path.join(a.base_run, 'boundaries.json')).items()}
    new = by_part(os.path.join(a.new_run, 'boundaries.json'))
    print('# %s\n' % (a.title or 'Review: unreviewed breaths in %s' % a.new_run))
    print('Base: `%s`  \nNew: `%s`\n' % (a.base_run, a.new_run))
    print('Listed: boundaries in the new run that are not GT, not banned, and not in the base run. '
          '"position" is the boundary instant (m.N b1 = after the last note of m.N-1); '
          '"comma on note" is the note carrying the comma in the rendered score. '
          'Mark only the objectionable ones **no**; the rest pass.\n')
    print('| part | instrument | position | qn | rest after (qn) | comma on note | ok / no |')
    print('|---|---|---|---|---|---|---|')
    n = 0
    for i in sorted(new):
        p = new[i]
        for x in p['boundaries']:
            t = float(x['time_quarter_notes'])
            if (any(abs(t - g) <= TOL for g in G.get(i, [])) or
                    any(abs(t - q) <= TOL for q in L.get(i, [])) or
                    any(abs(t - b) <= TOL for b in base.get(i, []))):
                continue
            ra = rest_after(a.new_run, i, t)
            n += 1
            print('| %d | %s | m.%s b%s | %.3f | %s | %s | |' % (
                i, p['name'], x['measure'], x['beat'], t,
                '-' if ra is None else '%.2f' % ra, comma_on(a.new_run, i, t)))
    print('\n%d positions.' % n)


if __name__ == '__main__':
    main()
