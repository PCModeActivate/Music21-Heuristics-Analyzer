#!/usr/bin/env python
"""
apply_repetition_fix2.py

Corrects the repetition-mask semantics in sectioning_v2_10_A.py after the
first Liz A/B (delta=0.7) showed two problems:

  1. Masking rhythm novelty at source was partially undone (and globally
     distorted) by the normalization inside compute_per_part_boundary_signal.
     Masking now happens POST-normalization, inside the function, so
     "novelty 0.83 x multiplier 0.37" means what it says and unmasked
     regions are not re-stretched.

  2. The dominant evidence at ASax m.54 was the slur-endpoint boost
     (0.979 at every cell: each 3-eighth cell carries its own slur).
     Periodic articulation is pattern-interior evidence, so the same
     multiplier now attenuates the slur-endpoint boost.

Requires: the wiring patch (apply_repetition_wiring.py) AND the updated
repetition_mask.py (v2, with the rest-backed rule) deployed next to the
target. The CLI patch (apply_repetition_cli_explain.py) is compatible
but not required.

Still masked elsewhere: following-gap (selection layer, unchanged).
Still unmasked: chroma novelty, LBDM, long-note arrivals, structural
bumps, cross support (cross now self-corrects: it is built from other
parts' B_pre, which use their own multipliers).

Everything remains behind delta_repetition=0.0 by default.

Safety: every anchor must occur EXACTLY ONCE or the script aborts
without writing. Timestamped .bak; py_compile with auto-restore.
"""

import os
import py_compile
import shutil
import sys
import time

TARGET = 'sectioning_v2_10_A.py'

PATCHES = []

# ---------------------------------------------------------------------------
# F1: function signature gains repetition_mult_i
# ---------------------------------------------------------------------------
PATCHES.append(('F1 signature', '''                                      gamma=0.4, zeta=0.4):
''', '''                                      gamma=0.4, zeta=0.4,
                                      repetition_mult_i=None):
'''))

# ---------------------------------------------------------------------------
# F2: post-normalization masking inside the function
# ---------------------------------------------------------------------------
PATCHES.append(('F2 post-norm mask', '''                  else np.zeros_like(chroma_norm))

    B_raw = (
''', '''                  else np.zeros_like(chroma_norm))

    if repetition_mult_i is not None:
        # v2.10 repetition mask, applied POST-normalization so the
        # attenuation has absolute meaning ("rhythm novelty 0.83 x
        # multiplier 0.37") and unmasked regions are not re-stretched.
        # Masks rhythm novelty and the slur-endpoint boost: articulation
        # that repeats with the pattern is pattern-interior evidence.
        # Chroma novelty, LBDM, structural bumps, and cross support are
        # deliberately unmasked.
        rhythm_norm = rhythm_norm * repetition_mult_i
        slur_endpoints_i = slur_endpoints_i * repetition_mult_i

    B_raw = (
'''))

# ---------------------------------------------------------------------------
# F3: remove the source masking from the novelty loop (keep the score)
# ---------------------------------------------------------------------------
PATCHES.append(('F3 unmask source', '''            # Mask rhythm novelty AT SOURCE: the masked signal flows into
            # B_i, the first-pass B_pre, and cross-rhythm support, so a
            # part cannot lend neighbors evidence that its own repetition
            # context just discounted.
            rhythm_nu = rhythm_nu * repetition_multiplier(
                rep_i, delta_repetition
            )
        else:
''', '''        else:
'''))

# ---------------------------------------------------------------------------
# F4a/b/c: build per-part multipliers alongside the scores
# ---------------------------------------------------------------------------
PATCHES.append(('F4a mults init', '''    repetition_scores = []
    repetition_best_lags = []
''', '''    repetition_scores = []
    repetition_best_lags = []
    repetition_mults = []
'''))

PATCHES.append(('F4b tacet branch', '''            repetition_scores.append(np.zeros(T))
            repetition_best_lags.append(np.zeros(T))
            continue
''', '''            repetition_scores.append(np.zeros(T))
            repetition_best_lags.append(np.zeros(T))
            repetition_mults.append(np.ones(T))
            continue
'''))

PATCHES.append(('F4c active branch', '''        repetition_scores.append(rep_i)
        repetition_best_lags.append(rep_lag_i)
''', '''        repetition_scores.append(rep_i)
        repetition_best_lags.append(rep_lag_i)
        if repetition_multiplier is not None:
            repetition_mults.append(
                repetition_multiplier(rep_i, delta_repetition))
        else:
            repetition_mults.append(np.ones(T))
'''))

# ---------------------------------------------------------------------------
# F5: console message reflects the new scope
# ---------------------------------------------------------------------------
PATCHES.append(('F5 console text', '''              f"(masks rhythm novelty + following-gap)")
''', '''              f"(masks rhythm novelty, slur-endpoint boost, "
              f"following-gap)")
'''))

# ---------------------------------------------------------------------------
# F6/F7: pass the multiplier at both call sites
# ---------------------------------------------------------------------------
PATCHES.append(('F6 B_pre call', '''            cross_rhythm_support_i=np.zeros(T),
''', '''            cross_rhythm_support_i=np.zeros(T),
            repetition_mult_i=repetition_mults[i],
'''))

PATCHES.append(('F7 final call', '''            cross_rhythm_support_i=cross_rhythm_support[i],
''', '''            cross_rhythm_support_i=cross_rhythm_support[i],
            repetition_mult_i=repetition_mults[i],
'''))


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"ERROR: {TARGET} not found in current directory.")

    with open(TARGET, 'r', encoding='utf-8') as f:
        src = f.read()

    if 'repetition_scores = []' not in src:
        sys.exit("ABORTED: repetition wiring not found "
                 "(run apply_repetition_wiring.py first). File not modified.")
    if 'repetition_mult_i' in src:
        sys.exit("ABORTED: fix2 appears to be already applied. "
                 "File not modified.")

    ok = True
    for name, old, _ in PATCHES:
        n = src.count(old)
        status = 'ok' if n == 1 else f'FAIL (found {n} occurrences)'
        print(f"  {name:18s} {status}")
        if n != 1:
            ok = False
    if not ok:
        sys.exit("ABORTED: anchors not unique/found. File not modified.")

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
        sys.exit(f"ABORTED: patched file failed to compile; restored.\n{e}")

    print("  py_compile         ok")
    print()
    print("Done. Deploy the UPDATED repetition_mask.py (v2) alongside, or")
    print("the rest-backed rule will silently not exist.")
    print("Re-run the A/B:")
    print("  python sectioning_v2_10_A.py liz.mxl -o out_default")
    print("  python sectioning_v2_10_A.py liz.mxl -o out_rep07 "
          "--delta_repetition 0.7")


if __name__ == '__main__':
    main()
