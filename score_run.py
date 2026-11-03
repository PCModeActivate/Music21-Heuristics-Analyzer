#!/usr/bin/env python3
"""
score_run.py -- one-line scoreboard for a run, against GT v2.

  exact   GT points with a run boundary in the same part within 0.1 qn
  extras  run boundaries with no GT point within 0.1 qn (same part)
  audit   audit_check.py PASS/FAIL against the given audit file
  objectionable  required GT misses + banned hits (both from the audit) +
          hits on the reviewer's objection list (--objections). The count a
          musician would reject; extras that are merely acceptable are not in it.
  causes  fail_trace.py summary of the FAILs

Usage:
    python score_run.py RUN_DIR [RUN_DIR ...]
        [--gt gt_boundaries_v2.json]
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
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOL = 0.1


def times(part):
    return [float(x['time_quarter_notes']) for x in part['boundaries']]


def exact_extras(gt_path, run_json):
    g = json.load(open(gt_path))
    r = json.load(open(run_json))
    rp = {p['index']: times(p) for p in r['per_part']}
    gp = {p['index']: times(p) for p in g['per_part']}
    hit = tot = 0
    for i, pts in gp.items():
        rb = rp.get(i, [])
        for t in pts:
            tot += 1
            hit += any(abs(b - t) <= TOL for b in rb)
    extras = sum(1 for i, rb in rp.items() for b in rb
                 if not any(abs(b - t) <= TOL for t in gp.get(i, [])))
    nrun = sum(len(v) for v in rp.values())
    return hit, tot, extras, nrun


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--gt', default=os.path.join(HERE, 'gt_boundaries_v2.json'))
    ap.add_argument('--audit', default=os.path.join(HERE, 'audit_cases_gt_v2_2026-09-02.json'))
    ap.add_argument('--musicxml', default=os.path.join(HERE, 'gt_rendered.musicxml'))
    ap.add_argument('--objections', default=os.path.join(HERE, 'review', 'objections_2026-11-03.json'))
    a = ap.parse_args()
    objs = []
    if a.objections and os.path.exists(a.objections):
        objs = [(o['part'], float(o['qn'])) for o in json.load(open(a.objections))['objections']]
    print('%-44s %9s %6s %5s %10s %4s %5s  %s' % ('run', 'exact', 'extras', 'total',
                                                   'audit P/F', 'uni', 'objec', 'FAIL causes'))
    for run in a.runs:
        bj = os.path.join(run, 'boundaries.json')
        hit, tot, extras, nrun = exact_extras(a.gt, bj)
        out = subprocess.run([sys.executable, os.path.join(HERE, 'audit_check.py'), bj,
                              '--audit', a.audit, '--musicxml', a.musicxml, '--fails-only'],
                             capture_output=True, text=True).stdout
        m = re.search(r'TOTAL: (\d+) PASS, (\d+) FAIL.*?(\d+) unison', out)
        req_miss = len(re.findall(r'^\s+FAIL .*expect=present', out, re.M))
        ban_hit = len(re.findall(r'^\s+FAIL .*expect=absent', out, re.M))
        rj = json.load(open(bj))
        rb = {p['index']: times(p) for p in rj['per_part']}
        obj_hit = sum(1 for i, q in objs if any(abs(b - q) <= TOL for b in rb.get(i, [])))
        objectionable = req_miss + ban_hit + obj_hit
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
            f.write(out)
            fails_path = f.name
        tr = subprocess.run([sys.executable, os.path.join(HERE, 'fail_trace.py'), run, fails_path],
                            capture_output=True, text=True).stdout
        os.unlink(fails_path)
        summ = tr.strip().splitlines()[-1].replace('SUMMARY: ', '') if tr.strip() else '?'
        summ = summ.split(' | ')[0]
        print('%-44s %4d/%-4d %6d %5d %5s/%-4s %4s %5d  %s' % (
            run.rstrip('/')[-44:], hit, tot, extras, nrun,
            m.group(1) if m else '?', m.group(2) if m else '?',
            m.group(3) if m else '?', objectionable, summ))
        print('%44s  objectionable = %d required missed + %d banned hit + %d objected'
              % ('', req_miss, ban_hit, obj_hit))


if __name__ == '__main__':
    main()
