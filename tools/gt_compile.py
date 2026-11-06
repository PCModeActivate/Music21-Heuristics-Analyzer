#!/usr/bin/env python3
"""
gt_compile.py -- compile a ground-truth boundary list from a run's
boundaries.json plus a fully-judged audit case file.

v1 (2026-07-10)
    GT per part = (existing marks surviving every hard 'absent' ruling)
                  + (every hard 'present' target not already covered)
    with entries labeled:
        "required"     added/confirmed by a hard present ruling
        "kept"         existing mark with no ruling against it
        "recommended"  soft present targets (only with --include-soft;
                       soft absents are likewise applied only with it)

    REFUSES to compile if any diagnostic point lacks an 'expect'
    (unjudged points mean the GT is not fully specified).

    VALIDITY INVARIANT (Robert, 2026-07-10): every GT boundary must sit
    at some note's RELEASE in its part -- a breath in a rest or on an
    onset is nonsense. If --musicxml is given, releases are extracted
    (divisions/backup/forward/chords/grand-staff aware) and violations
    are reported per entry; the GT is still written, with violators
    flagged "release_ok": false, so nothing fails silently.

    Unison constraints from the audit file are copied into the GT for
    downstream evaluators.

Usage:
    python gt_compile.py boundaries.json --audit audit_cases.json \
        [--musicxml sectioned.musicxml] [--include-soft] \
        [--out gt.json]
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import measure_map as _mm


def qn_of(measure: int, beat) -> float:
    return _mm.qn_of(measure, beat)


def fmt_qn(qn: float) -> str:
    m, b = _mm.locate(qn)
    return f"m.{m} end" if b == 'end' else f"m.{m} b{b:g}"


def releases_from_xml(path: str, n_bparts: int, bnames):
    """Note-release qns per boundaries part (grand-staff aware)."""
    root = ET.parse(path).getroot()
    per_xml = []
    for part in root.findall('part'):
        div, cursor, prev = 1.0, 0.0, 0.0
        rel = {}
        for meas in part.findall('measure'):
            for el in meas:
                if el.tag == 'attributes':
                    d = el.find('divisions')
                    if d is not None:
                        div = float(d.text)
                elif el.tag in ('backup', 'forward'):
                    cursor += (1 if el.tag == 'forward' else -1) * \
                        float(el.find('duration').text) / div
                elif el.tag == 'note':
                    dur = el.find('duration')
                    d_qn = float(dur.text) / div if dur is not None else 0.0
                    if el.find('chord') is not None:
                        start = prev
                    else:
                        start = cursor
                        cursor += d_qn
                    prev = start
                    if el.find('rest') is None and d_qn > 0:
                        st = el.find('staff')
                        staff = int(st.text) if st is not None else 1
                        rel.setdefault(staff, set()).add(
                            round(start + d_qn, 6))
        per_xml.append(rel)
    # same mapping heuristic as annotation_check: consecutive
    # same-named boundary parts share one grand-staff XML part.
    out, xi, bi = [], 0, 0
    while bi < n_bparts:
        two = bi + 1 < n_bparts and bnames[bi] == bnames[bi + 1]
        if two:
            out.append(sorted(per_xml[xi].get(1, set())))
            out.append(sorted(per_xml[xi].get(2, set())))
            bi += 2
        else:
            out.append(sorted(set().union(*per_xml[xi].values())
                              if per_xml[xi] else set()))
            bi += 1
        xi += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('boundaries')
    ap.add_argument('--audit', required=True)
    ap.add_argument('--musicxml', required=True,
                    help='score file; measure map + release-invariant check')
    ap.add_argument('--include-soft', action='store_true',
                    help='apply recommended (soft) rulings too')
    ap.add_argument('--out', default='gt.json')
    ap.add_argument('--release-tol', type=float, default=0.01)
    args = ap.parse_args()

    _mm.load(args.musicxml)
    bdoc = json.loads(Path(args.boundaries).read_text())
    _mm.verify_against_boundaries(bdoc)
    audit = json.loads(Path(args.audit).read_text())

    # ---- refuse on unjudged points ---------------------------------------
    unjudged = [(c.get('id'), p) for c in audit.get('cases', [])
                for p in c.get('diagnostic_points', [])
                if not p.get('expect')]
    if unjudged:
        print(f"REFUSING to compile: {len(unjudged)} unjudged point(s):")
        for cid, p in unjudged:
            print(f"  [{cid}] part {p['part_index']} m.{p['measure']} "
                  f"beat {p['beat']}")
        return 98

    # ---- gather rulings per part ------------------------------------------
    hard_abs, hard_pres, soft_abs, soft_pres = {}, {}, {}, {}
    for c in audit.get('cases', []):
        for p in c.get('diagnostic_points', []):
            q = qn_of(int(p['measure']), p['beat'])
            tol = p.get('tol') or 2.0
            soft = p.get('strength') == 'recommended'
            bucket = {('absent', False): hard_abs,
                      ('absent', True): soft_abs,
                      ('present', False): hard_pres,
                      ('present', True): soft_pres}[(p['expect'], soft)]
            bucket.setdefault(int(p['part_index']), []).append((q, tol))

    names = [e.get('name', '?') for e in bdoc['per_part']]
    releases = None
    if args.musicxml:
        releases = releases_from_xml(args.musicxml, len(names), names)

    out_parts = []
    n_req = n_kept = n_rec = n_removed = n_badrel = 0
    for entry in bdoc['per_part']:
        i = int(entry['index'])
        existing = sorted(float(b['time_quarter_notes'])
                          for b in entry.get('boundaries', []))
        removed, gt = [], []
        abs_rules = hard_abs.get(i, []) + \
            (soft_abs.get(i, []) if args.include_soft else [])
        for q in existing:
            if any(abs(q - aq) <= at for aq, at in abs_rules):
                removed.append(q); n_removed += 1
            else:
                gt.append([q, 'kept'])
        for q, tol in hard_pres.get(i, []):
            hit = next((g for g in gt if abs(g[0] - q) <= tol), None)
            if hit:
                hit[1] = 'required'
            else:
                gt.append([q, 'required'])
        if args.include_soft:
            for q, tol in soft_pres.get(i, []):
                if not any(abs(g[0] - q) <= tol for g in gt):
                    gt.append([q, 'recommended'])
        gt.sort()
        n_req += sum(1 for _, s in gt if s == 'required')
        n_kept += sum(1 for _, s in gt if s == 'kept')
        n_rec += sum(1 for _, s in gt if s == 'recommended')

        entries = []
        for q, status in gt:
            e = {"time_quarter_notes": q, "status": status}
            if releases is not None:
                ok = any(abs(q - r) <= args.release_tol
                         for r in releases[i])
                e["release_ok"] = ok
                if not ok:
                    n_badrel += 1
                    print(f"RELEASE-INVARIANT VIOLATION: part {i} "
                          f"{names[i]} qn {q:g} ({fmt_qn(q)}) [{status}] "
                          f"-- no note releases here")
            entries.append(e)
        out_parts.append({"index": i, "name": names[i],
                          "gt_boundaries": entries,
                          "removed_from_run": removed})

    constraints = [dict(c2, case=c.get('id'))
                   for c in audit.get('cases', [])
                   for c2 in c.get('constraints', [])]

    gt_doc = {
        "source_boundaries": args.boundaries,
        "source_params": {k: bdoc.get('parameters', {}).get(k)
                          for k in ('rest_seam_policy', 'input_sha256')},
        "audit_file": args.audit,
        "include_soft": args.include_soft,
        "per_part": out_parts,
        "constraints": constraints,
    }
    Path(args.out).write_text(json.dumps(gt_doc, indent=2,
                                         ensure_ascii=False))
    total = n_req + n_kept + n_rec
    print(f"\nwrote {args.out}: {total} GT boundaries "
          f"({n_req} required, {n_kept} kept, {n_rec} recommended); "
          f"{n_removed} run marks removed; "
          f"{n_badrel} release-invariant violations")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
