#!/usr/bin/env python3
"""
annotation_check.py -- cross-check breath marks in an annotated MusicXML
against boundaries.json.

v3 (2026-07-19)
    Release-first matching: v2's boundary-ordered greedy matching let an
    entry-onset attach steal the next boundary's correct mark, cascading
    OK+OK into ATTACH-NEXT+ATTACH-NEXT+MISSING (Euph m.15-16 shape;
    ~11 misclassifications on the E0 run). Boundaries now match all
    releases globally first, then starts, then leftovers.

v2 (2026-07-10)
    Two fixes after first-run diagnosis:
    (a) Grand-staff mapping: the XML Harp is ONE part (staff 1 = upper,
        staff 2 = lower) while boundaries.json splits it in two; marks are
        now split by <staff>. Trailing XML-only parts (Cymbal) are skipped.
    (b) Attachment classification: the annotation layer attaches marks to
        the note STARTING at the boundary when one exists (open issue 7),
        rendering the comma one note late. Such marks are now classified
        ATTACH-NEXT (start == boundary) instead of missing+extra pairs.
    Buckets per part: OK (carrying-note release == boundary),
    ATTACH-NEXT (carrying-note start == boundary; renders late),
    MISSING-IN-SCORE, EXTRA-IN-SCORE.

v1 (2026-07-10)
    New tool: computes each breath mark's carrying-note release in global
    qn (divisions, backup/forward, chords, grace notes) and diffs against
    boundaries.json.

Exit code = MISSING + EXTRA (true discrepancies; ATTACH-NEXT counted
separately since it is one known root cause), capped at 99.

Usage:
    python annotation_check.py sectioned.musicxml boundaries.json
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import measure_map as _mm


def fmt_qn(qn: float) -> str:
    m, b = _mm.locate(qn)
    return f"m.{m} end" if b == 'end' else f"m.{m} b{b:g}"


def marks_from_xml(path: str):
    """Per XML part: dict staff -> list of (start_qn, release_qn)."""
    root = ET.parse(path).getroot()
    names = [sp.find('part-name').text
             for sp in root.find('part-list').findall('score-part')]
    out = []
    for part in root.findall('part'):
        div = 1.0
        cursor = 0.0
        prev_start = 0.0
        marks = {}
        for meas in part.findall('measure'):
            for el in meas:
                if el.tag == 'attributes':
                    d = el.find('divisions')
                    if d is not None:
                        div = float(d.text)
                elif el.tag in ('backup', 'forward'):
                    sign = -1 if el.tag == 'backup' else 1
                    cursor += sign * float(el.find('duration').text) / div
                elif el.tag == 'note':
                    dur_el = el.find('duration')
                    d_qn = (float(dur_el.text) / div) if dur_el is not None else 0.0
                    if el.find('chord') is not None:
                        start = prev_start
                    else:
                        start = cursor
                        cursor += d_qn
                    prev_start = start
                    if el.find('.//breath-mark') is not None:
                        st = el.find('staff')
                        staff = int(st.text) if st is not None else 1
                        marks.setdefault(staff, []).append(
                            (start, start + d_qn))
        out.append(marks)
    return names, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('musicxml')
    ap.add_argument('boundaries')
    ap.add_argument('--tol', type=float, default=0.05)
    args = ap.parse_args()

    _mm.load(args.musicxml)
    xnames, xparts = marks_from_xml(args.musicxml)
    bdoc = json.loads(Path(args.boundaries).read_text())
    _mm.verify_against_boundaries(bdoc)
    bparts = bdoc.get('per_part', [])

    # map boundaries parts -> (xml part, staff): consume XML parts in
    # order; when consecutive boundary parts share a name and the XML part
    # has multi-staff marks, split by staff.
    mapping = []
    xi = 0
    bi = 0
    while bi < len(bparts):
        two = (bi + 1 < len(bparts)
               and bparts[bi].get('name') == bparts[bi + 1].get('name'))
        if two:
            mapping.append((bi, xi, 1))
            mapping.append((bi + 1, xi, 2))
            bi += 2
        else:
            mapping.append((bi, xi, None))
            bi += 1
        xi += 1

    n_ok = n_attach = n_missing = n_extra = 0
    for bi, xi, staff in mapping:
        entry = bparts[bi]
        name = entry.get('name', f'part {bi}')
        bqns = sorted(float(b['time_quarter_notes'])
                      for b in entry.get('boundaries', []))
        md = xparts[xi] if xi < len(xparts) else {}
        pool = (md.get(staff, []) if staff is not None
                else [m for L in md.values() for m in L])
        pool = sorted(pool)

        rows = []
        # v3 pass 1: match every boundary to a mark by RELEASE first,
        # so an attach-shaped mark cannot steal a later boundary's
        # correctly rendered mark.
        unmatched = []
        for q in bqns:
            rel = next((m for m in pool if abs(m[1] - q) <= args.tol), None)
            if rel is not None:
                pool.remove(rel); n_ok += 1
            else:
                unmatched.append(q)
        # v3 pass 2: remaining boundaries match by START (ATTACH-NEXT),
        # pass 3: leftovers are MISSING.
        for q in unmatched:
            st = next((m for m in pool if abs(m[0] - q) <= args.tol), None)
            if st is not None:
                pool.remove(st); n_attach += 1
                rows.append(f"    ATTACH-NEXT       qn {q:g} ({fmt_qn(q)}) "
                            f"-> renders after {fmt_qn(st[1])}")
            else:
                n_missing += 1
                rows.append(f"    MISSING-IN-SCORE  qn {q:g} ({fmt_qn(q)})")
        for m in pool:
            n_extra += 1
            rows.append(f"    EXTRA-IN-SCORE    mark on note "
                        f"{fmt_qn(m[0])}..{fmt_qn(m[1])}")

        status = "OK" if not rows else "see below"
        print(f"boundaries part {bi} {name} <- XML '{xnames[xi]}'"
              f"{f' staff {staff}' if staff else ''}: "
              f"{len(bqns)} boundaries -- {status}")
        for r in rows:
            print(r)

    print(f"\nTOTALS: {n_ok} rendered correctly, {n_attach} ATTACH-NEXT "
          f"(render one note late), {n_missing} missing, {n_extra} extra")
    return min(n_missing + n_extra, 99)


if __name__ == '__main__':
    raise SystemExit(main())
