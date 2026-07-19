#!/usr/bin/env python3
"""
patch_boundaries_diff_v2.py

boundaries_diff v2 (2026-07-19), two fixes:

(a) PARAMETER CHECK NOISE: all_knobs captures ephemeral locals
    (annotated_path, plot_path, output_dir, loop temps i/marker/n_*),
    so every run in a new directory fired the "NOT apples-to-apples"
    banner. Those keys are now dropped before comparison. Additionally,
    when one side is a GT reference file (parameters carry 'gt': True),
    the parameter comparison is skipped with a one-line note -- GT files
    have no knobs and the wall of '<absent>' diffs was pure noise.

(b) MEASURE/BEAT DISPLAY: qn_to_mb assumed 4/4 throughout, so every
    display after the 18/4 m.93 was wrong ("m.97 b3" for m.93 end,
    "m.98 b3" for m.94 end). The map is now built from the measure/beat
    fields already present in the two JSON files (the pipeline writes
    them via the real measure map; gt_boundaries_v2 carries them too),
    with 4/4 extrapolation only for measures no entry lands in.
    Barline instants display as "m.N end" per project convention.

Usage:
    python patch_boundaries_diff_v2.py boundaries_diff.py
(No backups -- git handles versioning.)
"""

import sys
from pathlib import Path

A_DOC = "boundaries_diff.py -- compare two boundaries.json outputs."
R_DOC = A_DOC + """

v2 (2026-07-19): parameter check ignores ephemeral all_knobs keys and
skips GT reference files ('gt': True); measure/beat display is built
from the JSON files' own measure/beat fields (18/4 m.93 correct)."""

A_MB = '''def qn_to_mb(qn):
    """Liz convention (4/4): for display only."""
    m = int(qn // 4) + 1
    b = (qn % 4) + 1
    return 'm.%d b%.3g' % (m, b)
'''

R_MB = '''_MB_STARTS = []   # [(start_qn, measure_number)], built from the inputs


def build_mb_map(*json_paths):
    """Harvest (measure -> start_qn) from boundary entries that carry
    numeric measure/beat fields. Barline instants are recorded as
    next-measure b1 by the pipeline, so they contribute exact starts."""
    starts = {}
    for path in json_paths:
        try:
            data = json.load(open(path))
        except Exception:
            continue
        for p in data.get('per_part', []):
            for b in p.get('boundaries', []):
                m, bt, t = b.get('measure'), b.get('beat'), \\
                    b.get('time_quarter_notes')
                if isinstance(m, int) and isinstance(bt, (int, float)) \\
                        and t is not None:
                    starts.setdefault(m, round(float(t) - (float(bt) - 1.0), 6))
    _MB_STARTS[:] = sorted((s, m) for m, s in starts.items())


def qn_to_mb(qn):
    """Display via the harvested measure map; 4/4 fallback for gaps.
    Barline instants render as 'm.N end' (project convention)."""
    if not _MB_STARTS:
        m = int(qn // 4) + 1
        return 'm.%d b%.3g' % (m, (qn % 4) + 1)
    prev = None
    for s, m in _MB_STARTS:
        if s > qn + 1e-6:
            break
        if abs(qn - s) <= 1e-6 and m > _MB_STARTS[0][1]:
            return 'm.%d end' % (m - 1)
        prev = (s, m)
    if prev is None:
        m = int(qn // 4) + 1
        return 'm.%d b%.3g' % (m, (qn % 4) + 1)
    s, m = prev
    off = qn - s
    nxt = next((sn for sn, _ in _MB_STARTS if sn > s + 1e-6), None)
    if nxt is None and off >= 4.0:
        # beyond the last harvested measure start: extrapolate 4/4
        skip = int(off // 4.0)
        m += skip
        off -= 4.0 * skip
    # if nxt exists, qn < nxt lies inside measure m's real span
    # (covers the 18/4 m.93 correctly: beats run 1..18)
    return 'm.%d b%.3g' % (m, off + 1.0)
'''

A_PARAMS = """def diff_parameters(old_json, new_json):
    po = json.load(open(old_json)).get('parameters', {})
    pn = json.load(open(new_json)).get('parameters', {})
"""

R_PARAMS = """_EPHEMERAL_KNOBS = {'annotated_path', 'plot_path', 'output_dir', 'i',
                    'marker', 'n_flagged', 'n_hp', 'n_nat_ties',
                    'n_phrase', 'n_struct', 'n_tie_like', 'n_tuplets'}


def diff_parameters(old_json, new_json):
    po = json.load(open(old_json)).get('parameters', {})
    pn = json.load(open(new_json)).get('parameters', {})
    if po.get('gt') is True or pn.get('gt') is True:
        print('(GT reference file: parameter comparison skipped)')
        print()
        return False
    for _d in (po, pn):
        _ak = _d.get('all_knobs')
        if isinstance(_ak, dict):
            for _k in _EPHEMERAL_KNOBS:
                _ak.pop(_k, None)
"""

A_MAIN = "    diff_parameters(args.old_json, args.new_json)"
R_MAIN = ("    build_mb_map(args.old_json, args.new_json)\n"
          "    diff_parameters(args.old_json, args.new_json)")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    src = path.read_text()

    assert '_EPHEMERAL_KNOBS' not in src, "already patched"
    for name, a in [('docstring', A_DOC), ('qn_to_mb', A_MB),
                    ('diff_parameters', A_PARAMS), ('main call', A_MAIN)]:
        n = src.count(a)
        assert n == 1, (f"REFUSING: {name} anchor found {n} times "
                        f"(expected 1); inspect boundaries_diff.py "
                        f"manually before applying.")

    src = src.replace(A_DOC, R_DOC, 1)
    src = src.replace(A_MB, R_MB, 1)
    src = src.replace(A_PARAMS, R_PARAMS, 1)
    src = src.replace(A_MAIN, R_MAIN, 1)
    path.write_text(src)
    print(f"boundaries_diff v2 applied to {path}.")
    print("Smoke test: rerun the GT diff -- the parameter wall becomes one "
          "line, and the far-end entries read m.93 b3 / m.93 end / "
          "m.94 end instead of m.96-98.")


if __name__ == '__main__':
    main()
