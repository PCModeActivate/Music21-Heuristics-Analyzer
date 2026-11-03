#!/usr/bin/env python3
"""
fail_trace.py -- attribute every audit FAIL to the pipeline stage that caused it.

Reads audit_check.py's own --fails-only output (so measure/beat -> qn conversion
is audit_check's, not re-derived here) and the run's result.pkl, then follows
each failing point through the stages in pipeline order:

    candidate peaks -> transitive grouping -> acceptance gate
      -> short-phrase filter -> E0b release anchoring -> validation

Required miss (expect=present) at GT time g, part i. Candidate positions that
could land on g are g itself, plus any frame inside the note(s) whose release
is g (E0b moves an onset or mid-note boundary to the note's release). Each
miss gets the FIRST stage at which the best such candidate was lost:

  NEAR_MISS        a final boundary exists within 1.5 qn (reported with offset)
  FILTER           a winner mapping to g was removed by the short-phrase filter
  VALIDATION       a boundary reached g but validation rejected it
  NOT_SHIFTED      a winner sits at the note onset but E0b did not move it to g
  SHIFTED_AWAY     a winner sat exactly on g and E0b moved it off
  GROUP_LOST       a peak mapping to g lost its group to another peak
  GATE             it won its group but acceptance < selection_accept_height
  FORBIDDEN        frames mapping to g are hard-forbidden (tie masks)
  WEAK             no candidate peak >= candidate_height maps to g

Banned hit (expect=absent) at time h: reports which winner produced it and by
which path (direct, or E0b shift reason).

Schema is checked on load; a missing key aborts with the key name.

Usage:
    python audit_check.py RUN/boundaries.json --audit AUDIT --musicxml gt_rendered.musicxml --fails-only > fails.txt
    python fail_trace.py RUN fails.txt [--summary]
"""
import argparse
import collections
import os
import pickle
import re
import sys

import numpy as np
from scipy.signal import find_peaks

EPS = 0.02
NEAR = 1.5

REQUIRED_KEYS = ('parameters', 'per_part_candidate_diagnostics', 'time_grid',
                 'short_phrase_filter_info', 'e0b_shift_info',
                 'boundary_target_info', 'per_part_boundaries',
                 'notes_per_part', 'is_tacet', 'part_names')

FAIL_RE = re.compile(r'^\s+FAIL p\s*(\d+)\s+.*?target qn\s+([\d.]+)\s+\((.*?)\)\s+expect=(present|absent)')


def load(run_dir):
    with open(os.path.join(run_dir, 'result.pkl'), 'rb') as f:
        r = pickle.load(f)
    missing = [k for k in REQUIRED_KEYS if k not in r]
    if missing:
        sys.exit('result.pkl missing keys: %s' % missing)
    return r


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


def part_groups(r, i):
    p = r['parameters']
    d = r['per_part_candidate_diagnostics'][i]
    cand, sel = d['candidate_signal'], d['selection_score']
    acc, forb = d['acceptance_score'], d['forbidden_mask']
    peaks, _ = find_peaks(cand, height=p['candidate_height'])
    peaks = [int(x) for x in peaks if forb[x] <= 0]
    if p.get('peak_grouping', 'transitive') == 'nms':
        return nms_groups(peaks, sel, acc, p['peak_distance_frames'],
                          p['selection_accept_height'])
    groups, g = [], []
    for x in peaks:
        if g and x - g[-1] > p['peak_distance_frames']:
            groups.append(g)
            g = []
        g.append(x)
    if g:
        groups.append(g)
    out = []
    for g in groups:
        best = max(g, key=lambda k: sel[k])
        out.append((g, best, acc[best] >= p['selection_accept_height']))
    return out


def e0b_index(r, i):
    return sum(1 for j in range(i) if not r['is_tacet'][j])


def releases(notes):
    return [(n['offset'], n['offset'] + n['duration']) for n in notes]


def frames_mapping_to(r, i, g):
    """Frame indices whose boundary would be anchored onto g: g itself and the
    span [onset, g) of any note releasing at g."""
    D = r['parameters']['division']
    fs = {int(round(g * D))}
    for on, rel in releases(r['notes_per_part'][i]):
        if abs(rel - g) <= EPS:
            fs.update(range(int(round(on * D)), int(round(g * D)) + 1))
    return fs


def trace_required(r, i, g):
    D = r['parameters']['division']
    tg = r['time_grid']
    final = [float(b) for b in r['per_part_boundaries'][i]]
    near = [b for b in final if abs(b - g) <= NEAR]
    removed = {round(x['time_quarter_notes'], 4): x for x in r['short_phrase_filter_info'][i]}
    shifts = {round(s['from'], 4): s for s in r['e0b_shift_info'][e0b_index(r, i)]}
    rejects = [t for t in r['boundary_target_info'][i] if not t.get('kept', True)]
    fs = frames_mapping_to(r, i, g)
    groups = part_groups(r, i)
    d = r['per_part_candidate_diagnostics'][i]

    # rejected at validation exactly at g
    for t in rejects:
        if abs(t['boundary_time'] - g) <= EPS:
            return 'VALIDATION', 'rejected: %s' % t.get('reject_reason')

    lost_detail = None
    gate_detail = None
    for members, best, accepted in groups:
        hits = [m for m in members if m in fs]
        if not hits:
            continue
        if best in fs:
            if not accepted:
                gate_detail = 'won group, acc %.3f < gate' % d['acceptance_score'][best]
                continue
            q = round(float(tg[best]), 4)
            if q in removed:
                x = removed[q]
                return 'FILTER', ('winner %.3f removed (segment %.3f..%.3f, %s side, %d notes, %.2fs sounding)'
                                  % (q, x['segment_start_qn'], x['segment_end_qn'],
                                     x['removed_side'], x['note_count'], x['sounding_seconds']))
            s = shifts.get(q)
            landed = s['to'] if s else q
            if abs(landed - g) > EPS:
                if abs(q - g) <= EPS:
                    return 'SHIFTED_AWAY', 'winner at g moved by E0b %s to %.3f' % (s['reason'], landed)
                return 'NOT_SHIFTED', 'winner %.3f stayed/landed at %.3f' % (q, landed)
            # it landed on g but is not final: dedup or later stage
            return 'VALIDATION', 'landed on g but absent from final (merged or snapped)'
        h = max(hits, key=lambda k: d['selection_score'][k])
        lost_detail = ('peak %.3f sel %.3f lost to %.3f sel %.3f (group %.2f..%.2f, %d peaks)'
                       % (tg[h], d['selection_score'][h], tg[best], d['selection_score'][best],
                          tg[members[0]], tg[members[-1]], len(members)))
    if near:
        b = min(near, key=lambda x: abs(x - g))
        extra = ''
        if lost_detail:
            extra = '; ' + lost_detail
        return 'NEAR_MISS', 'final boundary at %.3f (%+.3f)%s' % (b, b - g, extra)
    if lost_detail:
        return 'GROUP_LOST', lost_detail
    if gate_detail:
        return 'GATE', gate_detail
    forb = [f for f in fs if 0 <= f < len(d['forbidden_mask']) and d['forbidden_mask'][f] > 0]
    if forb and int(round(g * D)) in forb:
        return 'FORBIDDEN', 'forbidden at g (tie mask); max cand over mapping frames %.3f' % max(
            d['candidate_signal'][f] for f in fs if 0 <= f < len(d['candidate_signal']))
    mx = max(fs, key=lambda f: d['candidate_signal'][f] if 0 <= f < len(d['candidate_signal']) else -1)
    return 'WEAK', 'best cand %.3f at %.3f (height %.2f)%s' % (
        d['candidate_signal'][mx], tg[mx], r['parameters']['candidate_height'],
        '; some mapping frames forbidden' if forb else '')


def trace_banned(r, i, h):
    shifts = r['e0b_shift_info'][e0b_index(r, i)]
    for s in shifts:
        if abs(s['to'] - h) <= EPS and abs(s['from'] - h) > EPS:
            return 'BANNED_HIT', 'E0b %s from %.3f' % (s['reason'], s['from'])
    return 'BANNED_HIT', 'direct winner'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('fails')
    ap.add_argument('--summary', action='store_true')
    a = ap.parse_args()
    r = load(a.run_dir)
    rows = []
    for line in open(a.fails, encoding='utf-8'):
        m = FAIL_RE.match(line)
        if not m:
            continue
        i, q, mb, expect = int(m.group(1)), float(m.group(2)), m.group(3), m.group(4)
        if expect == 'present':
            cls, det = trace_required(r, i, q)
        else:
            cls, det = trace_banned(r, i, q)
        rows.append((cls, i, q, mb, det))
    for cls, i, q, mb, det in sorted(rows, key=lambda x: (x[0], x[1], x[2])):
        print('%-11s p%-2d %-16s %8.3f  %s' % (cls, i, r['part_names'][i][:16], q, mb), '|', det)
    c = collections.Counter(x[0] for x in rows)
    print('\nSUMMARY:', ', '.join('%s %d' % kv for kv in c.most_common()), '| total', len(rows))


if __name__ == '__main__':
    main()
