#!/usr/bin/env python
"""
explain.py — diagnostic CLI for sectioning_v2_5 results.

After running sectioning_v2_5.py on a piece, the output directory will
contain a result.pkl file alongside the diagnostics.png, boundaries.json,
and sectioned.musicxml files. This script loads that cached result and
calls explain() on a specific (part, measure, beat).

Usage:
    python explain.py <output_dir> <part_idx> <measure> [beat]

Example:
    python explain.py ./out_v25 0 7 1.0

The part_idx is zero-indexed and corresponds to the indices shown in
boundaries.json or in the sectioning console output.

If you'd rather use time in quarter notes instead of measure/beat:
    python explain.py <output_dir> <part_idx> --time <qn>
"""

import os
import sys
import argparse

# Add the directory containing sectioning_v2_5.py to sys.path so this
# script can be run from anywhere as long as it's next to the module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sectioning_v2_10_A import load_result, explain

def main():
    parser = argparse.ArgumentParser(
        description="Explain why a boundary did or didn't land at a "
                    "specific point in a sectioning result.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('output_dir',
                        help='Output directory from sectioning run '
                             '(must contain result.pkl)')
    parser.add_argument('part_idx', type=int,
                        help='Part index (zero-indexed; see boundaries.json)')
    parser.add_argument('measure', type=int, nargs='?', default=None,
                        help='Measure number (1-indexed)')
    parser.add_argument('beat', type=float, nargs='?', default=1.0,
                        help='Beat in measure (1-indexed, default 1.0)')
    parser.add_argument('--time', type=float, default=None,
                        help='Time in quarter notes (alternative to '
                             'measure/beat)')
    parser.add_argument('--window', type=float, default=4.0,
                        help='Window in qn for context (default 4.0)')

    args = parser.parse_args()

    cache_path = os.path.join(args.output_dir, 'result.pkl')
    if not os.path.exists(cache_path):
        print(f"ERROR: {cache_path} not found.")
        print(f"Run sectioning_v2_5.py first to produce it.")
        sys.exit(1)

    result = load_result(cache_path)

    if args.time is not None:
        explain(result, part_idx=args.part_idx,
                time_qn=args.time, window_qn=args.window)
    elif args.measure is not None:
        explain(result, part_idx=args.part_idx,
                measure=args.measure, beat=args.beat,
                window_qn=args.window)
    else:
        print("ERROR: Must provide either a measure number or --time")
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
