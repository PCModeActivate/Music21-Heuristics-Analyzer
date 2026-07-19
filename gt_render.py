#!/usr/bin/env python3
"""
gt_render.py  (v1, 2026-07-15)

Render a compiled GT file into the score as colored breath marks so
the GT itself can be eye-judged in MuseScore.

Colors:
  GREEN  #2ca02c  required, anchored at a note release (comma after it)
  BLUE   #1f77b4  kept, anchored at a note release
  ORANGE #ff7f0e  point could NOT be release-anchored (entry-onset,
                  stale onset value, or no note there) -- attached to
                  the starting/containing note instead. These are the
                  re-judge list; each is printed in the report.

Works on either the clean input score or a sectioned.musicxml
(existing breath marks are stripped first by default).
Part indexing convention: score-parts in order, one index per staff
(Harp staff 1 and staff 2 are separate indices), matching
boundaries.json.

Usage:
  python gt_render.py gt_liz_E0b_draft.json sectioned.musicxml \\
      -o gt_rendered.musicxml --report gt_render_report.txt
"""

import argparse
import json
import xml.etree.ElementTree as ET

TOL = 0.02
COLORS = {'required': '#2ca02c', 'kept': '#1f77b4'}
ORANGE = '#ff7f0e'


def part_note_index(part):
    """Per staff: list of (start_qn, release_qn, note_element),
    rests/grace excluded, chords collapsed to first chord note."""
    divisions, beats, beat_type = 1, 4, 4
    meas_start = 0.0
    idx = {}
    for meas in part.findall('measure'):
        att = meas.find('attributes')
        if att is not None:
            d = att.find('divisions')
            if d is not None:
                divisions = int(d.text)
            t = att.find('time')
            if t is not None:
                beats = int(t.find('beats').text)
                beat_type = int(t.find('beat-type').text)
        cursor, prev_d = 0.0, 0.0
        for el in meas:
            if el.tag == 'note':
                dur_el = el.find('duration')
                d = int(dur_el.text) / divisions if dur_el is not None else 0.0
                st_el = el.find('staff')
                staff = int(st_el.text) if st_el is not None else 1
                is_chord = el.find('chord') is not None
                is_rest = el.find('rest') is not None
                if dur_el is not None and not is_rest and not is_chord:
                    idx.setdefault(staff, []).append(
                        (meas_start + cursor, meas_start + cursor + d, el))
                if dur_el is not None and not is_chord:
                    cursor += d
                    prev_d = d
            elif el.tag == 'backup':
                cursor -= int(el.find('duration').text) / divisions
            elif el.tag == 'forward':
                cursor += int(el.find('duration').text) / divisions
        meas_start += beats * 4.0 / beat_type
    return idx


def measure_map(part):
    mm = []
    beats, beat_type, meas_start = 4, 4, 0.0
    for meas in part.findall('measure'):
        att = meas.find('attributes')
        if att is not None and att.find('time') is not None:
            t = att.find('time')
            beats = int(t.find('beats').text)
            beat_type = int(t.find('beat-type').text)
        mm.append((meas_start, int(meas.get('number'))))
        meas_start += beats * 4.0 / beat_type

    def disp(qn):
        prev = mm[0]
        for off, num in mm:
            if off > qn + 1e-6:
                break
            if abs(qn - off) <= 1e-6 and num > mm[0][1]:
                return f"m.{num - 1} end"
            prev = (off, num)
        off, num = prev
        return f"m.{num} b{qn - off + 1.0:g}"
    return disp


def strip_breaths(root):
    n = 0
    for note in root.iter('note'):
        for nots in note.findall('notations'):
            for arts in nots.findall('articulations'):
                for bm in arts.findall('breath-mark'):
                    arts.remove(bm)
                    n += 1
                if len(arts) == 0:
                    nots.remove(arts)
            if len(nots) == 0:
                note.remove(nots)
    return n


def add_breath(note_el, color):
    nots = note_el.find('notations')
    if nots is None:
        nots = ET.SubElement(note_el, 'notations')
    arts = nots.find('articulations')
    if arts is None:
        arts = ET.SubElement(nots, 'articulations')
    bm = ET.SubElement(arts, 'breath-mark')
    bm.set('color', color)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('gt_json')
    ap.add_argument('musicxml')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--report', default=None)
    ap.add_argument('--keep-existing', action='store_true',
                    help='do not strip existing breath marks')
    args = ap.parse_args()

    gt = json.load(open(args.gt_json))
    tree = ET.parse(args.musicxml)
    root = tree.getroot()

    if not args.keep_existing:
        stripped = strip_breaths(root)
    else:
        stripped = 0

    # sequential (part, staff) -> flat index, matching boundaries.json
    flat = []
    for part in root.findall('part'):
        staves = part_note_index(part)
        for staff in sorted(staves):
            flat.append((part, staff, staves[staff]))
    disp = measure_map(root.findall('part')[0])

    log = [f"gt_render: stripped {stripped} existing breath marks",
           "ORANGE (re-judge) points:", "-" * 60]
    counts = {'green': 0, 'blue': 0, 'orange': 0, 'skipped': 0}
    for p in gt['per_part']:
        i = p['index']
        if i >= len(flat):
            log.append(f"  part index {i} not in score -- skipped part")
            continue
        _, _, notes = flat[i]
        for pt in p['gt_boundaries']:
            qn = float(pt['time_quarter_notes'])
            status = pt.get('status', 'kept')
            rel_hit = next((el for (s, r, el) in notes
                            if abs(r - qn) <= TOL), None)
            if rel_hit is not None:
                add_breath(rel_hit, COLORS.get(status, ORANGE))
                counts['green' if status == 'required' else 'blue'] += 1
                continue
            alt = next((el for (s, r, el) in notes
                        if abs(s - qn) <= TOL or s < qn < r), None)
            if alt is not None:
                add_breath(alt, ORANGE)
                counts['orange'] += 1
                log.append(f"  {p['name']:<18} {disp(qn):<12} ({status}) "
                           f"not release-anchored -- comma shown on the "
                           f"note sounding there")
            else:
                counts['skipped'] += 1
                log.append(f"  {p['name']:<18} {disp(qn):<12} ({status}) "
                           f"NO NOTE at/around this instant -- not "
                           f"rendered (entry into silence?)")

    tree.write(args.output, encoding='UTF-8', xml_declaration=True)
    log.append("-" * 60)
    log.append(f"rendered: {counts['green']} required (green), "
               f"{counts['blue']} kept (blue), {counts['orange']} "
               f"orange re-judge, {counts['skipped']} unrenderable")
    text = "\n".join(log)
    print(text)
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as f:
            f.write(text + "\n")


if __name__ == '__main__':
    main()
