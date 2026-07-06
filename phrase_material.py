#!/usr/bin/env python
"""
phrase_material.py

Phrase-segment shape and material report for the v2.9.x sectioning pipeline.
This module is the v2.10-A layer described in Robert's v2.10 plan.

Design intent:
    The module is intentionally PASSIVE.  It consumes the boundary times and
    per-part note lists that run_sectioning() already produces, and emits a
    per-segment record of how much musical material the segment actually
    contains, what shape it has, and which conservative quality flags fire.

    The flags are advisory.  Removal decisions stay in the existing cleanup
    pass (postprocess_short_phrases), which can read these flags later.  No
    removal logic lives here.

Per-segment record:
    start_qn, end_qn
    elapsed_qn, elapsed_seconds
    sounding_qn, sounding_seconds         (note-overlap only, no rests)
    rest_qn, rest_ratio
    note_count                             (notes whose ONSET is in segment)
    attack_count                           (distinct attack offsets; matters
                                            once polyphonic event grouping
                                            lands in v2.10-C)
    unique_pitch_count
    pitch_min, pitch_max, pitch_range_semitones
    mean_attack_duration_qn, max_attack_duration_qn
    flags                                  (list of strings)
    flag_details                           (dict: flag -> reason string)

Flags emitted:
    too_little_material         low sounding seconds AND few onsets
    too_long_to_breathe         elapsed seconds beyond a generous ceiling
    repeated_long_note_fragment 2-N long notes with narrow pitch variety

Default thresholds are deliberately permissive: a segment must look
quite degenerate before a flag fires.  Tighten per piece if needed.
"""

import json

import numpy as np


# =============================================================================
# Configuration
# =============================================================================

def default_phrase_shape_thresholds():
    """Default flag thresholds.

    Conservative on purpose.  These should not flag a real phrase that
    happens to be short or low in note count.  Override per-piece via the
    `thresholds` parameter on compute_phrase_shape / compute_phrase_material_report.
    """
    return {
        # too_little_material
        'min_phrase_seconds': 1.25,
        'max_thin_phrase_notes': 1,

        # too_long_to_breathe
        'max_phrase_seconds': 12.0,

        # repeated_long_note_fragment
        'repeated_long_min_attacks': 2,
        'repeated_long_max_attacks': 4,
        'repeated_long_min_attack_duration_qn': 2.0,
        'repeated_long_max_unique_pitches': 2,
    }


# =============================================================================
# Tempo-map integration (local copy, keeps this module self-contained)
# =============================================================================

def _qn_span_to_seconds(start_qn, end_qn, tempo_segments):
    """Integrate a quarter-note span through a piecewise-constant tempo map.

    `tempo_segments` is a list of (offset_qn, bpm).  Matches the semantics
    of sectioning_v2_9_1.qn_span_to_seconds; included here so phrase_material
    has no import dependency on the sectioning module.
    """
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


# =============================================================================
# Per-segment shape
# =============================================================================

def compute_phrase_shape(notes_list, start_qn, end_qn, tempo_segments,
                          thresholds=None,
                          include_start_boundary=False):
    """Compute the full shape/material record for one segment.

    `notes_list` is the per-part note dict list that the sectioning pipeline
    already produces (post-tie-merge).  Each entry is expected to have at
    least 'offset', 'duration', and 'pitch'; missing fields default safely.

    Segment convention:
        Default (include_start_boundary=False): half-open on the left,
        closed on the right -- (start, end].  A note onset at exactly
        start_qn belongs to the PREVIOUS segment, an onset at exactly
        end_qn belongs to THIS segment.  This matches v2.9.1's existing
        compute_phrase_material convention, which is the right thing for
        every segment whose left edge is a previously-selected boundary
        (those boundaries fall on the breath-target note of the previous
        phrase).

        Set include_start_boundary=True for the FIRST segment of a piece,
        so that a pickup note at offset 0 is counted as belonging to the
        first phrase rather than being silently dropped.  The report
        builder (compute_phrase_material_report) handles this automatically.
    """
    if thresholds is None:
        thresholds = default_phrase_shape_thresholds()

    start_qn = float(start_qn)
    end_qn = float(end_qn)
    elapsed_qn = max(end_qn - start_qn, 0.0)
    elapsed_seconds = _qn_span_to_seconds(start_qn, end_qn, tempo_segments)

    eps = 0.01
    in_segment_attacks = []
    sounding_qn = 0.0
    sounding_seconds = 0.0

    for note in notes_list:
        off = float(note.get('offset', 0.0))
        dur = float(note.get('duration', 0.0))

        # Onset-in-segment counts as an "attack"
        if include_start_boundary:
            onset_in_segment = (start_qn - eps <= off <= end_qn + eps)
        else:
            onset_in_segment = (start_qn + eps < off <= end_qn + eps)
        if onset_in_segment:
            in_segment_attacks.append(note)

        # Sounding overlap: clip the note span to the segment.
        # A note that started before this segment can still contribute
        # sounding time here while its sustain bleeds in.
        n_start = max(start_qn, off)
        n_end = min(end_qn, off + dur)
        if n_end > n_start:
            sounding_qn += n_end - n_start
            sounding_seconds += _qn_span_to_seconds(
                n_start, n_end, tempo_segments
            )

    note_count = len(in_segment_attacks)

    # attack_count: distinct onset offsets among in-segment notes.
    # Equals note_count for the current monophonic-after-top-merge LBDM
    # representation; will diverge from it once v2.10-C lands and same-offset
    # events are grouped.
    attack_offsets = sorted({
        round(float(n.get('offset', 0.0)), 6)
        for n in in_segment_attacks
    })
    attack_count = len(attack_offsets)

    pitches = [
        int(n['pitch']) for n in in_segment_attacks
        if 'pitch' in n and n['pitch'] is not None
    ]
    unique_pitch_count = len(set(pitches))
    pitch_min = min(pitches) if pitches else None
    pitch_max = max(pitches) if pitches else None
    pitch_range = (pitch_max - pitch_min) if pitches else 0

    durations = [float(n.get('duration', 0.0)) for n in in_segment_attacks]
    mean_attack_duration_qn = float(np.mean(durations)) if durations else 0.0
    max_attack_duration_qn = float(np.max(durations)) if durations else 0.0

    rest_qn = max(elapsed_qn - sounding_qn, 0.0)
    rest_ratio = (rest_qn / elapsed_qn) if elapsed_qn > 0 else 0.0

    flags = []
    flag_details = {}

    if (sounding_seconds < thresholds['min_phrase_seconds']
            and note_count <= thresholds['max_thin_phrase_notes']):
        flags.append('too_little_material')
        flag_details['too_little_material'] = (
            f"sounding_seconds={sounding_seconds:.2f}"
            f"<{thresholds['min_phrase_seconds']:.2f}, "
            f"note_count={note_count}"
            f"<={thresholds['max_thin_phrase_notes']}"
        )

    if elapsed_seconds > thresholds['max_phrase_seconds']:
        flags.append('too_long_to_breathe')
        flag_details['too_long_to_breathe'] = (
            f"elapsed_seconds={elapsed_seconds:.2f}"
            f">{thresholds['max_phrase_seconds']:.2f}"
        )

    if (thresholds['repeated_long_min_attacks']
            <= attack_count
            <= thresholds['repeated_long_max_attacks']
            and mean_attack_duration_qn
                >= thresholds['repeated_long_min_attack_duration_qn']
            and unique_pitch_count
                <= thresholds['repeated_long_max_unique_pitches']):
        flags.append('repeated_long_note_fragment')
        flag_details['repeated_long_note_fragment'] = (
            f"attacks={attack_count}"
            f" in [{thresholds['repeated_long_min_attacks']},"
            f"{thresholds['repeated_long_max_attacks']}], "
            f"mean_dur_qn={mean_attack_duration_qn:.2f}"
            f">={thresholds['repeated_long_min_attack_duration_qn']:.2f}, "
            f"unique_pitches={unique_pitch_count}"
            f"<={thresholds['repeated_long_max_unique_pitches']}"
        )

    return {
        'start_qn': start_qn,
        'end_qn': end_qn,
        'elapsed_qn': elapsed_qn,
        'elapsed_seconds': elapsed_seconds,
        'sounding_qn': sounding_qn,
        'sounding_seconds': sounding_seconds,
        'rest_qn': rest_qn,
        'rest_ratio': rest_ratio,
        'note_count': int(note_count),
        'attack_count': int(attack_count),
        'unique_pitch_count': int(unique_pitch_count),
        'pitch_min': pitch_min,
        'pitch_max': pitch_max,
        'pitch_range_semitones': int(pitch_range),
        'mean_attack_duration_qn': mean_attack_duration_qn,
        'max_attack_duration_qn': max_attack_duration_qn,
        'flags': flags,
        'flag_details': flag_details,
    }


# =============================================================================
# Per-part report (one entry per segment between boundaries)
# =============================================================================

def compute_phrase_material_report(notes_list, boundaries, tempo_segments,
                                    start_time_qn=0.0,
                                    end_time_qn=None,
                                    thresholds=None):
    """Build the per-segment report for one part.

    Segments are formed as:
        (start_time_qn, b1], (b1, b2], ..., (bn, end_time_qn]

    so the report length is len(boundaries) + 1 when end_time_qn is given.

    If end_time_qn is None and there is at least one boundary, the trailing
    open segment is omitted; pass end_time_qn=score.duration.quarterLength
    to include it.
    """
    if thresholds is None:
        thresholds = default_phrase_shape_thresholds()

    bdys = sorted(float(b) for b in boundaries)
    segment_edges = [float(start_time_qn)] + bdys
    if end_time_qn is not None:
        segment_edges.append(float(end_time_qn))

    n_edges = len(segment_edges)
    report = []
    for k in range(n_edges - 1):
        s = segment_edges[k]
        e = segment_edges[k + 1]
        shape = compute_phrase_shape(
            notes_list, s, e, tempo_segments,
            thresholds=thresholds,
            include_start_boundary=(k == 0),
        )
        shape['segment_index'] = k
        shape['left_boundary_qn'] = (s if k > 0 else None)
        shape['right_boundary_qn'] = (e if k < n_edges - 2 else None)
        report.append(shape)

    return report


# =============================================================================
# Reporting helpers
# =============================================================================

def summarize_phrase_material(report, max_lines=None):
    """Human-readable one-line-per-segment summary.

    Useful for logs and quick visual inspection alongside the diagnostics
    plot.  Returned as a single string with newline separators.
    """
    lines = []
    for shape in report:
        flags = ','.join(shape['flags']) if shape['flags'] else '-'
        line = (
            f"seg {shape['segment_index']:3d}  "
            f"qn=({shape['start_qn']:6.2f},{shape['end_qn']:6.2f}]  "
            f"sound={shape['sounding_seconds']:5.2f}s "
            f"({shape['sounding_qn']:5.2f}qn)  "
            f"rest_ratio={shape['rest_ratio']:.2f}  "
            f"attacks={shape['attack_count']:2d}  "
            f"upitch={shape['unique_pitch_count']:2d}  "
            f"flags=[{flags}]"
        )
        lines.append(line)
        if max_lines is not None and len(lines) >= max_lines:
            break
    return '\n'.join(lines)


def write_phrase_material_summary(per_part_reports, part_names, is_tacet,
                                   score, output_path,
                                   thresholds=None,
                                   include_flag_details=True):
    """Write a JSON summary of the phrase-material reports.

    Mirrors the structure of boundaries.json so the two files can be
    cross-referenced segment-by-segment.  `score` is the music21 Score,
    used only to attach measure/beat to segment edges; if it is None or
    walking measures fails, those fields are omitted.
    """
    measure_offsets = []
    try:
        import music21 as m21
        if score is not None and len(score.parts) > 0:
            for measure in score.parts[0].getElementsByClass(m21.stream.Measure):
                measure_offsets.append((float(measure.offset), measure.number))
    except Exception:
        measure_offsets = []

    def offset_to_measure_beat(offset):
        if not measure_offsets or offset is None:
            return None, None
        candidate = measure_offsets[0]
        for mo in measure_offsets:
            if mo[0] <= offset:
                candidate = mo
            else:
                break
        m_offset, m_number = candidate
        return m_number, (float(offset) - m_offset + 1.0)

    if thresholds is None:
        thresholds = default_phrase_shape_thresholds()

    summary = {
        'thresholds': thresholds,
        'per_part': [],
    }

    for i, report in enumerate(per_part_reports):
        if i < len(is_tacet) and is_tacet[i]:
            continue
        name = part_names[i] if i < len(part_names) else f'part_{i}'
        n_flagged = sum(1 for r in report if r['flags'])
        entry = {
            'index': i,
            'name': name,
            'num_segments': len(report),
            'num_flagged_segments': n_flagged,
            'segments': [],
        }
        for shape in report:
            seg = dict(shape)
            m_s, b_s = offset_to_measure_beat(shape['start_qn'])
            m_e, b_e = offset_to_measure_beat(shape['end_qn'])
            seg['start_measure'] = m_s
            seg['start_beat'] = b_s
            seg['end_measure'] = m_e
            seg['end_beat'] = b_e
            if not include_flag_details:
                seg.pop('flag_details', None)
            entry['segments'].append(seg)
        summary['per_part'].append(entry)

    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2, default=float)

    return summary
