#!/usr/bin/env python
"""
sectioning_v2_4.py

V2.4 of the sectioning pipeline. Changes from v2.3:

1. TIE MERGING in LBDM. Consecutive notes connected by ties (same pitch,
   tied as one sustained sound) are merged into a single LBDM event with
   combined duration. Eliminates spurious LBDM peaks at tie boundaries
   where there's no real musical event.

2. TUPLET HANDLING in LBDM. Notes that are interior to a tuplet group
   (triplet, quintuplet, etc.) — i.e., not the first or last note of the
   tuplet — have their LBDM strength zeroed. This stops LBDM from
   fragmenting tuplet groups when there's internal pitch variation.
   Tuplet endpoints can still register boundaries.

3. TEMPO CHANGE bumps. MetronomeMark offsets in each part get a Gaussian
   bump in the additive boost stream, with weight zeta. Same architectural
   slot as slur endpoint bumps.

4. HAIRPIN INTERIOR SUPPRESSION. Crescendo and Diminuendo spanners
   (stretched cres./dim. wedges) get treated like slurs: their interior
   frames suppress B_raw. We use OR-aggregation across suppression masks,
   so being in any phrase-marking spanner (slur OR hairpin) counts as one
   suppression of strength delta. This avoids the (1-delta_s-delta_h<0)
   stacking problem.

5. EXPLAIN FUNCTION. New top-level function `explain(result, score,
   part_idx, time_qn)` that prints a detailed breakdown of every signal
   value, slur/hairpin/tempo context, peak detection status, role of the
   closest note, and breath-mark placement decision at a given point.
   Use this to debug specific bars after a run.

Math (per part i) — extended from v2.3:
    B_i_raw(t)        = alpha * nu_norm + beta * lbdm_norm
    in_marker_i(t)    = OR(in_slur_interior, in_hairpin_interior)
    boosts_i(t)       = gamma * slur_endpoints + zeta * tempo_changes
    B_i(t)            = B_i_raw * (1 - delta * in_marker_i) + boosts_i

Default modulation parameters:
    delta = 0.5  (suppression inside any phrase marker)
    gamma = 0.4  (slur-endpoint additive boost)
    zeta  = 0.4  (tempo-change additive boost, matches gamma)

Usage:
    python sectioning_v2_4.py path/to/score.mxl [-o output_dir]

As a library, with diagnostics:
    from sectioning_v2_4 import run_sectioning, explain
    result = run_sectioning('liz.mxl')
    explain(result, result['score'], part_idx=0, time_qn=32.0)
"""

import os
import json
import copy
import argparse

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks
from scipy.ndimage import gaussian_filter1d
import music21 as m21


# =============================================================================
# Score parsing and time grid (unchanged from v2.1)
# =============================================================================

def parse_score(path):
    score = m21.converter.parse(path)
    parts = list(score.parts)
    return score, parts


def get_part_name(part, default='unknown'):
    name = part.partName or part.partAbbreviation
    if not name:
        for instr in part.getInstruments(recurse=True):
            if instr.instrumentName:
                name = instr.instrumentName
                break
    return name or default


def create_time_grid(score, division):
    total = score.duration.quarterLength
    return np.arange(0, total + 1.0 / division, 1.0 / division)


# =============================================================================
# Per-frame features (unchanged from v2.1)
# =============================================================================

def extract_features(parts, time_grid, division):
    num_parts = len(parts)
    num_frames = len(time_grid)
    activity = np.zeros((num_parts, num_frames), dtype=int)
    chroma = np.zeros((num_parts, num_frames, 12))

    for i, part in enumerate(parts):
        for element in part.flatten().notesAndRests:
            start = float(element.offset)
            duration = float(element.duration.quarterLength)
            if duration <= 0:
                continue
            start_idx = int(round(start * division))
            end_idx = int(round((start + duration) * division))
            end_idx = min(end_idx, num_frames)
            start_idx = max(start_idx, 0)
            if start_idx >= num_frames:
                continue

            if isinstance(element, m21.note.Note):
                pc = element.pitch.pitchClass
                for idx in range(start_idx, end_idx):
                    chroma[i, idx, pc] += 1
                    activity[i, idx] = 1
            elif isinstance(element, m21.chord.Chord):
                for n in element.notes:
                    pc = n.pitch.pitchClass
                    for idx in range(start_idx, end_idx):
                        chroma[i, idx, pc] += 1
                        activity[i, idx] = 1

    return activity, chroma


def build_feature_vectors(activity, chroma):
    N, T, _ = chroma.shape
    phi = np.zeros((N, T, 13))
    for i in range(N):
        for t in range(T):
            if activity[i, t] == 1:
                c = chroma[i, t]
                norm = np.linalg.norm(c)
                if norm > 0:
                    phi[i, t, :12] = c / norm
            else:
                phi[i, t, 12] = 1.0
    return phi


def compute_activity_levels(activity, threshold=0.05):
    levels = np.mean(activity, axis=1)
    is_tacet = levels < threshold
    return levels, is_tacet


# =============================================================================
# SSM and novelty (unchanged from v2.1)
# =============================================================================

def build_ssm(phi_part):
    return phi_part @ phi_part.T


def make_checkerboard_kernel(L, sigma=None, convention='muller'):
    size = 2 * L + 1
    K = np.zeros((size, size))
    sign_diag = -1 if convention == 'muller' else +1
    sign_off = +1 if convention == 'muller' else -1

    for r in range(size):
        for s in range(size):
            if r == L or s == L:
                K[r, s] = 0
            elif (r < L) and (s < L):
                K[r, s] = sign_diag
            elif (r > L) and (s > L):
                K[r, s] = sign_diag
            elif (r < L) and (s > L):
                K[r, s] = sign_off
            elif (r > L) and (s < L):
                K[r, s] = sign_off

    if sigma is None:
        sigma = L / 2.0
    coords = np.arange(size) - L
    rs, cs = np.meshgrid(coords, coords, indexing='ij')
    gauss = np.exp(-(rs ** 2 + cs ** 2) / (2.0 * sigma ** 2))
    K = K * gauss
    return K


def compute_novelty(ssm, kernel, convention='muller', trim_edges=True):
    T = ssm.shape[0]
    L = kernel.shape[0] // 2
    novelty = np.zeros(T)
    padded = np.pad(ssm, L, mode='constant', constant_values=0.0)

    for t in range(T):
        patch = padded[t:t + 2 * L + 1, t:t + 2 * L + 1]
        novelty[t] = np.sum(patch * kernel)

    if convention == 'muller':
        novelty = -novelty

    if trim_edges:
        trim = min(L, T // 4)
        novelty[:trim] = 0
        novelty[-trim:] = 0

    return novelty


# =============================================================================
# LBDM with staccato awareness, tie merging, and tuplet handling
# =============================================================================

def has_staccato(element):
    if not hasattr(element, 'articulations'):
        return False
    for art in element.articulations:
        if isinstance(art, (
            m21.articulations.Staccato,
            m21.articulations.Staccatissimo,
            m21.articulations.Spiccato,
        )):
            return True
    return False


def get_tie_type(element):
    """Return music21 tie type ('start', 'continue', 'stop') or None."""
    return element.tie.type if element.tie is not None else None


def is_in_tuplet_interior(element):
    """
    True if element is interior to a tuplet group (not first or last note
    of the group). Used to suppress LBDM strength on tuplet-interior notes
    so triplets/quintuplets don't fragment as phrase boundaries.

    music21 marks each note's role in its tuplet via tuplet.type:
        'start'    = first note of the tuplet group
        'continue' = interior note
        'stop'     = last note
        None       = (rare) tuplet present but role unmarked
    """
    if not element.duration.tuplets:
        return False
    tup = element.duration.tuplets[0]
    return tup.type == 'continue'


def merge_tied_notes(raw_notes):
    """
    Merge consecutive tied same-pitch notes into single events.

    Musicians treat a tied chain (whether across barlines or within a
    measure) as one sustained note. Without merging, LBDM sees the
    individual segments as separate events with anomalous IOIs at every
    tie point, producing spurious mid-phrase boundaries.

    A chain merges when:
      - Previous note's tie_type is 'start' or 'continue'
      - Next note's tie_type is 'continue' or 'stop'
      - Pitches match
      - Notes are temporally contiguous (no gap)

    The merged event keeps the FIRST note's offset, pitch, and other
    attributes; only duration is summed across the chain.
    """
    if not raw_notes:
        return []

    merged = []
    i = 0
    while i < len(raw_notes):
        chain_first = raw_notes[i]
        chain_last = chain_first
        total_duration = chain_first['duration']
        j = i + 1

        while j < len(raw_notes):
            nxt = raw_notes[j]
            cur_tied_forward = chain_last.get('tie_type') in ('start', 'continue')
            nxt_tied_back = nxt.get('tie_type') in ('continue', 'stop')
            same_pitch = nxt['pitch'] == chain_last['pitch']
            contiguous = abs(
                nxt['offset'] - (chain_last['offset'] + chain_last['duration'])
            ) < 0.01

            if cur_tied_forward and nxt_tied_back and same_pitch and contiguous:
                total_duration += nxt['duration']
                chain_last = nxt
                j += 1
            else:
                break

        merged_event = chain_first.copy()
        merged_event['duration'] = total_duration
        # The merged event spans the chain — its tuplet status is taken
        # from the chain start. (Tied notes typically aren't tuplets.)
        merged.append(merged_event)
        i = j

    return merged


def extract_lbdm_profiles(part):
    """
    Build per-note records for LBDM, with tie-merged events and
    tuplet-interior flagging.

    Each record knows its offset, MIDI pitch (top note for chords),
    duration (post-tie-merge), staccato flag, and tuplet-interior flag.

    Then build three interval profiles between consecutive (merged)
    notes:
      - pitch_intervals: |MIDI_{i+1} - MIDI_i|
      - iois: offset_{i+1} - offset_i
      - rests: max(offset_{i+1} - (offset_i + duration_i), 0), with
               STACCATO OVERRIDE: if note i is staccato, rest = 0.
    """
    raw_notes = []
    for element in part.flatten().notes:
        if isinstance(element, m21.note.Note):
            raw_notes.append({
                'offset': float(element.offset),
                'pitch': element.pitch.midi,
                'duration': float(element.duration.quarterLength),
                'staccato': has_staccato(element),
                'tie_type': get_tie_type(element),
                'in_tuplet_interior': is_in_tuplet_interior(element),
                'element': element,
            })
        elif isinstance(element, m21.chord.Chord):
            top = max(element.notes, key=lambda n: n.pitch.midi)
            raw_notes.append({
                'offset': float(element.offset),
                'pitch': top.pitch.midi,
                'duration': float(element.duration.quarterLength),
                'staccato': has_staccato(element),
                'tie_type': get_tie_type(element),
                'in_tuplet_interior': is_in_tuplet_interior(element),
                'element': element,
            })

    raw_notes.sort(key=lambda x: x['offset'])

    # Merge tied chains BEFORE computing intervals — this is the crucial
    # ordering. Otherwise LBDM sees the tie-internal IOIs as boundaries.
    notes_list = merge_tied_notes(raw_notes)

    n = max(len(notes_list) - 1, 0)
    pitch_intervals = np.zeros(n)
    iois = np.zeros(n)
    rests = np.zeros(n)

    for i in range(n):
        cur = notes_list[i]
        nxt = notes_list[i + 1]
        pitch_intervals[i] = abs(nxt['pitch'] - cur['pitch'])
        iois[i] = nxt['offset'] - cur['offset']
        if cur['staccato']:
            rests[i] = 0.0
        else:
            rest_gap = nxt['offset'] - (cur['offset'] + cur['duration'])
            rests[i] = max(rest_gap, 0.0)

    return notes_list, pitch_intervals, iois, rests


def degree_of_change(profile):
    n = len(profile)
    if n < 2:
        return np.array([])
    r = np.zeros(n - 1)
    for i in range(n - 1):
        s = profile[i] + profile[i + 1]
        if s > 0 and profile[i] != profile[i + 1]:
            r[i] = abs(profile[i] - profile[i + 1]) / s
    return r


def boundary_strength(profile):
    n = len(profile)
    if n == 0:
        return np.array([])
    r = degree_of_change(profile)
    s = np.zeros(n)
    for i in range(n):
        r_prev = r[i - 1] if i > 0 and i - 1 < len(r) else 0.0
        r_next = r[i] if i < len(r) else 0.0
        s[i] = profile[i] * (r_prev + r_next)
    if s.max() > 0:
        s = s / s.max()
    return s


def compute_lbdm_per_part(part, w_pitch=0.25, w_ioi=0.50, w_rest=0.25):
    """
    Compute combined LBDM boundary strength per (post-tie-merge) note.

    NEW in v2.4: zeros out strengths on tuplet-interior notes so that
    triplets/quintuplets don't fragment into multiple boundaries due to
    internal pitch variation. The first and last notes of the tuplet
    group can still register as boundaries.
    """
    notes_list, pi, ioi, rest = extract_lbdm_profiles(part)
    s_pitch = boundary_strength(pi)
    s_ioi = boundary_strength(ioi)
    s_rest = boundary_strength(rest)

    n = min(len(s_pitch), len(s_ioi), len(s_rest))
    if n == 0:
        return notes_list, np.array([])
    sigma = (
        w_pitch * s_pitch[:n] +
        w_ioi * s_ioi[:n] +
        w_rest * s_rest[:n]
    )

    # Zero strengths on tuplet-interior notes.
    for i in range(n):
        if i < len(notes_list) and notes_list[i].get('in_tuplet_interior', False):
            sigma[i] = 0.0

    return notes_list, sigma


def project_lbdm_to_grid(notes_list, sigma, num_frames, division,
                          smoothing_sigma_qn=0.5):
    grid = np.zeros(num_frames)
    for k, note in enumerate(notes_list):
        if k >= len(sigma):
            break
        idx = int(round(note['offset'] * division))
        if 0 <= idx < num_frames:
            grid[idx] = max(grid[idx], sigma[k])

    sigma_frames = smoothing_sigma_qn * division
    if sigma_frames > 0:
        grid = gaussian_filter1d(grid, sigma_frames)

    return grid


# =============================================================================
# NEW: Slur extraction
# =============================================================================

def extract_slur_indicators(part, num_frames, division,
                              endpoint_sigma_qn=0.5):
    """
    Extract slur info for a part. Returns a dict with:

      in_slur_interior: shape (num_frames,), 1 strictly inside slurs.
      endpoint_bumps:   shape (num_frames,), Gaussian-smoothed indicator
                        of slur start AND end positions.
      n_slurs:          number of slurs found.
      slur_starts:      list of float onset times of slur-start notes.
      slur_ends:        list of float onset times of slur-end notes.

    The starts and ends lists are kept SEPARATELY (not just as combined
    endpoint positions) because role-aware breath mark placement needs
    to distinguish them. A given onset time may appear in both lists if
    one slur ends and another starts on the same note.

    Slur-finding uses music21's spanner API. For parts without slurs all
    fields are empty/zero arrays.

    Edge cases handled:
      - Slur whose start or end note is missing/None: skipped.
      - Slur with start_offset > end_offset: skipped (malformed).
      - Multiple overlapping slurs: in_slur_interior is set wherever ANY
        slur's interior covers the frame (boolean OR over slurs).
      - One note ending one slur and starting another: appears in both
        slur_starts and slur_ends lists.
    """
    in_slur_interior = np.zeros(num_frames, dtype=float)
    endpoints_raw = np.zeros(num_frames, dtype=float)
    slur_starts = []
    slur_ends = []

    slurs = []
    try:
        for sp in part.recurse().getElementsByClass(m21.spanner.Slur):
            slurs.append(sp)
    except Exception:
        pass

    for slur in slurs:
        try:
            spanned = slur.getSpannedElements()
            if len(spanned) < 2:
                continue
            start_elem = spanned[0]
            end_elem = spanned[-1]
            start_off = float(start_elem.offset)
            end_off = float(end_elem.offset)
            if end_off <= start_off:
                continue

            slur_starts.append(start_off)
            slur_ends.append(end_off)

            start_idx = int(round(start_off * division))
            end_idx = int(round(end_off * division))
            start_idx = max(start_idx, 0)
            end_idx = min(end_idx, num_frames - 1)

            if end_idx > start_idx + 1:
                in_slur_interior[start_idx + 1:end_idx] = 1.0

            if 0 <= start_idx < num_frames:
                endpoints_raw[start_idx] = max(endpoints_raw[start_idx], 1.0)
            if 0 <= end_idx < num_frames:
                endpoints_raw[end_idx] = max(endpoints_raw[end_idx], 1.0)
        except Exception:
            continue

    sigma_frames = endpoint_sigma_qn * division
    if sigma_frames > 0 and endpoints_raw.max() > 0:
        endpoint_bumps = gaussian_filter1d(endpoints_raw, sigma_frames)
        if endpoint_bumps.max() > 0:
            endpoint_bumps = endpoint_bumps / endpoint_bumps.max()
    else:
        endpoint_bumps = np.zeros_like(endpoints_raw)

    return {
        'in_slur_interior': in_slur_interior,
        'endpoint_bumps': endpoint_bumps,
        'n_slurs': len(slurs),
        'slur_starts': slur_starts,
        'slur_ends': slur_ends,
    }


# =============================================================================
# Hairpin (Crescendo / Diminuendo) extraction
# =============================================================================

def extract_hairpin_indicators(part, num_frames, division):
    """
    Extract hairpin (Crescendo/Diminuendo) interior mask for a part.

    Hairpins are stretched crescendo/decrescendo wedges (graphic
    < and > markings spanning multiple notes). They typically live
    INSIDE a phrase rather than crossing phrase boundaries — Robert's
    observation. So we treat their interior the same way as slur
    interior: any boundary peak inside should be suppressed.

    Returns:
        in_hairpin: shape (num_frames,), 1 strictly inside a hairpin.
        n_hairpins: count of hairpins found.

    Note: this only handles the SPANNING form (Crescendo / Diminuendo
    spanners). Bare text markings ("cres.", "dim." without a wedge)
    aren't handled — they're isolated points, not spans, and Robert
    flagged them as not as useful for boundary signaling.
    """
    in_hairpin = np.zeros(num_frames, dtype=float)
    n_hairpins = 0

    hairpins = []
    try:
        for cls in (m21.dynamics.Crescendo, m21.dynamics.Diminuendo):
            for sp in part.recurse().getElementsByClass(cls):
                hairpins.append(sp)
    except Exception:
        pass

    for hp in hairpins:
        try:
            spanned = hp.getSpannedElements()
            if len(spanned) < 2:
                continue
            start_off = float(spanned[0].offset)
            end_off = float(spanned[-1].offset)
            if end_off <= start_off:
                continue
            n_hairpins += 1

            start_idx = max(int(round(start_off * division)), 0)
            end_idx = min(int(round(end_off * division)), num_frames - 1)

            if end_idx > start_idx + 1:
                in_hairpin[start_idx + 1:end_idx] = 1.0
        except Exception:
            continue

    return in_hairpin, n_hairpins


# =============================================================================
# Structural event extraction (tempo, dynamics, key, time changes)
# =============================================================================

def extract_structural_event_offsets(part, score=None,
                                       initial_threshold_qn=0.5):
    """
    Extract offsets of structural change events in a part:
      - Tempo changes (MetronomeMark, MetricModulation)
      - Dynamic markings (Dynamic — point letter markings: f, p, mf, ...)
      - Key signature changes
      - Time signature changes

    Robert's observation: tempo changes, sudden dynamic markings, and
    sometimes key/time signature changes mark section boundaries. They
    don't always (a key change can happen mid-phrase) but often enough
    to be useful as a corroborating signal — same architectural slot as
    slur endpoint bumps.

    The initial_threshold_qn excludes events at the very start of the
    piece. The first tempo, key sig, time sig, and dynamic are STATE,
    not changes — they tell you how the piece begins, not where it
    transitions. Subsequent same-class events ARE changes and are kept.

    score: optional music21 Score, used to also pick up score-level
    events (e.g., a master tempo change that affects all parts).

    Returns:
        offsets: sorted list of event offset times in quarter notes.
        events: parallel list of event-type strings, for diagnostics.
    """
    offsets = []
    events = []

    event_classes = [
        ('tempo', m21.tempo.MetronomeMark),
        ('tempo', m21.tempo.MetricModulation),
        ('dynamic', m21.dynamics.Dynamic),
        ('key', m21.key.KeySignature),
        ('time', m21.meter.TimeSignature),
    ]

    seen = set()  # dedupe by (offset, kind)

    for kind, cls in event_classes:
        try:
            for el in part.recurse().getElementsByClass(cls):
                off = float(el.offset)
                if off > initial_threshold_qn:
                    key = (round(off, 4), kind)
                    if key not in seen:
                        seen.add(key)
                        offsets.append(off)
                        events.append(kind)
        except Exception:
            continue

    if score is not None:
        # Tempo/key/time often live at score level rather than per-part.
        for kind, cls in event_classes:
            if kind == 'dynamic':
                continue  # dynamics are inherently per-part
            try:
                for el in score.recurse().getElementsByClass(cls):
                    off = float(el.offset)
                    if off > initial_threshold_qn:
                        key = (round(off, 4), kind)
                        if key not in seen:
                            seen.add(key)
                            offsets.append(off)
                            events.append(kind)
            except Exception:
                continue

    # Sort by offset.
    paired = sorted(zip(offsets, events), key=lambda x: x[0])
    if paired:
        offsets, events = zip(*paired)
        return list(offsets), list(events)
    return [], []


def project_event_bumps(offsets, num_frames, division, sigma_qn=0.5):
    """
    Project a list of event offsets to a Gaussian-bumped time grid.

    Same recipe as the slur-endpoint bumps: place deltas at offsets,
    smooth with Gaussian of width sigma_qn quarter notes, normalize so
    the max bump is 1.0.

    For an empty offsets list returns a zero array.
    """
    raw = np.zeros(num_frames)
    for off in offsets:
        idx = int(round(off * division))
        if 0 <= idx < num_frames:
            raw[idx] = 1.0

    sigma_frames = sigma_qn * division
    if sigma_frames > 0 and raw.max() > 0:
        bumps = gaussian_filter1d(raw, sigma_frames)
        if bumps.max() > 0:
            bumps = bumps / bumps.max()
        return bumps
    return np.zeros_like(raw)


# =============================================================================
# Per-part boundary signal with slur modulation
# =============================================================================

def normalize_signal(x):
    x = np.asarray(x, dtype=float).copy()
    if x.max() > x.min():
        x = (x - x.min()) / (x.max() - x.min())
    return x


def compute_per_part_boundary_signal(novelty_i, lbdm_grid_i,
                                      in_slur_interior_i, slur_endpoints_i,
                                      in_hairpin_i, structural_bumps_i,
                                      alpha=0.5, beta=0.5,
                                      delta=0.5, gamma=0.4, zeta=0.4):
    """
    B_i(t) with multiple suppression and boost sources (extended in v2.4).

    Math:
        B_raw(t)    = alpha * nu_norm(t) + beta * lbdm_norm(t)
        in_marker(t) = max(in_slur_interior(t), in_hairpin(t))   [OR]
        boosts(t)   = gamma * slur_endpoints(t) + zeta * structural_bumps(t)
        B_i(t)      = B_raw(t) * (1 - delta * in_marker(t)) + boosts(t)

    Why OR-aggregation for suppression: if we summed delta_slur +
    delta_hairpin, frames inside both would suppress doubly and could
    push B_i negative. OR is the conservative choice — being inside any
    phrase-marking spanner counts as one suppression of strength delta.

    Why additive sum for boosts: the boost sources are independent
    pieces of evidence (slur ends vs structural events). They reinforce
    each other when they coincide.

    Args:
        novelty_i:           per-part SSM novelty curve (T,)
        lbdm_grid_i:         per-part LBDM strength on time grid (T,)
        in_slur_interior_i:  binary mask, slur interior (T,)
        slur_endpoints_i:    Gaussian bumps at slur endpoints (T,)
        in_hairpin_i:        binary mask, hairpin interior (T,)
        structural_bumps_i:  Gaussian bumps at structural events (T,)
        alpha, beta:         weights for SSM novelty vs LBDM in B_raw
        delta:               suppression weight (0..1, default 0.5)
        gamma:               slur-endpoint boost weight (default 0.4)
        zeta:                structural-event boost weight (default 0.4)

    Returns:
        B_i, nu_norm, lbdm_norm, B_raw  — last three for diagnostics.
    """
    nu_norm = normalize_signal(novelty_i)
    lbdm_norm = normalize_signal(lbdm_grid_i)
    B_raw = alpha * nu_norm + beta * lbdm_norm

    # OR-aggregate suppression masks
    in_marker = np.maximum(in_slur_interior_i, in_hairpin_i)

    # Sum boost sources
    boosts = gamma * slur_endpoints_i + zeta * structural_bumps_i

    B_i = B_raw * (1.0 - delta * in_marker) + boosts

    return B_i, nu_norm, lbdm_norm, B_raw


def detect_boundaries(B, time_grid, peak_height=0.3, peak_distance_frames=20):
    peaks, _ = find_peaks(B, height=peak_height, distance=peak_distance_frames)
    boundary_times = time_grid[peaks] if len(peaks) > 0 else np.array([])
    return boundary_times


# =============================================================================
# NEW: Breath mark annotation
# =============================================================================

def add_breath_marks_per_part(original_score, boundaries_per_part,
                                slur_info_per_part,
                                part_indices_to_annotate, output_path,
                                color='#d62728', onset_tolerance=0.5):
    """
    Role-aware breath mark placement (NEW in v2.3).

    For each detected boundary at time bt in part i, decide which note
    to attach the breath mark to based on the role of the closest note
    at the boundary:

      1. Find the "primary candidate" — the note whose onset is closest
         to (and within onset_tolerance of) bt.
      2. Determine the role of the primary candidate:
         - SLUR_END → breath ON primary. The slur ends here on the long
           note; player breathes after it.
         - SLUR_START (and not also slur_end) → breath on the PREVIOUS
           note. The boundary marks "new phrase begins on primary," so
           the breath goes on the LAST note of the prior phrase.
         - BOTH (one slur ends and another starts on the same note) →
           treat as slur_end (breath on primary). The "after this note"
           interpretation is the right one.
         - NEITHER (no slur involvement) → breath ON primary. We assume
           LBDM detected this note as a phrase-ending note via long IOI.
      3. If no primary candidate exists (boundary fell in a rest), fall
         back to the last note strictly before bt.

    Existing note colors (e.g., GT melody coloring) are preserved because
    we only mutate note.articulations, never note.style.

    onset_tolerance default 0.5 quarter notes covers Gaussian-smoothing
    peak shifts and small offset rounding errors; should not be so large
    that we cross over the previous note.
    """
    score_copy = copy.deepcopy(original_score)
    parts = list(score_copy.parts)

    for i, part in enumerate(parts):
        if i not in part_indices_to_annotate:
            continue
        boundaries = boundaries_per_part[i]
        slur_info = slur_info_per_part[i] if i < len(slur_info_per_part) else {}
        slur_starts = slur_info.get('slur_starts', [])
        slur_ends = slur_info.get('slur_ends', [])

        notes_with_offsets = sorted(
            [(float(n.offset), n) for n in part.flatten().notes],
            key=lambda x: x[0]
        )
        if not notes_with_offsets:
            continue

        for bt in boundaries:
            # Find primary candidate (closest note within tolerance) and
            # also track the fallback (last note strictly before bt).
            primary = None
            primary_off = None
            primary_dist = float('inf')
            fallback = None

            for off, n in notes_with_offsets:
                if off > bt + onset_tolerance:
                    break
                if abs(off - bt) <= onset_tolerance:
                    d = abs(off - bt)
                    if d < primary_dist:
                        primary_dist = d
                        primary = n
                        primary_off = off
                if off < bt:
                    fallback = n

            if primary is not None:
                # Role check on primary's onset.
                is_start = any(
                    abs(primary_off - s) <= onset_tolerance
                    for s in slur_starts
                )
                is_end = any(
                    abs(primary_off - e) <= onset_tolerance
                    for e in slur_ends
                )

                if is_start and not is_end:
                    # Slur START: breath on the note BEFORE primary
                    # (last note of the prior phrase). Use a strict-less
                    # search relative to primary_off, with a small
                    # epsilon to avoid floating-point ties.
                    target = None
                    eps = onset_tolerance / 4.0
                    for off, n in notes_with_offsets:
                        if off < primary_off - eps:
                            target = n
                        else:
                            break
                else:
                    # Slur END, BOTH, or neither: breath ON primary.
                    target = primary
            else:
                # No note at bt — boundary in a rest. Fall back to last
                # note before bt (the v2.2 behavior, correct for rests).
                target = fallback

            if target is None:
                continue

            breath = m21.articulations.BreathMark()
            try:
                if getattr(breath, 'style', None) is None:
                    breath.style = m21.style.TextStyle()
                breath.style.color = color
            except Exception:
                pass
            try:
                breath.placement = 'above'
            except Exception:
                pass
            target.articulations.append(breath)

    score_copy.write('musicxml', fp=output_path)


# =============================================================================
# Diagnostic plots (extended in v2.4 to show hairpins and structural events)
# =============================================================================

def plot_diagnostics_per_part(time_grid, per_part_signals, part_names,
                                boundaries_per_part, is_tacet,
                                activity_levels, slur_info, output_path,
                                hairpin_info=None, structural_info=None):
    """
    One panel per active part.
      - Gold shaded regions: slur interiors
      - Cyan shaded regions (v2.4): hairpin interiors
      - Magenta vertical ticks (v2.4): structural event positions
    Summary panel at top shows boundaries across all parts.
    """
    active_indices = [i for i in range(len(part_names)) if not is_tacet[i]]
    n_panels = len(active_indices) + 1

    fig, axes = plt.subplots(n_panels, 1,
                             figsize=(14, 1.4 * n_panels),
                             sharex=True)
    if n_panels == 1:
        axes = [axes]

    # Summary panel
    ax_sum = axes[0]
    ax_sum.set_title("Per-part boundaries (summary)", fontsize=10, loc='left')
    for j, i in enumerate(active_indices):
        for bt in boundaries_per_part[i]:
            ax_sum.scatter(bt, j, color='red', marker='|', s=80, linewidths=1.2)
        n_slurs = slur_info[i].get('n_slurs', 0) if i < len(slur_info) else 0
        n_hp = 0
        if hairpin_info is not None and i < len(hairpin_info):
            n_hp = hairpin_info[i].get('n_hairpins', 0)
        ax_sum.text(time_grid[0] - (time_grid[-1] - time_grid[0]) * 0.01,
                    j,
                    f"{part_names[i]} [{activity_levels[i]:.0%}, "
                    f"{n_slurs}sl/{n_hp}hp]",
                    fontsize=7, ha='right', va='center')
    ax_sum.set_yticks([])
    ax_sum.set_ylim(-1, len(active_indices))
    ax_sum.grid(axis='x', alpha=0.3)

    # Per-part B_i panels
    for j, i in enumerate(active_indices):
        ax = axes[j + 1]
        B_i, nu_i, lbdm_i, B_raw = per_part_signals[i]
        si = slur_info[i] if i < len(slur_info) else {}
        in_slur_i = si.get('in_slur_interior', np.zeros_like(time_grid))
        n_slurs = si.get('n_slurs', 0)

        # Shade slur interiors (gold)
        if in_slur_i.max() > 0:
            ax.fill_between(time_grid, 0, 1.1,
                            where=in_slur_i > 0,
                            color='gold', alpha=0.15,
                            transform=ax.get_xaxis_transform())

        # Shade hairpin interiors (cyan) if available
        n_hp = 0
        if hairpin_info is not None and i < len(hairpin_info):
            in_hp_i = hairpin_info[i].get('in_hairpin',
                                            np.zeros_like(time_grid))
            n_hp = hairpin_info[i].get('n_hairpins', 0)
            if in_hp_i.max() > 0:
                ax.fill_between(time_grid, 0, 1.1,
                                where=in_hp_i > 0,
                                color='cyan', alpha=0.15,
                                transform=ax.get_xaxis_transform())

        # Mark structural events (magenta vertical ticks at top)
        n_struct = 0
        if structural_info is not None and i < len(structural_info):
            offsets = structural_info[i].get('offsets', [])
            n_struct = len(offsets)
            for off in offsets:
                ax.axvline(x=off, color='magenta', alpha=0.4,
                           linewidth=0.6, linestyle=':')

        ax.plot(time_grid, nu_i, color='steelblue', alpha=0.3,
                linewidth=0.6, label='SSM nov')
        ax.plot(time_grid, lbdm_i, color='seagreen', alpha=0.3,
                linewidth=0.6, label='LBDM')
        ax.plot(time_grid, B_raw, color='gray', alpha=0.5,
                linewidth=0.7, label='B_raw')
        ax.plot(time_grid, B_i, color='black', linewidth=1.1, label='B_i')

        for bt in boundaries_per_part[i]:
            ax.axvline(x=bt, color='red', linestyle='--', alpha=0.6,
                       linewidth=0.8)

        ax.set_title(
            f"{part_names[i]} ({len(boundaries_per_part[i])} boundaries, "
            f"{n_slurs} slurs, {n_hp} hairpins, {n_struct} struct events)",
            fontsize=8, loc='left'
        )
        ax.legend(fontsize=6, loc='upper right')
        ax.set_ylim(-0.05, 1.15)

    axes[-1].set_xlabel("Time (quarter notes)")
    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close()


def write_summary_per_part(boundaries_per_part, part_names, activity_levels,
                            is_tacet, slur_info, score, output_path,
                            alpha, beta, delta, gamma,
                            w_pitch, w_ioi, w_rest,
                            division, kernel_size_frames):
    measure_offsets = []
    if len(score.parts) > 0:
        for measure in score.parts[0].getElementsByClass(m21.stream.Measure):
            measure_offsets.append((float(measure.offset), measure.number))

    def offset_to_measure_beat(offset):
        if not measure_offsets:
            return None, None
        candidate = measure_offsets[0]
        for mo in measure_offsets:
            if mo[0] <= offset:
                candidate = mo
            else:
                break
        m_offset, m_num = candidate
        beat = offset - m_offset + 1.0
        return m_num, beat

    summary = {
        'parameters': {
            'alpha_ssm_weight': alpha,
            'beta_lbdm_weight': beta,
            'delta_slur_suppression': delta,
            'gamma_slur_endpoint_boost': gamma,
            'lbdm_w_pitch': w_pitch,
            'lbdm_w_ioi': w_ioi,
            'lbdm_w_rest': w_rest,
            'division': division,
            'kernel_size_frames': kernel_size_frames,
        },
        'tacet_parts': [
            {'index': i, 'name': part_names[i],
             'activity_level': float(activity_levels[i])}
            for i in range(len(part_names)) if is_tacet[i]
        ],
        'num_active_parts': int(np.sum(~is_tacet)),
        'per_part': [],
    }
    for i in range(len(part_names)):
        if is_tacet[i]:
            continue
        boundaries = boundaries_per_part[i]
        si = slur_info[i] if i < len(slur_info) else {}
        n_slurs = si.get('n_slurs', 0)
        entry = {
            'index': i,
            'name': part_names[i],
            'activity_level': float(activity_levels[i]),
            'num_slurs': int(n_slurs),
            'num_boundaries': len(boundaries),
            'boundaries': [],
        }
        for bt in boundaries:
            m, b = offset_to_measure_beat(float(bt))
            entry['boundaries'].append({
                'time_quarter_notes': float(bt),
                'measure': m,
                'beat': b,
            })
        summary['per_part'].append(entry)

    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2)


# =============================================================================
# Main pipeline
# =============================================================================

def run_sectioning(input_path, output_dir='./output',
                    division=8,
                    kernel_size_frames=64,
                    alpha=0.5, beta=0.5,
                    delta=0.5, gamma=0.4, zeta=0.4,
                    w_pitch=0.25, w_ioi=0.50, w_rest=0.25,
                    lbdm_smoothing_qn=0.5,
                    slur_endpoint_sigma_qn=0.5,
                    structural_sigma_qn=0.5,
                    peak_height=0.3, peak_distance_qn=2.5,
                    convention='muller',
                    tacet_threshold=0.05,
                    breath_color='#d62728'):
    """
    V2.4 top-level pipeline.

    New args vs v2.3:
        zeta: structural-event additive boost weight (default 0.4).
              Combined boost for tempo changes, sudden dynamic markings,
              and key/time signature changes.
        structural_sigma_qn: Gaussian width for structural event bumps.

    Returns a dict containing per-part boundaries, signals, slur info,
    hairpin info, structural event info, and the score itself — enough
    for the explain() function to inspect any (part, time) point after
    the run.
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"[1/10] Loading {input_path}")
    score, parts = parse_score(input_path)
    part_names = [get_part_name(p, default=f'part_{i}')
                  for i, p in enumerate(parts)]
    print(f"       {len(parts)} parts, total length "
          f"{score.duration.quarterLength:.1f} quarter notes")

    print(f"[2/10] Time grid (division={division})")
    time_grid = create_time_grid(score, division)
    T = len(time_grid)
    print(f"       {T} frames")

    print("[3/10] Per-frame features")
    activity, chroma = extract_features(parts, time_grid, division)
    phi = build_feature_vectors(activity, chroma)

    print(f"[4/10] Tacet detection (threshold={tacet_threshold:.0%})")
    activity_levels, is_tacet = compute_activity_levels(
        activity, threshold=tacet_threshold
    )

    print("[5/10] Slur extraction")
    slur_info = []
    for i, part in enumerate(parts):
        if is_tacet[i]:
            slur_info.append({
                'in_slur_interior': np.zeros(T),
                'endpoint_bumps': np.zeros(T),
                'n_slurs': 0,
                'slur_starts': [],
                'slur_ends': [],
            })
            continue
        si = extract_slur_indicators(
            part, T, division,
            endpoint_sigma_qn=slur_endpoint_sigma_qn
        )
        slur_info.append(si)

    print("[6/10] Hairpin and structural event extraction")
    hairpin_info = []
    structural_info = []
    for i, part in enumerate(parts):
        if is_tacet[i]:
            hairpin_info.append({
                'in_hairpin': np.zeros(T),
                'n_hairpins': 0,
            })
            structural_info.append({
                'bumps': np.zeros(T),
                'offsets': [],
                'event_kinds': [],
            })
            continue
        in_hp, n_hp = extract_hairpin_indicators(part, T, division)
        hairpin_info.append({
            'in_hairpin': in_hp,
            'n_hairpins': n_hp,
        })
        struct_offsets, event_kinds = extract_structural_event_offsets(
            part, score=score
        )
        struct_bumps = project_event_bumps(
            struct_offsets, T, division, sigma_qn=structural_sigma_qn
        )
        structural_info.append({
            'bumps': struct_bumps,
            'offsets': struct_offsets,
            'event_kinds': event_kinds,
        })

    for i in range(len(parts)):
        marker = " [TACET]" if is_tacet[i] else ""
        n_slurs = slur_info[i]['n_slurs']
        n_hp = hairpin_info[i]['n_hairpins']
        n_struct = len(structural_info[i]['offsets'])
        print(f"       part {i:2d} {part_names[i]:25s} "
              f"activity={activity_levels[i]:.1%} "
              f"slurs={n_slurs} hairpins={n_hp} "
              f"struct_events={n_struct}{marker}")

    print(f"[7/10] Per-part SSM novelty (kernel={kernel_size_frames} frames)")
    L = kernel_size_frames // 2
    kernel = make_checkerboard_kernel(L, convention=convention)
    novelty_per_part = []
    for i in range(len(parts)):
        if is_tacet[i]:
            novelty_per_part.append(np.zeros(T))
            continue
        ssm = build_ssm(phi[i])
        nu = compute_novelty(ssm, kernel, convention=convention,
                             trim_edges=True)
        novelty_per_part.append(nu)

    print(f"[8/10] Per-part LBDM (sigma_smooth={lbdm_smoothing_qn} qn)")
    lbdm_grids = []
    notes_per_part = []  # save for explain()
    for i in range(len(parts)):
        if is_tacet[i]:
            lbdm_grids.append(np.zeros(T))
            notes_per_part.append([])
            continue
        notes_list, sigma = compute_lbdm_per_part(
            parts[i], w_pitch=w_pitch, w_ioi=w_ioi, w_rest=w_rest
        )
        notes_per_part.append(notes_list)
        grid = project_lbdm_to_grid(
            notes_list, sigma, T, division,
            smoothing_sigma_qn=lbdm_smoothing_qn
        )
        lbdm_grids.append(grid)

    print(f"[9/10] Per-part B_i(t) "
          f"(alpha={alpha}, beta={beta}, delta={delta}, "
          f"gamma={gamma}, zeta={zeta})")
    peak_distance_frames = max(int(round(peak_distance_qn * division)), 1)
    per_part_signals = []   # list of (B_i, nu_norm, lbdm_norm, B_raw)
    boundaries_per_part = []
    for i in range(len(parts)):
        if is_tacet[i]:
            per_part_signals.append(
                (np.zeros(T), np.zeros(T), np.zeros(T), np.zeros(T))
            )
            boundaries_per_part.append(np.array([]))
            continue
        in_slur_i = slur_info[i]['in_slur_interior']
        endpoints_i = slur_info[i]['endpoint_bumps']
        in_hp_i = hairpin_info[i]['in_hairpin']
        struct_bumps_i = structural_info[i]['bumps']
        B_i, nu_n, lbdm_n, B_raw = compute_per_part_boundary_signal(
            novelty_per_part[i], lbdm_grids[i],
            in_slur_i, endpoints_i,
            in_hp_i, struct_bumps_i,
            alpha=alpha, beta=beta,
            delta=delta, gamma=gamma, zeta=zeta
        )
        per_part_signals.append((B_i, nu_n, lbdm_n, B_raw))
        bdys = detect_boundaries(
            B_i, time_grid,
            peak_height=peak_height,
            peak_distance_frames=peak_distance_frames
        )
        boundaries_per_part.append(bdys)
        print(f"       part {i:2d} {part_names[i]:25s} "
              f"{len(bdys):3d} boundaries")

    print("[10/10] Writing outputs")
    annotated_path = os.path.join(output_dir, 'sectioned.musicxml')
    active_set = {i for i in range(len(parts)) if not is_tacet[i]}
    add_breath_marks_per_part(score, boundaries_per_part, slur_info,
                                active_set,
                                annotated_path, color=breath_color)

    plot_path = os.path.join(output_dir, 'diagnostics.png')
    plot_diagnostics_per_part(time_grid, per_part_signals, part_names,
                                boundaries_per_part, is_tacet,
                                activity_levels, slur_info, plot_path,
                                hairpin_info=hairpin_info,
                                structural_info=structural_info)

    summary_path = os.path.join(output_dir, 'boundaries.json')
    write_summary_per_part(
        boundaries_per_part, part_names, activity_levels, is_tacet,
        slur_info, score, summary_path,
        alpha=alpha, beta=beta, delta=delta, gamma=gamma,
        w_pitch=w_pitch, w_ioi=w_ioi, w_rest=w_rest,
        division=division, kernel_size_frames=kernel_size_frames,
    )

    print(f"       Annotated:   {annotated_path}")
    print(f"       Diagnostics: {plot_path}")
    print(f"       Summary:     {summary_path}")

    return {
        'score': score,
        'per_part_boundaries': boundaries_per_part,
        'part_names': part_names,
        'is_tacet': is_tacet,
        'activity_levels': activity_levels,
        'time_grid': time_grid,
        'per_part_signals': per_part_signals,
        'slur_info': slur_info,
        'hairpin_info': hairpin_info,
        'structural_info': structural_info,
        'notes_per_part': notes_per_part,
        'parameters': {
            'division': division,
            'kernel_size_frames': kernel_size_frames,
            'alpha': alpha, 'beta': beta,
            'delta': delta, 'gamma': gamma, 'zeta': zeta,
            'w_pitch': w_pitch, 'w_ioi': w_ioi, 'w_rest': w_rest,
            'peak_height': peak_height,
            'peak_distance_frames': peak_distance_frames,
            'peak_distance_qn': peak_distance_qn,
        },
    }


# =============================================================================
# Explain function — diagnostic for "why did/didn't a boundary land here?"
# =============================================================================

def explain(result, part_idx, time_qn=None, measure=None, beat=1.0,
            window_qn=4.0, max_notes_in_window=20):
    """
    Print a detailed breakdown of every signal value, slur/hairpin/event
    context, peak detection status, and breath-mark placement decision
    at a given (part, time) point.

    Args:
        result: dict returned by run_sectioning
        part_idx: int, index of the part to inspect
        time_qn: float, time in quarter notes. Alternative to measure/beat.
        measure: int, measure number (1-indexed). Alternative to time_qn.
        beat: float, beat in measure (1-indexed, default 1.0). Used with
              measure.
        window_qn: float, window size around the point for context
                   (default 4.0 qn).
        max_notes_in_window: cap on how many notes to list in the window
                             output to keep things readable.

    Either time_qn or measure must be provided.
    """
    score = result['score']
    parts = list(score.parts)
    if part_idx < 0 or part_idx >= len(parts):
        print(f"part_idx {part_idx} out of range [0, {len(parts)-1}]")
        return

    part_name = result['part_names'][part_idx]
    is_tacet = result['is_tacet'][part_idx]
    if is_tacet:
        print(f"Part {part_idx} ({part_name}) is tacet — no signal computed.")
        return

    # Resolve time_qn from measure/beat if needed.
    if time_qn is None:
        if measure is None:
            print("Must provide either time_qn or measure.")
            return
        # Walk first part's measures to map measure number to offset.
        m_off = None
        for m in score.parts[0].getElementsByClass(m21.stream.Measure):
            if m.number == measure:
                m_off = float(m.offset)
                break
        if m_off is None:
            print(f"Measure {measure} not found.")
            return
        time_qn = m_off + (beat - 1.0)

    # Dereference signals.
    time_grid = result['time_grid']
    division = result['parameters']['division']
    params = result['parameters']

    if time_qn < 0 or time_qn > time_grid[-1]:
        print(f"time_qn {time_qn} out of grid range [0, {time_grid[-1]:.2f}]")
        return

    idx = int(round(time_qn * division))
    idx = min(max(idx, 0), len(time_grid) - 1)
    actual_t = time_grid[idx]

    B_i, nu_norm, lbdm_norm, B_raw = result['per_part_signals'][part_idx]
    si = result['slur_info'][part_idx]
    hi = result['hairpin_info'][part_idx]
    ei = result['structural_info'][part_idx]

    # Compute the formula breakdown explicitly.
    alpha = params['alpha']
    beta = params['beta']
    delta = params['delta']
    gamma = params['gamma']
    zeta = params['zeta']

    nu_v = float(nu_norm[idx])
    lbdm_v = float(lbdm_norm[idx])
    B_raw_v = float(B_raw[idx])
    in_slur = float(si['in_slur_interior'][idx])
    in_hp = float(hi['in_hairpin'][idx])
    in_marker = max(in_slur, in_hp)
    slur_bump_v = float(si['endpoint_bumps'][idx])
    struct_bump_v = float(ei['bumps'][idx])
    B_i_v = float(B_i[idx])

    # Locate measure/beat.
    measure_offsets = []
    for m in score.parts[0].getElementsByClass(m21.stream.Measure):
        measure_offsets.append((float(m.offset), m.number))
    m_num, m_beat = None, None
    if measure_offsets:
        candidate = measure_offsets[0]
        for mo in measure_offsets:
            if mo[0] <= actual_t:
                candidate = mo
            else:
                break
        m_num = candidate[1]
        m_beat = actual_t - candidate[0] + 1.0

    sep = "=" * 70
    print(sep)
    if m_num is not None:
        loc = f"t={actual_t:.2f} qn (measure {m_num}, beat {m_beat:.2f})"
    else:
        loc = f"t={actual_t:.2f} qn"
    print(f"EXPLAIN: Part {part_idx} ({part_name}) at {loc}")
    print(sep)
    print()

    print("Signal values at this point:")
    print(f"  alpha * SSM_novelty:      {alpha:.2f} * {nu_v:.3f} = "
          f"{alpha*nu_v:.3f}")
    print(f"  beta  * LBDM:             {beta:.2f} * {lbdm_v:.3f} = "
          f"{beta*lbdm_v:.3f}")
    print(f"  ---")
    print(f"  B_raw:                                          "
          f"{B_raw_v:.3f}")
    print()

    print("Suppression context:")
    print(f"  in_slur_interior:         {int(in_slur)}")
    print(f"  in_hairpin:               {int(in_hp)}")
    print(f"  in_marker (OR):           {in_marker:.0f}")
    if in_marker > 0:
        print(f"  -> B_raw attenuated by delta*in_marker = "
              f"{delta*in_marker:.2f}, multiplier = {1-delta*in_marker:.2f}")
    print()

    print("Boost context:")
    print(f"  slur_endpoint_bump:       {slur_bump_v:.3f}")
    print(f"  structural_bump:          {struct_bump_v:.3f}")
    boost_total = gamma * slur_bump_v + zeta * struct_bump_v
    print(f"  total boost (gamma*slur + zeta*struct):  "
          f"{gamma:.2f}*{slur_bump_v:.3f} + {zeta:.2f}*{struct_bump_v:.3f} "
          f"= {boost_total:.3f}")
    print()

    print("Final B_i at this point:")
    print(f"  B_raw * (1 - delta * in_marker) + boost")
    print(f"  = {B_raw_v:.3f} * {1-delta*in_marker:.2f} + {boost_total:.3f}")
    print(f"  = {B_i_v:.3f}")
    print()

    # Boundary detection status.
    boundaries = result['per_part_boundaries'][part_idx]
    peak_height = params['peak_height']
    peak_dist_qn = params['peak_distance_qn']

    print("Boundary detection:")
    print(f"  peak_height threshold:    {peak_height:.2f}")
    print(f"  min peak distance:        {peak_dist_qn:.2f} qn "
          f"({params['peak_distance_frames']} frames)")
    nearby_boundaries = [b for b in boundaries
                          if abs(b - actual_t) <= window_qn / 2]
    here_boundaries = [b for b in boundaries
                        if abs(b - actual_t) < 1.0 / division + 1e-6]
    if here_boundaries:
        print(f"  Boundary detected at this point? YES "
              f"(at t={here_boundaries[0]:.2f})")
    else:
        print(f"  Boundary detected at this point? NO")
        if B_i_v < peak_height:
            print(f"  Reason: B_i = {B_i_v:.3f} < threshold {peak_height:.2f}")
        else:
            # Above threshold but didn't trigger — check if local max.
            if 0 < idx < len(B_i) - 1:
                if not (B_i[idx] > B_i[idx-1] and B_i[idx] > B_i[idx+1]):
                    print(f"  Reason: B_i = {B_i_v:.3f} clears threshold "
                          f"but is not a local maximum (B_i[idx-1]="
                          f"{B_i[idx-1]:.3f}, B_i[idx+1]={B_i[idx+1]:.3f})")
                else:
                    print(f"  Reason: likely eliminated by min peak "
                          f"distance constraint")
            else:
                print(f"  Reason: at edge of grid")
    print()

    # Slur context.
    print("Slur context:")
    slur_starts = si['slur_starts']
    slur_ends = si['slur_ends']
    nearby_starts = [s for s in slur_starts
                      if abs(s - actual_t) <= window_qn]
    nearby_ends = [e for e in slur_ends
                    if abs(e - actual_t) <= window_qn]
    print(f"  Slur starts within window: {[round(s, 2) for s in nearby_starts]}")
    print(f"  Slur ends within window:   {[round(e, 2) for e in nearby_ends]}")
    if in_slur:
        # Find which slur covers us.
        covering = []
        for s, e in zip(slur_starts, slur_ends):
            if s < actual_t < e:
                covering.append((s, e))
        if covering:
            print(f"  Currently INSIDE slur(s): "
                  f"{[(round(s, 2), round(e, 2)) for s, e in covering]}")
    print()

    # Structural events nearby.
    print("Structural events within window:")
    struct_offs = ei['offsets']
    struct_kinds = ei['event_kinds']
    nearby_struct = [(o, k) for o, k in zip(struct_offs, struct_kinds)
                      if abs(o - actual_t) <= window_qn]
    if nearby_struct:
        for o, k in nearby_struct:
            print(f"  t={o:.2f}  [{k}]")
    else:
        print("  (none)")
    print()

    # Notes in window.
    print(f"Notes in window [{actual_t - window_qn:.2f}, "
          f"{actual_t + window_qn:.2f}]:")
    notes_list = result['notes_per_part'][part_idx]
    in_window = [n for n in notes_list
                  if abs(n['offset'] - actual_t) <= window_qn]
    if len(in_window) > max_notes_in_window:
        in_window = in_window[:max_notes_in_window]
        truncated = True
    else:
        truncated = False
    for n in in_window:
        marker = ""
        if abs(n['offset'] - actual_t) < 0.01:
            marker += " <-- AT POINT"
        is_slur_start = any(abs(n['offset'] - s) <= 0.5 for s in slur_starts)
        is_slur_end = any(abs(n['offset'] - e) <= 0.5 for e in slur_ends)
        roles = []
        if is_slur_start:
            roles.append('slur_start')
        if is_slur_end:
            roles.append('slur_end')
        if n.get('staccato'):
            roles.append('staccato')
        if n.get('in_tuplet_interior'):
            roles.append('tuplet_interior')
        if n.get('tie_type'):
            roles.append(f"tie={n['tie_type']}")
        role_str = f"  [{', '.join(roles)}]" if roles else ""
        midi = n['pitch']
        try:
            pname = m21.pitch.Pitch(midi).nameWithOctave
        except Exception:
            pname = f"midi={midi}"
        print(f"  t={n['offset']:6.2f}  pitch={pname:6s}  "
              f"dur={n['duration']:.2f}{role_str}{marker}")
    if truncated:
        print(f"  ... ({len(in_window)} notes shown, more in window)")
    print()

    # Other detected boundaries in window.
    if nearby_boundaries:
        print(f"Other detected boundaries in window:")
        for b in nearby_boundaries:
            if not here_boundaries or abs(b - here_boundaries[0]) > 0.01:
                b_idx = int(round(b * division))
                b_idx = min(max(b_idx, 0), len(B_i) - 1)
                print(f"  t={b:.2f}  B_i={B_i[b_idx]:.3f}")
        print()

    print(sep)


def main():
    parser = argparse.ArgumentParser(
        description="V2.4 sectioning pipeline (per-part, slur/hairpin/"
                    "structural-event aware) for orchestral symbolic music."
    )
    parser.add_argument('input', help='Path to .mxl or .musicxml file')
    parser.add_argument('-o', '--output_dir', default='./output')
    parser.add_argument('--division', type=int, default=8)
    parser.add_argument('--kernel_size', type=int, default=64)
    parser.add_argument('--alpha', type=float, default=0.5)
    parser.add_argument('--beta', type=float, default=0.5)
    parser.add_argument('--delta', type=float, default=0.5,
                        help='Phrase-marker-interior suppression (0..1)')
    parser.add_argument('--gamma', type=float, default=0.4,
                        help='Slur-endpoint additive boost')
    parser.add_argument('--zeta', type=float, default=0.4,
                        help='Structural-event additive boost')
    parser.add_argument('--w_pitch', type=float, default=0.25)
    parser.add_argument('--w_ioi', type=float, default=0.50)
    parser.add_argument('--w_rest', type=float, default=0.25)
    parser.add_argument('--lbdm_smooth_qn', type=float, default=0.5)
    parser.add_argument('--slur_endpoint_sigma_qn', type=float, default=0.5)
    parser.add_argument('--structural_sigma_qn', type=float, default=0.5)
    parser.add_argument('--peak_height', type=float, default=0.3)
    parser.add_argument('--peak_distance_qn', type=float, default=2.5)
    parser.add_argument('--convention', choices=['muller', 'foote'],
                        default='muller')
    parser.add_argument('--tacet_threshold', type=float, default=0.05)
    parser.add_argument('--breath_color', default='#d62728')

    args = parser.parse_args()

    run_sectioning(
        args.input,
        output_dir=args.output_dir,
        division=args.division,
        kernel_size_frames=args.kernel_size,
        alpha=args.alpha, beta=args.beta,
        delta=args.delta, gamma=args.gamma, zeta=args.zeta,
        w_pitch=args.w_pitch, w_ioi=args.w_ioi, w_rest=args.w_rest,
        lbdm_smoothing_qn=args.lbdm_smooth_qn,
        slur_endpoint_sigma_qn=args.slur_endpoint_sigma_qn,
        structural_sigma_qn=args.structural_sigma_qn,
        peak_height=args.peak_height,
        peak_distance_qn=args.peak_distance_qn,
        convention=args.convention,
        tacet_threshold=args.tacet_threshold,
        breath_color=args.breath_color,
    )


if __name__ == '__main__':
    main()
