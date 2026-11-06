#!/usr/bin/env python3
"""
score_geometry_check.py

Mechanical measure-geometry check between two scores -- typically the pipeline
input and a derived/hand-edited render (gt_rendered.musicxml).

Answers, without eyes:
  1. Does every measure's actual duration equal its time signature's bar
     duration?  (catches stray rests, over-full bars, overshoots)
  2. Do per-part total lengths agree with each other and with the expected
     total?
  3. Do measure offsets agree between the two files?

Magnitude classification matters here.  Float accumulation across ~90 measure
offsets lands around 1e-5 qn and is harmless.  A stray 32nd is 0.125 qn.  A
missing/extra beat is >= 1.0.  The report separates these so "there is a
divergence" never again gets read as "there is a corruption".

Usage:
    python score_geometry_check.py SOURCE.mxl RENDERED.musicxml
    python score_geometry_check.py gt_rendered.musicxml          # self-check only

Exit code = number of SIGNIFICANT findings (>= --significant, default 0.01 qn).
"""

import argparse
import sys
from collections import OrderedDict

import music21 as m21

NOISE = 1e-4          # at or below this: float accumulation, reported as INFO


def measure_table(path):
    """-> (part_names, {part_index: OrderedDict[measure_number] = (offset, actual, expected)}, totals)"""
    score = m21.converter.parse(path)
    parts = list(score.parts)
    names, tables, totals = [], {}, {}

    for i, part in enumerate(parts):
        names.append((part.partName or part.id or 'part %d' % i))
        rows = OrderedDict()
        for meas in part.getElementsByClass(m21.stream.Measure):
            off = float(meas.getOffsetInHierarchy(part))
            actual = float(meas.duration.quarterLength)
            try:
                expected = float(meas.barDuration.quarterLength)
            except Exception:
                expected = None
            rows[meas.measureNumber] = (off, actual, expected)
        tables[i] = rows
        totals[i] = float(part.duration.quarterLength)

    return names, tables, totals


def classify(delta):
    d = abs(delta)
    if d <= NOISE:
        return 'INFO'
    return 'SIGNIF'


def check_internal(label, names, tables, totals, significant):
    """Bar durations vs their own time signatures, and part-length agreement."""
    findings = []
    print('=' * 72)
    print('INTERNAL GEOMETRY: %s' % label)
    print('=' * 72)

    for i, rows in tables.items():
        bad = []
        for num, (off, actual, expected) in rows.items():
            if expected is None:
                continue
            d = actual - expected
            if abs(d) > NOISE:
                bad.append((num, off, actual, expected, d))
        if bad:
            print('  part %-2d %-26s %d irregular measure(s)'
                  % (i, names[i][:26], len(bad)))
            for num, off, actual, expected, d in bad:
                tag = 'SIGNIF' if abs(d) >= significant else 'INFO'
                print('      [%s] m.%-4s offset %9.5f  actual %7.4f  '
                      'expected %7.4f  delta %+.5f'
                      % (tag, num, off, actual, expected, d))
                if tag == 'SIGNIF':
                    findings.append((label, i, num, d))
        else:
            print('  part %-2d %-26s all measures match their time signature'
                  % (i, names[i][:26]))

    print()
    print('  --- part total lengths ---')
    vals = sorted(set(round(v, 6) for v in totals.values()))
    for i in sorted(totals):
        print('      part %-2d %-26s %10.5f qn' % (i, names[i][:26], totals[i]))
    if len(vals) == 1:
        print('  all parts agree at %.5f qn' % vals[0])
    else:
        spread = max(vals) - min(vals)
        tag = 'SIGNIF' if spread >= significant else 'INFO'
        print('  [%s] parts DISAGREE, spread %.5f qn: %s' % (tag, spread, vals))
        if tag == 'SIGNIF':
            findings.append((label, None, 'part-length spread', spread))
    print()
    return findings


def check_cross(a_label, a_names, a_tables, b_label, b_names, b_tables,
                significant):
    """Measure offsets, file A versus file B."""
    findings = []
    print('=' * 72)
    print('CROSS-FILE: %s  vs  %s' % (a_label, b_label))
    print('=' * 72)

    if len(a_tables) != len(b_tables):
        print('  [SIGNIF] part count differs: %d vs %d'
              % (len(a_tables), len(b_tables)))
        findings.append((a_label, None, 'part count', len(a_tables) - len(b_tables)))

    worst_noise = 0.0
    for i in sorted(set(a_tables) & set(b_tables)):
        ra, rb = a_tables[i], b_tables[i]
        only_a = sorted(set(ra) - set(rb))
        only_b = sorted(set(rb) - set(ra))
        if only_a or only_b:
            print('  [SIGNIF] part %-2d measure numbers differ  only-A=%s  only-B=%s'
                  % (i, only_a[:8], only_b[:8]))
            findings.append((a_label, i, 'measure set', len(only_a) + len(only_b)))

        rows = []
        for num in sorted(set(ra) & set(rb)):
            d = ra[num][0] - rb[num][0]
            if abs(d) > NOISE:
                rows.append((num, ra[num][0], rb[num][0], d))
            else:
                worst_noise = max(worst_noise, abs(d))

        if rows:
            print('  part %-2d %-26s %d offset divergence(s)'
                  % (i, a_names[i][:26], len(rows)))
            for num, oa, ob, d in rows:
                tag = 'SIGNIF' if abs(d) >= significant else 'INFO'
                print('      [%s] m.%-4s  A %9.5f   B %9.5f   delta %+.5f'
                      % (tag, num, oa, ob, d))
                if tag == 'SIGNIF':
                    findings.append((a_label, i, num, d))

    print()
    print('  largest sub-threshold offset divergence: %.3e qn  '
          '(float accumulation, harmless)' % worst_noise)
    print()
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('score_a')
    ap.add_argument('score_b', nargs='?', default=None)
    ap.add_argument('--significant', type=float, default=0.01,
                    help='qn threshold above which a divergence counts as a '
                         'finding (default 0.01; a 32nd is 0.125)')
    args = ap.parse_args()

    print('significance threshold: %.5f qn   noise floor: %.1e qn\n'
          % (args.significant, NOISE))

    a_names, a_tables, a_totals = measure_table(args.score_a)
    findings = check_internal(args.score_a, a_names, a_tables, a_totals,
                              args.significant)

    if args.score_b:
        b_names, b_tables, b_totals = measure_table(args.score_b)
        findings += check_internal(args.score_b, b_names, b_tables, b_totals,
                                   args.significant)
        findings += check_cross(args.score_a, a_names, a_tables,
                                args.score_b, b_names, b_tables,
                                args.significant)

    print('=' * 72)
    if findings:
        print('%d SIGNIFICANT finding(s):' % len(findings))
        for label, part, where, d in findings:
            print('   %-30s part %-6s %-22s delta %+.5f'
                  % (label, part, where, d))
    else:
        print('No significant findings. Geometry is clean at the '
              '%.5f qn threshold.' % args.significant)
    print('=' * 72)
    return len(findings)


if __name__ == '__main__':
    sys.exit(main())
