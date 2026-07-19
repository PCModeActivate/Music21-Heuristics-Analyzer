#!/usr/bin/env python3
"""
patch_annotation_check_v3.py

annotation_check v3 (2026-07-19): release-first matching.

DIAGNOSIS: v2 walked boundaries in order testing release-match then
start-match per boundary against the remaining pool. A genuine
entry-onset attach could therefore STEAL the next boundary's correctly
rendered mark: Euphonium m.15-16 (boundaries 56/60/64, commas on both
F2s) was reported as ATTACH-NEXT + ATTACH-NEXT + MISSING when the truth
was miss + OK + OK. On the E0 run this cascade misclassified ~11 marks
(reported 29 ATTACH-NEXT vs 18 true).

FIX: three passes over each part -- (1) match ALL boundaries to marks by
release; (2) match the remainder by start (ATTACH-NEXT); (3) leftovers
are MISSING / EXTRA. Same output format, same exit-code semantics.

Usage:
    python patch_annotation_check_v3.py annotation_check.py
(No backups -- git handles versioning.)
"""

import sys
from pathlib import Path

A_DOC = "v2 (2026-07-10)"
R_DOC = """v3 (2026-07-19)
    Release-first matching: v2's boundary-ordered greedy matching let an
    entry-onset attach steal the next boundary's correct mark, cascading
    OK+OK into ATTACH-NEXT+ATTACH-NEXT+MISSING (Euph m.15-16 shape;
    ~11 misclassifications on the E0 run). Boundaries now match all
    releases globally first, then starts, then leftovers.

v2 (2026-07-10)"""

A_LOOP = """        rows = []
        for q in bqns:
            rel = next((m for m in pool if abs(m[1] - q) <= args.tol), None)
            if rel is not None:
                pool.remove(rel); n_ok += 1; continue
            st = next((m for m in pool if abs(m[0] - q) <= args.tol), None)
            if st is not None:
                pool.remove(st); n_attach += 1
                rows.append(f"    ATTACH-NEXT       qn {q:g} ({fmt_qn(q)}) "
                            f"-> renders after {fmt_qn(st[1])}")
            else:
                n_missing += 1
                rows.append(f"    MISSING-IN-SCORE  qn {q:g} ({fmt_qn(q)})")
"""

R_LOOP = """        rows = []
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
"""


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    src = path.read_text()

    assert 'v3 (2026-07-19)' not in src, "already patched"
    n = src.count(A_LOOP)
    assert n == 1, (f"REFUSING: matching-loop anchor found {n} times "
                    f"(expected 1); inspect annotation_check.py manually.")
    n = src.count(A_DOC)
    assert n == 1, (f"REFUSING: docstring anchor found {n} times "
                    f"(expected 1).")

    src = src.replace(A_LOOP, R_LOOP, 1)
    src = src.replace(A_DOC, R_DOC, 1)
    path.write_text(src)
    print(f"annotation_check v3 applied to {path}.")
    print("Smoke test vs the E0c run: expect OK/ATTACH-NEXT/MISSING/EXTRA "
          "close to 169-190 / <20 / ~60s / ~40s with no cascade artifacts; "
          "release-first counts can only shift marks OUT of ATTACH-NEXT "
          "and MISSING relative to v2, never in.")


if __name__ == '__main__':
    main()
