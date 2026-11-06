#!/usr/bin/env python
"""
apply_repetition_wiring.py

Wires repetition_mask.py into sectioning_v2_10_A.py (the m.54 fix).

Run from the directory containing BOTH sectioning_v2_10_A.py and
repetition_mask.py:

    python apply_repetition_wiring.py

What it does:
  P1  imports repetition_mask (soft, like the phrase_material import)
  P2  adds 4 kwargs to run_sectioning (delta_repetition=0.0 default)
  P3  computes per-part repetition scores in the novelty loop and masks
      rhythm novelty AT SOURCE: masked rhythm_nu flows into B_i, the
      first-pass B_pre, and cross-rhythm support consistently
  P4  masks gap_n by the same multiplier (affects selection_score and
      note_anchor_score, which both consume gap_n)
  P5  stores repetition_score + best_lag in per-part candidate diagnostics
  P6  records the 4 new parameters in the result parameters dict

Not touched: chroma novelty, long-note arrival, LBDM. Rationale: rhythm
repetition is evidence about rhythm; pitch-motivated boundaries inside
isochronous streams must survive on chroma evidence, and texture-exit
arrivals must survive on the long-note channel.

With delta_repetition=0.0 (default) the pipeline output is bit-identical
to pre-patch behavior: the multiplier is 1 everywhere and the score is
computed only for diagnostics. First A/B suggestion:

    run_sectioning(..., delta_repetition=0.7)

Safety: every replacement target must occur EXACTLY ONCE in the file or
the script aborts without writing. A timestamped .bak is written first.
"""

import os
import py_compile
import shutil
import sys
import time

TARGET = 'sectioning_v2_10_A.py'

PATCHES = []

# ---------------------------------------------------------------------------
# P1: soft import
# ---------------------------------------------------------------------------
PATCHES.append(('P1 import', '''except ImportError:
    compute_phrase_material_report = None
    default_phrase_shape_thresholds = None
    summarize_phrase_material = None
    write_phrase_material_summary = None
''', '''except ImportError:
    compute_phrase_material_report = None
    default_phrase_shape_thresholds = None
    summarize_phrase_material = None
    write_phrase_material_summary = None

try:
    from repetition_mask import (
        compute_repetition_score,
        repetition_multiplier,
    )
except ImportError:
    compute_repetition_score = None
    repetition_multiplier = None
'''))

# ---------------------------------------------------------------------------
# P2: run_sectioning kwargs
# ---------------------------------------------------------------------------
PATCHES.append(('P2 kwargs', '''                    phrase_shape_thresholds=None,
''', '''                    phrase_shape_thresholds=None,
                    delta_repetition=0.0,
                    repetition_lag_min_qn=0.5,
                    repetition_lag_max_qn=3.0,
                    repetition_window_qn=1.0,
'''))

# ---------------------------------------------------------------------------
# P3: repetition score in the novelty loop, rhythm novelty masked at source
# ---------------------------------------------------------------------------
PATCHES.append(('P3 novelty loop', '''    chroma_novelty_per_part = []
    rhythm_novelty_per_part = []
    for i in range(len(parts)):
        if is_tacet[i]:
            chroma_novelty_per_part.append(np.zeros(T))
            rhythm_novelty_per_part.append(np.zeros(T))
            continue
        chroma_ssm = build_ssm(phi_chroma[i])
        rhythm_ssm = build_ssm(phi_rhythm[i])
        chroma_nu = compute_novelty(chroma_ssm, kernel,
                                    convention=convention, trim_edges=True)
        rhythm_nu = compute_novelty(rhythm_ssm, kernel,
                                    convention=convention, trim_edges=True)
        chroma_novelty_per_part.append(chroma_nu)
        rhythm_novelty_per_part.append(rhythm_nu)
''', '''    chroma_novelty_per_part = []
    rhythm_novelty_per_part = []
    repetition_scores = []
    repetition_best_lags = []
    rep_available = compute_repetition_score is not None
    if delta_repetition > 0.0 and not rep_available:
        print("       WARNING: delta_repetition > 0 but repetition_mask "
              "module not importable; repetition masking DISABLED")
    if rep_available and delta_repetition > 0.0:
        print(f"       repetition mask ON: delta={delta_repetition}, "
              f"lags=[{repetition_lag_min_qn},{repetition_lag_max_qn}] qn, "
              f"window={repetition_window_qn} qn "
              f"(masks rhythm novelty + following-gap)")
    for i in range(len(parts)):
        if is_tacet[i]:
            chroma_novelty_per_part.append(np.zeros(T))
            rhythm_novelty_per_part.append(np.zeros(T))
            repetition_scores.append(np.zeros(T))
            repetition_best_lags.append(np.zeros(T))
            continue
        chroma_ssm = build_ssm(phi_chroma[i])
        rhythm_ssm = build_ssm(phi_rhythm[i])
        chroma_nu = compute_novelty(chroma_ssm, kernel,
                                    convention=convention, trim_edges=True)
        rhythm_nu = compute_novelty(rhythm_ssm, kernel,
                                    convention=convention, trim_edges=True)
        if rep_available:
            rep_i, rep_lag_i = compute_repetition_score(
                phi_rhythm[i], division,
                lag_min_qn=repetition_lag_min_qn,
                lag_max_qn=repetition_lag_max_qn,
                window_qn=repetition_window_qn,
                return_best_lag=True,
            )
            # Mask rhythm novelty AT SOURCE: the masked signal flows into
            # B_i, the first-pass B_pre, and cross-rhythm support, so a
            # part cannot lend neighbors evidence that its own repetition
            # context just discounted.
            rhythm_nu = rhythm_nu * repetition_multiplier(
                rep_i, delta_repetition
            )
        else:
            rep_i = np.zeros(T)
            rep_lag_i = np.zeros(T)
        repetition_scores.append(rep_i)
        repetition_best_lags.append(rep_lag_i)
        chroma_novelty_per_part.append(chroma_nu)
        rhythm_novelty_per_part.append(rhythm_nu)
'''))

# ---------------------------------------------------------------------------
# P4: mask gap_n (feeds both selection_score and note_anchor_score)
# ---------------------------------------------------------------------------
PATCHES.append(('P4 gap mask', '''        long_n = normalize_signal(long_note_grids[i])
        gap_n = normalize_signal(following_gap_grids[i])
''', '''        long_n = normalize_signal(long_note_grids[i])
        gap_n = normalize_signal(following_gap_grids[i])
        if repetition_multiplier is not None and delta_repetition > 0.0:
            # Rhythm repetition discounts gap evidence: a rest that recurs
            # every cell is part of the pattern, not a phrase edge.
            # long_n is deliberately NOT masked (texture exits arrive on
            # long notes and must survive).
            gap_n = gap_n * repetition_multiplier(
                repetition_scores[i], delta_repetition
            )
'''))

# ---------------------------------------------------------------------------
# P5: diagnostics
# ---------------------------------------------------------------------------
PATCHES.append(('P5 diagnostics', '''            'continuation_penalty': continuation_penalty,
            'forbidden_mask': forbidden,
        })
''', '''            'continuation_penalty': continuation_penalty,
            'forbidden_mask': forbidden,
            'repetition_score': repetition_scores[i],
            'repetition_best_lag_qn': repetition_best_lags[i],
        })
'''))

# ---------------------------------------------------------------------------
# P6: parameters dict
# ---------------------------------------------------------------------------
PATCHES.append(('P6 parameters', '''            'note_anchor_cross_weight': note_anchor_cross_weight,
''', '''            'note_anchor_cross_weight': note_anchor_cross_weight,
            'delta_repetition': delta_repetition,
            'repetition_lag_min_qn': repetition_lag_min_qn,
            'repetition_lag_max_qn': repetition_lag_max_qn,
            'repetition_window_qn': repetition_window_qn,
'''))


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"ERROR: {TARGET} not found in current directory.")
    if not os.path.exists('repetition_mask.py'):
        print("WARNING: repetition_mask.py not found next to the target. "
              "The patch still applies (soft import), but masking will be "
              "disabled at runtime until the module is present.")

    with open(TARGET, 'r', encoding='utf-8') as f:
        src = f.read()

    # Pre-check: every old block must occur exactly once.
    ok = True
    for name, old, _ in PATCHES:
        n = src.count(old)
        status = 'ok' if n == 1 else f'FAIL (found {n} occurrences)'
        print(f"  {name:16s} {status}")
        if n != 1:
            ok = False
    if not ok:
        sys.exit("ABORTED: anchors not unique/found. File not modified. "
                 "(Has the file drifted from the reviewed version?)")

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

    print("  py_compile     ok")
    print()
    print("Done. Default runs are bit-identical (delta_repetition=0.0).")
    print("A/B suggestion:   run_sectioning(..., delta_repetition=0.7)")
    print("Probe afterwards: per_part_candidate_diagnostics[i]"
          "['repetition_score'] and ['repetition_best_lag_qn']")


if __name__ == '__main__':
    main()
