#!/usr/bin/env python
"""
sectioning_v2_3.py

V2.3 of the sectioning pipeline. Changes from v2.2:

1. ROLE-AWARE BREATH MARK PLACEMENT. Slur start and slur end produce the
   same kind of peak in B_i(t), but the breath mark belongs in different
   places. We now track which boundaries correspond to slur starts vs
   slur ends and place the breath accordingly:

     - Boundary at a slur END (the long ending note's onset) → breath ON
       that note. Player breathes after finishing the long ending note.
     - Boundary at a slur START (the first note of the new phrase) →
       breath on the PREVIOUS note (the last note of the prior phrase).
       Player breathes BEFORE the slur begins, not in the middle of it.
     - Boundary at a note that is BOTH (slur ends and another starts on
       the same note) → treat as slur end (breath on the note).
     - Boundary not aligned with any slur endpoint (LBDM/SSM only) →
       breath on the boundary note (assume it's the long ending note,
       since that's what LBDM detects).
     - Boundary in a rest → breath on the last note before the boundary.

   This addresses v2.2's bug where slur starts produced breath marks
   inside slurs, breaking phrasing.

2. SLIGHTLY HIGHER gamma (0.3 -> 0.4). Small increase in the slur-endpoint
   additive boost so that slur ends register as boundaries even when
   LBDM and SSM novelty are quiet at that point (e.g., a slur ending on
   a normal-length note rather than an anomalously-long one).

3. PER-PART SLUR INFO is now stored as a dict instead of a tuple, with
   explicit lists of slur start and slur end onset times, used by the
   role-aware breath mark logic.

Math (per part i) — unchanged from v2.2:
    B_i_raw(t)        = alpha * nu_i_norm(t) + beta * sigma_i_grid_norm(t)
    in_slur_i(t)      = 1 if t in interior of a slur in part i, else 0
    slur_endpoints_i  = Gaussian bumps centered on slur start/end frames
    B_i(t) = B_i_raw(t) * (1 - delta * in_slur_i(t)) + gamma * slur_endpoints_i(t)
    boundaries_i = local peaks of B_i(t)

The math is the same; what changed is that we additionally track WHICH
notes are slur starts and slur ends (separately) so we can decide where
the breath mark goes for each detected boundary.

Default modulation parameters:
    delta = 0.5  (50% attenuation inside slurs)
    gamma = 0.4  (40% additive boost at slur endpoints, up from 0.3)
    bump_sigma_qn = 0.5

Usage:
    python sectioning_v2_3.py path/to/score.mxl [-o output_dir]
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
# Diagnostic plots (slightly extended to show slur regions)
# =============================================================================

def plot_diagnostics_per_part(time_grid, per_part_signals, part_names,
                                boundaries_per_part, is_tacet,
                                activity_levels, slur_info, output_path):
    """
    One panel per active part. Light gold shaded regions show slur
    interiors. Summary panel at top shows boundaries across all parts.
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
        si = slur_info[i] if i < len(slur_info) else {}
        in_slur_i = si.get('in_slur_interior', np.zeros_like(time_grid))
        n_slurs = si.get('n_slurs', 0)

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
                    delta=0.5, gamma=0.4,
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

    for i in range(len(parts)):
        marker = " [TACET]" if is_tacet[i] else ""
        n_slurs = slur_info[i]['n_slurs']
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
        in_slur_i = slur_info[i]['in_slur_interior']
        endpoints_i = slur_info[i]['endpoint_bumps']
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
    add_breath_marks_per_part(score, boundaries_per_part, slur_info,
                                active_set,
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
    parser.add_argument('--gamma', type=float, default=0.4,
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
