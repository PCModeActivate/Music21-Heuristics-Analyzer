#!/usr/bin/env python3
"""
audit_check.py -- compare an audit/complaint list against a boundaries.json.

v2 (2026-07-10)
    'strength': "recommended" on a point makes its failure SOFT (reported,
    not counted in the exit code). Cases may carry 'constraints':
    [{"type":"unison","parts":[...],"qn_lo":..,"qn_hi":..}] -- the parts'
    mark sets inside the range must match within 0.1 qn.

v1 (2026-07-10)
    New tool. For each diagnostic point in an audit case file (same schema
    as audit_cases_review_2026-07.json, with an OPTIONAL per-point
    'expect' field), report the nearest boundary in that part and a
    verdict:

        expect: "present" -> PASS if a boundary lies within --tol qn
        expect: "absent"  -> PASS if NO boundary lies within --tol qn
        expect missing    -> INFO (state reported, nothing judged)

    Quick complaints can also be given on the CLI without editing JSON:

        --point PART:MEASURE[:BEAT[:present|absent]]
        e.g.  --point 6:84::present      (Tpt m.84, beat defaults 1.0)
              --point 7:74:3.125:absent  (Euph m.74 b3.125 spurious)

    An optional --baseline boundaries.json prints the same nearest-boundary
    state from a second run next to each point (before -> after triage).

    Exit code: number of FAILs (0 = all expectations met), capped at 99.

Conventions (project-wide): measures are 4/4, qn = (measure-1)*4 + (beat-1).
Matching is done in qn against boundaries' time_quarter_notes.

Usage:
    python audit_check.py output_v2_10_D_patched/liz_seam/boundaries.json \
        --audit audit_cases_review_2026-07.json
    python audit_check.py NEW/boundaries.json --audit audit.json \
        --baseline OLD/boundaries.json --tol 2.0 --tag F
    python audit_check.py NEW/boundaries.json --point 6:84::present
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import measure_map as _mm


def qn_of(measure: int, beat) -> float:
    return _mm.qn_of(measure, beat)


def fmt_qn(qn: float) -> str:
    m, b = _mm.locate(qn)
    core = f"m.{m} end" if b == 'end' else f"m.{m} b{b:g}"
    return f"qn {qn:8.3f} ({core})"


def load_boundaries(path: str):
    doc = json.loads(Path(path).read_text())
    per_part = {}
    names = {}
    for entry in doc.get('per_part', []):
        idx = int(entry['index'])
        names[idx] = entry.get('name', f'part {idx}')
        per_part[idx] = sorted(
            float(b['time_quarter_notes']) for b in entry.get('boundaries', [])
        )
    params = doc.get('parameters', {})
    label = "{} [{} sha={}]".format(
        path,
        params.get('rest_seam_policy', 'policy?'),
        params.get('input_sha256', '?'),
    )
    return per_part, names, label


def nearest(bqns: list[float], target: float):
    """Return (qn, delta) of the nearest boundary, or (None, None)."""
    if not bqns:
        return None, None
    best = min(bqns, key=lambda q: abs(q - target))
    return best, best - target


def parse_cli_point(spec: str):
    """PART:MEASURE[:BEAT[:present|absent]] -> point dict."""
    fields = spec.split(':')
    if len(fields) < 2:
        raise SystemExit(f"bad --point '{spec}': need PART:MEASURE at least")
    part = int(fields[0])
    measure = int(fields[1])
    beat = fields[2] if len(fields) > 2 and fields[2] else 1.0
    if beat != 'end':
        beat = float(beat)
    expect = None
    if len(fields) > 3 and fields[3]:
        if fields[3] not in ('present', 'absent'):
            raise SystemExit(f"bad --point '{spec}': expect must be present|absent")
        expect = fields[3]
    return {
        'part_index': part, 'measure': measure, 'beat': beat,
        'expect': expect, 'strength': None, 'tol': None, 'why': '(CLI point)',
        '_case_id': 'cli', '_case_tags': [],
    }


def collect_points(audit_path, case_filter, tag_filter, cli_points):
    points = []
    if audit_path:
        audit = json.loads(Path(audit_path).read_text())
        for case in audit.get('cases', []):
            if case_filter and case.get('id') not in case_filter:
                continue
            if tag_filter and not (tag_filter & set(case.get('tags', []))):
                continue
            for p in case.get('diagnostic_points', []):
                points.append({
                    'part_index': int(p['part_index']),
                    'measure': int(p['measure']),
                    'beat': p.get('beat', 1.0),
                    'expect': p.get('expect'),
                    'strength': p.get('strength'),
                    'tol': p.get('tol'),
                    'why': p.get('why', ''),
                    '_case_id': case.get('id', '?'),
                    '_case_tags': case.get('tags', []),
                })
    points.extend(cli_points)
    return points


def describe(per_part, names, part, target, tol):
    """One-line boundary state for a part/target under this run."""
    if part not in per_part:
        return None, f"part {part} not in file"
    q, d = nearest(per_part[part], target)
    if q is None:
        return None, "no boundaries in part"
    hit = abs(d) <= tol
    tag = "HIT " if hit else "none"
    return hit, f"{tag} nearest {fmt_qn(q)}  ({d:+.3f} qn)"


def main() -> int:
    ap = argparse.ArgumentParser(
        description='Check audit/complaint points against a boundaries.json.')
    ap.add_argument('boundaries', help='boundaries.json of the run under test')
    ap.add_argument('--audit', help='audit case file (extend, do not fork)')
    ap.add_argument('--baseline',
                    help='optional second boundaries.json for before/after')
    ap.add_argument('--tol', type=float, default=2.0,
                    help='match tolerance in qn (default 2.0)')
    ap.add_argument('--case', action='append', default=[],
                    help='case id to include; may repeat')
    ap.add_argument('--tag', action='append', default=[],
                    help='include cases with this tag; may repeat')
    ap.add_argument('--point', action='append', default=[],
                    metavar='PART:MEASURE[:BEAT[:present|absent]]',
                    help='ad-hoc complaint point; may repeat')
    ap.add_argument('--musicxml', required=True,
                    help='score file; provides the real measure map')
    ap.add_argument('--fails-only', action='store_true',
                    help='print only FAIL verdicts')
    args = ap.parse_args()

    _mm.load(args.musicxml)
    _mm.verify_against_boundaries(
        json.loads(Path(args.boundaries).read_text()))
    if not args.audit and not args.point:
        ap.error('need --audit and/or at least one --point')

    per_part, names, label = load_boundaries(args.boundaries)
    base = None
    if args.baseline:
        base = load_boundaries(args.baseline)
        print(f"RUN:      {label}")
        print(f"BASELINE: {base[2]}")
    else:
        print(f"RUN: {label}")
    print(f"tolerance: {args.tol} qn\n")

    cli_points = [parse_cli_point(s) for s in args.point]
    points = collect_points(args.audit, set(args.case), set(args.tag),
                            cli_points)
    if not points:
        print("No points selected.")
        return 0

    n_pass = n_fail = n_info = n_soft = 0
    last_case = None
    for p in points:
        target = qn_of(p['measure'], p['beat'])
        tol = p.get('tol') or args.tol
        hit, state = describe(per_part, names, p['part_index'], target, tol)

        expect = p['expect']
        if expect == 'present':
            verdict = 'PASS' if hit else 'FAIL'
        elif expect == 'absent':
            # hit None means no boundaries in the part -> absent holds
            verdict = 'FAIL' if hit else 'PASS'
        else:
            verdict = 'INFO'
        if verdict == 'FAIL' and p.get('strength') == 'recommended':
            verdict = 'SOFT'

        if verdict == 'PASS':
            n_pass += 1
        elif verdict == 'FAIL':
            n_fail += 1
        elif verdict == 'SOFT':
            n_soft += 1
        else:
            n_info += 1

        if args.fails_only and verdict != 'FAIL':
            continue

        if p['_case_id'] != last_case:
            tags = ','.join(p['_case_tags'])
            print(f"--- {p['_case_id']}" + (f"  [{tags}]" if tags else ""))
            last_case = p['_case_id']

        pname = names.get(p['part_index'], f"part {p['part_index']}")
        exp_str = f" expect={expect}" if expect else ""
        if p.get('tol'):
            exp_str += f" tol={p['tol']:g}"
        print(f"  {verdict:4s} p{p['part_index']:>2} {pname:<20.20s} "
              f"target {fmt_qn(target)}{exp_str}")
        print(f"       run:      {state}")
        if base:
            _, bstate = describe(base[0], base[1], p['part_index'], target,
                                 args.tol)
            print(f"       baseline: {bstate}")
        if p['why']:
            print(f"       why: {p['why']}")

    # ---- constraints ----------------------------------------------------
    n_cviol = 0
    if args.audit:
        audit = json.loads(Path(args.audit).read_text())
        for case in audit.get('cases', []):
            for con in case.get('constraints', []):
                if con.get('type') != 'unison':
                    continue
                lo, hi = con['qn_lo'], con['qn_hi']
                sets = {pi: [q for q in per_part.get(pi, [])
                             if lo <= q <= hi] for pi in con['parts']}
                vals = list(sets.values())
                same = all(len(v) == len(vals[0]) and
                           all(abs(a - b) <= 0.1
                               for a, b in zip(v, vals[0]))
                           for v in vals)
                tag = 'UNISON-OK ' if same else 'UNISON-VIOLATION'
                if not same:
                    n_cviol += 1
                detail = "; ".join(
                    f"p{pi}:{[round(q,3) for q in s] or '--'}"
                    for pi, s in sets.items())
                print(f"{tag} {case.get('id','?')} qn[{lo:g},{hi:g}] "
                      f"{detail}")

    print(f"\nTOTAL: {n_pass} PASS, {n_fail} FAIL, {n_soft} SOFT, "
          f"{n_info} INFO, {n_cviol} unison violations "
          f"(tol {args.tol} qn)")
    return min(n_fail + n_cviol, 99)


if __name__ == '__main__':
    raise SystemExit(main())
