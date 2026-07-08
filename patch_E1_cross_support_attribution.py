#!/usr/bin/env python
"""
patch_E1_cross_support_attribution.py

E1 (first deliverable of roadmap item E): cross-support attribution.
Applies in-place anchored edits to sectioning_v2_10_C.py:

  1. compute_cross_rhythm_support gains attribution_out=None. When a
     dict is passed, it is filled with:
       'sim'         (N,N,T) float32 -- window cosine wherever the
                     similarity gate passed (even if contribution was 0)
       'contrib'     (N,N,T) float32 -- sim * borrowed local_B_near
       'raw_support' (N,T)  -- support BEFORE per-part normalization
       'local_B_pre' (N,T) float32 -- first-pass local evidence
       'shift_frames', 'window_qn', 'similarity_threshold'
  2. run_sectioning passes a dict and stores it as
     result['cross_support_attribution'] (pickled; ~3-4 MB extra).
  3. New top-level function explain_cross_support(result, part_idx,
     time_qn=None, measure=None, beat=1.0): per-source attribution at a
     point -- similarity, borrowed evidence within max_shift, and the
     nearest peak within a wider display window with its distance in qn
     (the E snap-design view).

PURE DIAGNOSTICS: boundaries.json / sectioned.musicxml must be
bit-identical before and after this patch. result.pkl grows.

Usage:  python patch_E1_cross_support_attribution.py [sectioning_v2_10_C.py]

Aborts without writing if any anchor is not found exactly once, or if
the patched source fails to compile.
"""

import re
import sys


def replace_once(src, old, new, label):
    n = src.count(old)
    if n != 1:
        raise SystemExit(
            f"ABORT [{label}]: anchor found {n} times, expected exactly 1. "
            f"File unchanged.")
    return src.replace(old, new)


# ---------------------------------------------------------------------------
# Edit 1: function signature -- add attribution_out=None
# ---------------------------------------------------------------------------
OLD_SIG = """                                  window_qn=4.0,
                                  similarity_threshold=0.85,
                                  max_shift_qn=0.5,
                                  min_active_qn=0.5):"""
NEW_SIG = """                                  window_qn=4.0,
                                  similarity_threshold=0.85,
                                  max_shift_qn=0.5,
                                  min_active_qn=0.5,
                                  attribution_out=None):"""

# ---------------------------------------------------------------------------
# Edit 2: allocate the attribution matrices next to `support`
# ---------------------------------------------------------------------------
OLD_ALLOC = """    support = np.zeros((N, T), dtype=float)"""
NEW_ALLOC = """    sim_matrix = np.zeros((N, N, T), dtype=np.float32)
    contrib_matrix = np.zeros((N, N, T), dtype=np.float32)
    support = np.zeros((N, T), dtype=float)"""

# ---------------------------------------------------------------------------
# Edit 3: record sim + contribution inside the gate
# ---------------------------------------------------------------------------
OLD_GATE = """                if sim >= similarity_threshold:
                    vals.append(sim * local_B_near[j, t])"""
NEW_GATE = """                if sim >= similarity_threshold:
                    c = sim * local_B_near[j, t]
                    sim_matrix[i, j, t] = sim
                    contrib_matrix[i, j, t] = c
                    vals.append(c)"""

# ---------------------------------------------------------------------------
# Edit 4: fill attribution_out with the RAW (pre-normalization) support
# ---------------------------------------------------------------------------
OLD_NORM = """    # Normalize per part so the scale is comparable across sparse/dense parts."""
NEW_NORM = """    if attribution_out is not None:
        attribution_out['sim'] = sim_matrix
        attribution_out['contrib'] = contrib_matrix
        attribution_out['raw_support'] = support.copy()
        attribution_out['local_B_pre'] = np.asarray(
            local_B_pre, dtype=np.float32).copy()
        attribution_out['shift_frames'] = int(shift_frames)
        attribution_out['window_qn'] = float(window_qn)
        attribution_out['similarity_threshold'] = float(similarity_threshold)

    # Normalize per part so the scale is comparable across sparse/dense parts."""

# ---------------------------------------------------------------------------
# Edit 5: call site -- pass the dict
# ---------------------------------------------------------------------------
OLD_CALL = """    cross_rhythm_support = compute_cross_rhythm_support(
        phi_rhythm, activity, local_B_pre, is_tacet, division,
        window_qn=cross_rhythm_window_qn,
        similarity_threshold=cross_rhythm_similarity_threshold,
        max_shift_qn=cross_rhythm_max_shift_qn,
    )"""
NEW_CALL = """    cross_support_attribution = {}
    cross_rhythm_support = compute_cross_rhythm_support(
        phi_rhythm, activity, local_B_pre, is_tacet, division,
        window_qn=cross_rhythm_window_qn,
        similarity_threshold=cross_rhythm_similarity_threshold,
        max_shift_qn=cross_rhythm_max_shift_qn,
        attribution_out=cross_support_attribution,
    )"""

# ---------------------------------------------------------------------------
# Edit 6: store in result just before the cache write
# ---------------------------------------------------------------------------
OLD_CACHE = """    cache_path = os.path.join(output_dir, 'result.pkl')"""
NEW_CACHE = """    result['cross_support_attribution'] = cross_support_attribution

    cache_path = os.path.join(output_dir, 'result.pkl')"""

# ---------------------------------------------------------------------------
# Edit 7: new explain function, inserted before the Explain banner
# ---------------------------------------------------------------------------
NEW_FUNC = '''# =============================================================================
# E1: Cross-support attribution -- who lent evidence, and how much
# =============================================================================

def _measure_beat_to_qn_defensive(result, measure, beat=1.0):
    """Measure/beat -> qn. Uses result['measure_offsets'] when it is a
    flat numeric list; falls back to the 4/4 convention (Liz)."""
    mo = result.get('measure_offsets')
    try:
        base = float(mo[int(measure) - 1])
        return base + (float(beat) - 1.0)
    except Exception:
        return (float(measure) - 1.0) * 4.0 + (float(beat) - 1.0)


def explain_cross_support(result, part_idx, time_qn=None, measure=None,
                          beat=1.0, display_window_qn=2.0, top_k=None):
    """
    Print cross-rhythm support attribution at a (part, time) point.

    Lists every source part j that passed the similarity gate for
    part_idx at the inspected frame, sorted by contribution:

      - window cosine similarity
      - borrowed evidence (max of j's first-pass B within +-max_shift)
        and the contribution sim * borrowed
      - the nearest peak of j's first-pass B within a WIDER display
        window (default +-2 qn) and its distance -- sources that are
        similar but whose evidence sits outside max_shift show up with
        contribution 0.000 and a nonzero peak distance. This is the E
        snap-tolerance view.

    Requires result['cross_support_attribution'] (E1 patch). Purely
    diagnostic; works from the pickle alone.
    """
    attr = result.get('cross_support_attribution')
    if not attr or 'sim' not in attr:
        print("No cross_support_attribution in result -- re-run the "
              "pipeline after applying the E1 patch.")
        return

    division = int(result.get('division', 8))
    if time_qn is None:
        if measure is None:
            raise ValueError("Provide time_qn or measure")
        time_qn = _measure_beat_to_qn_defensive(result, measure, beat)

    sim = attr['sim']
    contrib = attr['contrib']
    local_B_pre = attr.get('local_B_pre')
    shift = int(attr.get('shift_frames', 0))
    N, _, T = sim.shape
    t = max(0, min(T - 1, int(round(time_qn * division))))
    i = int(part_idx)
    disp = max(int(round(display_window_qn * division)), shift)

    part_names = result.get('part_names') or [
        'part{}'.format(k) for k in range(N)]

    def _name(k):
        return part_names[k] if k < len(part_names) else str(k)

    print("=== Cross-support attribution: part {} ({}) at qn {:.2f} "
          "(frame {}) ===".format(i, _name(i), time_qn, t))
    print("    window_qn={}, threshold={}, max_shift={} frames "
          "({:.2f} qn)".format(
              attr.get('window_qn'), attr.get('similarity_threshold'),
              shift, shift / float(division)))

    rows = []
    for j in range(N):
        s = float(sim[i, j, t])
        if s <= 0.0:
            continue
        c = float(contrib[i, j, t])
        borrowed = c / s if s > 0 else 0.0
        peak_qn, peak_val = None, None
        if local_B_pre is not None:
            lo = max(0, t - disp)
            hi = min(T, t + disp + 1)
            k = lo + int(np.argmax(local_B_pre[j, lo:hi]))
            peak_qn = k / float(division)
            peak_val = float(local_B_pre[j, k])
        rows.append((c, s, j, borrowed, peak_qn, peak_val))

    if not rows:
        raw = attr.get('raw_support')
        raw_v = float(raw[i, t]) if raw is not None else 0.0
        print("    No source passed the similarity gate at this frame "
              "(raw support {:.3f}).".format(raw_v))
        print("    Either windows were dissimilar, or this part / all "
              "neighbors were below the activity minimum.")
        return

    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    if top_k:
        rows = rows[:top_k]
    for c, s, j, borrowed, peak_qn, peak_val in rows:
        if peak_qn is not None:
            dist = peak_qn - time_qn
            peak_txt = ("  nearest peak {:.3f} at qn {:.2f} "
                        "({:+.2f} qn)".format(peak_val, peak_qn, dist))
        else:
            peak_txt = ""
        print("    source: {:<16s} sim {:.3f}  borrowed B {:.3f}  "
              "-> contribution {:.3f}{}".format(
                  _name(j), s, borrowed, c, peak_txt))

    raw = attr.get('raw_support')
    if raw is not None:
        print("    raw support (mean of contributions): {:.3f}".format(
            float(raw[i, t])))
        print("    (final cross_n = this signal normalized per part)")


'''

BANNER_RE = re.compile(
    r"(# =+\n# Explain function[^\n]*\n# =+\n)")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'sectioning_v2_10_C.py'
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()

    src = replace_once(src, OLD_SIG, NEW_SIG, 'signature')
    src = replace_once(src, OLD_ALLOC, NEW_ALLOC, 'allocation')
    src = replace_once(src, OLD_GATE, NEW_GATE, 'gate recording')
    src = replace_once(src, OLD_NORM, NEW_NORM, 'attribution fill')
    src = replace_once(src, OLD_CALL, NEW_CALL, 'call site')
    src = replace_once(src, OLD_CACHE, NEW_CACHE, 'result storage')

    matches = BANNER_RE.findall(src)
    if len(matches) != 1:
        raise SystemExit(
            f"ABORT [explain banner]: found {len(matches)} banner matches, "
            f"expected 1. File unchanged.")
    src = BANNER_RE.sub(lambda m: NEW_FUNC + m.group(1), src, count=1)

    try:
        compile(src, path, 'exec')
    except SyntaxError as e:
        raise SystemExit(f"ABORT: patched source fails to compile: {e}. "
                         f"File unchanged.")

    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"Patched {path}: 6 anchored edits + explain_cross_support "
          f"appended. Pure diagnostics -- boundaries.json must be "
          f"identical to pre-patch.")


if __name__ == '__main__':
    main()
