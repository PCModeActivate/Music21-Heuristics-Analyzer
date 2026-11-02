#!/usr/bin/env python3
"""
roadmap_status.py -- verify roadmap item presence against the actual source.

Greps the live codebase for a distinctive marker per roadmap item and
compares against the expected status. Exit code = number of SURPRISES
(found-but-expected-absent, or absent-but-expected-found), following the
audit_check.py convention.

This is a status probe, not a test: a marker proves the code path exists,
not that it is correct or validated. Items marked PASSIVE or UNVALIDATED
in the notes column are present but not earning their keep.

Usage:
    python roadmap_status.py                       # defaults to cwd
    python roadmap_status.py --root ~/sectioning
    python roadmap_status.py --pipeline sectioning_v2_10_F1.py
"""

import argparse
import os
import re
import sys

# (roadmap, marker regex, file glob hint, expected, note)
PROBES = [
    ("A   phrase material",     r"too_long_to_breathe",        "phrase_material.py", True,  "PASSIVE: nothing consumes the flags"),
    ("B   interval kernel",     r"chroma_kernel",              "PIPELINE",           True,  "UNVALIDATED: never run musically"),
    ("C   offset grouping",     r"lbdm_polyphony_mode",        "PIPELINE",           True,  ""),
    ("D   dedup + fermata",     r"dedup_window_qn|'fermata'",  "PIPELINE",           True,  ""),
    ("E1  cross attribution",   r"explain_cross_support",      "PIPELINE",           True,  ""),
    ("G0  one-note wedge",      r"getOffsetInHierarchy",       "PIPELINE",           True,  "weak marker; confirm by eye"),
    ("S0  knob serialization",  r"all_knobs",                  "PIPELINE",           True,  ""),
    ("S0  input hash",          r"input_sha256",               "PIPELINE",           True,  ""),
    ("S1  seam policy",         r"_REST_SEAM_POLICY",          "PIPELINE",           True,  ""),
    ("E0  release retarget",    r"_ANNOT_RELEASE_RETARGET",    "PIPELINE",           True,  ""),
    ("E0b release anchoring",   r"e0b_shift_info",             "PIPELINE",           True,  ""),
    ("F1  expressive release",  r"_F1_EXPRESSIVE",             "PIPELINE",           True,  ""),
    ("F1  explain patch",       r"_f1_explain_block",          "PIPELINE",           True,  ""),
    # --- expected ABSENT: anything found here means the snapshot is stale ---
    ("F1b slur deferral",       r"_f1_slur_defer|defer_to_slur_end",   "PIPELINE", False, ""),
    ("F1b rest-gated seam",     r"rest_after|restAfter",               "PIPELINE", False, ""),
    ("F1b F1 through mult",     r"F1_THROUGH_MULT",                    "PIPELINE", False, ""),
    ("D1  typed channels",      r"struct_change|zeta_change|channel_type", "PIPELINE", False, ""),
    ("D1  start/end edge",      r"start_edge|end_edge",                "PIPELINE", False, ""),
    ("E   snap arbitration",    r"snap_arbitrat|ensemble_align",       "PIPELINE", False, ""),
    ("E   breathability",       r"breathability|Theta_breath",         "PIPELINE", False, ""),
    ("G1  unclassified text",   r"unclassified_text",                  "PIPELINE", False, ""),
    ("G2  rehearsal marks",     r"RehearsalMark",                      "PIPELINE", False, ""),
    ("H   ornament spans",      r"delta_ornament|ornament_delta",      "PIPELINE", False, ""),
]


def find_pipeline(root):
    """Newest sectioning_v2_*.py by version-ish sort."""
    cands = [f for f in os.listdir(root)
             if re.match(r"sectioning_v2_.*\.py$", f)]
    if not cands:
        return None
    return sorted(cands)[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--pipeline", default=None,
                    help="pipeline filename; default = newest sectioning_v2_*.py")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    pipeline = args.pipeline or find_pipeline(root)
    if pipeline is None:
        sys.exit("No sectioning_v2_*.py found in %s" % root)

    print("root     : %s" % root)
    print("pipeline : %s\n" % pipeline)

    cache = {}

    def read(name):
        if name not in cache:
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    cache[name] = fh.read()
            except OSError:
                cache[name] = None
        return cache[name]

    surprises = 0
    print("%-24s %-8s %-8s %-8s %s"
          % ("ROADMAP", "EXPECT", "FOUND", "VERDICT", "NOTE"))
    print("-" * 86)

    for label, pattern, where, expected, note in PROBES:
        fname = pipeline if where == "PIPELINE" else where
        src = read(fname)
        if src is None:
            found, verdict = False, "NOFILE"
            surprises += 1
        else:
            found = bool(re.search(pattern, src))
            if found == expected:
                verdict = "ok"
            else:
                verdict = "SURPRISE"
                surprises += 1
        print("%-24s %-8s %-8s %-8s %s"
              % (label,
                 "present" if expected else "absent",
                 "present" if found else "absent",
                 verdict, note))

    print("-" * 86)
    print("surprises: %d" % surprises)
    if surprises:
        print("\nA SURPRISE means the roadmap table disagrees with the source.")
        print("Either the item shipped and the table is stale, or a marker")
        print("regex is wrong. Check the marker before believing the table.")
    return surprises


if __name__ == "__main__":
    sys.exit(main())
