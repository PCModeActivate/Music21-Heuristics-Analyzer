#!/usr/bin/env python
"""
sectioning_v2_10_C.py  (the v2.10-B/C batch)

Changes from v2.10-B:

  * v2.10-C same-offset event grouping (extract_lbdm_profiles): all
    pitched elements starting at the same offset collapse into ONE
    event carrying top_pitch, bass_pitch, pitch_set, onset_count,
    duration_max/min. Same-time polyphony is no longer a sequence of
    zero-IOI melodic events. --lbdm_polyphony_mode top|bass|outer
    selects the melodic surface LBDM hears (default 'top'; single-line
    parts are unaffected by grouping). Extra keys survive tie merging
    (merge_tied_notes copies records), so 'outer' is fully live.

  * Structural-event dedup (extract_structural_event_offsets,
    dedup_window_qn=2.0): same-kind event runs within the window
    collapse to their FIRST event, with a sliding window so long
    unrolled rit./accel. tempo cascades stay one gesture. Changes
    default output: boost spam from playback tempo marks is gone
    (part event counts drop roughly by half). dedup_window_qn=0
    disables. Burst-END anchoring (the a tempo) is reserved for F.

  * Fermata extraction: fermatas live in note.expressions, not as
    stream elements, and were previously invisible to the pipeline.
    Now emitted as typed 'fermata' events (weight 1.0 via the
    event-weight default; dedicated kwarg pending). Endpoint
    side-choice semantics are D1/F work.

  * EXPERIMENTAL, default OFF: selection_repetition_penalty adds
    rhythm-repetition R as a continuation penalty (tuplet-style)
    into selection_score and note_anchor_score. Validated on Liz
    (with delta_repetition=0.8): fixes ASax m.54 / removes Harp
    m.54, but over-suppresses accompaniment parts (R>0.8 across
    85-89% of Trumpet/Euphonium). NOT promoted to defaults;
    revisit requires a per-part prevalence gate and onset-gated
    similarity. See handover notes.

  * Companion phrase_material.py: single_attack_phrase advisory flag
    (catches whole-note-per-bar chains split across segments).

Carried from v2.10-A/B: phrase material report; note_anchor weights
as kwargs; repetition mask (post-normalization, masks rhythm novelty +
slur-endpoint boost + following-gap; delta_repetition=0.0 default);
--chroma_kernel exact|interval (interval-class SSM, default exact).

Usage with caching:
    from sectioning_v2_10_A import run_sectioning, explain, save_result, load_result
    import os

    cache = 'liz.cache.pkl'
    if os.path.exists(cache):
        result = load_result(cache)
    else:
        result = run_sectioning('liz.mxl')
        save_result(result, cache)

    explain(result, part_idx=0, measure=15, beat=1.0)
"""

import os
import json
import copy
import pickle
import argparse
import re

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks
from scipy.ndimage import gaussian_filter1d, maximum_filter1d
import music21 as m21

try:
    from phrase_material import (
        compute_phrase_material_report,
        default_phrase_shape_thresholds,
        summarize_phrase_material,
        write_phrase_material_summary,
    )
except ImportError:
    compute_phrase_material_report = None
    default_phrase_shape_thresholds = None
    summarize_phrase_material = None
    write_phrase_material_summary = None

try:
    from repetition_mask import (
        compute_repetition_score,
        repetition_multiplier,
    )
except ImportError:
    compute_repetition_score = None
    repetition_multiplier = None

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
    """
    Extract per-frame activity, onset, and chroma features.

    Returns:
        activity: shape (parts, frames), 1 while a note/chord is sounding.
        onset:    shape (parts, frames), 1 at note/chord attack frames.
        chroma:   shape (parts, frames, 12), pitch-class activity.

    The onset matrix is new in v2.7 and is used to build rhythm features
    separately from pitch/chroma features.
    """
    num_parts = len(parts)
    num_frames = len(time_grid)
    activity = np.zeros((num_parts, num_frames), dtype=int)
    onset = np.zeros((num_parts, num_frames), dtype=int)
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

            if isinstance(element, m21.note.Rest):
                continue

            if isinstance(element, m21.note.Note):
                pc = element.pitch.pitchClass
                onset[i, start_idx] = 1
                for idx in range(start_idx, end_idx):
                    chroma[i, idx, pc] += 1
                    activity[i, idx] = 1
            elif isinstance(element, m21.chord.Chord):
                onset[i, start_idx] = 1
                for n in element.notes:
                    pc = n.pitch.pitchClass
                    for idx in range(start_idx, end_idx):
                        chroma[i, idx, pc] += 1
                        activity[i, idx] = 1

    return activity, onset, chroma


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



def build_rhythm_feature_vectors(activity, onset,
                                 attack_weight=1.0,
                                 sustain_weight=0.65,
                                 rest_weight=0.25):
    """
    Build rhythm-only frame features from attack/sustain/rest state.

    V2.8 intentionally keeps this independent from pitch. Two parts that
    play different notes with the same attack/sustain/rest pattern should
    look rhythmically similar. Rest is weighted lower than attack/sustain
    so long shared rests do not dominate similarity.

    Returns shape (parts, frames, 3): [attack, sustain, rest].
    """
    N, T = activity.shape
    phi = np.zeros((N, T, 3), dtype=float)
    for i in range(N):
        for t in range(T):
            if onset[i, t] == 1:
                phi[i, t, 0] = attack_weight
            elif activity[i, t] == 1:
                phi[i, t, 1] = sustain_weight
            else:
                phi[i, t, 2] = rest_weight
    return phi


def make_chroma_interval_kernel(rest_similarity=1.0):
    """
    Return a 13x13 feature-space kernel for musical chroma similarity.

    Dimensions 0..11 are pitch classes and dimension 12 is rest. The
    pitch-class block uses interval-class weights rather than exact-match
    chroma only. This function is currently used for cross-part diagnostic
    similarity, not for the main boundary signal.
    """
    interval_sim = {
        0: 1.00,   # unison/octave
        1: 0.05,   # semitone / major seventh
        2: 0.25,   # whole tone / minor seventh
        3: 0.70,   # minor third / major sixth
        4: 0.75,   # major third / minor sixth
        5: 0.55,   # fourth / fifth-ish inversion class partner
        6: 0.10,   # tritone
    }
    K = np.zeros((13, 13), dtype=float)
    for a in range(12):
        for b in range(12):
            d = abs(a - b) % 12
            ic = min(d, 12 - d)
            K[a, b] = interval_sim[ic]
    K[12, 12] = rest_similarity
    return K


def build_ssm_with_kernel(phi_part, feature_kernel=None):
    """
    Build a self-similarity matrix for one part.

    If feature_kernel is None, this is the ordinary dot product used by
    earlier versions. If a kernel is supplied, similarity is phi K phi^T.
    """
    if feature_kernel is None:
        return phi_part @ phi_part.T
    return phi_part @ feature_kernel @ phi_part.T


def compute_cross_part_synchronous_similarity(phi, is_tacet=None,
                                               feature_kernel=None):
    """
    Compute time-aligned cross-part similarity diagnostics.

    Returns an array of shape (parts, parts, frames), where entry [i,j,t]
    compares part i and part j at the same time t. This is intentionally
    not the full T-by-T cross-similarity matrix for every part pair, which
    would be much larger. V2.8 stores these diagnostics but does not use
    them for boundary decisions.
    """
    N, T, D = phi.shape
    sims = np.zeros((N, N, T), dtype=float)
    if is_tacet is None:
        is_tacet = np.zeros(N, dtype=bool)

    for i in range(N):
        if is_tacet[i]:
            continue
        for j in range(N):
            if is_tacet[j]:
                continue
            if feature_kernel is None:
                vals = np.sum(phi[i] * phi[j], axis=1)
            else:
                vals = np.einsum('td,dk,tk->t', phi[i], feature_kernel, phi[j])
            sims[i, j, :] = vals
    return sims


def _window_cosine(a, b):
    """Cosine similarity for two flattened local windows."""
    af = a.reshape(-1)
    bf = b.reshape(-1)
    denom = np.linalg.norm(af) * np.linalg.norm(bf)
    if denom <= 0:
        return 0.0
    return float(np.dot(af, bf) / denom)


def compute_cross_rhythm_support(rhythm_phi, activity, local_B_pre,
                                  is_tacet, division,
                                  window_qn=4.0,
                                  similarity_threshold=0.85,
                                  max_shift_qn=0.5,
                                  min_active_qn=0.5,
                                  attribution_out=None):
    """
    Soft cross-part rhythm support for boundary evidence.

    For each part/time, compare the local rhythm window with every other
    active part. If the windows are similar enough, borrow the other part's
    nearby local boundary evidence. This supports doubled or rhythmically
    matched lines without forcing identical boundaries.

    This support is used in v2.7's boundary signal and candidate selection.
    """
    N, T, _ = rhythm_phi.shape
    half_window = max(int(round(window_qn * division / 2.0)), 1)
    shift_frames = max(int(round(max_shift_qn * division)), 0)
    min_active_frames = max(int(round(min_active_qn * division)), 1)

    local_B_near = np.zeros_like(local_B_pre)
    filter_size = 2 * shift_frames + 1
    for j in range(N):
        if filter_size > 1:
            local_B_near[j] = maximum_filter1d(local_B_pre[j], size=filter_size)
        else:
            local_B_near[j] = local_B_pre[j]

    sim_matrix = np.zeros((N, N, T), dtype=np.float32)
    contrib_matrix = np.zeros((N, N, T), dtype=np.float32)
    support = np.zeros((N, T), dtype=float)
    for t in range(T):
        lo = max(0, t - half_window)
        hi = min(T, t + half_window + 1)
        for i in range(N):
            if is_tacet[i]:
                continue
            if int(np.sum(activity[i, lo:hi])) < min_active_frames:
                continue
            vals = []
            for j in range(N):
                if i == j or is_tacet[j]:
                    continue
                if int(np.sum(activity[j, lo:hi])) < min_active_frames:
                    continue
                sim = _window_cosine(rhythm_phi[i, lo:hi, :],
                                     rhythm_phi[j, lo:hi, :])
                if sim >= similarity_threshold:
                    c = sim * local_B_near[j, t]
                    sim_matrix[i, j, t] = sim
                    contrib_matrix[i, j, t] = c
                    vals.append(c)
            if vals:
                support[i, t] = float(np.mean(vals))

    if attribution_out is not None:
        attribution_out['sim'] = sim_matrix
        attribution_out['contrib'] = contrib_matrix
        attribution_out['raw_support'] = support.copy()
        attribution_out['local_B_pre'] = np.asarray(
            local_B_pre, dtype=np.float32).copy()
        attribution_out['shift_frames'] = int(shift_frames)
        attribution_out['window_qn'] = float(window_qn)
        attribution_out['similarity_threshold'] = float(similarity_threshold)

    # Normalize per part so the scale is comparable across sparse/dense parts.
    for i in range(N):
        if support[i].max() > 0:
            support[i] = support[i] / support[i].max()
    return support


# =============================================================================
# SSM and novelty (unchanged from v2.1)
# =============================================================================

def build_ssm(phi_part):
    return build_ssm_with_kernel(phi_part)


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
    Merge consecutive tied same-pitch notes into single breath events.

    Musicians treat a tied chain as one sustained note.  The chain must
    not be split by a breath mark before its final segment.  For boundary
    detection, however, the breath-eligible endpoint is the final tied
    segment, not the first tied segment.

    A chain merges when:
      - Previous note's tie_type is 'start' or 'continue'
      - Next note's tie_type is 'continue' or 'stop'
      - Pitches match
      - Notes are temporally contiguous (no gap)

    The merged event keeps the first note's musical duration span, but
    stores:
      - boundary_offset: onset of the final tied segment, where a breath
        after the sustained event can be attached.
      - tie_chain_length: number of tied segments in the chain.
      - tie_chain_start_offset / tie_chain_final_offset for diagnostics.
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

        chain_len = j - i
        merged_event = chain_first.copy()
        merged_event['duration'] = total_duration
        merged_event['boundary_offset'] = chain_last['offset']
        merged_event['tie_chain_length'] = chain_len
        merged_event['tie_chain_start_offset'] = chain_first['offset']
        merged_event['tie_chain_final_offset'] = chain_last['offset']

        # Preserve whether this merged event came from a natural/synthetic
        # tied chain for explain() output.
        if chain_len > 1:
            merged_event['tie_type'] = 'chain'
        merged.append(merged_event)
        i = j

    return merged


# =============================================================================
# v2.10-C: paste this over the existing extract_lbdm_profiles in
# sectioning_v2_10_B.py (same location, same callers). Wiring one-liners
# are listed in the accompanying message.
# =============================================================================

def extract_lbdm_profiles(part, tie_like_spans=None, polyphony_mode='top'):
    """
    Build per-note records for LBDM, with tie-merged events,
    tuplet-interior flagging, and (v2.10-C) same-offset event grouping.

    v2.10-C: all pitched elements starting at the same offset (chord
    members were already collapsed; this extends to separate same-offset
    Note/Chord elements from multiple voices) are grouped into ONE event.
    Same-time polyphony is no longer treated as a sequence of melodic
    events with zero IOIs. Each grouped event records top_pitch,
    bass_pitch, pitch_set, onset_count, duration_max/min for downstream
    use.

    polyphony_mode selects the melodic surface LBDM hears:
        'top'   - top pitch line (grouped; default)
        'bass'  - bass pitch line
        'outer' - pitch interval = max(|d top|, |d bass|); IOI/rest
                  profiles are event-level and identical across modes
    For strictly single-line parts all three modes are identical to the
    pre-C behavior (grouping is a no-op there).

    Carried v2.5-v2.9 invariants: synthetic ties from same-pitch
    tie-like slurs; tie chains merged BEFORE interval computation;
    staccato rest override (rest gap forced to 0); tuplet-interior flag
    from the representative element.
    """
    if tie_like_spans is None:
        tie_like_spans = []
    if polyphony_mode not in ('top', 'bass', 'outer'):
        raise ValueError(f"unknown polyphony_mode: {polyphony_mode!r}")

    def synth_tie_type_for(offset, pitch):
        """Synthesized tie_type from tie_like_spans (v2.5 semantics)."""
        for start_off, end_off in tie_like_spans:
            if abs(offset - start_off) < 0.01:
                return 'start'
            if abs(offset - end_off) < 0.01:
                return 'stop'
            if start_off < offset < end_off:
                return 'continue'
        return None

    # -- 1. collect raw pitched elements ---------------------------------
    raw_elements = []
    for element in part.flatten().notes:
        offset = float(element.offset)
        if isinstance(element, m21.note.Note):
            pitches = [element.pitch.midi]
        elif isinstance(element, m21.chord.Chord):
            pitches = sorted(n.pitch.midi for n in element.notes)
        else:
            continue
        raw_elements.append({
            'offset': offset,
            'pitches': pitches,
            'duration': float(element.duration.quarterLength),
            'staccato': has_staccato(element),
            'natural_tie': get_tie_type(element),
            'in_tuplet_interior': is_in_tuplet_interior(element),
            'element': element,
        })

    raw_elements.sort(key=lambda x: (x['offset'], -max(x['pitches'])))

    # -- 2. group by (rounded) offset -------------------------------------
    groups = {}
    order = []
    for rec in raw_elements:
        key = round(rec['offset'], 4)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(rec)

    raw_notes = []
    for key in order:
        members = groups[key]
        all_pitches = sorted({p for m in members for p in m['pitches']})
        top_pitch = all_pitches[-1]
        bass_pitch = all_pitches[0]
        # Representative element: the one carrying the top pitch — the
        # melodic surface keeps ownership of articulation/tie/tuplet
        # state ('bass' mode still uses the top carrier for these; only
        # the interval profile changes).
        rep = max(members, key=lambda m: max(m['pitches']))
        offset = float(key)

        lead_pitch = bass_pitch if polyphony_mode == 'bass' else top_pitch
        natural_tie = rep['natural_tie']
        synthetic_tie = synth_tie_type_for(offset, lead_pitch)
        tie_type = natural_tie if natural_tie else synthetic_tie

        raw_notes.append({
            'offset': offset,
            'pitch': lead_pitch,
            'top_pitch': top_pitch,
            'bass_pitch': bass_pitch,
            'pitch_set': all_pitches,
            'onset_count': len(members),
            'duration': max(m['duration'] for m in members),
            'duration_min': min(m['duration'] for m in members),
            'staccato': rep['staccato'],
            'tie_type': tie_type,
            'in_tuplet_interior': rep['in_tuplet_interior'],
            'element': rep['element'],
        })

    # -- 3. merge tied chains BEFORE computing intervals -------------------
    # (crucial ordering, unchanged from v2.5: otherwise LBDM sees
    # tie-internal IOIs as boundaries)
    notes_list = merge_tied_notes(raw_notes)

    # -- 4. interval profiles ----------------------------------------------
    n = max(len(notes_list) - 1, 0)
    pitch_intervals = np.zeros(n)
    iois = np.zeros(n)
    rests = np.zeros(n)

    for i in range(n):
        cur = notes_list[i]
        nxt = notes_list[i + 1]
        if polyphony_mode == 'outer':
            # .get fallbacks in case merge_tied_notes rebuilds dicts
            # without the extra keys; degrades to 'top' behavior then.
            d_top = abs(nxt.get('top_pitch', nxt['pitch'])
                        - cur.get('top_pitch', cur['pitch']))
            d_bass = abs(nxt.get('bass_pitch', nxt['pitch'])
                         - cur.get('bass_pitch', cur['pitch']))
            pitch_intervals[i] = max(d_top, d_bass)
        else:
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


def compute_lbdm_per_part(part, w_pitch=0.25, w_ioi=0.50, w_rest=0.25,
                            tie_like_spans=None, polyphony_mode='top'):
    """
    Compute combined LBDM boundary strength per (post-tie-merge) note.

    NEW in v2.4: zeros out strengths on tuplet-interior notes so that
    triplets/quintuplets don't fragment into multiple boundaries due to
    internal pitch variation. The first and last notes of the tuplet
    group can still register as boundaries.

    NEW in v2.5: tie_like_spans propagates through to extract_lbdm_profiles,
    causing same-pitch slurs to be treated as ties for merge purposes.
    """
    notes_list, pi, ioi, rest = extract_lbdm_profiles(
        part, tie_like_spans=tie_like_spans, polyphony_mode=polyphony_mode
    )
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
    """
    Project note-level LBDM to the frame grid.

    V2.8 uses note['boundary_offset'] when available.  This matters for
    tied chains: the merged event starts at the first segment, but the
    breath-eligible endpoint is the final tied segment.
    """
    grid = np.zeros(num_frames)
    for k, note in enumerate(notes_list):
        if k >= len(sigma):
            break
        off = float(note.get('boundary_offset', note['offset']))
        idx = int(round(off * division))
        if 0 <= idx < num_frames:
            grid[idx] = max(grid[idx], sigma[k])

    sigma_frames = smoothing_sigma_qn * division
    if sigma_frames > 0:
        grid = gaussian_filter1d(grid, sigma_frames)

    return grid


# =============================================================================
# NEW: Slur extraction
# =============================================================================

def _global_offset(element, ancestor):
    """Best-effort global offset of an element within a part/score."""
    try:
        return float(element.getOffsetInHierarchy(ancestor))
    except Exception:
        return float(element.offset)


def _top_pitch_midi(element):
    """Return the melody-reduction pitch used elsewhere, or None."""
    if isinstance(element, m21.note.Note):
        return element.pitch.midi
    if isinstance(element, m21.chord.Chord):
        return max(n.pitch.midi for n in element.notes)
    return None


def _note_like_events(part):
    """
    Flattened note/chord events with global offsets and top-pitch reduction.

    We use this for slur classification instead of relying only on
    slur.getSpannedElements().  In MusicXML imported through music21,
    a slur spanner may expose only its endpoint elements.  If a slur is
    F-G-E-F, checking only endpoints would falsely classify it as a
    same-pitch tie-like slur.  Scanning all note/chord onsets inside the
    spanned offset range avoids that false tie classification.
    """
    events = []
    for el in part.flatten().notes:
        pitch = _top_pitch_midi(el)
        if pitch is None:
            continue
        events.append({
            'offset': float(el.offset),
            'pitch': pitch,
            'duration': float(el.duration.quarterLength),
            'element': el,
        })
    events.sort(key=lambda e: e['offset'])
    return events


def _strictly_inside_any_span(t, spans, skip_index=None, eps=0.01):
    """True iff t is strictly inside any span other than skip_index."""
    for j, (start, end) in enumerate(spans):
        if skip_index is not None and j == skip_index:
            continue
        if start + eps < t < end - eps:
            return True
    return False


def extract_slur_indicators(part, num_frames, division,
                              endpoint_sigma_qn=0.5):
    """
    Extract slur info for a part. Returns a dict with:

      in_slur_interior:  shape (num_frames,), 1 strictly inside ANY slur.
                         This is the main phrase-suppression mask.  The
                         important invariant is: if a point is inside an
                         outer slur, nested local slur endpoints must not
                         relax suppression.
      endpoint_bumps:    shape (num_frames,), Gaussian-smoothed indicator
                         of EFFECTIVE phrase-slur endpoints only.  A slur
                         endpoint is effective only when that endpoint is
                         not strictly inside another slur.
      in_tie_like:       shape (num_frames,), hard no-breath mask for
                         same-pitch tie-like slurs under [start, end)
                         breath semantics.
      n_slurs:           total number of slurs found.
      n_phrase_slurs:    number of non-tie-like slurs.
      n_tie_like_slurs:  number of same-pitch tie-like slurs.
      slur_starts:       effective phrase-start offsets.
      slur_ends:         effective phrase-end offsets.
      tie_like_spans:    list of (start_off, end_off) for same-pitch slurs,
                         passed to LBDM so merge_tied_notes can collapse
                         the spanned notes into a single event.

    Tie-like detection is deliberately stricter than the v2.5 endpoint-only
    check.  A slur is tie-like only if every note/chord onset contained in
    its start/end offset span has the same reduced pitch.  Thus an F-G-E-F
    slur is a phrase/articulation slur, not a tie-like span.
    """
    in_slur_interior = np.zeros(num_frames, dtype=float)
    in_tie_like = np.zeros(num_frames, dtype=float)
    endpoints_raw = np.zeros(num_frames, dtype=float)
    slur_starts = []
    slur_ends = []
    tie_like_spans = []

    note_events = _note_like_events(part)

    raw_slurs = []
    try:
        raw_slurs = list(part.recurse().getElementsByClass(m21.spanner.Slur))
    except Exception:
        raw_slurs = []

    spans = []
    for slur in raw_slurs:
        try:
            spanned = slur.getSpannedElements()
            if len(spanned) < 2:
                continue
            start_elem = spanned[0]
            end_elem = spanned[-1]
            start_off = _global_offset(start_elem, part)
            end_off = _global_offset(end_elem, part)
            if end_off <= start_off:
                continue
            spans.append((start_off, end_off, slur))
        except Exception:
            continue

    span_ranges = [(s, e) for s, e, _ in spans]
    n_phrase_slurs = 0
    n_tie_like_slurs = 0
    eps = 0.01

    for span_idx, (start_off, end_off, slur) in enumerate(spans):
        start_idx = max(int(round(start_off * division)), 0)
        end_idx = min(int(round(end_off * division)), num_frames - 1)

        # Every slur protects [start, end) under breath-mark semantics:
        # a breath after the first note would break the marked span, while
        # a breath after the final note is allowed.  This also handles
        # nested slurs: an inner endpoint remains suppressed if an outer
        # slur still contains that time.
        if end_idx > start_idx:
            in_slur_interior[start_idx:end_idx] = 1.0

        contained = [
            ev for ev in note_events
            if start_off - eps <= ev['offset'] <= end_off + eps
        ]
        pitches = [ev['pitch'] for ev in contained]
        is_tie_like = (
            len(pitches) >= 2 and
            all(p == pitches[0] for p in pitches)
        )

        if is_tie_like:
            n_tie_like_slurs += 1
            tie_like_spans.append((start_off, end_off))
            # Tie-like spans are one sustained musical event.  Protect
            # [start, end): no breaths after the beginning/interior
            # segments, but a breath after the final note is allowed.
            if end_idx > start_idx:
                in_tie_like[start_idx:end_idx] = 1.0
            continue

        n_phrase_slurs += 1

        start_nested = _strictly_inside_any_span(
            start_off, span_ranges, skip_index=span_idx, eps=eps
        )
        end_nested = _strictly_inside_any_span(
            end_off, span_ranges, skip_index=span_idx, eps=eps
        )

        # Endpoint bumps are boundary-positive evidence only if the
        # endpoint is not inside any other slur.  Inner ornamental slurs
        # under an outer phrase slur are therefore neutral/suppressive,
        # never boundary-positive.
        if not start_nested:
            # Keep start metadata for annotation/explain, but do not boost
            # slur starts. A start says a new span begins here; it is not
            # itself evidence for a breath after the starting note.
            slur_starts.append(start_off)

        if not end_nested:
            slur_ends.append(end_off)
            if 0 <= end_idx < num_frames:
                endpoints_raw[end_idx] = max(endpoints_raw[end_idx], 1.0)

    sigma_frames = endpoint_sigma_qn * division
    if sigma_frames > 0 and endpoints_raw.max() > 0:
        endpoint_bumps = gaussian_filter1d(endpoints_raw, sigma_frames)
        if endpoint_bumps.max() > 0:
            endpoint_bumps = endpoint_bumps / endpoint_bumps.max()
    else:
        endpoint_bumps = np.zeros_like(endpoints_raw)

    return {
        'in_slur_interior': in_slur_interior,
        'in_tie_like': in_tie_like,
        'endpoint_bumps': endpoint_bumps,
        'n_slurs': len(spans),
        'n_phrase_slurs': n_phrase_slurs,
        'n_tie_like_slurs': n_tie_like_slurs,
        'slur_starts': sorted(slur_starts),
        'slur_ends': sorted(slur_ends),
        'tie_like_spans': tie_like_spans,
    }


# =============================================================================
# Hairpin (Crescendo / Diminuendo) extraction
# =============================================================================

def extract_hairpin_indicators(part, num_frames, division):
    """
    Extract hairpin (Crescendo/Diminuendo) context for a part.

    Hairpins are stretched crescendo/decrescendo wedges. V2.8 treats their
    span with the same [start, end) breath semantics used for slurs: the
    beginning and middle of the span are phrase-continuation context, while
    the final note is allowed to be a boundary. Hairpins attenuate rather
    than hard-veto the boundary signal.

    Returns:
        in_hairpin: shape (num_frames,), 1 on [start, end) hairpin spans.
        n_hairpins: count of hairpins found.
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
            if not spanned:
                continue
            try:
                start_off = float(spanned[0].getOffsetInHierarchy(part))
                end_off = float(spanned[-1].getOffsetInHierarchy(part))
            except Exception:
                start_off = float(spanned[0].offset)
                end_off = float(spanned[-1].offset)
            if len(spanned) == 1:
                end_off = start_off + float(spanned[0].duration.quarterLength)
            if end_off <= start_off:
                continue
            n_hairpins += 1

            start_idx = max(int(round(start_off * division)), 0)
            end_idx = min(int(round(end_off * division)), num_frames - 1)
            if end_idx > start_idx:
                in_hairpin[start_idx:end_idx] = 1.0
        except Exception:
            continue

    return in_hairpin, n_hairpins


def extract_tuplet_indicators(part, num_frames, division):
    """
    Extract [start, end) tuplet-span suppression context.

    Earlier versions only zeroed LBDM on tuplet-interior notes. V2.8 also
    prevents final boundary selection from placing breaths after the
    beginning/interior notes of a tuplet group. The final tuplet note is
    not protected by this mask, because a breath after the final note is
    allowed.

    Returns:
        in_tuplet_span: shape (num_frames,), 1 on [tuplet_start, tuplet_end)
        n_tuplets: number of tuplets whose start/stop could be inferred.
    """
    in_tuplet = np.zeros(num_frames, dtype=float)
    n_tuplets = 0
    active_start = None

    notes = sorted(part.flatten().notes, key=lambda n: float(n.offset))
    for el in notes:
        if not getattr(el.duration, 'tuplets', None):
            continue
        if not el.duration.tuplets:
            continue
        tup = el.duration.tuplets[0]
        role = tup.type
        off = float(el.offset)

        if role == 'start':
            active_start = off
        elif role == 'stop':
            if active_start is not None and off > active_start:
                start_idx = max(int(round(active_start * division)), 0)
                end_idx = min(int(round(off * division)), num_frames - 1)
                if end_idx > start_idx:
                    in_tuplet[start_idx:end_idx] = 1.0
                    n_tuplets += 1
            active_start = None

    return in_tuplet, n_tuplets



def extract_natural_tie_indicators(part, num_frames, division):
    """
    Extract hard no-breath spans for ordinary MusicXML natural ties.

    A natural tie means the tied segments are one sustained note. Under
    breath-mark semantics, protect [first_tied_segment_onset,
    final_tied_segment_onset): no breath after the first/internal tied
    segments, but a breath after the final tied segment is allowed.

    Returns:
        dict with:
          in_natural_tie: shape (num_frames,), 1 on protected tie spans.
          natural_tie_spans: list of (start_off, final_off).
          n_natural_ties: number of tied chains found.
    """
    in_tie = np.zeros(num_frames, dtype=float)
    tie_spans = []
    active_start = None
    last_seen_offset = None

    notes = sorted(part.flatten().notes, key=lambda n: float(n.offset))
    for el in notes:
        tie_type = get_tie_type(el)
        off = float(el.offset)

        if tie_type == 'start':
            # Close any malformed active chain defensively by starting anew.
            active_start = off
            last_seen_offset = off
        elif tie_type == 'continue':
            if active_start is not None:
                last_seen_offset = off
        elif tie_type == 'stop':
            if active_start is not None and off > active_start:
                final_off = off
                start_idx = max(int(round(active_start * division)), 0)
                end_idx = min(int(round(final_off * division)), num_frames - 1)
                if end_idx > start_idx:
                    in_tie[start_idx:end_idx] = 1.0
                tie_spans.append((active_start, final_off))
            active_start = None
            last_seen_offset = None

    return {
        'in_natural_tie': in_tie,
        'natural_tie_spans': tie_spans,
        'n_natural_ties': len(tie_spans),
    }


# =============================================================================
# Structural event extraction (tempo, dynamics, key, time changes)
# =============================================================================


def _event_text(element):
    """Best-effort text payload for tempo/text-expression-like objects."""
    for attr in ('content', 'text', 'value'):
        val = getattr(element, attr, None)
        if val:
            return str(val)
    try:
        return str(element)
    except Exception:
        return ''


def _classify_tempo_or_expression_text(text):
    """
    Classify expression text that likely signals tempo/phrase structure.

    The exact MusicXML import path varies: rit. might arrive as a
    TextExpression, TempoText, or another Expression-like object.  We keep
    this parser deliberately explainable and conservative.
    """
    raw = (text or '').strip()
    lowered = raw.lower()
    lowered = lowered.replace('ì', 'i').replace('í', 'i').replace('ù', 'u')
    lowered = lowered.replace('più', 'piu')

    if not lowered:
        return None
    if re.search(r'\ba\s*tempo\b', lowered):
        return 'tempo_text_a_tempo'
    if re.search(r'\b(rit|rit\.|ritard|ritardando|rall|rall\.|rallentando|retenu|retenuto|slargando)\b', lowered):
        return 'tempo_text_slowing'
    if re.search(r'\b(accel|accel\.|accelerando|stringendo|stretto)\b', lowered):
        return 'tempo_text_accel'
    if re.search(r'\b(meno\s+mosso|piu\s+mosso|poco\s+piu|poco\s+meno)\b', lowered):
        return 'tempo_text_mosso'
    if re.search(r'\b(tempo|rubato|calando|smorzando|morendo)\b', lowered):
        return 'tempo_text_other'
    return None


def make_structural_event_weight_map(dynamic_weight=0.80,
                                     tempo_weight=1.00,
                                     tempo_text_weight=1.00,
                                     key_weight=0.80,
                                     time_weight=1.00):
    """Return typed structural-event weights for project_event_bumps()."""
    return {
        'dynamic': dynamic_weight,
        'tempo': tempo_weight,
        'tempo_text_slowing': tempo_text_weight,
        'tempo_text_accel': tempo_text_weight,
        'tempo_text_a_tempo': tempo_text_weight,
        'tempo_text_mosso': tempo_text_weight,
        'tempo_text_other': tempo_text_weight * 0.75,
        'key': key_weight,
        'time': time_weight,
    }


def extract_structural_event_offsets(part, score=None,
                                       initial_threshold_qn=0.5, dedup_window_qn=2.0):
    """
    Extract typed structural-change events in a part.

    V2.9 keeps the v2.8 dynamic/tempo/key/time cues and adds tempo or
    expression text such as rit., rall., accel., stringendo, a tempo, meno
    mosso, and plus mosso.  Returned event kinds are typed strings so later
    scoring can tune or ablate dynamics, tempo text, key changes, and time
    changes independently.

    The initial_threshold_qn excludes opening state markings.  A first
    dynamic/tempo/key/time mark describes how the piece starts; a later one
    is more likely to signal a phrase or section transition.

    Returns:
        offsets: sorted event offsets in quarter notes.
        events:  sorted event-kind strings parallel to offsets.
    """
    offsets = []
    events = []
    seen = set()

    event_classes = [
        ('tempo', m21.tempo.MetronomeMark),
        ('tempo', m21.tempo.MetricModulation),
        ('dynamic', m21.dynamics.Dynamic),
        ('key', m21.key.KeySignature),
        ('time', m21.meter.TimeSignature),
    ]

    def add_event(off, kind, text_key=''):
        if off <= initial_threshold_qn:
            return
        key = (round(float(off), 4), kind, text_key)
        if key in seen:
            return
        seen.add(key)
        offsets.append(float(off))
        events.append(kind)

    for kind, cls in event_classes:
        try:
            for el in part.recurse().getElementsByClass(cls):
                add_event(_global_offset(el, part), kind)
        except Exception:
            continue

    text_classes = []
    for dotted in ((m21, 'expressions', 'TextExpression'),
                   (m21, 'tempo', 'TempoText')):
        obj = dotted[0]
        try:
            for attr in dotted[1:]:
                obj = getattr(obj, attr)
            text_classes.append(obj)
        except Exception:
            pass

    for cls in text_classes:
        try:
            for el in part.recurse().getElementsByClass(cls):
                text = _event_text(el)
                kind = _classify_tempo_or_expression_text(text)
                if kind is not None:
                    add_event(_global_offset(el, part), kind, text_key=text.lower())
        except Exception:
            continue

    # v2.10-D: fermatas are note expressions, not stream elements —
    # they were previously invisible to the entire pipeline.
    try:
        for n in part.recurse().notes:
            for expr in n.expressions:
                if isinstance(expr, m21.expressions.Fermata):
                    add_event(_global_offset(n, part), 'fermata')
    except Exception:
        pass

    if score is not None:
        for kind, cls in event_classes:
            if kind == 'dynamic':
                continue
            try:
                for el in score.recurse().getElementsByClass(cls):
                    add_event(_global_offset(el, score), kind)
            except Exception:
                continue
        for cls in text_classes:
            try:
                for el in score.recurse().getElementsByClass(cls):
                    text = _event_text(el)
                    kind = _classify_tempo_or_expression_text(text)
                    if kind is not None:
                        add_event(_global_offset(el, score), kind, text_key=text.lower())
            except Exception:
                continue

    paired = sorted(zip(offsets, events), key=lambda x: x[0])
    if not paired:
        return [], []
    # Collapse same-kind runs within dedup_window_qn into the FIRST event:
    # MuseScore unrolls rit./accel. into per-beat tempo marks; a burst is
    # one musical gesture anchored where it begins. dedup_window_qn=0
    # disables. (Burst-END anchoring is v2.10-F work.)
    out_offsets, out_events = [], []
    last_seen = {}
    for off, kind in paired:
        if dedup_window_qn > 0 and kind in last_seen \
                and off - last_seen[kind] < dedup_window_qn:
            last_seen[kind] = off   # slide, so long cascades stay one event
            continue
        last_seen[kind] = off
        out_offsets.append(off)
        out_events.append(kind)
    return out_offsets, out_events


def project_event_bumps(offsets, num_frames, division, sigma_qn=0.5,
                        event_kinds=None, event_weights=None):
    """
    Project structural event offsets to a weighted Gaussian-bumped grid.

    V2.9 accepts event_kinds and event_weights so dynamics, tempo text,
    key changes, and time changes can be tuned or ablated independently.
    The output is still normalized to max 1.0 before the global zeta weight
    is applied.
    """
    raw = np.zeros(num_frames)
    if event_weights is None:
        event_weights = {}
    if event_kinds is None:
        event_kinds = ['structural'] * len(offsets)

    for off, kind in zip(offsets, event_kinds):
        idx = int(round(off * division))
        if 0 <= idx < num_frames:
            raw[idx] = max(raw[idx], float(event_weights.get(kind, 1.0)))

    sigma_frames = sigma_qn * division
    if sigma_frames > 0 and raw.max() > 0:
        bumps = gaussian_filter1d(raw, sigma_frames)
        if bumps.max() > 0:
            bumps = bumps / bumps.max()
        return bumps
    return np.zeros_like(raw)


def extract_tempo_segments(score, default_bpm=60.0):
    """
    Extract a simple piecewise-constant tempo map as (offset, bpm) pairs.

    This is used for phrase-duration-in-seconds features.  If no usable
    MetronomeMark number is present, default_bpm is used.
    """
    events = []
    try:
        for mm in score.recurse().getElementsByClass(m21.tempo.MetronomeMark):
            bpm = getattr(mm, 'number', None)
            if bpm is None:
                continue
            off = _global_offset(mm, score)
            events.append((float(off), float(bpm)))
    except Exception:
        pass

    events = sorted(events, key=lambda x: x[0])
    deduped = []
    for off, bpm in events:
        if deduped and abs(deduped[-1][0] - off) < 0.001:
            deduped[-1] = (off, bpm)
        else:
            deduped.append((off, bpm))
    if not deduped or deduped[0][0] > 0.001:
        deduped.insert(0, (0.0, float(default_bpm)))
    return deduped


def qn_span_to_seconds(start_qn, end_qn, tempo_segments):
    """Integrate quarter-note span length through the tempo map."""
    if end_qn <= start_qn:
        return 0.0
    if not tempo_segments:
        tempo_segments = [(0.0, 60.0)]

    total = 0.0
    cur = float(start_qn)
    segments = list(tempo_segments) + [(float('inf'), tempo_segments[-1][1])]
    idx = 0
    while idx + 1 < len(segments) and segments[idx + 1][0] <= cur:
        idx += 1
    while cur < end_qn and idx < len(segments):
        bpm = max(float(segments[idx][1]), 1e-6)
        next_off = min(float(end_qn), float(segments[idx + 1][0]))
        if next_off > cur:
            total += (next_off - cur) * (60.0 / bpm)
        cur = next_off
        idx += 1
    return total


def count_note_events_between(notes_list, start_qn, end_qn):
    """Count note events whose onset lies in (start_qn, end_qn]."""
    eps = 0.01
    return sum(
        1 for n in notes_list
        if float(start_qn) + eps < float(n.get('offset', 0.0)) <= float(end_qn) + eps
    )


def compute_phrase_material(notes_list, start_qn, end_qn, tempo_segments):
    """
    Compute phrase material between two boundary times, excluding rests.

    The segment is (start_qn, end_qn].  note_count counts note onsets in the
    segment.  sounding_qn/seconds measure actual sounding-note overlap only;
    rests never add phrase material.
    """
    start_qn = float(start_qn)
    end_qn = float(end_qn)
    if end_qn <= start_qn:
        return {
            'elapsed_qn': 0.0,
            'elapsed_seconds': 0.0,
            'sounding_qn': 0.0,
            'sounding_seconds': 0.0,
            'note_count': 0,
        }

    note_count = 0
    sounding_qn = 0.0
    sounding_seconds = 0.0
    eps = 0.01
    for note in notes_list:
        off = float(note.get('offset', 0.0))
        dur = float(note.get('duration', 0.0))
        if start_qn + eps < off <= end_qn + eps:
            note_count += 1
        note_start = max(start_qn, off)
        note_end = min(end_qn, off + dur)
        if note_end > note_start:
            sounding_qn += note_end - note_start
            sounding_seconds += qn_span_to_seconds(note_start, note_end, tempo_segments)

    return {
        'elapsed_qn': end_qn - start_qn,
        'elapsed_seconds': qn_span_to_seconds(start_qn, end_qn, tempo_segments),
        'sounding_qn': sounding_qn,
        'sounding_seconds': sounding_seconds,
        'note_count': int(note_count),
    }


def postprocess_short_phrases(boundaries, notes_list, selection_score,
                              division, tempo_segments,
                              min_phrase_seconds=1.25,
                              max_phrase_notes=1,
                              start_time_qn=0.0):
    """
    Conservatively remove tiny phrase fragments using sounding material.

    This is not "quarter note bad."  A segment is suspicious only if it has
    little sounding time AND very few note events.  Rests do not count as
    musical material.  When a tiny phrase is found between two boundaries,
    remove the weaker neighboring boundary by selection_score.  The pass
    repeats until stable.

    Returns:
        filtered_boundaries, removed_records
    """
    bdys = sorted(float(b) for b in boundaries)
    removed = []
    if len(bdys) == 0:
        return np.array([]), removed

    changed = True
    while changed and bdys:
        changed = False
        prev = float(start_time_qn)
        for idx, cur in enumerate(list(bdys)):
            material = compute_phrase_material(notes_list, prev, cur, tempo_segments)
            if (material['sounding_seconds'] < min_phrase_seconds and
                    material['note_count'] <= max_phrase_notes):
                if idx == 0:
                    remove_idx = idx
                else:
                    prev_boundary = bdys[idx - 1]
                    prev_i = min(max(int(round(prev_boundary * division)), 0), len(selection_score) - 1)
                    cur_i = min(max(int(round(cur * division)), 0), len(selection_score) - 1)
                    remove_idx = idx - 1 if selection_score[prev_i] < selection_score[cur_i] else idx
                removed_boundary = bdys.pop(remove_idx)
                record = {
                    'time_quarter_notes': float(removed_boundary),
                    'reason': 'short_phrase_fragment',
                }
                record.update(material)
                removed.append(record)
                changed = True
                break
            prev = cur
    return np.array(bdys), removed

# =============================================================================
# Per-part boundary signal with slur modulation
# =============================================================================

def normalize_signal(x):
    x = np.asarray(x, dtype=float).copy()
    if x.max() > x.min():
        x = (x - x.min()) / (x.max() - x.min())
    return x


def compute_per_part_boundary_signal(chroma_novelty_i, rhythm_novelty_i,
                                      lbdm_grid_i,
                                      in_slur_interior_i, slur_endpoints_i,
                                      in_hairpin_i, structural_bumps_i,
                                      in_tuplet_i=None,
                                      in_tie_like_i=None,
                                      in_natural_tie_i=None,
                                      cross_rhythm_support_i=None,
                                      alpha_chroma=0.20,
                                      alpha_rhythm=0.35,
                                      beta_lbdm=0.45,
                                      eta_cross_rhythm=0.20,
                                      delta=0.5,
                                      slur_delta=0.70,
                                      tuplet_delta=0.80,
                                      gamma=0.4, zeta=0.4,
                                      repetition_mult_i=None):
    """
    B_i(t) with separate chroma/rhythm novelty and stateful context.

    Math:
        B_raw(t) = alpha_chroma * chroma_novelty_norm(t)
                 + alpha_rhythm * rhythm_novelty_norm(t)
                 + beta_lbdm    * lbdm_norm(t)

        boosts(t) = gamma * slur_endpoint_bumps(t)
                  + zeta  * structural_bumps(t)
                  + eta_cross_rhythm * cross_rhythm_support(t)

    V2.8 semantics:
      - Natural ties and same-pitch tie-like slurs are hard no-breath
        zones because they represent one sustained note.
      - Slurs, tuplets, and hairpins are continuation-context penalties,
        not universal hard rejects.
      - Boosts are multiplied by the same continuation penalties, so weak
        endpoint/structural noise cannot punch through phrase context.
    """
    chroma_norm = normalize_signal(chroma_novelty_i)
    rhythm_norm = normalize_signal(rhythm_novelty_i)
    lbdm_norm = normalize_signal(lbdm_grid_i)
    cross_norm = (normalize_signal(cross_rhythm_support_i)
                  if cross_rhythm_support_i is not None
                  else np.zeros_like(chroma_norm))

    if repetition_mult_i is not None:
        # v2.10 repetition mask, applied POST-normalization so the
        # attenuation has absolute meaning ("rhythm novelty 0.83 x
        # multiplier 0.37") and unmasked regions are not re-stretched.
        # Masks rhythm novelty and the slur-endpoint boost: articulation
        # that repeats with the pattern is pattern-interior evidence.
        # Chroma novelty, LBDM, structural bumps, and cross support are
        # deliberately unmasked.
        rhythm_norm = rhythm_norm * repetition_mult_i
        slur_endpoints_i = slur_endpoints_i * repetition_mult_i

    B_raw = (
        alpha_chroma * chroma_norm +
        alpha_rhythm * rhythm_norm +
        beta_lbdm * lbdm_norm
    )
    boosts = (
        gamma * slur_endpoints_i +
        zeta * structural_bumps_i +
        eta_cross_rhythm * cross_norm
    )

    hairpin_multiplier = 1.0 - delta * np.clip(in_hairpin_i, 0.0, 1.0)
    slur_multiplier = 1.0 - slur_delta * np.clip(in_slur_interior_i, 0.0, 1.0)

    if in_tuplet_i is None:
        tuplet_multiplier = 1.0
    else:
        tuplet_multiplier = 1.0 - tuplet_delta * np.clip(in_tuplet_i, 0.0, 1.0)

    B_i = (B_raw + boosts) * hairpin_multiplier * slur_multiplier * tuplet_multiplier

    if in_tie_like_i is not None:
        B_i = np.where(in_tie_like_i > 0, 0.0, B_i)
    if in_natural_tie_i is not None:
        B_i = np.where(in_natural_tie_i > 0, 0.0, B_i)

    return B_i, chroma_norm, rhythm_norm, lbdm_norm, cross_norm, B_raw


def build_long_note_arrival_grid(notes_list, num_frames, division,
                                 min_duration_qn=1.0,
                                 full_duration_qn=2.5,
                                 smoothing_sigma_qn=0.25):
    """
    Project long-note breath-target support to the time grid.

    V2.8 uses note['boundary_offset'] when available, so a tied chain's
    long-note support is anchored at the final tied segment rather than
    the chain start.
    """
    grid = np.zeros(num_frames, dtype=float)
    denom = max(full_duration_qn - min_duration_qn, 1e-6)
    for note in notes_list:
        dur = float(note.get('duration', 0.0))
        if dur < min_duration_qn:
            continue
        val = min((dur - min_duration_qn) / denom, 1.0)
        off = float(note.get('boundary_offset', note['offset']))
        idx = int(round(off * division))
        if 0 <= idx < num_frames:
            grid[idx] = max(grid[idx], val)

    sigma_frames = smoothing_sigma_qn * division
    if sigma_frames > 0 and grid.max() > 0:
        grid = gaussian_filter1d(grid, sigma_frames)
        if grid.max() > 0:
            grid = grid / grid.max()
    return grid


def build_following_gap_grid(notes_list, num_frames, division,
                             full_gap_qn=1.0,
                             smoothing_sigma_qn=0.25):
    """
    Project following-rest/gap support to the breath-target grid.

    A candidate is more plausible if a rest or large temporal gap follows
    the note/chord event.  For tied chains, the event duration is the full
    sustained duration from the first segment, while the support is anchored
    at boundary_offset, i.e. the final tied segment.
    """
    grid = np.zeros(num_frames, dtype=float)
    for k, note in enumerate(notes_list[:-1]):
        nxt = notes_list[k + 1]
        event_end = float(note['offset']) + float(note.get('duration', 0.0))
        gap = max(float(nxt['offset']) - event_end, 0.0)
        if gap <= 0:
            continue
        val = min(gap / max(full_gap_qn, 1e-6), 1.0)
        off = float(note.get('boundary_offset', note['offset']))
        idx = int(round(off * division))
        if 0 <= idx < num_frames:
            grid[idx] = max(grid[idx], val)

    sigma_frames = smoothing_sigma_qn * division
    if sigma_frames > 0 and grid.max() > 0:
        grid = gaussian_filter1d(grid, sigma_frames)
        if grid.max() > 0:
            grid = grid / grid.max()
    return grid


def detect_boundaries(B, time_grid, peak_height=0.3, peak_distance_frames=20,
                      candidate_height=None, selection_score=None,
                      forbidden_mask=None, candidate_signal=None,
                      acceptance_score=None, acceptance_height=None):
    """
    Detect boundaries with phrase-aware candidate selection.

    V2.8 separates three roles:
      - B: the final frame boundary evidence.
      - candidate_signal: where candidate maxima are allowed to originate.
        If omitted, B is used.  Passing a note-anchor signal lets a strong
        long-note endpoint compete even when the raw SSM peak is nearby.
      - selection_score: how candidates inside an exclusion window are
        ranked.
      - acceptance_score: optional score used for final acceptance.  If
        omitted, B is used.

    forbidden_mask hard-removes candidates only for true sustained-event
    invalidity, e.g. natural tie interiors or same-pitch tie-like spans.
    """
    if candidate_height is None:
        candidate_height = peak_height
    if acceptance_height is None:
        acceptance_height = peak_height

    seed = candidate_signal if candidate_signal is not None else B
    score = selection_score if selection_score is not None else B
    accept = acceptance_score if acceptance_score is not None else B

    peaks, _ = find_peaks(seed, height=candidate_height)
    if forbidden_mask is not None and len(peaks) > 0:
        peaks = np.array([p for p in peaks if forbidden_mask[p] <= 0], dtype=int)
    if len(peaks) == 0:
        return np.array([])

    chosen = []
    group = [int(peaks[0])]
    for p in peaks[1:]:
        p = int(p)
        if p - group[-1] <= peak_distance_frames:
            group.append(p)
        else:
            best = max(group, key=lambda idx: score[idx])
            if accept[best] >= acceptance_height:
                chosen.append(best)
            group = [p]
    best = max(group, key=lambda idx: score[idx])
    if accept[best] >= acceptance_height:
        chosen.append(best)

    return time_grid[np.array(chosen, dtype=int)] if chosen else np.array([])

# =============================================================================
# NEW: Breath mark annotation
# =============================================================================

def _target_pitch_label(element):
    if element is None:
        return None
    try:
        if isinstance(element, m21.note.Note):
            return element.pitch.nameWithOctave
        if isinstance(element, m21.chord.Chord):
            return '.'.join(n.pitch.nameWithOctave for n in element.notes)
    except Exception:
        return None
    return None


def _note_tie_type(element):
    try:
        if isinstance(element, m21.note.Note):
            return element.tie.type if element.tie is not None else None
        if isinstance(element, m21.chord.Chord):
            tie_types = [n.tie.type for n in element.notes if n.tie is not None]
            if not tie_types:
                return None
            if 'start' in tie_types or 'continue' in tie_types:
                return 'continue' if 'continue' in tie_types else 'start'
            if 'stop' in tie_types:
                return 'stop'
    except Exception:
        return None
    return None


def _notes_and_rests_with_offsets(part):
    events = []
    for el in part.flatten().notesAndRests:
        try:
            off = float(el.offset)
            dur = float(el.duration.quarterLength)
        except Exception:
            continue
        events.append({
            'offset': off,
            'duration': dur,
            'end': off + dur,
            'is_rest': isinstance(el, m21.note.Rest),
            'element': el,
        })
    events.sort(key=lambda x: (x['offset'], 1 if x['is_rest'] else 0))
    return events


def resolve_breath_target_for_part(part, boundary_time, slur_info,
                                   structural_info=None,
                                   natural_tie_info=None,
                                   onset_tolerance=0.5,
                                   structural_phrase_start_kinds=None):
    """
    Resolve a selected boundary time to the note that would receive a breath.

    The resolver is intentionally shared by validation, annotation, and
    explain().  It reports whether the boundary lies in a rest, whether the
    target note has tie markings, and why the target was chosen.
    """
    bt = float(boundary_time)
    if structural_phrase_start_kinds is None:
        structural_phrase_start_kinds = {
            'dynamic', 'tempo', 'tempo_text_slowing', 'tempo_text_accel',
            'tempo_text_a_tempo', 'tempo_text_mosso', 'tempo_text_other',
            'key', 'time',
        }
    if structural_info is None:
        structural_info = {}
    if natural_tie_info is None:
        natural_tie_info = {}

    slur_starts = slur_info.get('slur_starts', [])
    slur_ends = slur_info.get('slur_ends', [])
    tie_like_spans = slur_info.get('tie_like_spans', [])
    natural_tie_spans = natural_tie_info.get('natural_tie_spans', [])
    structural_offsets = structural_info.get('offsets', [])
    structural_kinds = structural_info.get('event_kinds', [])

    note_rest_events = _notes_and_rests_with_offsets(part)
    notes_with_offsets = [
        (ev['offset'], ev['element'])
        for ev in note_rest_events
        if not ev['is_rest']
    ]

    rec = {
        'boundary_time': bt,
        'target_offset': None,
        'target_duration': None,
        'target_pitch': None,
        'target_tie_type': None,
        'target_reason': None,
        'boundary_lies_in_rest': False,
        'rest_offset': None,
        'rest_duration': None,
        'inside_tie_like_span': any(start - 0.01 <= bt < end - 0.01
                                    for start, end in tie_like_spans),
        'inside_natural_tie_span': any(start - 0.01 <= bt < end - 0.01
                                       for start, end in natural_tie_spans),
        'target_has_outgoing_tie': False,
        'valid': True,
        'reject_reason': None,
    }

    for ev in note_rest_events:
        if ev['is_rest'] and ev['offset'] - 0.01 <= bt < ev['end'] - 0.01:
            rec['boundary_lies_in_rest'] = True
            rec['rest_offset'] = ev['offset']
            rec['rest_duration'] = ev['duration']
            break

    if rec['inside_tie_like_span']:
        rec['valid'] = False
        rec['reject_reason'] = 'inside_tie_like_span'
    if rec['inside_natural_tie_span']:
        rec['valid'] = False
        rec['reject_reason'] = 'inside_natural_tie_span'

    primary = None
    primary_off = None
    primary_dist = float('inf')
    fallback = None
    fallback_off = None

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
            fallback_off = off

    if primary is not None:
        is_start = any(abs(primary_off - s) <= onset_tolerance for s in slur_starts)
        is_end = any(abs(primary_off - e) <= onset_tolerance for e in slur_ends)
        is_structural_start = any(
            abs(primary_off - off) <= onset_tolerance and kind in structural_phrase_start_kinds
            for off, kind in zip(structural_offsets, structural_kinds)
        )
        if (is_start or is_structural_start) and not is_end:
            target = None
            target_off = None
            eps = onset_tolerance / 4.0
            for off, n in notes_with_offsets:
                if off < primary_off - eps:
                    target = n
                    target_off = off
                else:
                    break
            rec['target_reason'] = 'previous_note_before_phrase_start'
        else:
            target = primary
            target_off = primary_off
            rec['target_reason'] = 'primary_note'
    else:
        target = fallback
        target_off = fallback_off
        rec['target_reason'] = 'fallback_previous_note'

    if rec['boundary_lies_in_rest']:
        rec['valid'] = False
        rec['reject_reason'] = 'boundary_lies_in_rest'

    if target is None:
        rec['valid'] = False
        if rec['reject_reason'] is None:
            rec['reject_reason'] = 'no_target_note'
        return rec, None

    try:
        rec['target_offset'] = float(target_off)
        rec['target_duration'] = float(target.duration.quarterLength)
    except Exception:
        pass
    rec['target_pitch'] = _target_pitch_label(target)
    rec['target_tie_type'] = _note_tie_type(target)
    rec['target_has_outgoing_tie'] = rec['target_tie_type'] in ('start', 'continue')
    if rec['target_has_outgoing_tie']:
        rec['valid'] = False
        rec['reject_reason'] = 'target_has_outgoing_tie'

    return rec, target


def validate_boundaries_for_part(part, boundaries, slur_info, structural_info,
                                 natural_tie_info, onset_tolerance=0.5,
                                 reject_rest_boundaries=True,
                                 reject_outgoing_ties=True):
    """Resolve and filter boundaries using final breath-target semantics."""
    kept = []
    records = []
    for bt in boundaries:
        rec, _ = resolve_breath_target_for_part(
            part, bt, slur_info,
            structural_info=structural_info,
            natural_tie_info=natural_tie_info,
            onset_tolerance=onset_tolerance,
        )
        valid = bool(rec.get('valid', True))
        if reject_rest_boundaries and rec.get('boundary_lies_in_rest'):
            valid = False
            rec['reject_reason'] = 'boundary_lies_in_rest'
        if reject_outgoing_ties and rec.get('target_has_outgoing_tie'):
            valid = False
            rec['reject_reason'] = 'target_has_outgoing_tie'
        rec['kept'] = valid
        if valid:
            kept.append(float(bt))
        records.append(rec)
    return np.array(kept), records


def add_breath_marks_per_part(original_score, boundaries_per_part,
                                slur_info_per_part,
                                part_indices_to_annotate, output_path,
                                color='#d62728', onset_tolerance=0.5,
                                natural_tie_info_per_part=None,
                                structural_info_per_part=None,
                                structural_phrase_start_kinds=None):
    """
    Role-aware breath mark placement.

    V2.9.1 delegates target choice to resolve_breath_target_for_part(), so the
    same semantics are used for validation, annotation, and diagnostics.  Rest
    boundaries and invalid tied targets are skipped rather than silently turned
    into breath marks on nearby notes.
    """
    score_copy = copy.deepcopy(original_score)
    parts = list(score_copy.parts)

    for i, part in enumerate(parts):
        if i not in part_indices_to_annotate:
            continue
        boundaries = boundaries_per_part[i]
        slur_info = slur_info_per_part[i] if i < len(slur_info_per_part) else {}
        natural_tie_info = {}
        if natural_tie_info_per_part is not None and i < len(natural_tie_info_per_part):
            natural_tie_info = natural_tie_info_per_part[i]
        structural_info = {}
        if structural_info_per_part is not None and i < len(structural_info_per_part):
            structural_info = structural_info_per_part[i]

        for bt in boundaries:
            rec, target = resolve_breath_target_for_part(
                part, bt, slur_info,
                structural_info=structural_info,
                natural_tie_info=natural_tie_info,
                onset_tolerance=onset_tolerance,
                structural_phrase_start_kinds=structural_phrase_start_kinds,
            )
            if not rec.get('valid', True) or target is None:
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
                                hairpin_info=None, structural_info=None,
                                tuplet_info=None):
    """
    One panel per active part.
      - Gold shaded regions: slur interiors
      - Cyan shaded regions: hairpin spans
      - Lavender shaded regions: tuplet [start, end) spans
      - Magenta vertical ticks: structural event positions
      - Curves: chroma SSM novelty, rhythm SSM novelty, LBDM, B_raw, B_i
    """
    active_indices = [i for i in range(len(part_names)) if not is_tacet[i]]
    n_panels = len(active_indices) + 1

    fig, axes = plt.subplots(n_panels, 1,
                             figsize=(14, 1.4 * n_panels),
                             sharex=True)
    if n_panels == 1:
        axes = [axes]

    ax_sum = axes[0]
    ax_sum.set_title("Per-part boundaries (summary)", fontsize=10, loc='left')
    for j, i in enumerate(active_indices):
        for bt in boundaries_per_part[i]:
            ax_sum.scatter(bt, j, color='red', marker='|', s=80, linewidths=1.2)
        n_slurs = slur_info[i].get('n_slurs', 0) if i < len(slur_info) else 0
        n_hp = hairpin_info[i].get('n_hairpins', 0) if hairpin_info is not None else 0
        n_tuplets = tuplet_info[i].get('n_tuplets', 0) if tuplet_info is not None else 0
        ax_sum.text(time_grid[0] - (time_grid[-1] - time_grid[0]) * 0.01,
                    j,
                    f"{part_names[i]} [{activity_levels[i]:.0%}, "
                    f"{n_slurs}sl/{n_hp}hp/{n_tuplets}tu]",
                    fontsize=7, ha='right', va='center')
    ax_sum.set_yticks([])
    ax_sum.set_ylim(-1, len(active_indices))
    ax_sum.grid(axis='x', alpha=0.3)

    for j, i in enumerate(active_indices):
        ax = axes[j + 1]
        sig = per_part_signals[i]
        if len(sig) == 6:
            B_i, chroma_i, rhythm_i, lbdm_i, cross_i, B_raw = sig
        else:
            B_i, chroma_i, lbdm_i, B_raw = sig
            rhythm_i = np.zeros_like(B_i)
            cross_i = np.zeros_like(B_i)

        si = slur_info[i] if i < len(slur_info) else {}
        in_slur_i = si.get('in_slur_interior', np.zeros_like(time_grid))
        n_slurs = si.get('n_slurs', 0)

        if in_slur_i.max() > 0:
            ax.fill_between(time_grid, 0, 1.1,
                            where=in_slur_i > 0,
                            color='gold', alpha=0.15,
                            transform=ax.get_xaxis_transform())

        n_hp = 0
        if hairpin_info is not None and i < len(hairpin_info):
            in_hp_i = hairpin_info[i].get('in_hairpin', np.zeros_like(time_grid))
            n_hp = hairpin_info[i].get('n_hairpins', 0)
            if in_hp_i.max() > 0:
                ax.fill_between(time_grid, 0, 1.1,
                                where=in_hp_i > 0,
                                color='cyan', alpha=0.15,
                                transform=ax.get_xaxis_transform())

        n_tuplets = 0
        if tuplet_info is not None and i < len(tuplet_info):
            in_tup_i = tuplet_info[i].get('in_tuplet', np.zeros_like(time_grid))
            n_tuplets = tuplet_info[i].get('n_tuplets', 0)
            if in_tup_i.max() > 0:
                ax.fill_between(time_grid, 0, 1.1,
                                where=in_tup_i > 0,
                                color='violet', alpha=0.12,
                                transform=ax.get_xaxis_transform())

        n_struct = 0
        if structural_info is not None and i < len(structural_info):
            offsets = structural_info[i].get('offsets', [])
            n_struct = len(offsets)
            for off in offsets:
                ax.axvline(x=off, color='magenta', alpha=0.4,
                           linewidth=0.6, linestyle=':')

        ax.plot(time_grid, chroma_i, color='steelblue', alpha=0.3,
                linewidth=0.6, label='chroma SSM')
        ax.plot(time_grid, rhythm_i, color='darkorange', alpha=0.35,
                linewidth=0.6, label='rhythm SSM')
        ax.plot(time_grid, lbdm_i, color='seagreen', alpha=0.3,
                linewidth=0.6, label='LBDM')
        if cross_i.max() > 0:
            ax.plot(time_grid, cross_i, color='purple', alpha=0.25,
                    linewidth=0.6, label='cross rhythm')
        ax.plot(time_grid, B_raw, color='gray', alpha=0.5,
                linewidth=0.7, label='B_raw')
        ax.plot(time_grid, B_i, color='black', linewidth=1.1, label='B_i')

        for bt in boundaries_per_part[i]:
            ax.axvline(x=bt, color='red', linestyle='--', alpha=0.6,
                       linewidth=0.8)

        ax.set_title(
            f"{part_names[i]} ({len(boundaries_per_part[i])} boundaries, "
            f"{n_slurs} slurs, {n_hp} hairpins, {n_tuplets} tuplets, "
            f"{n_struct} struct events)",
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
                            alpha_chroma, alpha_rhythm, beta_lbdm,
                            eta_cross_rhythm, delta, gamma,
                            w_pitch, w_ioi, w_rest,
                            division, kernel_size_frames,
                            short_phrase_filter=False,
                            min_phrase_seconds=1.25,
                            max_phrase_notes=1,
                            structural_event_weights=None,
                            reject_rest_boundaries=True,
                            reject_outgoing_ties=True):
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
            'alpha_chroma_ssm_weight': alpha_chroma,
            'alpha_rhythm_ssm_weight': alpha_rhythm,
            'beta_lbdm_weight': beta_lbdm,
            'eta_cross_rhythm_weight': eta_cross_rhythm,
            'slur_interior_suppression': 'hard_zero',
            'delta_hairpin_suppression': delta,
            'gamma_slur_endpoint_boost': gamma,
            'lbdm_w_pitch': w_pitch,
            'lbdm_w_ioi': w_ioi,
            'lbdm_w_rest': w_rest,
            'division': division,
            'kernel_size_frames': kernel_size_frames,
            'boundary_detection': 'candidate_selection_v2_9_1',
            'short_phrase_filter': bool(short_phrase_filter),
            'min_phrase_seconds': min_phrase_seconds,
            'max_phrase_notes': max_phrase_notes,
            'structural_event_weights': structural_event_weights or {},
            'reject_rest_boundaries': bool(reject_rest_boundaries),
            'reject_outgoing_ties': bool(reject_outgoing_ties),
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
                    alpha_chroma=0.20, alpha_rhythm=0.35,
                    beta_lbdm=0.45, eta_cross_rhythm=0.20,
                    delta=0.5, slur_delta=0.70, tuplet_delta=0.80,
                    gamma=0.4, zeta=0.4,
                    w_pitch=0.25, w_ioi=0.50, w_rest=0.25,
                    lbdm_smoothing_qn=0.5,
                    slur_endpoint_sigma_qn=0.5,
                    structural_sigma_qn=0.5,
                    peak_height=0.3, candidate_height=0.22,
                    peak_distance_qn=2.5,
                    selection_lbdm_weight=0.30,
                    selection_long_weight=0.30,
                    selection_gap_weight=0.20,
                    selection_cross_rhythm_weight=0.25,
                    selection_slur_penalty=0.35,
                    selection_hairpin_penalty=0.25,
                    selection_tuplet_penalty=0.45,
                    note_candidate_weight=0.65,
                    note_anchor_long_weight=0.50,
                    note_anchor_lbdm_weight=0.35,
                    note_anchor_gap_weight=0.25,
                    note_anchor_cross_weight=0.15,
                    selection_accept_height=0.30,
                    short_phrase_filter=True,
                    min_phrase_seconds=1.25,
                    max_phrase_notes=1,
                    dynamic_event_weight=0.80,
                    tempo_event_weight=1.00,
                    tempo_text_event_weight=1.00,
                    key_event_weight=0.80,
                    time_event_weight=1.00,
                    reject_rest_boundaries=True,
                    reject_outgoing_ties=True,
                    phrase_shape_thresholds=None,
                    delta_repetition=0.0,
                    repetition_lag_min_qn=0.5,
                    repetition_lag_max_qn=3.0,
                    repetition_window_qn=1.0,
                    selection_repetition_penalty=0.0,
                    lbdm_polyphony_mode="top",
                    chroma_kernel='exact',
                    cross_rhythm_window_qn=4.0,
                    cross_rhythm_similarity_threshold=0.85,
                    cross_rhythm_max_shift_qn=0.5,
                    convention='muller',
                    tacet_threshold=0.05,
                    breath_color='#d62728'):
    """
    V2.9.1 top-level pipeline.

    Main boundary evidence:
        chroma self-SSM novelty + rhythm self-SSM novelty + LBDM
        + soft cross-part rhythm support + slur/structural boosts.

    Boundary selection:
        candidate peaks are selected by a phrase-oriented score that can
        prefer nearby long-note/LBDM/cross-rhythm-supported arrivals over
        slightly taller raw novelty spikes.

    Diagnostics:
        cross-part synchronous rhythm and musical-chroma similarities are
        computed and stored in result['cross_similarity_info'], but they
        are not used for boundary decisions in this version.
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"[1/11] Loading {input_path}")
    score, parts = parse_score(input_path)
    part_names = [get_part_name(p, default=f'part_{i}')
                  for i, p in enumerate(parts)]
    print(f"       {len(parts)} parts, total length "
          f"{score.duration.quarterLength:.1f} quarter notes")

    print(f"[2/11] Time grid (division={division})")
    time_grid = create_time_grid(score, division)
    T = len(time_grid)
    print(f"       {T} frames")

    tempo_segments = extract_tempo_segments(score)
    structural_event_weights = make_structural_event_weight_map(
        dynamic_weight=dynamic_event_weight,
        tempo_weight=tempo_event_weight,
        tempo_text_weight=tempo_text_event_weight,
        key_weight=key_event_weight,
        time_weight=time_event_weight,
    )

    print("[3/11] Per-frame chroma/rhythm features")
    activity, onset, chroma = extract_features(parts, time_grid, division)
    phi_chroma = build_feature_vectors(activity, chroma)
    phi_rhythm = build_rhythm_feature_vectors(activity, onset)

    print(f"[4/11] Tacet detection (threshold={tacet_threshold:.0%})")
    activity_levels, is_tacet = compute_activity_levels(
        activity, threshold=tacet_threshold
    )

    print("[5/11] Slur extraction")
    slur_info = []
    for i, part in enumerate(parts):
        if is_tacet[i]:
            slur_info.append({
                'in_slur_interior': np.zeros(T),
                'in_tie_like': np.zeros(T),
                'endpoint_bumps': np.zeros(T),
                'n_slurs': 0,
                'n_phrase_slurs': 0,
                'n_tie_like_slurs': 0,
                'slur_starts': [],
                'slur_ends': [],
                'tie_like_spans': [],
            })
            continue
        si = extract_slur_indicators(
            part, T, division,
            endpoint_sigma_qn=slur_endpoint_sigma_qn
        )
        slur_info.append(si)

    print("[6/11] Hairpin, tuplet, and structural event extraction")
    hairpin_info = []
    tuplet_info = []
    natural_tie_info = []
    structural_info = []
    for i, part in enumerate(parts):
        if is_tacet[i]:
            hairpin_info.append({'in_hairpin': np.zeros(T), 'n_hairpins': 0})
            tuplet_info.append({'in_tuplet': np.zeros(T), 'n_tuplets': 0})
            natural_tie_info.append({
                'in_natural_tie': np.zeros(T),
                'natural_tie_spans': [],
                'n_natural_ties': 0,
            })
            structural_info.append({'bumps': np.zeros(T), 'offsets': [], 'event_kinds': []})
            continue
        in_hp, n_hp = extract_hairpin_indicators(part, T, division)
        hairpin_info.append({'in_hairpin': in_hp, 'n_hairpins': n_hp})

        in_tuplet, n_tuplets = extract_tuplet_indicators(part, T, division)
        tuplet_info.append({'in_tuplet': in_tuplet, 'n_tuplets': n_tuplets})

        nti = extract_natural_tie_indicators(part, T, division)
        natural_tie_info.append(nti)

        struct_offsets, event_kinds = extract_structural_event_offsets(
            part, score=score
        )
        struct_bumps = project_event_bumps(
            struct_offsets, T, division, sigma_qn=structural_sigma_qn,
            event_kinds=event_kinds, event_weights=structural_event_weights
        )
        structural_info.append({
            'bumps': struct_bumps,
            'offsets': struct_offsets,
            'event_kinds': event_kinds,
        })

    for i in range(len(parts)):
        marker = " [TACET]" if is_tacet[i] else ""
        n_phrase = slur_info[i].get('n_phrase_slurs', 0)
        n_tie_like = slur_info[i].get('n_tie_like_slurs', 0)
        n_hp = hairpin_info[i]['n_hairpins']
        n_tuplets = tuplet_info[i]['n_tuplets']
        n_nat_ties = natural_tie_info[i]['n_natural_ties']
        n_struct = len(structural_info[i]['offsets'])
        print(f"       part {i:2d} {part_names[i]:25s} "
              f"activity={activity_levels[i]:.1%} "
              f"slurs={n_phrase}+{n_tie_like}tie hairpins={n_hp} "
              f"tuplets={n_tuplets} natural_ties={n_nat_ties} "
              f"struct_events={n_struct}{marker}")

    print(f"[7/11] Chroma and rhythm self-SSM novelty "
          f"(kernel={kernel_size_frames} frames)")
    L = kernel_size_frames // 2
    kernel = make_checkerboard_kernel(L, convention=convention)
    chroma_novelty_per_part = []
    rhythm_novelty_per_part = []
    repetition_scores = []
    repetition_best_lags = []
    repetition_mults = []
    chroma_feature_kernel = (make_chroma_interval_kernel()
                             if chroma_kernel == 'interval' else None)
    if chroma_feature_kernel is not None:
        print("       chroma SSM kernel: interval-class (v2.10-B)")
    rep_available = compute_repetition_score is not None
    if delta_repetition > 0.0 and not rep_available:
        print("       WARNING: delta_repetition > 0 but repetition_mask "
              "module not importable; repetition masking DISABLED")
    if rep_available and delta_repetition > 0.0:
        print(f"       repetition mask ON: delta={delta_repetition}, "
              f"lags=[{repetition_lag_min_qn},{repetition_lag_max_qn}] qn, "
              f"window={repetition_window_qn} qn "
              f"(masks rhythm novelty, slur-endpoint boost, "
              f"following-gap)")
    for i in range(len(parts)):
        if is_tacet[i]:
            chroma_novelty_per_part.append(np.zeros(T))
            rhythm_novelty_per_part.append(np.zeros(T))
            repetition_scores.append(np.zeros(T))
            repetition_best_lags.append(np.zeros(T))
            repetition_mults.append(np.ones(T))
            continue
        chroma_ssm = build_ssm_with_kernel(phi_chroma[i],
                                           chroma_feature_kernel)
        rhythm_ssm = build_ssm(phi_rhythm[i])
        chroma_nu = compute_novelty(chroma_ssm, kernel,
                                    convention=convention, trim_edges=True)
        rhythm_nu = compute_novelty(rhythm_ssm, kernel,
                                    convention=convention, trim_edges=True)
        if rep_available:
            rep_i, rep_lag_i = compute_repetition_score(
                phi_rhythm[i], division,
                lag_min_qn=repetition_lag_min_qn,
                lag_max_qn=repetition_lag_max_qn,
                window_qn=repetition_window_qn,
                return_best_lag=True,
            )
        else:
            rep_i = np.zeros(T)
            rep_lag_i = np.zeros(T)
        repetition_scores.append(rep_i)
        repetition_best_lags.append(rep_lag_i)
        if repetition_multiplier is not None:
            repetition_mults.append(
                repetition_multiplier(rep_i, delta_repetition))
        else:
            repetition_mults.append(np.ones(T))
        chroma_novelty_per_part.append(chroma_nu)
        rhythm_novelty_per_part.append(rhythm_nu)

    print("[8/11] Cross-part synchronous similarity diagnostics")
    cross_similarity_info = {
        'rhythm_sync': compute_cross_part_synchronous_similarity(
            phi_rhythm, is_tacet=is_tacet
        ),
        'chroma_sync_musical': compute_cross_part_synchronous_similarity(
            phi_chroma, is_tacet=is_tacet,
            feature_kernel=make_chroma_interval_kernel()
        ),
        'used_for_boundary_detection': False,
    }

    print(f"[9/11] Per-part LBDM and long-note arrivals "
          f"(sigma_smooth={lbdm_smoothing_qn} qn)")
    lbdm_grids = []
    long_note_grids = []
    following_gap_grids = []
    notes_per_part = []
    for i in range(len(parts)):
        if is_tacet[i]:
            lbdm_grids.append(np.zeros(T))
            long_note_grids.append(np.zeros(T))
            following_gap_grids.append(np.zeros(T))
            notes_per_part.append([])
            continue
        notes_list, sigma = compute_lbdm_per_part(
            parts[i], w_pitch=w_pitch, w_ioi=w_ioi, w_rest=w_rest,
            tie_like_spans=slur_info[i].get('tie_like_spans', [])
        )
        notes_per_part.append(notes_list)
        grid = project_lbdm_to_grid(
            notes_list, sigma, T, division,
            smoothing_sigma_qn=lbdm_smoothing_qn
        )
        lbdm_grids.append(grid)
        long_note_grids.append(build_long_note_arrival_grid(
            notes_list, T, division
        ))
        following_gap_grids.append(build_following_gap_grid(
            notes_list, T, division
        ))

    print("[10/11] Boundary signal, cross-rhythm support, and candidates")
    peak_distance_frames = max(int(round(peak_distance_qn * division)), 1)
    per_part_signals = []
    boundaries_per_part = []
    short_phrase_filter_info = []
    boundary_target_info = []
    per_part_candidate_diagnostics = []

    # First pass: local signal without cross-rhythm support.
    local_B_pre = np.zeros((len(parts), T), dtype=float)
    for i in range(len(parts)):
        if is_tacet[i]:
            continue
        B_pre, *_ = compute_per_part_boundary_signal(
            chroma_novelty_per_part[i], rhythm_novelty_per_part[i],
            lbdm_grids[i],
            slur_info[i]['in_slur_interior'], slur_info[i]['endpoint_bumps'],
            hairpin_info[i]['in_hairpin'], structural_info[i]['bumps'],
            in_tuplet_i=tuplet_info[i]['in_tuplet'],
            in_tie_like_i=slur_info[i].get('in_tie_like', np.zeros(T)),
            in_natural_tie_i=natural_tie_info[i]['in_natural_tie'],
            cross_rhythm_support_i=np.zeros(T),
            repetition_mult_i=repetition_mults[i],
            alpha_chroma=alpha_chroma,
            alpha_rhythm=alpha_rhythm,
            beta_lbdm=beta_lbdm,
            eta_cross_rhythm=0.0,
            delta=delta,
            slur_delta=slur_delta,
            tuplet_delta=tuplet_delta,
            gamma=gamma, zeta=zeta
        )
        local_B_pre[i] = B_pre

    cross_support_attribution = {}
    cross_rhythm_support = compute_cross_rhythm_support(
        phi_rhythm, activity, local_B_pre, is_tacet, division,
        window_qn=cross_rhythm_window_qn,
        similarity_threshold=cross_rhythm_similarity_threshold,
        max_shift_qn=cross_rhythm_max_shift_qn,
        attribution_out=cross_support_attribution,
    )

    for i in range(len(parts)):
        if is_tacet[i]:
            per_part_signals.append(
                (np.zeros(T), np.zeros(T), np.zeros(T), np.zeros(T),
                 np.zeros(T), np.zeros(T))
            )
            boundaries_per_part.append(np.array([]))
            short_phrase_filter_info.append([])
            boundary_target_info.append([])
            per_part_candidate_diagnostics.append({})
            continue

        in_slur_i = slur_info[i]['in_slur_interior']
        endpoints_i = slur_info[i]['endpoint_bumps']
        in_hp_i = hairpin_info[i]['in_hairpin']
        in_tuplet_i = tuplet_info[i]['in_tuplet']
        struct_bumps_i = structural_info[i]['bumps']
        in_tie_i = slur_info[i].get('in_tie_like', np.zeros(T))
        in_nat_tie_i = natural_tie_info[i]['in_natural_tie']

        B_i, chroma_n, rhythm_n, lbdm_n, cross_n, B_raw = compute_per_part_boundary_signal(
            chroma_novelty_per_part[i], rhythm_novelty_per_part[i],
            lbdm_grids[i],
            in_slur_i, endpoints_i,
            in_hp_i, struct_bumps_i,
            in_tuplet_i=in_tuplet_i,
            in_tie_like_i=in_tie_i,
            in_natural_tie_i=in_nat_tie_i,
            cross_rhythm_support_i=cross_rhythm_support[i],
            repetition_mult_i=repetition_mults[i],
            alpha_chroma=alpha_chroma,
            alpha_rhythm=alpha_rhythm,
            beta_lbdm=beta_lbdm,
            eta_cross_rhythm=eta_cross_rhythm,
            delta=delta,
            slur_delta=slur_delta,
            tuplet_delta=tuplet_delta,
            gamma=gamma, zeta=zeta
        )
        per_part_signals.append((B_i, chroma_n, rhythm_n, lbdm_n, cross_n, B_raw))

        long_n = normalize_signal(long_note_grids[i])
        gap_n = normalize_signal(following_gap_grids[i])
        if repetition_multiplier is not None and delta_repetition > 0.0:
            # Rhythm repetition discounts gap evidence: a rest that recurs
            # every cell is part of the pattern, not a phrase edge.
            # long_n is deliberately NOT masked (texture exits arrive on
            # long notes and must survive).
            gap_n = gap_n * repetition_multiplier(
                repetition_scores[i], delta_repetition
            )

        # Only true sustained-note identity constraints are hard-invalid.
        forbidden = np.maximum.reduce([in_tie_i, in_nat_tie_i])

        continuation_penalty = (
            selection_slur_penalty * np.clip(in_slur_i, 0.0, 1.0) +
            selection_hairpin_penalty * np.clip(in_hp_i, 0.0, 1.0) +
            selection_tuplet_penalty * np.clip(in_tuplet_i, 0.0, 1.0) +
            selection_repetition_penalty * np.clip(repetition_scores[i], 0.0, 1.0)
        )

        selection_score = (
            B_i +
            selection_lbdm_weight * lbdm_n +
            selection_long_weight * long_n +
            selection_gap_weight * gap_n +
            selection_cross_rhythm_weight * cross_n -
            continuation_penalty
        )
        selection_score = np.maximum(selection_score, 0.0)

        note_anchor_score = normalize_signal(
            note_anchor_long_weight * long_n +
            note_anchor_lbdm_weight * lbdm_n +
            note_anchor_gap_weight * gap_n +
            note_anchor_cross_weight * cross_n -
            continuation_penalty
        )
        candidate_signal = np.maximum(B_i, note_candidate_weight * note_anchor_score)
        acceptance_score = np.maximum(B_i, selection_score)

        bdys = detect_boundaries(
            B_i, time_grid,
            peak_height=peak_height,
            peak_distance_frames=peak_distance_frames,
            candidate_height=candidate_height,
            selection_score=selection_score,
            forbidden_mask=forbidden,
            candidate_signal=candidate_signal,
            acceptance_score=acceptance_score,
            acceptance_height=selection_accept_height,
        )
        if short_phrase_filter:
            bdys, removed_short = postprocess_short_phrases(
                bdys, notes_per_part[i], selection_score, division,
                tempo_segments,
                min_phrase_seconds=min_phrase_seconds,
                max_phrase_notes=max_phrase_notes,
            )
        else:
            removed_short = []

        bdys, target_records = validate_boundaries_for_part(
            parts[i], bdys, slur_info[i], structural_info[i], natural_tie_info[i],
            reject_rest_boundaries=reject_rest_boundaries,
            reject_outgoing_ties=reject_outgoing_ties,
        )

        boundaries_per_part.append(bdys)
        short_phrase_filter_info.append(removed_short)
        boundary_target_info.append(target_records)
        per_part_candidate_diagnostics.append({
            'candidate_signal': candidate_signal,
            'selection_score': selection_score,
            'acceptance_score': acceptance_score,
            'note_anchor_score': note_anchor_score,
            'continuation_penalty': continuation_penalty,
            'forbidden_mask': forbidden,
            'repetition_score': repetition_scores[i],
            'repetition_best_lag_qn': repetition_best_lags[i],
        })
        print(f"       part {i:2d} {part_names[i]:25s} "
              f"{len(bdys):3d} boundaries")

    # v2.10-A: phrase material / shape report (passive read-out).
    print("[10b] Phrase material report")
    if compute_phrase_material_report is None:
        print("       phrase_material module not importable; skipping report")
        phrase_material_per_part = [[] for _ in parts]
        phrase_shape_thresholds_used = None
    else:
        phrase_shape_thresholds_used = (
            phrase_shape_thresholds
            if phrase_shape_thresholds is not None
            else default_phrase_shape_thresholds()
        )
        score_end_qn = float(score.duration.quarterLength)
        phrase_material_per_part = []
        for i in range(len(parts)):
            if is_tacet[i]:
                phrase_material_per_part.append([])
                continue
            report = compute_phrase_material_report(
                notes_per_part[i],
                boundaries_per_part[i],
                tempo_segments,
                start_time_qn=0.0,
                end_time_qn=score_end_qn,
                thresholds=phrase_shape_thresholds_used,
            )
            phrase_material_per_part.append(report)
            n_flagged = sum(1 for r in report if r['flags'])
            if n_flagged > 0:
                print(f"       part {i:2d} {part_names[i]:25s} "
                      f"{n_flagged}/{len(report)} segments flagged")

    print("[11/11] Writing outputs")
    annotated_path = os.path.join(output_dir, 'sectioned.musicxml')
    active_set = {i for i in range(len(parts)) if not is_tacet[i]}
    add_breath_marks_per_part(score, boundaries_per_part, slur_info,
                                active_set,
                                annotated_path, color=breath_color,
                                natural_tie_info_per_part=natural_tie_info,
                                structural_info_per_part=structural_info)

    plot_path = os.path.join(output_dir, 'diagnostics.png')
    plot_diagnostics_per_part(time_grid, per_part_signals, part_names,
                                boundaries_per_part, is_tacet,
                                activity_levels, slur_info, plot_path,
                                hairpin_info=hairpin_info,
                                structural_info=structural_info,
                                tuplet_info=tuplet_info)

    summary_path = os.path.join(output_dir, 'boundaries.json')
    write_summary_per_part(
        boundaries_per_part, part_names, activity_levels, is_tacet,
        slur_info, score, summary_path,
        alpha_chroma=alpha_chroma,
        alpha_rhythm=alpha_rhythm,
        beta_lbdm=beta_lbdm,
        eta_cross_rhythm=eta_cross_rhythm,
        delta=delta, gamma=gamma,
        w_pitch=w_pitch, w_ioi=w_ioi, w_rest=w_rest,
        division=division, kernel_size_frames=kernel_size_frames,
        short_phrase_filter=short_phrase_filter,
        min_phrase_seconds=min_phrase_seconds,
        max_phrase_notes=max_phrase_notes,
        structural_event_weights=structural_event_weights,
        reject_rest_boundaries=reject_rest_boundaries,
        reject_outgoing_ties=reject_outgoing_ties,
    )
    material_path = os.path.join(output_dir, 'phrase_material.json')
    if write_phrase_material_summary is not None:
        write_phrase_material_summary(
            phrase_material_per_part, part_names, is_tacet, score,
            material_path,
            thresholds=phrase_shape_thresholds_used,
        )
        print(f"       Material:    {material_path}")

    print(f"       Annotated:   {annotated_path}")
    print(f"       Diagnostics: {plot_path}")
    print(f"       Summary:     {summary_path}")

    measure_offsets = []
    if len(parts) > 0:
        for m in parts[0].getElementsByClass(m21.stream.Measure):
            measure_offsets.append((float(m.offset), m.number))

    result = {
        'score': score,
        'input_path': input_path,
        'measure_offsets': measure_offsets,
        'per_part_boundaries': boundaries_per_part,
        'part_names': part_names,
        'is_tacet': is_tacet,
        'activity_levels': activity_levels,
        'time_grid': time_grid,
        'per_part_signals': per_part_signals,
        'slur_info': slur_info,
        'hairpin_info': hairpin_info,
        'tuplet_info': tuplet_info,
        'natural_tie_info': natural_tie_info,
        'structural_info': structural_info,
        'notes_per_part': notes_per_part,
        'long_note_grids': long_note_grids,
        'following_gap_grids': following_gap_grids,
        'short_phrase_filter_info': short_phrase_filter_info,
        'phrase_material_per_part': phrase_material_per_part,
        'boundary_target_info': boundary_target_info,
        'per_part_candidate_diagnostics': per_part_candidate_diagnostics,
        'tempo_segments': tempo_segments,
        'cross_rhythm_support': cross_rhythm_support,
        'cross_similarity_info': cross_similarity_info,
        'parameters': {
            'division': division,
            'kernel_size_frames': kernel_size_frames,
            'alpha_chroma': alpha_chroma,
            'alpha_rhythm': alpha_rhythm,
            'beta_lbdm': beta_lbdm,
            'eta_cross_rhythm': eta_cross_rhythm,
            'delta': delta,
            'slur_delta': slur_delta,
            'tuplet_delta': tuplet_delta,
            'gamma': gamma, 'zeta': zeta,
            'w_pitch': w_pitch, 'w_ioi': w_ioi, 'w_rest': w_rest,
            'peak_height': peak_height,
            'candidate_height': candidate_height,
            'selection_accept_height': selection_accept_height,
            'peak_distance_frames': peak_distance_frames,
            'peak_distance_qn': peak_distance_qn,
            'selection_lbdm_weight': selection_lbdm_weight,
            'selection_long_weight': selection_long_weight,
            'selection_gap_weight': selection_gap_weight,
            'selection_cross_rhythm_weight': selection_cross_rhythm_weight,
            'selection_slur_penalty': selection_slur_penalty,
            'selection_hairpin_penalty': selection_hairpin_penalty,
            'selection_tuplet_penalty': selection_tuplet_penalty,
            'note_candidate_weight': note_candidate_weight,
            'note_anchor_long_weight': note_anchor_long_weight,
            'note_anchor_lbdm_weight': note_anchor_lbdm_weight,
            'note_anchor_gap_weight': note_anchor_gap_weight,
            'note_anchor_cross_weight': note_anchor_cross_weight,
            'delta_repetition': delta_repetition,
            'repetition_lag_min_qn': repetition_lag_min_qn,
            'repetition_lag_max_qn': repetition_lag_max_qn,
            'repetition_window_qn': repetition_window_qn,
            'selection_repetition_penalty': selection_repetition_penalty,
            'lbdm_polyphony_mode': lbdm_polyphony_mode,
            'chroma_kernel': chroma_kernel,
            'short_phrase_filter': bool(short_phrase_filter),
            'min_phrase_seconds': min_phrase_seconds,
            'max_phrase_notes': max_phrase_notes,
            'dynamic_event_weight': dynamic_event_weight,
            'tempo_event_weight': tempo_event_weight,
            'tempo_text_event_weight': tempo_text_event_weight,
            'key_event_weight': key_event_weight,
            'time_event_weight': time_event_weight,
            'reject_rest_boundaries': bool(reject_rest_boundaries),
            'reject_outgoing_ties': bool(reject_outgoing_ties),
            'phrase_shape_thresholds': phrase_shape_thresholds_used,
            'cross_rhythm_window_qn': cross_rhythm_window_qn,
            'cross_rhythm_similarity_threshold': cross_rhythm_similarity_threshold,
            'cross_rhythm_max_shift_qn': cross_rhythm_max_shift_qn,
        },
    }

    result['cross_support_attribution'] = cross_support_attribution

    cache_path = os.path.join(output_dir, 'result.pkl')
    save_result(result, cache_path)
    print(f"       Cache:       {cache_path}")

    return result


# =============================================================================
# Result persistence
# =============================================================================

def save_result(result, path):
    """
    Save a result dict to a pickle file.

    Strips music21-specific fields that don't pickle cleanly:
      - 'score': the music21 Score object. We save 'input_path' instead;
        callers that need the score can re-parse from there.
      - 'element' field inside each note dict in notes_per_part: these
        are music21 Note objects.

    The cached result is sufficient for explain(); it is NOT sufficient
    for re-running breath mark annotation (which needs the score). For
    that, re-run run_sectioning.

    Returns the path written.
    """
    # Build a shallow-cleaned copy.
    cacheable = {k: v for k, v in result.items() if k != 'score'}

    # Strip 'element' from notes_per_part.
    if 'notes_per_part' in cacheable:
        notes_clean = []
        for notes_list in cacheable['notes_per_part']:
            stripped = [
                {k: v for k, v in n.items() if k != 'element'}
                for n in notes_list
            ]
            notes_clean.append(stripped)
        cacheable['notes_per_part'] = notes_clean

    with open(path, 'wb') as f:
        pickle.dump(cacheable, f)
    return path


def load_result(path):
    """
    Load a result dict from a pickle file produced by save_result.

    The 'score' field is NOT restored — explain() doesn't need it. If
    you need the score, parse it from result['input_path'] using
    music21.converter.parse().
    """
    with open(path, 'rb') as f:
        return pickle.load(f)


# =============================================================================
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

    NEW IN v2.5: This function no longer requires result['score']. It
    reads measure_offsets and notes directly from the result dict, so it
    works with cached/pickled results from save_result/load_result.
    """
    n_parts = len(result['part_names'])
    if part_idx < 0 or part_idx >= n_parts:
        print(f"part_idx {part_idx} out of range [0, {n_parts-1}]")
        return

    part_name = result['part_names'][part_idx]
    is_tacet = result['is_tacet'][part_idx]
    if is_tacet:
        print(f"Part {part_idx} ({part_name}) is tacet — no signal computed.")
        return

    measure_offsets_list = result.get('measure_offsets', [])

    # Resolve time_qn from measure/beat if needed.
    if time_qn is None:
        if measure is None:
            print("Must provide either time_qn or measure.")
            return
        m_off = None
        for off, num in measure_offsets_list:
            if num == measure:
                m_off = off
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

    sig = result['per_part_signals'][part_idx]
    if len(sig) == 6:
        B_i, chroma_norm, rhythm_norm, lbdm_norm, cross_norm, B_raw = sig
    else:
        B_i, chroma_norm, lbdm_norm, B_raw = sig
        rhythm_norm = np.zeros_like(B_i)
        cross_norm = np.zeros_like(B_i)
    si = result['slur_info'][part_idx]
    hi = result['hairpin_info'][part_idx]
    ei = result['structural_info'][part_idx]

    # Compute the formula breakdown explicitly.
    alpha_chroma = params.get('alpha_chroma', params.get('alpha', 0.5))
    alpha_rhythm = params.get('alpha_rhythm', 0.0)
    beta_lbdm = params.get('beta_lbdm', params.get('beta', 0.5))
    eta_cross_rhythm = params.get('eta_cross_rhythm', 0.0)
    delta = params['delta']
    slur_delta = params.get('slur_delta', 1.0)
    tuplet_delta = params.get('tuplet_delta', 1.0)
    gamma = params['gamma']
    zeta = params['zeta']

    chroma_v = float(chroma_norm[idx])
    rhythm_v = float(rhythm_norm[idx])
    lbdm_v = float(lbdm_norm[idx])
    cross_v = float(cross_norm[idx])
    B_raw_v = float(B_raw[idx])
    in_slur = float(si['in_slur_interior'][idx])
    in_hp = float(hi['in_hairpin'][idx])
    in_tie_like = float(si.get('in_tie_like', np.zeros_like(time_grid))[idx])
    nti = result.get('natural_tie_info', [{} for _ in result['part_names']])[part_idx]
    in_natural_tie = float(nti.get('in_natural_tie', np.zeros_like(time_grid))[idx])
    ti = result.get('tuplet_info', [{} for _ in result['part_names']])[part_idx]
    in_tuplet = float(ti.get('in_tuplet', np.zeros_like(time_grid))[idx])
    in_marker = max(in_slur, in_hp, in_tuplet, in_tie_like, in_natural_tie)
    slur_bump_v = float(si['endpoint_bumps'][idx])
    struct_bump_v = float(ei['bumps'][idx])
    B_i_v = float(B_i[idx])

    # Locate measure/beat from the cached measure_offsets.
    m_num, m_beat = None, None
    if measure_offsets_list:
        candidate = measure_offsets_list[0]
        for mo in measure_offsets_list:
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
    print(f"  alpha_chroma * chroma SSM: {alpha_chroma:.2f} * {chroma_v:.3f} = "
          f"{alpha_chroma*chroma_v:.3f}")
    print(f"  alpha_rhythm * rhythm SSM: {alpha_rhythm:.2f} * {rhythm_v:.3f} = "
          f"{alpha_rhythm*rhythm_v:.3f}")
    print(f"  beta_lbdm * LBDM:          {beta_lbdm:.2f} * {lbdm_v:.3f} = "
          f"{beta_lbdm*lbdm_v:.3f}")
    print(f"  ---")
    print(f"  B_raw:                                          "
          f"{B_raw_v:.3f}")
    print()

    print("Suppression context:")
    print(f"  in_slur_interior:         {int(in_slur)}")
    print(f"  in_hairpin:               {int(in_hp)}")
    print(f"  in_tie_like:              {int(in_tie_like)}")
    print(f"  in_natural_tie:           {int(in_natural_tie)}")
    print(f"  in_tuplet_span:           {int(in_tuplet)}")
    print(f"  in_marker (OR):           {in_marker:.0f}")
    if in_slur > 0:
        print(f"  -> slur continuation penalty: multiplier = "
              f"{1-slur_delta*in_slur:.2f}")
    if in_tuplet > 0:
        print(f"  -> tuplet continuation penalty: multiplier = "
              f"{1-tuplet_delta*in_tuplet:.2f}")
    if in_hp > 0:
        print(f"  -> hairpin attenuation: delta*in_hairpin = "
              f"{delta*in_hp:.2f}, multiplier = {1-delta*in_hp:.2f}")
    if in_tie_like > 0:
        print("  -> hard tie-like no-breath veto applies")
    if in_natural_tie > 0:
        print("  -> hard natural-tie no-breath veto applies")
    print()

    print("Boost context:")
    print(f"  slur_endpoint_bump:       {slur_bump_v:.3f}")
    print(f"  structural_bump:          {struct_bump_v:.3f}")
    print(f"  cross_rhythm_support:     {cross_v:.3f}")
    boost_total = gamma * slur_bump_v + zeta * struct_bump_v + eta_cross_rhythm * cross_v
    print(f"  total boost (gamma*slur + zeta*struct + eta*cross):  "
          f"{gamma:.2f}*{slur_bump_v:.3f} + {zeta:.2f}*{struct_bump_v:.3f} + "
          f"{eta_cross_rhythm:.2f}*{cross_v:.3f} = {boost_total:.3f}")
    print()

    print("Final B_i at this point:")
    if in_tie_like > 0 or in_natural_tie > 0:
        effective_mult = 0.0
    else:
        effective_mult = (
            (1.0 - delta * in_hp) *
            (1.0 - slur_delta * in_slur) *
            (1.0 - tuplet_delta * in_tuplet)
        )
    print(f"  (B_raw + boost) * effective continuation multiplier")
    print(f"  = ({B_raw_v:.3f} + {boost_total:.3f}) * {effective_mult:.2f}")
    print(f"  = {B_i_v:.3f}")
    print()

    candidate_diag = result.get('per_part_candidate_diagnostics', [{} for _ in result['part_names']])[part_idx]
    candidate_signal = candidate_diag.get('candidate_signal')
    selection_score = candidate_diag.get('selection_score')
    acceptance_score = candidate_diag.get('acceptance_score')
    note_anchor_score = candidate_diag.get('note_anchor_score')
    continuation_penalty = candidate_diag.get('continuation_penalty')
    forbidden_mask = candidate_diag.get('forbidden_mask')
    if candidate_signal is not None:
        print("Candidate-selection values at this point:")
        print(f"  candidate_signal:        {float(candidate_signal[idx]):.3f}")
        print(f"  selection_score:         {float(selection_score[idx]):.3f}")
        print(f"  acceptance_score:        {float(acceptance_score[idx]):.3f}")
        print(f"  note_anchor_score:       {float(note_anchor_score[idx]):.3f}")
        print(f"  continuation_penalty:    {float(continuation_penalty[idx]):.3f}")
        print(f"  forbidden_mask:          {int(float(forbidden_mask[idx]) > 0)}")
        rep_score = candidate_diag.get('repetition_score')
        rep_lag = candidate_diag.get('repetition_best_lag_qn')
        if rep_score is not None:
            dr = params.get('delta_repetition', 0.0)
            print(f"  repetition_score R:      {float(rep_score[idx]):.3f}"
                  f"  (delta_repetition={dr}"
                  f"{'' if dr > 0 else ' -- masking OFF'})")
            if rep_lag is not None and float(rep_score[idx]) > 1e-6:
                print(f"    local rhythm matches material "
                      f"{float(rep_lag[idx]):.2f} qn away on both sides")
        print()

        cand_height = params.get('candidate_height', params.get('peak_height', 0.30))
        cand_peaks, _ = find_peaks(candidate_signal, height=cand_height)
        nearby_cands = [p for p in cand_peaks if abs(time_grid[p] - actual_t) <= window_qn / 2]
        if nearby_cands:
            print("Candidate peaks within window:")
            for p in nearby_cands:
                rep_str = ""
                if rep_score is not None:
                    rep_str = f"  R={float(rep_score[p]):.2f}"
                print(f"  t={time_grid[p]:.2f}  cand={candidate_signal[p]:.3f}  "
                      f"sel={selection_score[p]:.3f}  acc={acceptance_score[p]:.3f}  "
                      f"B_i={B_i[p]:.3f}  forbidden={int(float(forbidden_mask[p]) > 0)}"
                      f"{rep_str}")
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

    target_records = result.get('boundary_target_info', [[] for _ in result['part_names']])[part_idx]
    nearby_targets = [r for r in target_records
                      if abs(float(r.get('boundary_time', -9999)) - actual_t) <= window_qn / 2]
    if nearby_targets:
        print("Resolved breath targets within window:")
        for r in nearby_targets:
            status = "kept" if r.get('kept') else f"rejected:{r.get('reject_reason')}"
            print(f"  bt={r.get('boundary_time'):.2f}  {status}  "
                  f"target_t={r.get('target_offset')} pitch={r.get('target_pitch')} "
                  f"reason={r.get('target_reason')} rest={r.get('boundary_lies_in_rest')} "
                  f"tie={r.get('target_tie_type')}")
        print()

    print(sep)


def main():
    parser = argparse.ArgumentParser(
        description="V2.9.1 sectioning pipeline with chroma/rhythm self-SSM, "
                    "cross-rhythm support, long-mark [start,end) "
                    "suppression, and candidate selection."
    )
    parser.add_argument('input', help='Path to .mxl or .musicxml file')
    parser.add_argument('-o', '--output_dir', default='./output')
    parser.add_argument('--division', type=int, default=8)
    parser.add_argument('--kernel_size', type=int, default=64)
    parser.add_argument('--alpha_chroma', type=float, default=0.20)
    parser.add_argument('--alpha_rhythm', type=float, default=0.35)
    parser.add_argument('--beta_lbdm', type=float, default=0.45)
    parser.add_argument('--eta_cross_rhythm', type=float, default=0.20)
    parser.add_argument('--delta', type=float, default=0.5,
                        help='Hairpin attenuation strength (0..1)')
    parser.add_argument('--slur_delta', type=float, default=0.70,
                        help='Slur continuation attenuation strength (0..1)')
    parser.add_argument('--tuplet_delta', type=float, default=0.80,
                        help='Tuplet continuation attenuation strength (0..1)')
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
    parser.add_argument('--candidate_height', type=float, default=0.22)
    parser.add_argument('--peak_distance_qn', type=float, default=2.5)
    parser.add_argument('--selection_lbdm_weight', type=float, default=0.30)
    parser.add_argument('--selection_long_weight', type=float, default=0.30)
    parser.add_argument('--selection_gap_weight', type=float, default=0.20)
    parser.add_argument('--selection_cross_rhythm_weight', type=float, default=0.25)
    parser.add_argument('--selection_slur_penalty', type=float, default=0.35)
    parser.add_argument('--selection_hairpin_penalty', type=float, default=0.25)
    parser.add_argument('--selection_tuplet_penalty', type=float, default=0.45)
    parser.add_argument('--note_candidate_weight', type=float, default=0.65)
    parser.add_argument('--selection_accept_height', type=float, default=0.30)
    parser.add_argument('--disable_short_phrase_filter', action='store_true',
                        help='Disable v2.9 tempo-aware tiny-phrase filter')
    parser.add_argument('--min_phrase_seconds', type=float, default=1.25)
    parser.add_argument('--max_phrase_notes', type=int, default=1)
    parser.add_argument('--dynamic_event_weight', type=float, default=0.80)
    parser.add_argument('--tempo_event_weight', type=float, default=1.00)
    parser.add_argument('--tempo_text_event_weight', type=float, default=1.00)
    parser.add_argument('--key_event_weight', type=float, default=0.80)
    parser.add_argument('--time_event_weight', type=float, default=1.00)
    parser.add_argument('--allow_rest_boundaries', action='store_true',
                        help='Do not reject selected boundaries that land inside rests')
    parser.add_argument('--allow_outgoing_tie_targets', action='store_true',
                        help='Do not reject breath targets with tie=start/continue')
    parser.add_argument('--cross_rhythm_window_qn', type=float, default=4.0)
    parser.add_argument('--cross_rhythm_similarity_threshold', type=float, default=0.85)
    parser.add_argument('--cross_rhythm_max_shift_qn', type=float, default=0.5)
    parser.add_argument('--delta_repetition', type=float, default=0.0,
                        help='Strength of rhythm-repetition masking, 0=off. '
                             'Masks rhythm novelty (at source) and '
                             'following-gap evidence by (1 - delta*R).')
    parser.add_argument('--repetition_lag_min_qn', type=float, default=0.5,
                        help='Minimum repetition period searched (qn)')
    parser.add_argument('--repetition_lag_max_qn', type=float, default=3.0,
                        help='Maximum repetition period searched (qn). '
                             'Musically: the largest period that counts as '
                             'figuration rather than phrase repetition.')
    parser.add_argument('--repetition_window_qn', type=float, default=1.0,
                        help='Half-window (qn) for local context comparison')
    parser.add_argument('--selection_repetition_penalty', type=float, default=0.0,
                        help='Continuation penalty from rhythm repetition R (tuplet-style; 0=off)')
    parser.add_argument('--lbdm_polyphony_mode', choices=['top','bass','outer'], default='top')
    parser.add_argument('--chroma_kernel', choices=['exact', 'interval'],
                        default='exact',
                        help='Chroma SSM similarity: exact pitch-class '
                             'match (default) or interval-class kernel '
                             '(v2.10-B)')
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
        alpha_chroma=args.alpha_chroma,
        alpha_rhythm=args.alpha_rhythm,
        beta_lbdm=args.beta_lbdm,
        eta_cross_rhythm=args.eta_cross_rhythm,
        delta=args.delta,
        slur_delta=args.slur_delta,
        tuplet_delta=args.tuplet_delta,
        gamma=args.gamma, zeta=args.zeta,
        w_pitch=args.w_pitch, w_ioi=args.w_ioi, w_rest=args.w_rest,
        lbdm_smoothing_qn=args.lbdm_smooth_qn,
        slur_endpoint_sigma_qn=args.slur_endpoint_sigma_qn,
        structural_sigma_qn=args.structural_sigma_qn,
        peak_height=args.peak_height,
        candidate_height=args.candidate_height,
        peak_distance_qn=args.peak_distance_qn,
        selection_lbdm_weight=args.selection_lbdm_weight,
        selection_long_weight=args.selection_long_weight,
        selection_gap_weight=args.selection_gap_weight,
        selection_cross_rhythm_weight=args.selection_cross_rhythm_weight,
        selection_slur_penalty=args.selection_slur_penalty,
        selection_hairpin_penalty=args.selection_hairpin_penalty,
        selection_tuplet_penalty=args.selection_tuplet_penalty,
        note_candidate_weight=args.note_candidate_weight,
        selection_accept_height=args.selection_accept_height,
        short_phrase_filter=not args.disable_short_phrase_filter,
        min_phrase_seconds=args.min_phrase_seconds,
        max_phrase_notes=args.max_phrase_notes,
        dynamic_event_weight=args.dynamic_event_weight,
        tempo_event_weight=args.tempo_event_weight,
        tempo_text_event_weight=args.tempo_text_event_weight,
        key_event_weight=args.key_event_weight,
        time_event_weight=args.time_event_weight,
        reject_rest_boundaries=not args.allow_rest_boundaries,
        reject_outgoing_ties=not args.allow_outgoing_tie_targets,
        cross_rhythm_window_qn=args.cross_rhythm_window_qn,
        cross_rhythm_similarity_threshold=args.cross_rhythm_similarity_threshold,
        cross_rhythm_max_shift_qn=args.cross_rhythm_max_shift_qn,
        delta_repetition=args.delta_repetition,
        repetition_lag_min_qn=args.repetition_lag_min_qn,
        repetition_lag_max_qn=args.repetition_lag_max_qn,
        repetition_window_qn=args.repetition_window_qn,
        selection_repetition_penalty=args.selection_repetition_penalty,
        lbdm_polyphony_mode=args.lbdm_polyphony_mode,
        chroma_kernel=args.chroma_kernel,
        convention=args.convention,
        tacet_threshold=args.tacet_threshold,
        breath_color=args.breath_color,
    )


if __name__ == '__main__':
    main()
