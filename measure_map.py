#!/usr/bin/env python3
"""
measure_map.py -- real measure map for the audit tools. Meter-agnostic.

v2 (2026-07-10)
    Fallback REMOVED. v1 kept a 4/4 formula for when no score was loaded;
    that formula silently produced wrong TARGETS (not just wrong labels)
    on any non-4/4 score, so the tools now hard-require a map. There is
    no assumption about time signature anywhere in the audit toolchain.
    Also new: .mxl (zipped) input, and verify_against_boundaries().

v1 (2026-07-10)
    Created after the phantom "m.97 b3" incident: the tools assumed 4/4
    throughout while Liz's real m.93 is 18/4 (94 measures, 390 qn). The
    PIPELINE was always right (music21 measure numbers in boundaries.json);
    only the session tools' display math was wrong.

SELF-VERIFICATION
    boundaries.json records the pipeline's own (measure, beat) for every
    boundary, derived from music21. verify_against_boundaries() round-trips
    each one through qn_of() and requires it to reproduce the boundary's
    time_quarter_notes -- this checks the map against an independent
    implementation at every boundary on every run. If a score has repeats,
    pickup numbering, or anything else this parser gets wrong, the tools
    fail loudly instead of scoring against phantom positions.

KNOWN LIMIT
    Measures are read in document order; written-out repeats are fine, but
    a score whose pipeline offsets come from EXPANDED repeats would
    diverge. verify_against_boundaries() catches exactly that case.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

MAP = None    # list of (number:int, start_qn:float, length_qn:float)
SOURCE = None


class MeasureMapError(RuntimeError):
    pass


def _root_of(path: str):
    if path.lower().endswith('.mxl'):
        with zipfile.ZipFile(path) as z:
            try:
                container = ET.fromstring(z.read('META-INF/container.xml'))
                inner = container.find('.//rootfile').get('full-path')
            except Exception:
                cands = [n for n in z.namelist()
                         if n.lower().endswith(('.xml', '.musicxml'))
                         and not n.startswith('META-INF')]
                if not cands:
                    raise MeasureMapError(f"no score found inside {path}")
                inner = cands[0]
            return ET.fromstring(z.read(inner))
    return ET.parse(path).getroot()


def load(path: str):
    """Build the map from a MusicXML (.musicxml/.xml) or .mxl file."""
    global MAP, SOURCE
    root = _root_of(path)
    if root.tag != 'score-partwise':
        raise MeasureMapError(
            f"{path}: expected score-partwise, got '{root.tag}' "
            "(timewise scores are not supported)")
    parts = root.findall('part')
    if not parts:
        raise MeasureMapError(f"{path}: no parts")

    div = 1.0
    cum = 0.0
    rows = []
    for meas in parts[0].findall('measure'):
        d = meas.find('attributes/divisions')
        if d is not None:
            div = float(d.text)
        length = 0.0
        cursor = 0.0
        for el in meas:
            if el.tag == 'note' and el.find('chord') is None:
                dur = el.find('duration')
                if dur is not None:
                    cursor += float(dur.text) / div
            elif el.tag == 'forward':
                cursor += float(el.find('duration').text) / div
            elif el.tag == 'backup':
                cursor -= float(el.find('duration').text) / div
            length = max(length, cursor)
        if length <= 0:
            raise MeasureMapError(
                f"{path}: measure {meas.get('number')} has zero length in "
                "part 0 -- cannot build a map from it")
        try:
            num = int(meas.get('number'))
        except (TypeError, ValueError):
            raise MeasureMapError(
                f"{path}: non-integer measure number "
                f"{meas.get('number')!r} (alternate endings?)")
        rows.append((num, cum, length))
        cum += length
    MAP = rows
    SOURCE = path
    return rows


def _require():
    if not MAP:
        raise MeasureMapError(
            "no measure map loaded -- pass the score with --musicxml. The "
            "audit tools make no assumption about time signature, so "
            "measure/beat cannot be resolved without the score.")


def locate(qn: float, eps: float = 1e-6):
    """qn -> (measure_number, beat); beat == 'end' at a barline instant."""
    _require()
    for num, start, length in MAP:
        if abs(qn - (start + length)) <= eps:
            return num, 'end'
        if start - eps <= qn < start + length - eps:
            return num, qn - start + 1.0
    raise MeasureMapError(
        f"qn {qn:g} lies outside the score "
        f"(0 .. {MAP[-1][1] + MAP[-1][2]:g})")


def qn_of(measure: int, beat) -> float:
    """(measure, beat) -> qn; beat may be 'end' for the barline instant."""
    _require()
    for num, start, length in MAP:
        if num == int(measure):
            if beat == 'end':
                return start + length
            b = float(beat)
            if b < 1.0 or b > length + 1.0 + 1e-6:
                raise MeasureMapError(
                    f"beat {b:g} is outside measure {measure} "
                    f"(length {length:g} qn)")
            return start + b - 1.0
    raise MeasureMapError(
        f"measure {measure} not in score "
        f"(map covers {MAP[0][0]}..{MAP[-1][0]})")


def verify_against_boundaries(bdoc, eps: float = 1e-3):
    """Round-trip the pipeline's own (measure, beat) labels through this
    map; every boundary must reproduce its time_quarter_notes."""
    _require()
    bad = []
    n = 0
    for entry in bdoc.get('per_part', []):
        for b in entry.get('boundaries', []):
            m, beat = b.get('measure'), b.get('beat')
            if m is None or beat is None:
                continue
            n += 1
            try:
                got = qn_of(int(m), float(beat))
            except MeasureMapError as e:
                bad.append((entry.get('index'), m, beat,
                            b['time_quarter_notes'], str(e)))
                continue
            if abs(got - float(b['time_quarter_notes'])) > eps:
                bad.append((entry.get('index'), m, beat,
                            b['time_quarter_notes'], f"map says qn {got:g}"))
    if bad:
        lines = "\n".join(
            f"  part {p} pipeline says m.{m} b{bt} = qn {q}; {msg}"
            for p, m, bt, q, msg in bad[:10])
        raise MeasureMapError(
            f"measure map disagrees with the pipeline at {len(bad)}/{n} "
            f"boundaries -- REFUSING to score against it "
            f"(repeats? pickup numbering? wrong score file?):\n{lines}")
    return n
