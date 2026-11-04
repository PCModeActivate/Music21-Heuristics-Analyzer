#!/usr/bin/env python3
"""
patch_F1_explain.py — teach explain about the F1 expressive release channel.

Target: sectioning_v2_10_F1.py (pass path as argv[1] if named otherwise).
Strict verbatim anchors; aborts with the file unchanged on any mismatch.
No backups. Compile-checked before writing.

WHY
  F1 adds evidence to B_i AFTER the continuation multiplier, so explain's
  identity line "(B_raw + boost) * mult = B_i" is arithmetically wrong at
  every injected frame — B_i reads higher than its printed parts. Auditing
  by eye against a lying explain is exactly the failure this project has
  paid for before.

WHAT IT ADDS (diagnostics only — boundaries are untouched)
  1. The identity line is corrected: base term, F1 term, then B_i.
  2. A new "F1 expressive release evidence" block listing every F1 event
     within the window with kind / anchor / weight / fate, plus:
       - slur status of each anchor under breath semantics, including the
         half-open case (anchor == last slurred note's ONSET), which the
         in_slur_interior mask does NOT flag;
       - any E0b shift that moved the anchor elsewhere, with its reason.
  3. Reads f1_events.json from parameters.all_knobs['output_dir'], so it
     works on EXISTING result.pkl files with no re-run. Runs made before
     F1 simply print nothing.

APPLY
    python patch_F1_explain.py sectioning_v2_10_F1.py
Then, unchanged workflow:
    python explain.py output_v2_10_F1/liz_seam_F1 5 41 4
"""

import sys


def replace_once(src, old, new, label):
    n = src.count(old)
    if n != 1:
        raise SystemExit(
            f"ABORT [{label}]: anchor found {n} times (need exactly 1). "
            f"File unchanged.")
    return src.replace(old, new, 1)


# ---------------------------------------------------------------------------
# X1: helpers, inserted immediately before the F1 knob block.
# ---------------------------------------------------------------------------
OLD_X1 = """_F1_EXPRESSIVE = {"""
NEW_X1 = '''_F1_EXPLAIN_CACHE = {}


def _f1_explain_load(result):
    """(weights, events) from the run's f1_events.json, or (None, None)."""
    ak = (result.get('parameters', {}) or {}).get('all_knobs', {}) or {}
    out_dir = ak.get('output_dir')
    if not out_dir:
        return None, None
    path = os.path.join(str(out_dir), 'f1_events.json')
    if path not in _F1_EXPLAIN_CACHE:
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                doc = json.load(fh)
            _F1_EXPLAIN_CACHE[path] = (doc.get('weights') or {},
                                       doc.get('events') or [])
        except Exception:
            _F1_EXPLAIN_CACHE[path] = (None, None)
    return _F1_EXPLAIN_CACHE[path]


def _f1_explain_slur_status(slur_info_i, anchor, division):
    """Slur position of a release anchor under breath semantics.

    in_slur_interior covers [first onset, last onset), so an anchor sitting
    exactly on the LAST slurred note's onset reads 0 while a breath there
    still separates that note from the rest of the slur. Report both.
    """
    try:
        anchor = float(anchor)
        mask = slur_info_i['in_slur_interior']
        f = int(round(anchor * division))
        if 0 <= f < len(mask) and float(mask[f]) > 0.0:
            return 'INSIDE SLUR (breath forbidden here)'
        for s, e in zip(slur_info_i.get('slur_starts', []),
                        slur_info_i.get('slur_ends', [])):
            if abs(float(e) - anchor) <= 1e-6 and float(s) < anchor:
                return ('AT LAST-SLURRED-NOTE ONSET (slur %.2f->%.2f): a '
                        'breath here separates the final slurred note'
                        % (float(s), float(e)))
    except Exception:
        pass
    return ''


def _f1_explain_shift(result, part_idx, anchor):
    """Any E0b shift that moved this anchor, as a printable suffix."""
    try:
        shifts = (result.get('e0b_shift_info') or [])[part_idx]
    except Exception:
        return ''
    for s in shifts or []:
        try:
            frm, to = float(s.get('from')), float(s.get('to'))
        except (TypeError, ValueError):
            continue
        if abs(frm - float(anchor)) <= 1e-3 and abs(to - frm) > 1e-3:
            return '  -> E0b moved it to %.3f [%s]' % (to, s.get('reason'))
    return ''


def _f1_explain_block(result, part_idx, actual_t, idx, division, window_qn):
    """Print the F1 section. Returns the injected value at this frame."""
    weights, events = _f1_explain_load(result)
    if events is None:
        return 0.0
    try:
        slur_info_i = result['slur_info'][part_idx]
    except Exception:
        slur_info_i = {}

    here = 0.0
    in_window = []
    for e in events:
        if int(e.get('part', -1)) != int(part_idx):
            continue
        anchor = e.get('anchor_qn')
        ref = anchor if anchor is not None else e.get('raw_qn')
        if ref is None or abs(float(ref) - float(actual_t)) > window_qn:
            continue
        in_window.append(e)
        if e.get('fate') == 'injected' and anchor is not None \\
                and int(round(float(anchor) * division)) == idx:
            here += float(e.get('weight') or 0.0)

    print("F1 expressive release evidence:")
    if weights:
        print("  weights: " + ", ".join(
            "%s=%.2f" % (k.replace('_weight', ''), float(v))
            for k, v in sorted(weights.items())))
    print("  injected at THIS frame: %+.3f" % here)
    if not in_window:
        print("  (no F1 events within the window)")
    else:
        for e in sorted(in_window,
                        key=lambda x: float(x.get('anchor_qn')
                                            if x.get('anchor_qn') is not None
                                            else x.get('raw_qn'))):
            anchor = e.get('anchor_qn')
            loc = ('anchor %8.3f' % float(anchor)) if anchor is not None \\
                else ('raw    %8.3f' % float(e.get('raw_qn')))
            print("    %s  %-16s w%.2f  %-22s %s"
                  % (loc, e.get('kind', '?'), float(e.get('weight') or 0.0),
                     e.get('fate', '?'), e.get('detail', '')))
            if anchor is not None:
                note = _f1_explain_slur_status(slur_info_i, anchor, division)
                if note:
                    print("        ** %s **" % note)
                shift = _f1_explain_shift(result, part_idx, anchor)
                if shift:
                    print("      %s" % shift.strip())
    print()
    return here


_F1_EXPRESSIVE = {'''

# ---------------------------------------------------------------------------
# X2: correct the identity line and print the block. The three-line
# "(B_raw + boost) * effective continuation multiplier" print is unique.
# ---------------------------------------------------------------------------
OLD_X2 = """    print(f"  (B_raw + boost) * effective continuation multiplier")
    print(f"  = ({B_raw_v:.3f} + {boost_total:.3f}) * {effective_mult:.2f}")
    print(f"  = {B_i_v:.3f}")
    print()"""
NEW_X2 = """    _f1_base = (B_raw_v + boost_total) * effective_mult
    print(f"  (B_raw + boost) * effective continuation multiplier")
    print(f"  = ({B_raw_v:.3f} + {boost_total:.3f}) * {effective_mult:.2f}")
    print(f"  = {_f1_base:.3f}")
    _f1_here = _f1_explain_block(result, part_idx, actual_t, idx,
                                 division, window_qn)
    if abs(_f1_here) > 1e-9:
        print(f"  + F1 expressive release evidence: {_f1_here:+.3f}")
    print(f"  = B_i {B_i_v:.3f}")
    if abs(_f1_base + _f1_here - B_i_v) > 5e-3:
        print(f"  NOTE: components do not reconstruct B_i "
              f"(residual {B_i_v - _f1_base - _f1_here:+.3f}) -- "
              f"an unprinted term is contributing.")
    print()"""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'sectioning_v2_10_F1.py'
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()

    src = replace_once(src, OLD_X1, NEW_X1, 'X1 explain helpers')
    src = replace_once(src, OLD_X2, NEW_X2, 'X2 identity line + F1 block')

    try:
        compile(src, path, 'exec')
    except SyntaxError as e:
        raise SystemExit("ABORT: patched source fails to compile: %s. "
                         "File unchanged." % e)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print("Patched %s: explain now prints the F1 term, nearby F1 events "
          "with slur status and E0b re-anchoring, and warns if the printed "
          "components fail to reconstruct B_i.\n"
          "Diagnostic-only: boundaries.json is unaffected and no re-run is "
          "needed." % path)


if __name__ == '__main__':
    main()
