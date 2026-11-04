#!/usr/bin/env python
"""
sectioning_v2_1.py

V2.1 of the sectioning pipeline. Changes from v2:

1. PER-PART B_i(t) — each part gets its own boundary score and its own
   detected boundaries. Sections are now per-instrument, not global, which
   matches the musical reality that different instruments have different
   phrase structures and don't all play at the same time.

2. TACET-PART EXCLUSION — parts with low overall activity (default <5%)
   are flagged as tacet (typically percussion) and excluded from analysis.
   They appear in the output summary but contribute no boundaries.

3. DEFAULT DIVISION = 8 — 16th-note grid resolution, captures rhythms that
   division=4 was aliasing.

4. EDGE ARTIFACT FIX — the first and last L frames of each part's novelty
   curve are zeroed, eliminating the "kernel sticking outside the SSM"
   spike that v2 produced at t=0 and t=T.

5. LBDM TIME-GRID SMOOTHING — per-note LBDM strengths are projected to the
   time grid and convolved with a Gaussian (default sigma = ~0.5 quarter
   notes). Without this, LBDM is sparse delta-spikes that lose visibility
   when combined with the dense SSM novelty curve.

6. STACCATO-AWARE LBDM — when a note carries a staccato (or staccatissimo)
   articulation, the rest-gap to the next note is treated as 0 for the
   LBDM rest profile. This prevents the algorithm from reading every
   air-gap inside a staccato run as a phrase boundary. The IOI profile is
   untouched: rhythm is unchanged by staccato, only the interpretation of
   the printed silence as boundary evidence is.

Math (per part i, generalizing v2):
    phi_i(t) = [a_i(t) * c_i(t); 1 - a_i(t)]      (13D unit vector)
    S_i(t1, t2) = <phi_i(t1), phi_i(t2)>          (per-part SSM)
    nu_i(t)    = -conv(S_i, K_Box)(t)             (per-part novelty)
    sigma_i(k) = sum_p w_p * boundary_strength_p(part_i, k)   (per-part LBDM)
    sigma_i_grid(t) = gaussian_smooth(project_to_grid(sigma_i, notes_i))
    B_i(t)     = alpha * nu_i_norm(t) + beta * sigma_i_grid_norm(t)
    boundaries_i = local peaks of B_i(t)

Output: per-part boundaries, per-part diagnostic plots, score with each
part's section starts colored independently.

Usage:
    python sectioning_v2_1.py path/to/score.mxl [-o output_dir]

As a library:
    from sectioning_v2_1 import run_sectioning
    result = run_sectioning('score.mxl', output_dir='./out')
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
# 1. Score parsing and time grid (unchanged from v2)
# =============================================================================

def parse_score(path):
    score = m21.converter.parse(path)
    parts = list(score.parts)
    return score, parts


def get_part_name(part, default='unknown'):
    """Best-effort part name extraction."""
    name = part.partName or part.partAbbreviation
    if not name:
        for instr in part.getInstruments(recurse=True):
            if instr.instrumentName:
                name = instr.instrumentName
                break
    return name or default


def find_smallest_interval(score):
    smallest = float('inf')
    for element in score.flatten().notesAndRests:
        if hasattr(element, 'duration'):
            d = element.duration.quarterLength
            if d > 0 and d < smallest:
                smallest = d
    return smallest if smallest != float('inf') else 0.25


def create_time_grid(score, division):
    total = score.duration.quarterLength
    return np.arange(0, total + 1.0 / division, 1.0 / division)


# =============================================================================
# 2. Per-frame features (unchanged from v2)
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
    """13D unit-norm feature vectors. See v2 for derivation."""
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


# =============================================================================
# 3. NEW: Tacet-part detection
# =============================================================================

def compute_activity_levels(activity, threshold=0.05):
    """
    Per-part activity ratio (fraction of frames where the part is sounding).

    Returns:
        levels: shape (N,), the activity ratio per part
        is_tacet: shape (N,), True if level < threshold

    Default threshold of 0.05 catches percussion parts that play only
    occasional cymbal hits, while still keeping low-activity but
    musically-significant parts (e.g. a single solo line in one section).
    """
    levels = np.mean(activity, axis=1)
    is_tacet = levels < threshold
    return levels, is_tacet


# =============================================================================
# 4. Per-part SSM (unchanged from v2)
# =============================================================================

def build_ssm(phi_part):
    return phi_part @ phi_part.T


# =============================================================================
# 5. Foote/Muller checkerboard kernel (unchanged from v2)
# =============================================================================

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


# =============================================================================
# 6. Novelty with edge artifact fix
# =============================================================================

def compute_novelty(ssm, kernel, convention='muller', trim_edges=True):
    """
    Slide the kernel along the SSM diagonal and compute novelty.

    NEW in v2.1: optionally zero out the first L and last L frames of the
    output. The kernel sticking outside the SSM (where padded zeros sit)
    produces a large spurious response in v2; trimming the edges removes
    this artifact.

    For very short pieces where 2L >= T, edge trimming would zero out the
    entire signal, so we cap the trim at T // 4.
    """
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
# 7. LBDM with staccato awareness
# =============================================================================

def has_staccato(element):
    """
    True if the note element has a staccato or staccatissimo articulation.
    music21 represents Staccatissimo as a subclass of Staccato, so the
    isinstance check on Staccato catches both. Spiccato is a string
    instrument articulation that is rhythmically similar to staccato; we
    include it as well.
    """
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


def extract_lbdm_profiles(part):
    """
    Build per-note records for LBDM. Each record knows its offset, MIDI
    pitch (top note for chords), duration, and whether it carries a
    staccato-style articulation.

    Then build three interval profiles between consecutive notes:
      - pitch_intervals: |MIDI_{i+1} - MIDI_i|
      - iois: offset_{i+1} - offset_i
      - rests: max(offset_{i+1} - (offset_i + duration_i), 0), with
        STACCATO OVERRIDE: if note i is staccato, rest is forced to 0
        regardless of literal silence. The air-gap is articulation, not
        phrase boundary.
    """
    notes_list = []
    for element in part.flatten().notes:
        if isinstance(element, m21.note.Note):
            notes_list.append({
                'offset': float(element.offset),
                'pitch': element.pitch.midi,
                'duration': float(element.duration.quarterLength),
                'staccato': has_staccato(element),
            })
        elif isinstance(element, m21.chord.Chord):
            top = max(element.notes, key=lambda n: n.pitch.midi)
            notes_list.append({
                'offset': float(element.offset),
                'pitch': top.pitch.midi,
                'duration': float(element.duration.quarterLength),
                'staccato': has_staccato(element),
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
        if cur['staccato']:
            rests[i] = 0.0  # staccato override
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
    return notes_list, sigma


# =============================================================================
# 8. NEW: project LBDM to time grid and smooth
# =============================================================================

def project_lbdm_to_grid(notes_list, sigma, num_frames, division,
                          smoothing_sigma_qn=0.5):
    """
    Project per-note LBDM strengths onto the time grid and Gaussian-smooth.

    Without smoothing, LBDM is a sparse signal (one value per note onset),
    and when combined with the dense SSM novelty signal it loses most of
    its visibility. Smoothing each note's contribution into a small bump
    gives LBDM fair weight in the combination.

    smoothing_sigma_qn: Gaussian sigma in quarter notes. Default 0.5 means
    each note's LBDM contribution spreads over ~1 quarter note (sigma=0.5).
    Converted to frames as sigma_frames = smoothing_sigma_qn * division.
    """
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
# 9. NEW: per-part combination and boundary detection
# =============================================================================

def normalize_signal(x):
    """Min-max normalize to [0,1]. Returns a copy."""
    x = np.asarray(x, dtype=float).copy()
    if x.max() > x.min():
        x = (x - x.min()) / (x.max() - x.min())
    return x


def compute_per_part_boundary_signal(novelty_i, lbdm_grid_i,
                                      alpha=0.5, beta=0.5):
    """
    Combine per-part SSM novelty and per-part LBDM into a single boundary
    score B_i(t). Both inputs are normalized to [0,1] first so alpha/beta
    represent meaningful relative weights.
    """
    nu_norm = normalize_signal(novelty_i)
    lbdm_norm = normalize_signal(lbdm_grid_i)
    B_i = alpha * nu_norm + beta * lbdm_norm
    return B_i, nu_norm, lbdm_norm


def detect_boundaries(B, time_grid, peak_height=0.3, peak_distance_frames=20):
    peaks, _ = find_peaks(B, height=peak_height, distance=peak_distance_frames)
    boundary_times = time_grid[peaks] if len(peaks) > 0 else np.array([])
    return boundary_times


# =============================================================================
# 10. Outputs (per-part variants)
# =============================================================================

# Distinct color cycles for section markers; each part cycles through its
# own list so different parts' sections can be visually separated.
SECTION_COLORS = ['#d62728', '#1f77b4', '#2ca02c', '#9467bd',
                  '#ff7f0e', '#17becf', '#bcbd22', '#e377c2']


def annotate_score_per_part(original_score, boundaries_per_part,
                             part_indices_to_annotate, output_path,
                             tolerance=0.5):
    """
    Color the first note of each detected section in each ACTIVE part.
    Each part's sections cycle through SECTION_COLORS independently — this
    means the same color may appear in different parts at different times,
    which is fine; the visual cue is "first note of a section is colored,"
    not "color identifies which section."

    Tacet parts are not annotated (their notes remain default color).
    """
    score_copy = copy.deepcopy(original_score)
    parts = list(score_copy.parts)

    for i, part in enumerate(parts):
        if i not in part_indices_to_annotate:
            continue
        boundaries = boundaries_per_part[i]
        sections_starts = [0.0] + list(boundaries)
        color_for_section = [SECTION_COLORS[k % len(SECTION_COLORS)]
                             for k in range(len(sections_starts))]

        for element in part.flatten().notes:
            offset = float(element.offset)
            section_idx = 0
            for k, start in enumerate(sections_starts):
                if offset + tolerance >= start:
                    section_idx = k
                else:
                    break
            if abs(offset - sections_starts[section_idx]) <= tolerance:
                if hasattr(element, 'style'):
                    element.style.color = color_for_section[section_idx]

    score_copy.write('musicxml', fp=output_path)


def plot_diagnostics_per_part(time_grid, per_part_signals, part_names,
                                boundaries_per_part, is_tacet,
                                activity_levels, output_path):
    """
    One panel per active part showing:
      - normalized SSM novelty (light blue, transparent)
      - normalized LBDM (light green, transparent)
      - combined B_i (black, opaque)
      - detected boundaries (red dashed verticals)

    Plus a top "summary" panel showing all parts' boundaries on a shared
    timeline, so you can see at a glance which parts agree and which
    diverge.
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
        ax_sum.text(time_grid[0] - (time_grid[-1] - time_grid[0]) * 0.01,
                    j, f"{part_names[i]} [{activity_levels[i]:.0%}]",
                    fontsize=7, ha='right', va='center')
    ax_sum.set_yticks([])
    ax_sum.set_ylim(-1, len(active_indices))
    ax_sum.grid(axis='x', alpha=0.3)

    # Per-part B_i panels
    for j, i in enumerate(active_indices):
        ax = axes[j + 1]
        B_i, nu_i, lbdm_i = per_part_signals[i]
        ax.plot(time_grid, nu_i, color='steelblue', alpha=0.35,
                linewidth=0.7, label='SSM nov')
        ax.plot(time_grid, lbdm_i, color='seagreen', alpha=0.35,
                linewidth=0.7, label='LBDM')
        ax.plot(time_grid, B_i, color='black', linewidth=1.1, label='B_i')
        for bt in boundaries_per_part[i]:
            ax.axvline(x=bt, color='red', linestyle='--', alpha=0.6,
                       linewidth=0.8)
        ax.set_title(f"{part_names[i]} ({len(boundaries_per_part[i])} boundaries)",
                     fontsize=8, loc='left')
        ax.legend(fontsize=6, loc='upper right')
        ax.set_ylim(-0.05, 1.1)

    axes[-1].set_xlabel("Time (quarter notes)")
    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close()


def write_summary_per_part(boundaries_per_part, part_names, activity_levels,
                            is_tacet, score, output_path,
                            alpha, beta, w_pitch, w_ioi, w_rest,
                            division, kernel_size_frames):
    """JSON summary with per-part boundary lists and metadata."""
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
        entry = {
            'index': i,
            'name': part_names[i],
            'activity_level': float(activity_levels[i]),
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
# 11. Main pipeline
# =============================================================================

def run_sectioning(input_path, output_dir='./output',
                    division=8,
                    kernel_size_frames=64,
                    alpha=0.5, beta=0.5,
                    w_pitch=0.25, w_ioi=0.50, w_rest=0.25,
                    lbdm_smoothing_qn=0.5,
                    peak_height=0.3, peak_distance_qn=2.5,
                    convention='muller',
                    tacet_threshold=0.05):
    """
    Top-level v2.1 pipeline.

    Args:
        input_path: path to .mxl or .musicxml file
        output_dir: where to write outputs
        division: frames per quarter note (default 8 = 16th note resolution).
        kernel_size_frames: full kernel size (default 64 frames = 8 qn at
                             division=8 = 2 measures of 4/4)
        alpha, beta: weights for SSM novelty vs LBDM in B_i(t)
        w_pitch, w_ioi, w_rest: LBDM internal weights (Cambouropoulos defaults)
        lbdm_smoothing_qn: Gaussian sigma in quarter notes for LBDM smoothing
        peak_height: minimum normalized peak value (in [0,1]) for a boundary
        peak_distance_qn: minimum spacing between boundaries in quarter notes
        convention: 'muller' or 'foote' kernel sign convention
        tacet_threshold: parts with activity below this are excluded

    Returns:
        dict with per_part_boundaries (list of arrays), part_names, is_tacet,
        activity_levels.
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"[1/8] Loading {input_path}")
    score, parts = parse_score(input_path)
    part_names = [get_part_name(p, default=f'part_{i}')
                  for i, p in enumerate(parts)]
    print(f"      {len(parts)} parts, total length "
          f"{score.duration.quarterLength:.1f} quarter notes")

    print(f"[2/8] Time grid (division={division})")
    time_grid = create_time_grid(score, division)
    T = len(time_grid)
    print(f"      {T} frames")

    print("[3/8] Per-frame features")
    activity, chroma = extract_features(parts, time_grid, division)
    phi = build_feature_vectors(activity, chroma)

    print(f"[4/8] Tacet detection (threshold={tacet_threshold:.0%})")
    activity_levels, is_tacet = compute_activity_levels(
        activity, threshold=tacet_threshold
    )
    for i in range(len(parts)):
        marker = " [TACET]" if is_tacet[i] else ""
        print(f"      part {i:2d} {part_names[i]:25s} "
              f"activity={activity_levels[i]:.1%}{marker}")

    print(f"[5/8] Per-part SSM novelty (kernel={kernel_size_frames} frames)")
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

    print(f"[6/8] Per-part LBDM (sigma_smooth={lbdm_smoothing_qn} qn)")
    lbdm_grids = []
    for i in range(len(parts)):
        if is_tacet[i]:
            lbdm_grids.append(np.zeros(T))
            continue
        notes_list, sigma = compute_lbdm_per_part(
            parts[i], w_pitch=w_pitch, w_ioi=w_ioi, w_rest=w_rest
        )
        grid = project_lbdm_to_grid(
            notes_list, sigma, T, division,
            smoothing_sigma_qn=lbdm_smoothing_qn
        )
        lbdm_grids.append(grid)

    print(f"[7/8] Per-part B_i(t) and boundary detection "
          f"(alpha={alpha}, beta={beta})")
    peak_distance_frames = max(int(round(peak_distance_qn * division)), 1)
    per_part_signals = []   # list of (B_i, nu_norm, lbdm_norm)
    boundaries_per_part = []
    for i in range(len(parts)):
        if is_tacet[i]:
            per_part_signals.append((np.zeros(T), np.zeros(T), np.zeros(T)))
            boundaries_per_part.append(np.array([]))
            continue
        B_i, nu_n, lbdm_n = compute_per_part_boundary_signal(
            novelty_per_part[i], lbdm_grids[i],
            alpha=alpha, beta=beta
        )
        per_part_signals.append((B_i, nu_n, lbdm_n))
        bdys = detect_boundaries(
            B_i, time_grid,
            peak_height=peak_height,
            peak_distance_frames=peak_distance_frames
        )
        boundaries_per_part.append(bdys)
        print(f"      part {i:2d} {part_names[i]:25s} "
              f"{len(bdys):3d} boundaries")

    print("[8/8] Writing outputs")
    annotated_path = os.path.join(output_dir, 'sectioned.musicxml')
    active_set = {i for i in range(len(parts)) if not is_tacet[i]}
    annotate_score_per_part(score, boundaries_per_part, active_set,
                             annotated_path)

    plot_path = os.path.join(output_dir, 'diagnostics.png')
    plot_diagnostics_per_part(time_grid, per_part_signals, part_names,
                                boundaries_per_part, is_tacet,
                                activity_levels, plot_path)

    summary_path = os.path.join(output_dir, 'boundaries.json')
    write_summary_per_part(
        boundaries_per_part, part_names, activity_levels, is_tacet,
        score, summary_path,
        alpha=alpha, beta=beta,
        w_pitch=w_pitch, w_ioi=w_ioi, w_rest=w_rest,
        division=division, kernel_size_frames=kernel_size_frames,
    )

    print(f"      Annotated:   {annotated_path}")
    print(f"      Diagnostics: {plot_path}")
    print(f"      Summary:     {summary_path}")

    return {
        'per_part_boundaries': boundaries_per_part,
        'part_names': part_names,
        'is_tacet': is_tacet,
        'activity_levels': activity_levels,
        'time_grid': time_grid,
        'per_part_signals': per_part_signals,
    }


def main():
    parser = argparse.ArgumentParser(
        description="V2.1 sectioning pipeline (per-part) for orchestral "
                    "symbolic music."
    )
    parser.add_argument('input', help='Path to .mxl or .musicxml file')
    parser.add_argument('-o', '--output_dir', default='./output')
    parser.add_argument('--division', type=int, default=8)
    parser.add_argument('--kernel_size', type=int, default=64)
    parser.add_argument('--alpha', type=float, default=0.5)
    parser.add_argument('--beta', type=float, default=0.5)
    parser.add_argument('--w_pitch', type=float, default=0.25)
    parser.add_argument('--w_ioi', type=float, default=0.50)
    parser.add_argument('--w_rest', type=float, default=0.25)
    parser.add_argument('--lbdm_smooth_qn', type=float, default=0.5)
    parser.add_argument('--peak_height', type=float, default=0.3)
    parser.add_argument('--peak_distance_qn', type=float, default=2.5)
    parser.add_argument('--convention', choices=['muller', 'foote'],
                        default='muller')
    parser.add_argument('--tacet_threshold', type=float, default=0.05)

    args = parser.parse_args()

    run_sectioning(
        args.input,
        output_dir=args.output_dir,
        division=args.division,
        kernel_size_frames=args.kernel_size,
        alpha=args.alpha, beta=args.beta,
        w_pitch=args.w_pitch, w_ioi=args.w_ioi, w_rest=args.w_rest,
        lbdm_smoothing_qn=args.lbdm_smooth_qn,
        peak_height=args.peak_height,
        peak_distance_qn=args.peak_distance_qn,
        convention=args.convention,
        tacet_threshold=args.tacet_threshold,
    )


if __name__ == '__main__':
    main()
