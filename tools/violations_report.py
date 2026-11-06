#!/usr/bin/env python3
"""
violations_report.py -- every objectionable breath in a run, in musician terms.

Objectionable = required GT breath missed + banned position hit + reviewer
objection hit (the same count score_run.py prints). For each one this lists
the part, where the breath belongs or sits ("m.53 end" = after the last note
of m.53), the note that carries / should carry the comma, what the run did
instead (nearest boundary in that part), and the stage that caused it
(fail_trace.py labels). Required misses that belong to a close GT pair
(another GT breath in the same part <= 4 qn away) are flagged: those are the
cases spacing rules cannot both keep.

Usage:
    python violations_report.py RUN_DIR [--md OUT.md]
        [--audit audit_cases_gt_v2_2026-09-02.json]
        [--musicxml gt_rendered.musicxml]
        [--objections review/objections_2026-11-03.json]
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fail_trace as _ft          # noqa: E402
from review_list import comma_on  # noqa: E402

FAIL_RE = re.compile(r'^\s+FAIL p\s*(\d+)\s+(.*?)\s+target qn\s+([\d.]+)\s+\((.*?)\)\s+expect=(present|absent)')
RUN_RE = re.compile(r'^\s+run:\s+(\S+)\s+nearest qn\s+([\d.]+)\s+\((.*?)\)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--md', default=None, help='also write a Markdown report here')
    ap.add_argument('--audit', default=os.path.join(HERE, 'audit_cases_gt_v2_2026-09-02.json'))
    ap.add_argument('--musicxml', default=os.path.join(HERE, 'gt_rendered.musicxml'))
    ap.add_argument('--objections', default=os.path.join(HERE, 'review', 'objections_2026-11-03.json'))
    ap.add_argument('--gt', default=os.path.join(HERE, 'gt_boundaries_v2.json'))
    a = ap.parse_args()

    bj = os.path.join(a.run_dir, 'boundaries.json')
    out = subprocess.run([sys.executable, os.path.join(HERE, 'audit_check.py'), bj,
                          '--audit', a.audit, '--musicxml', a.musicxml, '--fails-only'],
                         capture_output=True, text=True).stdout
    r = _ft.load(a.run_dir)
    names = r['part_names']
    G = {p['index']: sorted(float(x['time_quarter_notes']) for x in p['boundaries'])
         for p in json.load(open(a.gt))['per_part']}
    R = {p['index']: sorted(float(x['time_quarter_notes']) for x in p['boundaries'])
         for p in json.load(open(bj))['per_part']}

    req, ban = [], []
    lines = out.splitlines()
    for k, line in enumerate(lines):
        m = FAIL_RE.match(line)
        if not m:
            continue
        i, q, where, expect = int(m.group(1)), float(m.group(3)), m.group(4), m.group(5)
        nearest = ''
        if k + 1 < len(lines):
            mr = RUN_RE.match(lines[k + 1])
            if mr:
                nq = float(mr.group(2))
                nearest = '%s (%+.2f qn)' % (mr.group(3), nq - q)
            elif 'run:      none' in lines[k + 1] or 'none' in lines[k + 1]:
                nearest = 'none in part'
        if expect == 'present':
            cls, det = _ft.trace_required(r, i, q)
            close = [g for g in G.get(i, []) if 0 < abs(g - q) <= 4 + 1e-6]
            req.append(dict(part=i, name=names[i], qn=q, where=where,
                            should=comma_on(a.run_dir, i, q), nearest=nearest,
                            cause=cls, detail=det,
                            close=', '.join('%+.0f' % (g - q) for g in close)))
        else:
            cls, det = _ft.trace_banned(r, i, q)
            ban.append(dict(part=i, name=names[i], qn=q, where=where,
                            comma=comma_on(a.run_dir, i, q), cause=det))

    obj = []
    accepted = []
    if a.objections and os.path.exists(a.objections):
        accepted = [(o['part'], float(o['qn'])) for o in json.load(open(a.objections)).get('accepted', [])]
    n_acc = sum(1 for x in ban if any(x['part'] == ai and abs(x['qn'] - aq) <= 0.1 for ai, aq in accepted))
    ban = [x for x in ban if not any(x['part'] == ai and abs(x['qn'] - aq) <= 0.1 for ai, aq in accepted)]
    if a.objections and os.path.exists(a.objections):
        for o in json.load(open(a.objections))['objections']:
            if any(abs(b - o['qn']) <= 0.1 for b in R.get(o['part'], [])):
                obj.append(dict(part=o['part'], name=names[o['part']], qn=o['qn'],
                                where=o['instant'], comma=comma_on(a.run_dir, o['part'], o['qn']),
                                note=o['note']))

    md = []
    md.append('# Objectionable breaths in `%s`\n' % a.run_dir)
    md.append('%d total = %d required missed + %d banned hit + %d objected.\n'
              % (len(req) + len(ban) + len(obj), len(req), len(ban), len(obj)))
    md.append('"m.N end" is after the last note of m.N. "comma on" is the note that carries '
              '(or should carry) the comma.\n')
    md.append('## Required breaths missed (%d)\n' % len(req))
    md.append('| part | breath belongs at | comma should be on | run has instead | cause | close GT pair |')
    md.append('|---|---|---|---|---|---|')
    for x in sorted(req, key=lambda x: (x['part'], x['qn'])):
        md.append('| %s (%d) | %s | %s | %s | %s: %s | %s |' % (
            x['name'], x['part'], x['where'], x['should'], x['nearest'],
            x['cause'], x['detail'].replace('|', '/'), x['close'] or ''))
    md.append('\n## Banned positions hit (%d; %d more on reviewer-accepted positions not listed)\n' % (len(ban), n_acc))
    md.append('| part | breath at | comma on | how it got there |')
    md.append('|---|---|---|---|')
    for x in sorted(ban, key=lambda x: (x['part'], x['qn'])):
        md.append('| %s (%d) | %s | %s | %s |' % (x['name'], x['part'], x['where'], x['comma'], x['cause']))
    md.append('\n## Reviewer objections hit (%d)\n' % len(obj))
    md.append('| part | breath at | comma on | verdict |')
    md.append('|---|---|---|---|')
    for x in sorted(obj, key=lambda x: (x['part'], x['qn'])):
        md.append('| %s (%d) | %s | %s | %s |' % (x['name'], x['part'], x['where'], x['comma'], x['note']))
    text = '\n'.join(md) + '\n'
    print(text)
    if a.md:
        open(a.md, 'w', encoding='utf-8').write(text)


if __name__ == '__main__':
    main()
