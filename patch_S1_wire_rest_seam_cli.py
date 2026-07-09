#!/usr/bin/env python
"""
patch_S1_wire_rest_seam_cli.py

Completes the S0/S1 patch by wiring rest_seam_policy end-to-end:

  W1  run_sectioning() gains rest_seam_policy='legacy' as a keyword arg
  W2  the first line of its body sets _REST_SEAM_POLICY['policy'] so
      resolve_breath_target_for_part / validate_boundaries_for_part
      (already patched) pick it up
  W3  main()'s argparse gains --rest_seam_policy {legacy,seam}
  W4  the run_sectioning(...) call in main() passes it through

Run this AFTER patch_S01_provenance_and_rest_seam.py has already been
applied (it targets the same file). Anchored edits; aborts without
writing if any anchor is not found exactly once, or if the result
fails to compile.

Usage:
    python patch_S1_wire_rest_seam_cli.py [sectioning_v2_10_D.py]

If you committed the S0/S1 patch under a different filename (e.g.
sectioning_v2_10_D_patch.py), pass that path instead.
"""

import sys


def replace_once(src, old, new, label):
    n = src.count(old)
    if n != 1:
        raise SystemExit(
            f"ABORT [{label}]: anchor found {n} times, expected exactly 1. "
            f"File unchanged.")
    return src.replace(old, new)


# ---------------------------------------------------------------------------
# W1: add the kwarg at the end of run_sectioning's signature
# ---------------------------------------------------------------------------
OLD_W1 = """                    convention='muller',
                    tacet_threshold=0.05,
                    breath_color='#d62728'):
    \"\"\"
    V2.9.1 top-level pipeline."""
NEW_W1 = """                    convention='muller',
                    tacet_threshold=0.05,
                    breath_color='#d62728',
                    rest_seam_policy='legacy'):
    \"\"\"
    V2.9.1 top-level pipeline."""

# ---------------------------------------------------------------------------
# W2: set the module-level switch as the first line of the body, right
# after the docstring closes (anchor = the docstring's distinctive tail).
# ---------------------------------------------------------------------------
OLD_W2 = """        cross-part synchronous rhythm and musical-chroma similarities are
        computed and stored in result['cross_similarity_info'], but they
        are not used for boundary decisions in this version.
    \"\"\""""
NEW_W2 = """        cross-part synchronous rhythm and musical-chroma similarities are
        computed and stored in result['cross_similarity_info'], but they
        are not used for boundary decisions in this version.
    \"\"\"
    _REST_SEAM_POLICY['policy'] = rest_seam_policy"""

# ---------------------------------------------------------------------------
# W3: CLI flag, inserted right before --tacet_threshold
# ---------------------------------------------------------------------------
OLD_W3 = """    parser.add_argument('--convention', choices=['muller', 'foote'],
                        default='muller')
    parser.add_argument('--tacet_threshold', type=float, default=0.05)
    parser.add_argument('--breath_color', default='#d62728')

    args = parser.parse_args()"""
NEW_W3 = """    parser.add_argument('--convention', choices=['muller', 'foote'],
                        default='muller')
    parser.add_argument('--rest_seam_policy', choices=['legacy', 'seam'],
                        default='legacy',
                        help="'legacy': at-seam boundaries classify as "
                             "in-rest (v2.9.1 behavior). 'seam': at-seam "
                             "boundaries are kept (breath after the final "
                             "note), near-seam boundaries snap to the "
                             "seam, only strictly-inside-rest boundaries "
                             "are rejected.")
    parser.add_argument('--tacet_threshold', type=float, default=0.05)
    parser.add_argument('--breath_color', default='#d62728')

    args = parser.parse_args()"""

# ---------------------------------------------------------------------------
# W4: pass it through in the run_sectioning(...) call
# ---------------------------------------------------------------------------
OLD_W4 = """        chroma_kernel=args.chroma_kernel,
        convention=args.convention,
        tacet_threshold=args.tacet_threshold,
        breath_color=args.breath_color,
    )


if __name__ == '__main__':
    main()"""
NEW_W4 = """        chroma_kernel=args.chroma_kernel,
        convention=args.convention,
        tacet_threshold=args.tacet_threshold,
        breath_color=args.breath_color,
        rest_seam_policy=args.rest_seam_policy,
    )


if __name__ == '__main__':
    main()"""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'sectioning_v2_10_D.py'
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()

    src = replace_once(src, OLD_W1, NEW_W1, 'W1 signature kwarg')
    src = replace_once(src, OLD_W2, NEW_W2, 'W2 policy setter')
    src = replace_once(src, OLD_W3, NEW_W3, 'W3 CLI flag')
    src = replace_once(src, OLD_W4, NEW_W4, 'W4 call site pass-through')

    try:
        compile(src, path, 'exec')
    except SyntaxError as e:
        raise SystemExit(f"ABORT: patched source fails to compile: {e}. "
                         f"File unchanged.")

    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"Patched {path}: rest_seam_policy wired through run_sectioning() "
          f"and --rest_seam_policy added to the CLI. Default remains "
          f"'legacy' -- run A should still be diff-identical.")


if __name__ == '__main__':
    main()
