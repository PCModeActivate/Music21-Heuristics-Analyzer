#!/usr/bin/env python
"""
apply_repetition_cli_explain.py

Completes the repetition-mask integration in sectioning_v2_10_A.py:

  E1  four --repetition CLI args in main()'s argparse block
  E2  pass-through of those args into the run_sectioning() call
  E3  explain() prints repetition_score / best_lag / delta at the query
      point (in the candidate-selection section)
  E4  the "Candidate peaks within window" listing gains an R=... column,
      so one explain call answers "why here and not one cell over"

Requires the wiring patch (apply_repetition_wiring.py) to have been
applied already; aborts if it wasn't.

Run from the directory containing sectioning_v2_10_A.py:

    python apply_repetition_cli_explain.py

After this, the full A/B needs no ad-hoc Python:

    python sectioning_v2_10_A.py liz.mxl -o output_default
    python sectioning_v2_10_A.py liz.mxl -o output_rep07 --delta_repetition 0.7
    python explain.py output_rep07 5 54 2.5 --window 16
    diff output_default/boundaries.json output_rep07/boundaries.json

Safety: every anchor must occur EXACTLY ONCE or the script aborts
without writing. Timestamped .bak first; py_compile after, with
auto-restore on failure.
"""

import os
import py_compile
import shutil
import sys
import time

TARGET = 'sectioning_v2_10_A.py'

PATCHES = []

# ---------------------------------------------------------------------------
# E1: argparse
# ---------------------------------------------------------------------------
PATCHES.append(('E1 argparse', '''    parser.add_argument('--cross_rhythm_max_shift_qn', type=float, default=0.5)
''', '''    parser.add_argument('--cross_rhythm_max_shift_qn', type=float, default=0.5)
    parser.add_argument('--delta_repetition', type=float, default=0.0,
                        help='Strength of rhythm-repetition masking, 0=off. '
                             'Masks rhythm novelty (at source) and '
                             'following-gap evidence by (1 - delta*R).')
    parser.add_argument('--repetition_lag_min_qn', type=float, default=0.5,
                        help='Minimum repetition period searched (qn)')
    parser.add_argument('--repetition_lag_max_qn', type=float, default=3.0,
                        help='Maximum repetition period searched (qn). '
                             'Musically: the largest period that counts as '
                             'figuration rather than phrase repetition.')
    parser.add_argument('--repetition_window_qn', type=float, default=1.0,
                        help='Half-window (qn) for local context comparison')
'''))

# ---------------------------------------------------------------------------
# E2: pass-through into run_sectioning()
# ---------------------------------------------------------------------------
PATCHES.append(('E2 passthrough', '''        cross_rhythm_max_shift_qn=args.cross_rhythm_max_shift_qn,
''', '''        cross_rhythm_max_shift_qn=args.cross_rhythm_max_shift_qn,
        delta_repetition=args.delta_repetition,
        repetition_lag_min_qn=args.repetition_lag_min_qn,
        repetition_lag_max_qn=args.repetition_lag_max_qn,
        repetition_window_qn=args.repetition_window_qn,
'''))

# ---------------------------------------------------------------------------
# E3: explain() point values
# ---------------------------------------------------------------------------
PATCHES.append(('E3 explain point', '''        print(f"  continuation_penalty:    {float(continuation_penalty[idx]):.3f}")
        print(f"  forbidden_mask:          {int(float(forbidden_mask[idx]) > 0)}")
        print()
''', '''        print(f"  continuation_penalty:    {float(continuation_penalty[idx]):.3f}")
        print(f"  forbidden_mask:          {int(float(forbidden_mask[idx]) > 0)}")
        rep_score = candidate_diag.get('repetition_score')
        rep_lag = candidate_diag.get('repetition_best_lag_qn')
        if rep_score is not None:
            dr = params.get('delta_repetition', 0.0)
            print(f"  repetition_score R:      {float(rep_score[idx]):.3f}"
                  f"  (delta_repetition={dr}"
                  f"{'' if dr > 0 else ' -- masking OFF'})")
            if rep_lag is not None and float(rep_score[idx]) > 1e-6:
                print(f"    local rhythm matches material "
                      f"{float(rep_lag[idx]):.2f} qn away on both sides")
        print()
'''))

# ---------------------------------------------------------------------------
# E4: explain() peak listing gains an R column
# ---------------------------------------------------------------------------
PATCHES.append(('E4 peak listing', '''            print("Candidate peaks within window:")
            for p in nearby_cands:
                print(f"  t={time_grid[p]:.2f}  cand={candidate_signal[p]:.3f}  "
                      f"sel={selection_score[p]:.3f}  acc={acceptance_score[p]:.3f}  "
                      f"B_i={B_i[p]:.3f}  forbidden={int(float(forbidden_mask[p]) > 0)}")
''', '''            print("Candidate peaks within window:")
            for p in nearby_cands:
                rep_str = ""
                if rep_score is not None:
                    rep_str = f"  R={float(rep_score[p]):.2f}"
                print(f"  t={time_grid[p]:.2f}  cand={candidate_signal[p]:.3f}  "
                      f"sel={selection_score[p]:.3f}  acc={acceptance_score[p]:.3f}  "
                      f"B_i={B_i[p]:.3f}  forbidden={int(float(forbidden_mask[p]) > 0)}"
                      f"{rep_str}")
'''))


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"ERROR: {TARGET} not found in current directory.")

    with open(TARGET, 'r', encoding='utf-8') as f:
        src = f.read()

    # Guard: the wiring patch must already be in.
    if 'delta_repetition=0.0,' not in src:
        sys.exit("ABORTED: repetition wiring not found in the target "
                 "(run apply_repetition_wiring.py first). "
                 "File not modified.")

    ok = True
    for name, old, _ in PATCHES:
        n = src.count(old)
        status = 'ok' if n == 1 else f'FAIL (found {n} occurrences)'
        print(f"  {name:18s} {status}")
        if n != 1:
            ok = False
    if not ok:
        sys.exit("ABORTED: anchors not unique/found. File not modified. "
                 "(Hand edits to main() or explain() since the reviewed "
                 "version?)")

    backup = TARGET + '.bak.' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(TARGET, backup)
    print(f"  backup -> {backup}")

    for name, old, new in PATCHES:
        src = src.replace(old, new, 1)

    with open(TARGET, 'w', encoding='utf-8') as f:
        f.write(src)

    try:
        py_compile.compile(TARGET, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup, TARGET)
        sys.exit(f"ABORTED: patched file failed to compile; restored from "
                 f"backup.\n{e}")

    print("  py_compile         ok")
    print()
    print("Done. New CLI args: --delta_repetition --repetition_lag_min_qn")
    print("                    --repetition_lag_max_qn --repetition_window_qn")
    print("explain() now reports R and best-lag at the query point and an")
    print("R column in the peaks-within-window listing.")


if __name__ == '__main__':
    main()
