#!/usr/bin/env python
"""
sectioning_v2.py

V2 of the sectioning pipeline for orchestral symbolic music.

Key changes from v1:
1. 13D feature representation with explicit rest dimension. Cosine similarity
   now handles rests cleanly: rest-rest = 1, rest-pitched = 0, pitched-pitched
   = chroma cosine. See `build_feature_vectors`.
2. Proper Foote/Muller K_Box checkerboard kernel with Gaussian taper, replacing
   the (incorrect) triu-tril kernel from v1. See `make_checkerboard_kernel`.
3. Per-part LBDM (Cambouropoulos 2001) added as a complementary signal. See
   `compute_lbdm_per_part`.
4. Cross-part aggregation via weighted combination of mean novelty and mean
   LBDM strength. See `aggregate_signals`.

Mathematical pipeline (see also accompanying derivation):
    phi_i(t) = [a_i(t) * c_i(t); 1 - a_i(t)]   (13D unit vector)
    S_i(t1, t2) = <phi_i(t1), phi_i(t2)>       (per-part SSM)
    nu_i(t) = -conv(S_i, K_Box)(t)             (per-part novelty, peaks at boundaries)
    sigma_i(k) = sum_p w_p * boundary_strength_p(part_i)   (per-part LBDM)
    B(t) = alpha * mean_i(nu_i(t)) + beta * mean_i(sigma_i_projected(t))
    boundaries = local peaks of B(t)

Usage:
    python sectioning_v2.py path/to/score.mxl [output_dir]

Or as a library:
    from sectioning_v2 import run_sectioning
    boundaries, B = run_sectioning('score.mxl', output_dir='./out')
"""

import os
import sys
import json
import copy
import argparse
from itertools import cycle

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks
import music21 as m21


# =============================================================================
# 1. Score parsing and time grid
# =============================================================================

def parse_score(path):
    """Load a MusicXML / MXL file and return the score and its parts."""
    score = m21.converter.parse(path)
    parts = list(score.parts)
    return score, parts


def find_smallest_interval(score):
    """Smallest note duration in quarter lengths. Falls back to a 16th note."""
    smallest = float('inf')
    for element in score.flatten().notesAndRests:
        if hasattr(element, 'duration'):
            d = element.duration.quarterLength
            if d > 0 and d < smallest:
                smallest = d
    return smallest if smallest != float('inf') else 0.25


def create_time_grid(score, division):
    """
    Time grid in quarter lengths at the given division (frames per quarter note).
    division=4 means 4 frames per quarter note (16th note resolution).
    """
    total = score.duration.quarterLength
    return np.arange(0, total + 1.0 / division, 1.0 / division)


# =============================================================================
# 2. Per-frame features
# =============================================================================

def extract_features(parts, time_grid, division):
    """
    For each (part, frame), extract:
      - activity: 1 if a note/chord is sounding, 0 if rest or empty
      - chroma: 12-dim count of active pitch classes (NOT YET normalized)

    Rests intentionally leave both activity=0 and chroma=0 at their frames.
    The rest-as-zero pathology is fixed downstream in `build_feature_vectors`.
    """
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
            # Rests: leave activity=0 and chroma=0 (the rest dimension below
            # will pick this up).

    return activity, chroma


def build_feature_vectors(activity, chroma):
    """
    Build the 13D unit-norm feature vector per (part, frame):

        phi(t) = [a(t) * c(t) / ||c(t)||;  1 - a(t)]    in R^13

    Properties:
      - When active: phi[:12] = unit chroma, phi[12] = 0  -> ||phi|| = 1
      - When resting: phi[:12] = 0, phi[12] = 1            -> ||phi|| = 1
      - All vectors are unit norm, so cosine = dot product

    Pairwise cosine similarity then gives:
      - Both resting   -> 1   (identity)
      - Both playing   -> cos(chroma1, chroma2)
      - One of each    -> 0   (orthogonal)

    This is the rest-aware similarity worked out in the math derivation.
    """
    N, T, _ = chroma.shape
    phi = np.zeros((N, T, 13))
    for i in range(N):
        for t in range(T):
            if activity[i, t] == 1:
                c = chroma[i, t]
                norm = np.linalg.norm(c)
                if norm > 0:
                    phi[i, t, :12] = c / norm
                # Active but somehow norm 0 (shouldn't happen): leave as zeros.
                # Don't set rest dimension because activity says we're playing.
            else:
                phi[i, t, 12] = 1.0
    return phi


# =============================================================================
# 3. Per-part SSM
# =============================================================================

def build_ssm(phi_part):
    """
    SSM for a single part, computed as the cosine similarity between every pair
    of frames. Since phi is unit-norm, cosine == dot product.

    Args:
        phi_part: shape (T, 13)
    Returns:
        ssm: shape (T, T), values in [0, 1] roughly (chroma cosine can dip
             slightly negative but with non-negative chroma it stays >= 0).
    """
    return phi_part @ phi_part.T


# =============================================================================
# 4. Foote/Muller checkerboard kernel and novelty
# =============================================================================

def make_checkerboard_kernel(L, sigma=None, convention='muller'):
    """
    Construct a (2L+1) x (2L+1) checkerboard kernel with Gaussian taper.

    Two conventions, mathematically equivalent up to negation:
      - 'foote': +1 in TL, BR (diagonal blocks); -1 in TR, BL.
        Convolution gives positive peaks at boundaries.
      - 'muller': -1 in TL, BR; +1 in TR, BL (matches FMP K_Box).
        Convolution gives negative peaks; we negate downstream.

    Both flag the "past block self-similarity + future block self-similarity vs
    cross-region similarity" geometry that makes this a boundary detector.

    The middle row and column are zeroed to avoid the trivial diagonal of the
    SSM polluting the response (Muller's K_Box convention).

    Gaussian taper sigma defaults to L/2; this softens edge effects and is
    standard practice (Muller FMP C4S4).
    """
    size = 2 * L + 1
    K = np.zeros((size, size))

    sign_diag = -1 if convention == 'muller' else +1
    sign_off = +1 if convention == 'muller' else -1

    for r in range(size):
        for s in range(size):
            if r == L or s == L:
                K[r, s] = 0  # center cross
            elif (r < L) and (s < L):
                K[r, s] = sign_diag  # TL
            elif (r > L) and (s > L):
                K[r, s] = sign_diag  # BR
            elif (r < L) and (s > L):
                K[r, s] = sign_off  # TR
            elif (r > L) and (s < L):
                K[r, s] = sign_off  # BL

    if sigma is None:
        sigma = L / 2.0
    coords = np.arange(size) - L
    rs, cs = np.meshgrid(coords, coords, indexing='ij')
    gauss = np.exp(-(rs ** 2 + cs ** 2) / (2.0 * sigma ** 2))
    K = K * gauss

    return K


def compute_novelty(ssm, kernel, convention='muller'):
    """
    Slide the kernel along the diagonal of the SSM. With the Muller convention,
    negate the result so that boundaries appear as positive peaks.

    Returns a 1D array of length T (same as one side of the SSM).
    """
    T = ssm.shape[0]
    L = kernel.shape[0] // 2
    novelty = np.zeros(T)

    # Pad SSM with zeros so the kernel is defined at boundaries.
    padded = np.pad(ssm, L, mode='constant', constant_values=0.0)

    for t in range(T):
        patch = padded[t:t + 2 * L + 1, t:t + 2 * L + 1]
        novelty[t] = np.sum(patch * kernel)

    if convention == 'muller':
        novelty = -novelty

    return novelty


# =============================================================================
# 5. LBDM (Cambouropoulos 2001) per part
# =============================================================================

def extract_lbdm_profiles(part):
    """
    From a music21 part, extract:
      - notes: list of dicts {offset, pitch (MIDI), duration} sorted by offset
      - pitch_intervals: |MIDI_{i+1} - MIDI_i| between consecutive notes
      - iois: offset_{i+1} - offset_i  (inter-onset intervals)
      - rests: max(offset_{i+1} - (offset_i + duration_i), 0)  (silence between)

    Chords are reduced to their highest pitch (skyline-style) for LBDM purposes.
    Tied notes are NOT merged — each tied segment counts as its own note.
    """
    notes_list = []
    for element in part.flatten().notes:
        if isinstance(element, m21.note.Note):
            notes_list.append({
                'offset': float(element.offset),
                'pitch': element.pitch.midi,
                'duration': float(element.duration.quarterLength),
            })
        elif isinstance(element, m21.chord.Chord):
            top = max(element.notes, key=lambda n: n.pitch.midi)
            notes_list.append({
                'offset': float(element.offset),
                'pitch': top.pitch.midi,
                'duration': float(element.duration.quarterLength),
            })

    notes_list.sort(key=lambda x: x['offset'])

    n = max(len(notes_list) - 1, 0)
    pitch_intervals = np.zeros(n)
    iois = np.zeros(n)
    rests = np.zeros(n)

    for i in range(n):
        cur = notes_list[i]
        nxt = notes_list[i + 1]
        pitch_intervals[i] = abs(nxt['pitch'] - cur['pitch'])
        iois[i] = nxt['offset'] - cur['offset']
        rest_gap = nxt['offset'] - (cur['offset'] + cur['duration'])
        rests[i] = max(rest_gap, 0.0)

    return notes_list, pitch_intervals, iois, rests


def degree_of_change(profile):
    """
    LBDM degree-of-change function:

        r_{i, i+1} = |x_i - x_{i+1}| / (x_i + x_{i+1})   if x_i + x_{i+1} > 0
                                                        and x_i != x_{i+1}
                   = 0                                   otherwise

    Returns r of length len(profile) - 1, or empty if profile too short.
    """
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
    """
    LBDM boundary strength on each interval:

        s_i = x_i * (r_{i-1, i} + r_{i, i+1})

    where r is the degree-of-change function. Endpoints use 0 for the missing
    neighbor. Result is normalized to [0, 1] by max value.
    """
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
    Compute combined LBDM boundary strength per note for a single part.

    Default weights are Cambouropoulos's literature-grounded values
    (pitch=0.25, IOI=0.50, rest=0.25). IOI carries the most weight.

    Returns:
        notes: list of note dicts (with 'offset' field)
        sigma: 1D array of combined boundary strengths, length len(notes) (or
               len(notes)-1 if fewer than 2 notes; aligned with notes by index)
    """
    notes_list, pi, ioi, rest = extract_lbdm_profiles(part)
    s_pitch = boundary_strength(pi)
    s_ioi = boundary_strength(ioi)
    s_rest = boundary_strength(rest)

    # All three should have the same length (len(notes) - 1).
    n = min(len(s_pitch), len(s_ioi), len(s_rest))
    if n == 0:
        return notes_list, np.array([])
    sigma = (
        w_pitch * s_pitch[:n] +
        w_ioi * s_ioi[:n] +
        w_rest * s_rest[:n]
    )
    return notes_list, sigma


# =============================================================================
# 6. Cross-part aggregation
# =============================================================================

def aggregate_signals(time_grid, novelty_per_part, lbdm_results,
                      division, alpha=0.5, beta=0.5):
    """
    Combine per-part SSM novelty and per-part LBDM strength into a single
    boundary score on the time grid:

        B(t) = alpha * mean_i(nu_i(t))  +  beta * mean_i(sigma_i_projected(t))

    LBDM is sparse (per-note) and gets projected to the time grid by placing
    each note's strength at its offset frame.

    Both component signals are normalized to [0, 1] before combination so that
    alpha, beta represent meaningful relative weights regardless of raw scale.
    """
    T = len(time_grid)
    N = len(novelty_per_part)

    # SSM novelty: average across parts, then normalize to [0, 1].
    avg_novelty = np.mean(novelty_per_part, axis=0)
    if avg_novelty.max() > avg_novelty.min():
        avg_novelty = (avg_novelty - avg_novelty.min()) / (
            avg_novelty.max() - avg_novelty.min()
        )

    # LBDM: project each part's per-note strength onto the time grid, then
    # average across parts (frames with no notes contribute 0).
    lbdm_grid = np.zeros((N, T))
    for i, (notes_list, sigma) in enumerate(lbdm_results):
        for k, note in enumerate(notes_list):
            if k >= len(sigma):
                break
            idx = int(round(note['offset'] * division))
            if 0 <= idx < T:
                lbdm_grid[i, idx] = max(lbdm_grid[i, idx], sigma[k])
    avg_lbdm = np.mean(lbdm_grid, axis=0)
    if avg_lbdm.max() > 0:
        avg_lbdm = avg_lbdm / avg_lbdm.max()

    B = alpha * avg_novelty + beta * avg_lbdm
    return B, avg_novelty, avg_lbdm


# =============================================================================
# 7. Boundary detection
# =============================================================================

def detect_boundaries(B, time_grid, peak_height=0.3, peak_distance_frames=20):
    """
    Find local peaks in the combined boundary score B(t).

    peak_height: minimum value (in normalized [0,1] units) for a peak to count.
    peak_distance_frames: minimum spacing between peaks, in frames.
    """
    peaks, _ = find_peaks(B, height=peak_height, distance=peak_distance_frames)
    boundary_times = time_grid[peaks] if len(peaks) > 0 else np.array([])
    return boundary_times, peaks


# =============================================================================
# 8. Outputs
# =============================================================================

# A small, deliberately-distinct color cycle for sections in MuseScore.
SECTION_COLORS = ['#d62728', '#1f77b4', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf']


def annotate_score(original_score, boundary_times, output_path,
                   tolerance=0.5):
    """
    Color the first note of each detected section with a distinct color cycling
    through SECTION_COLORS. Writes the modified score to output_path.

    tolerance: a note within this many quarter notes of a boundary counts as
    the section-starting note.
    """
    score_copy = copy.deepcopy(original_score)

    # Assign a color to each section. Section k starts at boundary_times[k-1]
    # (or at offset 0 for section 0). We have len(boundary_times) + 1 sections.
    sections_starts = [0.0] + list(boundary_times)
    color_for_section = [SECTION_COLORS[k % len(SECTION_COLORS)]
                         for k in range(len(sections_starts))]

    for part in score_copy.parts:
        for element in part.flatten().notes:
            offset = float(element.offset)
            # Find which section this note's offset falls into.
            section_idx = 0
            for k, start in enumerate(sections_starts):
                if offset + tolerance >= start:
                    section_idx = k
                else:
                    break
            # Only color notes that ARE the section start (within tolerance).
            if abs(offset - sections_starts[section_idx]) <= tolerance:
                # Color via style.color (works in MuseScore for MusicXML)
                if hasattr(element, 'style'):
                    element.style.color = color_for_section[section_idx]

    score_copy.write('musicxml', fp=output_path)


def plot_diagnostics(time_grid, B, avg_novelty, avg_lbdm,
                     novelty_per_part, lbdm_results, boundary_times,
                     output_path):
    """
    Multi-panel diagnostic plot:
      - One panel per part showing per-part SSM novelty
      - Averaged SSM novelty (normalized)
      - Averaged LBDM strength (normalized)
      - Combined B(t) with detected boundaries marked
    """
    N = len(novelty_per_part)
    n_panels = N + 3
    fig, axes = plt.subplots(n_panels, 1, figsize=(14, 1.6 * n_panels),
                             sharex=True)
    if n_panels == 1:
        axes = [axes]

    for i in range(N):
        axes[i].plot(time_grid[:len(novelty_per_part[i])],
                     novelty_per_part[i], linewidth=0.8)
        axes[i].set_title(f"SSM novelty - part {i}", fontsize=9, loc='left')
        for bt in boundary_times:
            axes[i].axvline(x=bt, color='r', linestyle='--', alpha=0.4,
                            linewidth=0.8)

    axes[N].plot(time_grid, avg_novelty, color='steelblue', linewidth=1.2)
    axes[N].set_title("Mean SSM novelty (normalized)", fontsize=9, loc='left')
    for bt in boundary_times:
        axes[N].axvline(x=bt, color='r', linestyle='--', alpha=0.4,
                        linewidth=0.8)

    axes[N + 1].plot(time_grid, avg_lbdm, color='seagreen', linewidth=1.2)
    axes[N + 1].set_title("Mean LBDM strength (normalized)",
                          fontsize=9, loc='left')
    for bt in boundary_times:
        axes[N + 1].axvline(x=bt, color='r', linestyle='--', alpha=0.4,
                            linewidth=0.8)

    axes[N + 2].plot(time_grid, B, color='black', linewidth=1.5)
    axes[N + 2].set_title(
        f"Combined B(t) — {len(boundary_times)} boundaries detected",
        fontsize=9, loc='left'
    )
    axes[N + 2].set_xlabel("Time (quarter notes)")
    for bt in boundary_times:
        axes[N + 2].axvline(x=bt, color='r', linestyle='--', alpha=0.7,
                            linewidth=1.0)

    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close()


def write_summary(boundary_times, score, output_path,
                  alpha=0.5, beta=0.5,
                  w_pitch=0.25, w_ioi=0.50, w_rest=0.25):
    """
    Write boundaries + parameter settings as JSON for inspection.

    Each boundary is annotated with its measure number and beat-in-measure
    when those can be computed from the score.
    """
    # Build a measure-offset map by walking the first part's measures.
    measure_offsets = []  # list of (offset, measure_number, time_signature)
    if len(score.parts) > 0:
        for measure in score.parts[0].getElementsByClass(m21.stream.Measure):
            ts = None
            for sig in measure.getElementsByClass(m21.meter.TimeSignature):
                ts = (sig.numerator, sig.denominator)
                break
            measure_offsets.append((float(measure.offset), measure.number, ts))

    def offset_to_measure_beat(offset):
        if not measure_offsets:
            return None, None
        # Find latest measure starting at or before offset.
        candidate = measure_offsets[0]
        for mo in measure_offsets:
            if mo[0] <= offset:
                candidate = mo
            else:
                break
        measure_offset, measure_number, _ = candidate
        beat = offset - measure_offset + 1.0  # 1-indexed beat
        return measure_number, beat

    summary = {
        'parameters': {
            'alpha_ssm_weight': alpha,
            'beta_lbdm_weight': beta,
            'lbdm_w_pitch': w_pitch,
            'lbdm_w_ioi': w_ioi,
            'lbdm_w_rest': w_rest,
        },
        'num_boundaries': len(boundary_times),
        'boundaries': [],
    }
    for bt in boundary_times:
        m, b = offset_to_measure_beat(float(bt))
        summary['boundaries'].append({
            'time_quarter_notes': float(bt),
            'measure': m,
            'beat': b,
        })

    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2)


# =============================================================================
# 9. Main pipeline
# =============================================================================

def run_sectioning(input_path, output_dir='./output',
                   division=4,
                   kernel_size_frames=32,
                   alpha=0.5, beta=0.5,
                   w_pitch=0.25, w_ioi=0.50, w_rest=0.25,
                   peak_height=0.3, peak_distance_frames=20,
                   convention='muller'):
    """
    Top-level pipeline.

    Args:
        input_path: path to .mxl or .musicxml file
        output_dir: where to write annotated score, diagnostic plot, JSON summary
        division: frames per quarter note for the time grid (default 4 = 16th
                  note resolution, fine for sectioning; larger = finer/slower)
        kernel_size_frames: full kernel size in frames (must be even);
                            default 32 frames = 8 quarter notes at division=4
                            = 2 measures of 4/4
        alpha, beta: weights for SSM novelty vs LBDM in the combined B(t)
        w_pitch, w_ioi, w_rest: LBDM internal weights (literature defaults
                                from Cambouropoulos 2001)
        peak_height: minimum normalized peak value to count as a boundary
        peak_distance_frames: minimum spacing between detected boundaries
        convention: 'muller' or 'foote' for the kernel sign convention

    Returns:
        boundary_times: array of detected boundary times in quarter notes
        B: the combined boundary score on the time grid
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"[1/7] Loading {input_path}")
    score, parts = parse_score(input_path)
    print(f"      {len(parts)} parts, total length "
          f"{score.duration.quarterLength:.1f} quarter notes")

    print(f"[2/7] Building time grid (division={division} frames/qn)")
    time_grid = create_time_grid(score, division)
    print(f"      {len(time_grid)} frames")

    print("[3/7] Extracting per-frame features")
    activity, chroma = extract_features(parts, time_grid, division)
    phi = build_feature_vectors(activity, chroma)

    print(f"[4/7] Per-part SSMs and novelty (kernel={kernel_size_frames} frames)")
    L = kernel_size_frames // 2
    kernel = make_checkerboard_kernel(L, convention=convention)
    novelty_per_part = []
    for i in range(len(parts)):
        ssm = build_ssm(phi[i])
        nu = compute_novelty(ssm, kernel, convention=convention)
        novelty_per_part.append(nu)
    novelty_per_part = np.array(novelty_per_part)

    print(f"[5/7] Per-part LBDM (weights pitch={w_pitch}, IOI={w_ioi}, "
          f"rest={w_rest})")
    lbdm_results = []
    for part in parts:
        notes_list, sigma = compute_lbdm_per_part(
            part, w_pitch=w_pitch, w_ioi=w_ioi, w_rest=w_rest
        )
        lbdm_results.append((notes_list, sigma))

    print(f"[6/7] Aggregating signals (alpha={alpha}, beta={beta})")
    B, avg_nov, avg_lbdm = aggregate_signals(
        time_grid, novelty_per_part, lbdm_results, division,
        alpha=alpha, beta=beta
    )

    boundary_times, _ = detect_boundaries(
        B, time_grid,
        peak_height=peak_height,
        peak_distance_frames=peak_distance_frames
    )
    print(f"      Detected {len(boundary_times)} boundaries")

    print("[7/7] Writing outputs")
    annotated_path = os.path.join(output_dir, 'sectioned.musicxml')
    annotate_score(score, boundary_times, annotated_path)

    plot_path = os.path.join(output_dir, 'diagnostics.png')
    plot_diagnostics(time_grid, B, avg_nov, avg_lbdm,
                     novelty_per_part, lbdm_results, boundary_times,
                     plot_path)

    summary_path = os.path.join(output_dir, 'boundaries.json')
    write_summary(boundary_times, score, summary_path,
                  alpha=alpha, beta=beta,
                  w_pitch=w_pitch, w_ioi=w_ioi, w_rest=w_rest)

    print(f"      Annotated score: {annotated_path}")
    print(f"      Diagnostic plot: {plot_path}")
    print(f"      Summary JSON:    {summary_path}")

    return boundary_times, B


def main():
    parser = argparse.ArgumentParser(
        description="V2 sectioning pipeline for orchestral symbolic music."
    )
    parser.add_argument('input', help='Path to .mxl or .musicxml file')
    parser.add_argument('-o', '--output_dir', default='./output',
                        help='Output directory (default: ./output)')
    parser.add_argument('--division', type=int, default=4,
                        help='Frames per quarter note (default: 4)')
    parser.add_argument('--kernel_size', type=int, default=32,
                        help='Kernel size in frames, must be even (default: 32)')
    parser.add_argument('--alpha', type=float, default=0.5,
                        help='SSM novelty weight in B(t) (default: 0.5)')
    parser.add_argument('--beta', type=float, default=0.5,
                        help='LBDM weight in B(t) (default: 0.5)')
    parser.add_argument('--w_pitch', type=float, default=0.25)
    parser.add_argument('--w_ioi', type=float, default=0.50)
    parser.add_argument('--w_rest', type=float, default=0.25)
    parser.add_argument('--peak_height', type=float, default=0.3,
                        help='Minimum normalized peak value (default: 0.3)')
    parser.add_argument('--peak_distance', type=int, default=20,
                        help='Minimum frames between peaks (default: 20)')
    parser.add_argument('--convention', choices=['muller', 'foote'],
                        default='muller',
                        help='Kernel sign convention (default: muller)')

    args = parser.parse_args()

    run_sectioning(
        args.input,
        output_dir=args.output_dir,
        division=args.division,
        kernel_size_frames=args.kernel_size,
        alpha=args.alpha, beta=args.beta,
        w_pitch=args.w_pitch, w_ioi=args.w_ioi, w_rest=args.w_rest,
        peak_height=args.peak_height,
        peak_distance_frames=args.peak_distance,
        convention=args.convention,
    )


if __name__ == '__main__':
    main()
