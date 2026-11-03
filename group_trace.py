#!/usr/bin/env python3
"""
group_trace.py -- replay detect_boundaries' transitive peak grouping from a
result.pkl, offline, with no pipeline change.

Uses the exact arrays the pipeline stored in per_part_candidate_diagnostics
(candidate_signal, selection_score, acceptance_score, forbidden_mask) and the
parameters block (candidate_height, selection_accept_height,
peak_distance_frames). Mirrors detect_boundaries() in sectioning_v2_10_F1c.py.

Usage:
    python group_trace.py RUN_DIR --verify
    python group_trace.py RUN_DIR PART QN            # the group containing QN
    python group_trace.py RUN_DIR PART QN --vs OTHER_RUN_DIR
"""
import argparse
import os
import pickle
import sys

import numpy as np
from scipy.signal import find_peaks


def load(run_dir):
    with open(os.path.join(run_dir, 'result.pkl'), 'rb') as f:
        return pickle.load(f)


def groups_for_part(r, i):
    """Return list of groups; each group is a list of dicts, winner flagged."""
    p = r['parameters']
    d = r['per_part_candidate_diagnostics'][i]
    if not d or d.get('candidate_signal') is None:
        return []
    tg = r['time_grid']
    cand, sel = d['candidate_signal'], d['selection_score']
    acc, forb = d['acceptance_score'], d['forbidden_mask']
    peaks, _ = find_peaks(cand, height=p['candidate_height'])
    peaks = [int(x) for x in peaks if forb[x] <= 0]
    dist = p['peak_distance_frames']
    out, g = [], []
    for x in peaks:
        if g and x - g[-1] > dist:
            out.append(g)
            g = []
        g.append(x)
    if g:
        out.append(g)
    res = []
    for g in out:
        best = max(g, key=lambda k: sel[k])
        accepted = acc[best] >= p['selection_accept_height']
        res.append([{'qn': float(tg[k]), 'cand': float(cand[k]),
                     'sel': float(sel[k]), 'acc': float(acc[k]),
                     'winner': k == best, 'accepted': accepted and k == best}
                    for k in g])
    return res


def winners(r, i):
    return [m['qn'] for g in groups_for_part(r, i) for m in g if m['accepted']]


def verify(r):
    """winners -> minus short-phrase removals -> E0b shifts must equal the set
    of boundaries that reached validation (kept + rejected)."""
    ok = True
    nparts = len(r['per_part_candidate_diagnostics'])
    e0b = r['e0b_shift_info']
    e_idx = 0
    for i in range(nparts):
        if r['is_tacet'][i]:
            continue
        w = winners(r, i)
        removed = {round(x['time_quarter_notes'], 4)
                   for x in r['short_phrase_filter_info'][i]}
        pre = [b for b in w if round(b, 4) not in removed]
        shifts = {round(s['from'], 4): s['to'] for s in e0b[e_idx]}
        e_idx += 1
        post = sorted({round(shifts.get(round(b, 4), b), 4) for b in pre})
        seen = sorted({round(t['boundary_time'], 4)
                       for t in r['boundary_target_info'][i]})
        match = post == seen
        ok &= match
        print('part %2d %-20s winners %3d  removed %2d  -> %3d   validated %3d  %s'
              % (i, r['part_names'][i][:20], len(w), len(w) - len(pre),
                 len(post), len(seen), 'OK' if match else 'MISMATCH'))
        if not match:
            print('    only replay:', sorted(set(post) - set(seen)))
            print('    only pipeline:', sorted(set(seen) - set(post)))
    return ok


def show(r, i, qn, label):
    for g in groups_for_part(r, i):
        if g[0]['qn'] - 0.01 <= qn <= g[-1]['qn'] + 0.01:
            print('%s: part %d group %.2f .. %.2f qn, %d peaks'
                  % (label, i, g[0]['qn'], g[-1]['qn'], len(g)))
            for m in g:
                tag = ('WINNER%s' % ('' if m['accepted'] else ' (rejected <acc)')
                       if m['winner'] else '')
                print('   %8.3f  cand %.3f  sel %.3f  acc %.3f  %s'
                      % (m['qn'], m['cand'], m['sel'], m['acc'], tag))
            return
    print('%s: no candidate peak group spans qn %.3f in part %d' % (label, qn, i))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('part', type=int, nargs='?')
    ap.add_argument('qn', type=float, nargs='?')
    ap.add_argument('--vs', help='second run dir to compare the same point')
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()
    r = load(a.run_dir)
    if a.verify:
        sys.exit(0 if verify(r) else 1)
    show(r, a.part, a.qn, os.path.basename(a.run_dir.rstrip('/')))
    if a.vs:
        show(load(a.vs), a.part, a.qn, os.path.basename(a.vs.rstrip('/')))


if __name__ == '__main__':
    main()
