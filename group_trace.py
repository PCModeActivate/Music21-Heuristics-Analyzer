#!/usr/bin/env python3
"""
group_trace.py -- replay detect_boundaries' transitive peak grouping from a
result.pkl, offline, with no pipeline change.

Handles parameters['peak_grouping'] in {transitive, nms} (v2.11-A).
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


def nms_groups(peaks, sel, acc, dist, acc_h):
    """Mirror of detect_boundaries' 'nms' mode (v2.11-A), expressed as groups:
    each accepted peak heads a group holding the peaks it suppressed; a peak
    failing the gate is its own unaccepted group. Returns (members, best,
    accepted) triples."""
    order = sorted(peaks, key=lambda k: (-float(sel[k]), k))
    chosen, owner, rejected = [], {}, []
    for p in order:
        if acc[p] < acc_h:
            rejected.append(p)
            continue
        sup = next((c for c in chosen if abs(p - c) <= dist), None)
        if sup is None:
            chosen.append(p)
            owner[p] = [p]
        else:
            owner[sup].append(p)
    out = [(sorted(owner[c]), c, True) for c in chosen]
    out += [([p], p, False) for p in rejected]
    return sorted(out, key=lambda t: t[0][0])


def soft_groups(peaks, sel, acc, dist, acc_h, power):
    """Mirror of detect_boundaries' 'soft' mode (v2.11-A). Each accepted peak
    heads a group holding the not-accepted peaks nearest to it; peaks that
    never clear the gate after penalties are reported in those groups."""
    cand = list(peaks)
    fac = {p: 1.0 for p in cand}
    chosen = []
    while True:
        alive = [p for p in cand if p not in chosen and acc[p] * fac[p] >= acc_h]
        if not alive:
            break
        p = max(alive, key=lambda k: (float(sel[k]) * fac[k], -k))
        chosen.append(p)
        for q in cand:
            if q not in chosen and abs(q - p) < dist:
                fac[q] *= (abs(q - p) / float(dist)) ** power
    if not chosen:
        return [([p], p, False) for p in cand]
    owner = {c: [c] for c in chosen}
    lone = []
    for q in cand:
        if q in owner:
            continue
        near = min(chosen, key=lambda c: abs(c - q))
        if abs(near - q) < dist:
            owner[near].append(q)
        else:
            lone.append(q)
    out = [(sorted(v), c, True) for c, v in owner.items()]
    out += [([q], q, False) for q in lone]
    return sorted(out, key=lambda t: t[0][0])


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
    mode = p.get('peak_grouping', 'transitive')
    if mode in ('nms', 'soft'):
        res = []
        fn = (nms_groups(peaks, sel, acc, dist, p['selection_accept_height'])
              if mode == 'nms' else
              soft_groups(peaks, sel, acc, dist, p['selection_accept_height'],
                          p.get('soft_power', 1.0)))
        for members, best, accepted in fn:
            res.append([{'qn': float(tg[k]), 'cand': float(cand[k]),
                         'sel': float(sel[k]), 'acc': float(acc[k]),
                         'winner': k == best, 'accepted': accepted and k == best}
                        for k in members])
        return res
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
        shifts = {round(s['from'], 4): s['to'] for s in e0b[e_idx]}
        e_idx += 1
        if r['parameters'].get('filter_after_anchor'):
            # v2.11-A order: anchor, then filter (removal times are anchored)
            anchored = {round(shifts.get(round(b, 4), b), 4) for b in w}
            pre = w
            post = sorted(b for b in anchored if b not in removed)
        else:
            pre = [b for b in w if round(b, 4) not in removed]
            post = sorted({round(shifts.get(round(b, 4), b), 4) for b in pre})
        for ch in (r.get('ensemble_info') or [[]] * (i + 1))[i]:
            if ch['from'] is not None:
                post = [b for b in post if abs(b - ch['from']) > 1e-3]
            post = sorted(set(post) | {round(ch['to'], 4)})
        seen = sorted({round(t['boundary_time'], 4)
                       for t in r['boundary_target_info'][i]})
        match = post == seen
        ok &= match
        print('part %2d %-20s winners %3d  removed %2d  -> %3d   validated %3d  %s'
              % (i, r['part_names'][i][:20], len(w), len(removed),
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
