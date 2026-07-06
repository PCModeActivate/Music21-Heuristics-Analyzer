#!/usr/bin/env python
"""
apply_chroma_kernel_B.py  --  v2.10-B: chroma SSM interval-kernel switch

Plumbs the ALREADY-EXISTING make_chroma_interval_kernel() (13x13,
interval-class weights + rest dimension, previously used only for the
cross-part diagnostic) into the per-part chroma SSM construction.

Adds:
    run_sectioning(..., chroma_kernel='exact')     # or 'interval'
    --chroma_kernel exact|interval                 # CLI, default exact

With 'exact' (default), build_ssm_with_kernel(phi, None) is the plain
dot product -- bit-identical to pre-patch behavior. With 'interval',
chroma self-similarity uses the explainable interval-class table
(unison 1.0, m3/M3 0.70/0.75, tritone 0.10, ...), so transposed or
intervallically-related material registers as similar and chroma
novelty fires on harmonic change rather than exact pitch-class change.

alpha_chroma is deliberately untouched: novelty is normalized per-part
inside compute_per_part_boundary_signal regardless of kernel, and
changing the mixing weight in the same run would conflate two effects.

Requires the repetition wiring + CLI + fix2 patches (anchors depend on
them); aborts otherwise.

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
# B1: run_sectioning kwarg
# ---------------------------------------------------------------------------
PATCHES.append(('B1 kwarg', '''                    repetition_window_qn=1.0,
''', '''                    repetition_window_qn=1.0,
                    chroma_kernel='exact',
'''))

# ---------------------------------------------------------------------------
# B2a: build the kernel once, before the novelty loop
# ---------------------------------------------------------------------------
PATCHES.append(('B2a kernel build', '''    rep_available = compute_repetition_score is not None
''', '''    chroma_feature_kernel = (make_chroma_interval_kernel()
                             if chroma_kernel == 'interval' else None)
    if chroma_feature_kernel is not None:
        print("       chroma SSM kernel: interval-class (v2.10-B)")
    rep_available = compute_repetition_score is not None
'''))

# ---------------------------------------------------------------------------
# B2b: use it in the per-part chroma SSM
# ---------------------------------------------------------------------------
PATCHES.append(('B2b chroma SSM', '''        chroma_ssm = build_ssm(phi_chroma[i])
''', '''        chroma_ssm = build_ssm_with_kernel(phi_chroma[i],
                                           chroma_feature_kernel)
'''))

# ---------------------------------------------------------------------------
# B3: record in parameters dict
# ---------------------------------------------------------------------------
PATCHES.append(('B3 parameters', '''            'repetition_window_qn': repetition_window_qn,
''', '''            'repetition_window_qn': repetition_window_qn,
            'chroma_kernel': chroma_kernel,
'''))

# ---------------------------------------------------------------------------
# B4: CLI argument
# ---------------------------------------------------------------------------
PATCHES.append(('B4 argparse', '''    parser.add_argument('--repetition_window_qn', type=float, default=1.0,
                        help='Half-window (qn) for local context comparison')
''', '''    parser.add_argument('--repetition_window_qn', type=float, default=1.0,
                        help='Half-window (qn) for local context comparison')
    parser.add_argument('--chroma_kernel', choices=['exact', 'interval'],
                        default='exact',
                        help='Chroma SSM similarity: exact pitch-class '
                             'match (default) or interval-class kernel '
                             '(v2.10-B)')
'''))

# ---------------------------------------------------------------------------
# B5: CLI pass-through
# ---------------------------------------------------------------------------
PATCHES.append(('B5 passthrough', '''        repetition_window_qn=args.repetition_window_qn,
''', '''        repetition_window_qn=args.repetition_window_qn,
        chroma_kernel=args.chroma_kernel,
'''))


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"ERROR: {TARGET} not found in current directory.")

    with open(TARGET, 'r', encoding='utf-8') as f:
        src = f.read()

    if 'repetition_mult_i' not in src or '--repetition_window_qn' not in src:
        sys.exit("ABORTED: expected wiring + CLI + fix2 patches in the "
                 "target first. File not modified.")
    if 'chroma_feature_kernel' in src:
        sys.exit("ABORTED: v2.10-B appears to be already applied. "
                 "File not modified.")

    ok = True
    for name, old, _ in PATCHES:
        n = src.count(old)
        status = 'ok' if n == 1 else f'FAIL (found {n} occurrences)'
        print(f"  {name:16s} {status}")
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

    print("  py_compile       ok")
    print()
    print("Done. Default (--chroma_kernel exact) is bit-identical.")
    print("A/B:  python sectioning_v2_10_A.py liz.mxl -o out_interval "
          "--chroma_kernel interval")


if __name__ == '__main__':
    main()
