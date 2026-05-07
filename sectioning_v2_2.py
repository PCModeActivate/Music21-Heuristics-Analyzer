#!/usr/bin/env python
"""
sectioning_v2_2.py

V2.2 of the sectioning pipeline. Changes from v2.1:

1. SLUR-AWARE BOUNDARY MODULATION. Each part's slurs (when present in the
   MusicXML) modulate the per-part boundary signal B_i(t):
     - Peaks in the INTERIOR of a slur are suppressed (multiplicative
       attenuation) to kill mid-phrase false positives.
     - Slur START and END points get a small additive Gaussian boost,
       corroborating genuine phrase boundaries.
   Parts without slurs are unaffected — the modulation reduces to identity.

2. BREATH MARK OUTPUT instead of note coloring. Each detected boundary
   results in a colored BreathMark articulation attached to the last note
   before the boundary in that part. This preserves any pre-existing note
   colors in the score (e.g., GT melody coloring), and breath marks are
   the musically correct notation for phrase endings anyway.

Math (per part i):
    B_i_raw(t)        = alpha * nu_i_norm(t) + beta * sigma_i_grid_norm(t)
    in_slur_i(t)      = 1 if t in interior of a slur in part i, else 0
    slur_endpoints_i  = Gaussian bumps centered on slur start/end frames
    B_i(t) = B_i_raw(t) * (1 - delta * in_slur_i(t)) + gamma * slur_endpoints_i(t)
    boundaries_i = local peaks of B_i(t)

Default modulation parameters:
    delta = 0.5  (50% attenuation inside slurs)
    gamma = 0.3  (30% additive boost at slur endpoints)
    bump_sigma_qn = 0.5  (Gaussian width of endpoint bump)

Usage:
    python sectioning_v2_2.py path/to/score.mxl [-o output_dir]
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
# LBDM with staccato awareness (unchanged from v2.1)
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


def extract_lbdm_profiles(part):
    notes_list = []
    for element in part.flatten().notes:
        if isinstance(element, m21.note.Note):
            notes_list.append({
                'offset': float(element.offset),
                'pitch': element.pitch.midi,
                'duration': float(element.duration.quarterLength),
                'staccato': has_staccato(element),
                'element': element,
            })
        elif isinstance(element, m21.chord.Chord):
            top = max(element.notes, key=lambda n: n.pitch.midi)
            notes_list.append({
                'offset': float(element.offset),
                'pitch': top.pitch.midi,
                'duration': float(element.duration.quarterLength),
                'staccato': has_staccato(element),
                'element': element,
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
    Extract two arrays from a part's slurs:

    in_slur_interior: shape (num_frames,), value 1 inside a slur (strictly
        between start frame and end frame, exclusive of both endpoints) and
        0 elsewhere. The endpoints themselves are NOT marked as interior
        because they ARE the boundary candidates.

    endpoint_bumps: shape (num_frames,), Gaussian-smoothed indicator of
        slur start AND end positions. Each endpoint contributes a bump of
        height 1 with sigma=endpoint_sigma_qn quarter notes. Adjacent
        endpoints (e.g., end of one slur + start of the next on the same
        note) accumulate.

    Slur-finding uses music21's spanner API. For parts without slurs both
    arrays are all zeros and downstream modulation is a no-op.

    Edge cases handled:
      - Slur whose start or end note is missing/None: skipped.
      - Slur with start_note.offset > end_note.offset: skipped (malformed).
      - Multiple overlapping slurs: in_slur_interior is set wherever ANY
        slur's interior covers the frame (boolean OR over slurs).
    """
    in_slur_interior = np.zeros(num_frames, dtype=float)
    endpoints_raw = np.zeros(num_frames, dtype=float)

    # music21 surfaces slurs as spanners on the part. The full spanner list
    # is reachable via part.spanners (a Stream), and Slur is a subclass of
    # Spanner. We iterate carefully because some scores have weird
    # spanners that aren't slurs.
    slurs = []
    try:
        for sp in part.recurse().getElementsByClass(m21.spanner.Slur):
            slurs.append(sp)
    except Exception:
        # If a part has no spanners at all, this can return empty
        # cleanly; the try/except guards against malformed scores.
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

            start_idx = int(round(start_off * division))
            end_idx = int(round(end_off * division))
            start_idx = max(start_idx, 0)
            end_idx = min(end_idx, num_frames - 1)

            # Mark interior (exclusive of endpoints).
            if end_idx > start_idx + 1:
                in_slur_interior[start_idx + 1:end_idx] = 1.0

            # Endpoint deltas (will be Gaussian-smoothed below).
            if 0 <= start_idx < num_frames:
                endpoints_raw[start_idx] = max(endpoints_raw[start_idx], 1.0)
            if 0 <= end_idx < num_frames:
                endpoints_raw[end_idx] = max(endpoints_raw[end_idx], 1.0)
        except Exception:
            # Skip individual malformed slurs without breaking the part.
            continue

    # Gaussian-smooth the endpoint deltas to bumps.
    sigma_frames = endpoint_sigma_qn * division
    if sigma_frames > 0 and endpoints_raw.max() > 0:
        endpoint_bumps = gaussian_filter1d(endpoints_raw, sigma_frames)
        # Renormalize so the max bump is 1.0 (so gamma is a meaningful
        # additive amount on a [0,1]-scaled signal).
        if endpoint_bumps.max() > 0:
            endpoint_bumps = endpoint_bumps / endpoint_bumps.max()
    else:
        endpoint_bumps = np.zeros_like(endpoints_raw)

    return in_slur_interior, endpoint_bumps, len(slurs)


# =============================================================================
# Per-part boundary signal with slur modulation
# =============================================================================

def normalize_signal(x):
    x = np.asarray(x, dtype=float).copy()
    if x.max() > x.min():
        x = (x - x.min()) / (x.max() - x.min())
    return x


def compute_per_part_boundary_signal(novelty_i, lbdm_grid_i,
                                      in_slur_interior_i, endpoint_bumps_i,
                                      alpha=0.5, beta=0.5,
                                      delta=0.5, gamma=0.3):
    """
    B_i(t) with slur modulation:
        B_raw(t) = alpha * nu_norm(t) + beta * lbdm_norm(t)
        B_i(t)   = B_raw(t) * (1 - delta * in_slur_interior(t))
                 + gamma * endpoint_bumps(t)

    delta: how much to attenuate B_raw inside slurs (0 = no attenuation,
           1 = full suppression). Default 0.5 = halve mid-slur peaks.
    gamma: additive boost at slur endpoints. Default 0.3 means a strong
           endpoint contributes up to +0.3 to B (pre-renormalization).

    Returns:
        B_i, nu_norm, lbdm_norm, B_raw  — last three for diagnostics.
    """
    nu_norm = normalize_signal(novelty_i)
    lbdm_norm = normalize_signal(lbdm_grid_i)
    B_raw = alpha * nu_norm + beta * lbdm_norm

    B_i = B_raw * (1.0 - delta * in_slur_interior_i) + gamma * endpoint_bumps_i

    return B_i, nu_norm, lbdm_norm, B_raw


def detect_boundaries(B, time_grid, peak_height=0.3, peak_distance_frames=20):
    peaks, _ = find_peaks(B, height=peak_height, distance=peak_distance_frames)
    boundary_times = time_grid[peaks] if len(peaks) > 0 else np.array([])
    return boundary_times


# =============================================================================
# NEW: Breath mark annotation
# =============================================================================

def add_breath_marks_per_part(original_score, boundaries_per_part,
                                part_indices_to_annotate, output_path,
                                color='#d62728', onset_tolerance=0.5):
    """
    Attach a colored BreathMark articulation to the phrase-ending note for
    each detected boundary.

    Selection rule (FIXED in v2.2.1):
      Prefer the note whose ONSET is within onset_tolerance of the boundary
      time bt. This is typically the long note that ends the phrase: LBDM
      puts its strength at this note's onset (because the IOI from here to
      the next note is anomalously long), and the slur-endpoint bump is
      also centered here (slurs end ON the long note's onset, not after
      its duration). So the detected peak in B_i lands at this onset, and
      the breath mark belongs ON this note — meaning "take a breath after
      playing this," which IS the long phrase-ending note.

      Fallback: if no note is within onset_tolerance of bt (e.g., the
      boundary fell inside a rest between phrases), attach to the last
      note strictly before bt — the v2.2 behavior, which is correct for
      that case.

    Tolerance default of 0.5 quarter notes covers Gaussian-smoothing peak
    shifts and small offset rounding errors; should not so large that we
    cross over the "real" preceding note.

    Existing note colors (e.g., GT melody coloring) are preserved because
    we only mutate note.articulations, never note.style.

    Color handling: we initialize style.TextStyle if needed and set
    style.color, then also set placement='above' so engravers render the
    breath mark above the staff (its conventional position).
    """
    score_copy = copy.deepcopy(original_score)
    parts = list(score_copy.parts)

    for i, part in enumerate(parts):
        if i not in part_indices_to_annotate:
            continue
        boundaries = boundaries_per_part[i]
        notes_with_offsets = sorted(
            [(float(n.offset), n) for n in part.flatten().notes],
            key=lambda x: x[0]
        )
        if not notes_with_offsets:
            continue

        for bt in boundaries:
            # Find best target: closest note whose onset is within
            # onset_tolerance of bt. Track fallback simultaneously: the
            # last note strictly before bt, used if no note is near bt.
            near_target = None
            near_dist = float('inf')
            fallback_target = None

            for off, n in notes_with_offsets:
                if off > bt + onset_tolerance:
                    break
                # Candidate for "near" match
                if abs(off - bt) <= onset_tolerance:
                    d = abs(off - bt)
                    if d < near_dist:
                        near_dist = d
                        near_target = n
                # Candidate for fallback
                if off < bt:
                    fallback_target = n

            target = near_target if near_target is not None else fallback_target
            if target is None:
                continue

            breath = m21.articulations.BreathMark()

            # Initialize style and set color. music21's articulation.style
            # may be None until first accessed in some versions; we make
            # sure it's a TextStyle before assigning.
            try:
                if getattr(breath, 'style', None) is None:
                    breath.style = m21.style.TextStyle()
                breath.style.color = color
            except Exception:
                pass

            # Conventional rendering position. Not all engravers honor
            # this, but it's the right hint to give them.
            try:
                breath.placement = 'above'
            except Exception:
                pass

            target.articulations.append(breath)

    score_copy.write('musicxml', fp=output_path)


# =============================================================================
# Diagnostic plots (slightly extended to show slur regions)
# =============================================================================

def plot_diagnostics_per_part(time_grid, per_part_signals, part_names,
                                boundaries_per_part, is_tacet,
                                activity_levels, slur_info, output_path):
    """
    One panel per active part. New in v2.2: light shaded regions show
    where slurs are (interior); small triangle markers at slur endpoints.
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
        n_slurs = slur_info[i][2] if i < len(slur_info) else 0
        ax_sum.text(time_grid[0] - (time_grid[-1] - time_grid[0]) * 0.01,
                    j,
                    f"{part_names[i]} [{activity_levels[i]:.0%}, "
                    f"{n_slurs} slurs]",
                    fontsize=7, ha='right', va='center')
    ax_sum.set_yticks([])
    ax_sum.set_ylim(-1, len(active_indices))
    ax_sum.grid(axis='x', alpha=0.3)

    # Per-part B_i panels
    for j, i in enumerate(active_indices):
        ax = axes[j + 1]
        B_i, nu_i, lbdm_i, B_raw = per_part_signals[i]
        in_slur_i, endpoints_i, _ = slur_info[i]

        # Shade slur interiors
        if in_slur_i.max() > 0:
            ax.fill_between(time_grid, 0, 1.1,
                            where=in_slur_i > 0,
                            color='gold', alpha=0.12,
                            transform=ax.get_xaxis_transform())

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

        n_slurs = slur_info[i][2] if i < len(slur_info) else 0
        ax.set_title(
            f"{part_names[i]} ({len(boundaries_per_part[i])} boundaries, "
            f"{n_slurs} slurs)",
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
        n_slurs = slur_info[i][2] if i < len(slur_info) else 0
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
                    delta=0.5, gamma=0.3,
                    w_pitch=0.25, w_ioi=0.50, w_rest=0.25,
                    lbdm_smoothing_qn=0.5,
                    slur_endpoint_sigma_qn=0.5,
                    peak_height=0.3, peak_distance_qn=2.5,
                    convention='muller',
                    tacet_threshold=0.05,
                    breath_color='#d62728'):
    """
    V2.2 top-level pipeline.

    New args vs v2.1:
        delta: slur-interior suppression factor (default 0.5)
        gamma: slur-endpoint additive boost (default 0.3)
        slur_endpoint_sigma_qn: Gaussian width of endpoint bumps (default 0.5 qn)
        breath_color: hex color for the boundary breath marks (default red)
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"[1/9] Loading {input_path}")
    score, parts = parse_score(input_path)
    part_names = [get_part_name(p, default=f'part_{i}')
                  for i, p in enumerate(parts)]
    print(f"      {len(parts)} parts, total length "
          f"{score.duration.quarterLength:.1f} quarter notes")

    print(f"[2/9] Time grid (division={division})")
    time_grid = create_time_grid(score, division)
    T = len(time_grid)
    print(f"      {T} frames")

    print("[3/9] Per-frame features")
    activity, chroma = extract_features(parts, time_grid, division)
    phi = build_feature_vectors(activity, chroma)

    print(f"[4/9] Tacet detection (threshold={tacet_threshold:.0%})")
    activity_levels, is_tacet = compute_activity_levels(
        activity, threshold=tacet_threshold
    )

    print(f"[5/9] Slur extraction")
    slur_info = []
    for i, part in enumerate(parts):
        if is_tacet[i]:
            slur_info.append((np.zeros(T), np.zeros(T), 0))
            continue
        in_slur, endpoints, n_slurs = extract_slur_indicators(
            part, T, division,
            endpoint_sigma_qn=slur_endpoint_sigma_qn
        )
        slur_info.append((in_slur, endpoints, n_slurs))

    for i in range(len(parts)):
        marker = " [TACET]" if is_tacet[i] else ""
        n_slurs = slur_info[i][2]
        print(f"      part {i:2d} {part_names[i]:25s} "
              f"activity={activity_levels[i]:.1%} slurs={n_slurs}{marker}")

    print(f"[6/9] Per-part SSM novelty (kernel={kernel_size_frames} frames)")
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

    print(f"[7/9] Per-part LBDM (sigma_smooth={lbdm_smoothing_qn} qn)")
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

    print(f"[8/9] Per-part B_i(t) with slur modulation "
          f"(alpha={alpha}, beta={beta}, delta={delta}, gamma={gamma})")
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
        in_slur_i, endpoints_i, _ = slur_info[i]
        B_i, nu_n, lbdm_n, B_raw = compute_per_part_boundary_signal(
            novelty_per_part[i], lbdm_grids[i],
            in_slur_i, endpoints_i,
            alpha=alpha, beta=beta, delta=delta, gamma=gamma
        )
        per_part_signals.append((B_i, nu_n, lbdm_n, B_raw))
        bdys = detect_boundaries(
            B_i, time_grid,
            peak_height=peak_height,
            peak_distance_frames=peak_distance_frames
        )
        boundaries_per_part.append(bdys)
        print(f"      part {i:2d} {part_names[i]:25s} "
              f"{len(bdys):3d} boundaries")

    print("[9/9] Writing outputs")
    annotated_path = os.path.join(output_dir, 'sectioned.musicxml')
    active_set = {i for i in range(len(parts)) if not is_tacet[i]}
    add_breath_marks_per_part(score, boundaries_per_part, active_set,
                                annotated_path, color=breath_color)

    plot_path = os.path.join(output_dir, 'diagnostics.png')
    plot_diagnostics_per_part(time_grid, per_part_signals, part_names,
                                boundaries_per_part, is_tacet,
                                activity_levels, slur_info, plot_path)

    summary_path = os.path.join(output_dir, 'boundaries.json')
    write_summary_per_part(
        boundaries_per_part, part_names, activity_levels, is_tacet,
        slur_info, score, summary_path,
        alpha=alpha, beta=beta, delta=delta, gamma=gamma,
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
        'slur_info': slur_info,
    }


def main():
    parser = argparse.ArgumentParser(
        description="V2.2 sectioning pipeline (per-part, slur-aware) for "
                    "orchestral symbolic music."
    )
    parser.add_argument('input', help='Path to .mxl or .musicxml file')
    parser.add_argument('-o', '--output_dir', default='./output')
    parser.add_argument('--division', type=int, default=8)
    parser.add_argument('--kernel_size', type=int, default=64)
    parser.add_argument('--alpha', type=float, default=0.5)
    parser.add_argument('--beta', type=float, default=0.5)
    parser.add_argument('--delta', type=float, default=0.5,
                        help='Slur-interior suppression (0..1)')
    parser.add_argument('--gamma', type=float, default=0.3,
                        help='Slur-endpoint additive boost')
    parser.add_argument('--w_pitch', type=float, default=0.25)
    parser.add_argument('--w_ioi', type=float, default=0.50)
    parser.add_argument('--w_rest', type=float, default=0.25)
    parser.add_argument('--lbdm_smooth_qn', type=float, default=0.5)
    parser.add_argument('--slur_endpoint_sigma_qn', type=float, default=0.5)
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
        delta=args.delta, gamma=args.gamma,
        w_pitch=args.w_pitch, w_ioi=args.w_ioi, w_rest=args.w_rest,
        lbdm_smoothing_qn=args.lbdm_smooth_qn,
        slur_endpoint_sigma_qn=args.slur_endpoint_sigma_qn,
        peak_height=args.peak_height,
        peak_distance_qn=args.peak_distance_qn,
        convention=args.convention,
        tacet_threshold=args.tacet_threshold,
        breath_color=args.breath_color,
    )


if __name__ == '__main__':
    main()
