#!/usr/bin/env python3
"""
history_check.py -- what every GT and audit file in the repo ever said about
a set of positions.

The current GT and its bans are not the only record of musical judgement:
older GT compilations (gt_liz_2026-07-10.json, gt_liz_v2_2026-07-15.json) and
the audit-case files (full, review, v2, gt_v2 07-19 / 09-02) hold earlier
rulings, removals and complaints. This walks every one of them generically
(any dict carrying time_quarter_notes, or measure + beat), takes the part
index from the record or its nearest enclosing record, converts measure/beat
with audit_check's own measure_map, and reports every record within --tol of
each queried position.

Note: ALGORITHM.md 23 says GT v2 supersedes the per-case rulings of the
deprecated audit files. Older records are evidence about a position, not the
ruling.

Usage:
    python history_check.py review/v2_11_A_candidate_vs_C1.md [--tol 0.1] [--near 0.5]
    (any Markdown table whose rows start "| part | instrument | position | qn |")
"""
import argparse
import glob
import json
import os
import re

import measure_map as _mm

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = sorted(set(glob.glob(os.path.join(HERE, 'gt_liz*.json')) +
                   glob.glob(os.path.join(HERE, 'audit_cases*.json')) +
                   [os.path.join(HERE, 'gt_boundaries_v2.json')]))

# keys that name the bucket a record sits in
BUCKET_KEYS = ('gt_boundaries', 'removed_points', 'removed_from_run', 'boundaries',
               'diagnostic_points')


def walk(node, part=None, bucket=None, ctx=None, out=None, src=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        part = node.get('part_index', node.get('index', part))
        ctx = node if any(k in node for k in ('summary', 'id', 'expected_action')) else ctx
        qn = None
        if 'time_quarter_notes' in node:
            qn = float(node['time_quarter_notes'])
        elif 'measure' in node and 'beat' in node and node.get('measure') is not None:
            try:
                qn = float(_mm.qn_of(int(node['measure']), node['beat']))
            except Exception:
                qn = None
        if qn is not None and part is not None and bucket is not None:
            out.append({'src': src, 'part': int(part), 'qn': qn, 'bucket': bucket,
                        'status': node.get('status') or node.get('expect'),
                        'why': node.get('why') or node.get('migrate_reason'),
                        'case': (ctx or {}).get('id')})
        for k, v in node.items():
            walk(v, part, k if k in BUCKET_KEYS else bucket, ctx, out, src)
    elif isinstance(node, list):
        for v in node:
            walk(v, part, bucket, ctx, out, src)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('table')
    ap.add_argument('--tol', type=float, default=0.1)
    ap.add_argument('--near', type=float, default=0.5)
    ap.add_argument('--musicxml', default=os.path.join(HERE, 'gt_rendered.musicxml'))
    a = ap.parse_args()
    _mm.load(a.musicxml)
    recs = []
    for f in FILES:
        recs += walk(json.load(open(f)), src=os.path.basename(f))
    print('scanned %d records from %d files' % (len(recs), len(FILES)))
    rows = [l for l in open(a.table) if re.match(r'^\| \d', l)]
    n_any = 0
    for k, l in enumerate(rows, 1):
        c = [x.strip() for x in l.strip().strip('|').split('|')]
        i, q = int(c[0]), float(c[3])
        hits = sorted((r for r in recs if r['part'] == i and abs(r['qn'] - q) <= a.near),
                      key=lambda r: (abs(r['qn'] - q), r['src']))
        exact = [r for r in hits if abs(r['qn'] - q) <= a.tol]
        tag = 'EXACT' if exact else ('near' if hits else '-')
        n_any += bool(exact)
        print('\n#%-2d p%d %-16s qn %8.3f  %s' % (k, i, c[1][:16], q, tag))
        for r in hits:
            print('     %+.3f  %-34s %-17s %-9s %s%s' % (
                r['qn'] - q, r['src'], r['bucket'], r['status'] or '',
                (r['case'] + ': ') if r['case'] else '', (r['why'] or '')[:90]))
    print('\n%d of %d positions have a record within %.2f qn' % (n_any, len(rows), a.tol))


if __name__ == '__main__':
    main()
