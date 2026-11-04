#!/usr/bin/env python
"""
patch_S01_provenance_and_rest_seam.py

Session 0 (provenance hardening) + Session 1 (rest-seam policy) for
sectioning_v2_10_D.py. Anchored in-place edits; aborts without writing
if any anchor is not found exactly once, or if the result fails to
compile.

SESSION 0 -- provenance:
  * run_sectioning captures every scalar knob via locals() and the
    input file's sha256, then augments the 'parameters' block of BOTH
    boundaries.json and result.pkl with:
      input_file, input_sha256, rest_seam_policy, all_knobs{...}
    boundaries_diff.py's parameter check will now catch experimental
    flags (delta_repetition!) and input drift automatically.

SESSION 1 -- rest_seam_policy ('legacy' default; NO output change until
flipped to 'seam'):
  legacy: current v2.9.1 behavior, bit-identical.
  seam:
    * A boundary at EXACTLY a note-end/rest-start seam (|bt - rest
      start| <= 0.02 qn) is no longer classified as in-rest; it is kept,
      target = the final note (breath after it). Recovers the 15.
    * A boundary landing within 0.25 qn BEFORE the target note's end,
      when that end is a seam, snaps TO the seam (rec['seam_snap_to']).
      Normalizes the 21 b4.88 keeps; closes issue 7's placement half.
    * Strictly-inside-rest boundaries are still rejected (the 38).
    * NEW DIAGNOSTIC FIELD ONLY: rec['boundary_at_entry_onset'] marks
      kept boundaries whose target is the first note after a gap (the
      26). No behavior change -- the penalty is a selection-stage
      feature, deferred per the "penalize, never ban" decision.

After patching, wire the policy with two direct edits (see chat), run
once with defaults (must be diff-identical apart from the parameters
block), then flip to 'seam' and diff. Expected under 'seam' on Liz:
~15 ADDED at seams, ~21 MOVED by <=0.25 qn onto seams, REMOVED ~0,
inside-rest rejections still 38 in the target records.

Usage: python patch_S01_provenance_and_rest_seam.py [sectioning_v2_10_D.py]
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
# S0-a: capture knobs + input hash before boundaries.json is written
# ---------------------------------------------------------------------------
OLD_S0A = """    summary_path = os.path.join(output_dir, 'boundaries.json')
    write_summary_per_part("""
NEW_S0A = """    import hashlib as _hashlib
    _knobs = {k: v for k, v in sorted(locals().items())
              if isinstance(v, (int, float, bool, str)) or v is None}
    try:
        with open(input_path, 'rb') as _f:
            _input_sha = _hashlib.sha256(_f.read()).hexdigest()[:16]
    except Exception:
        _input_sha = None

    summary_path = os.path.join(output_dir, 'boundaries.json')
    write_summary_per_part("""

# ---------------------------------------------------------------------------
# S0-b: augment boundaries.json parameters right after it is written.
# Anchor includes the structural_event_weights line to disambiguate this
# call site from function signatures and the validate call.
# ---------------------------------------------------------------------------
OLD_S0B = """        structural_event_weights=structural_event_weights,
        reject_rest_boundaries=reject_rest_boundaries,
        reject_outgoing_ties=reject_outgoing_ties,
    )
    material_path = os.path.join(output_dir, 'phrase_material.json')"""
NEW_S0B = """        structural_event_weights=structural_event_weights,
        reject_rest_boundaries=reject_rest_boundaries,
        reject_outgoing_ties=reject_outgoing_ties,
    )
    try:
        with open(summary_path, 'r', encoding='utf-8') as _f:
            _summary_doc = json.load(_f)
        _summary_doc['parameters'].update({
            'input_file': os.path.basename(str(input_path)),
            'input_sha256': _input_sha,
            'rest_seam_policy': _REST_SEAM_POLICY['policy'],
            'rest_seam_snap_qn': _REST_SEAM_POLICY['snap_qn'],
            'all_knobs': _knobs,
        })
        with open(summary_path, 'w', encoding='utf-8') as _f:
            json.dump(_summary_doc, _f, indent=2)
    except Exception as _e:
        print(f"       WARNING: could not augment parameters block: {_e}")
    material_path = os.path.join(output_dir, 'phrase_material.json')"""

# ---------------------------------------------------------------------------
# S0-c: same fields into result['parameters'] (pkl)
# ---------------------------------------------------------------------------
OLD_S0C = """        'parameters': {
            'division': division,"""
NEW_S0C = """        'parameters': {
            'input_file': os.path.basename(str(input_path)),
            'input_sha256': _input_sha,
            'rest_seam_policy': _REST_SEAM_POLICY['policy'],
            'rest_seam_snap_qn': _REST_SEAM_POLICY['snap_qn'],
            'all_knobs': _knobs,
            'division': division,"""

# ---------------------------------------------------------------------------
# S1-a: module-level policy, inserted before validate_boundaries_for_part
# ---------------------------------------------------------------------------
OLD_S1A = """def validate_boundaries_for_part(part, boundaries, slur_info, structural_info,"""
NEW_S1A = """# Rest-seam policy (session 1).
#   'legacy': v2.9.1 behavior -- a boundary at the exact note-end/rest-start
#             seam classifies as in-rest and is rejected (frame lottery).
#   'seam':   at-seam boundaries are kept (breath after the final note);
#             near-seam boundaries snap to the seam; only strictly-inside-
#             rest boundaries are rejected.
# Module-level so resolve/validate share it without signature changes; set
# from run_sectioning / the CLI before running.
_REST_SEAM_POLICY = {'policy': 'legacy', 'snap_qn': 0.25}


def validate_boundaries_for_part(part, boundaries, slur_info, structural_info,"""

# ---------------------------------------------------------------------------
# S1-b: new record fields in the rec literal
# ---------------------------------------------------------------------------
OLD_S1B = """        'reject_reason': None,
    }

    for ev in note_rest_events:"""
NEW_S1B = """        'reject_reason': None,
        'boundary_at_seam': False,
        'boundary_at_entry_onset': False,
        'seam_snap_to': None,
    }

    for ev in note_rest_events:"""

# ---------------------------------------------------------------------------
# S1-c: seam-aware in-rest classification
# ---------------------------------------------------------------------------
OLD_S1C = """    for ev in note_rest_events:
        if ev['is_rest'] and ev['offset'] - 0.01 <= bt < ev['end'] - 0.01:
            rec['boundary_lies_in_rest'] = True
            rec['rest_offset'] = ev['offset']
            rec['rest_duration'] = ev['duration']
            break"""
NEW_S1C = """    for ev in note_rest_events:
        if ev['is_rest'] and ev['offset'] - 0.01 <= bt < ev['end'] - 0.01:
            rec['rest_offset'] = ev['offset']
            rec['rest_duration'] = ev['duration']
            if (_REST_SEAM_POLICY['policy'] == 'seam'
                    and abs(bt - ev['offset']) <= 0.02):
                # Exactly at the note-end/rest-start seam: this is the
                # phrase's exit edge, not an in-rest boundary.
                rec['boundary_at_seam'] = True
            else:
                rec['boundary_lies_in_rest'] = True
            break"""

# ---------------------------------------------------------------------------
# S1-d: near-seam snap + entry-onset diagnostic, before resolve() returns
# ---------------------------------------------------------------------------
OLD_S1D = """    if rec['target_has_outgoing_tie']:
        rec['valid'] = False
        rec['reject_reason'] = 'target_has_outgoing_tie'

    return rec, target"""
NEW_S1D = """    if rec['target_has_outgoing_tie']:
        rec['valid'] = False
        rec['reject_reason'] = 'target_has_outgoing_tie'

    # 'seam' policy: a boundary landing inside the target note within
    # snap_qn of its end, when that end is a rest start, snaps to the
    # seam (normalizes near-seam keeps; consistent placement semantics).
    if (_REST_SEAM_POLICY['policy'] == 'seam'
            and rec.get('target_offset') is not None
            and rec.get('target_duration') is not None):
        _t_end = rec['target_offset'] + rec['target_duration']
        if (rec['target_offset'] - 1e-6 <= bt < _t_end - 1e-6
                and 0.0 < _t_end - bt <= _REST_SEAM_POLICY['snap_qn']):
            for ev in note_rest_events:
                if ev['is_rest'] and abs(ev['offset'] - _t_end) <= 0.02:
                    rec['seam_snap_to'] = float(_t_end)
                    rec['boundary_at_seam'] = True
                    break

    # Diagnostic only (no behavior): mark boundaries whose target is the
    # first note after a gap -- entry-onset marks, pending the selection-
    # stage penalty ("penalize, never ban").
    if rec.get('target_offset') is not None:
        for ev in note_rest_events:
            if ev['is_rest'] and abs(ev['end'] - rec['target_offset']) <= 0.02:
                rec['boundary_at_entry_onset'] = bool(
                    rec.get('target_reason') == 'primary_note'
                    and abs(bt - rec['target_offset']) <= 0.02)
                break

    return rec, target"""

# ---------------------------------------------------------------------------
# S1-e: kept boundaries use the snapped time
# ---------------------------------------------------------------------------
OLD_S1E = """        rec['kept'] = valid
        if valid:
            kept.append(float(bt))
        records.append(rec)"""
NEW_S1E = """        rec['kept'] = valid
        if valid:
            _bt_out = rec.get('seam_snap_to')
            kept.append(float(_bt_out) if _bt_out is not None else float(bt))
        records.append(rec)"""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'sectioning_v2_10_D.py'
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()

    src = replace_once(src, OLD_S0A, NEW_S0A, 'S0-a knob capture')
    src = replace_once(src, OLD_S0B, NEW_S0B, 'S0-b boundaries.json augment')
    src = replace_once(src, OLD_S0C, NEW_S0C, 'S0-c pkl parameters')
    src = replace_once(src, OLD_S1A, NEW_S1A, 'S1-a policy global')
    src = replace_once(src, OLD_S1B, NEW_S1B, 'S1-b rec fields')
    src = replace_once(src, OLD_S1C, NEW_S1C, 'S1-c seam classification')
    src = replace_once(src, OLD_S1D, NEW_S1D, 'S1-d snap + entry diagnostic')
    src = replace_once(src, OLD_S1E, NEW_S1E, 'S1-e snapped kept time')

    try:
        compile(src, path, 'exec')
    except SyntaxError as e:
        raise SystemExit(f"ABORT: patched source fails to compile: {e}. "
                         f"File unchanged.")

    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"Patched {path}: S0 provenance (2 sites + capture) and S1 "
          f"rest-seam policy (4 sites, default 'legacy' -- no output "
          f"change until flipped to 'seam').")


if __name__ == '__main__':
    main()
