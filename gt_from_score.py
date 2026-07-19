#!/usr/bin/env python3
"""
gt_from_score.py  (v1, 2026-07-15)

Compile a hand-corrected score (breath marks edited in MuseScore) back
into GT files. The score IS the ground truth; this tool only transcribes
it.

Outputs:
  --gt          compiled GT JSON (gt_liz schema). Statuses: marks that
                coincide with a point in --prior inherit its status;
                marks with no prior match = 'required' (explicit hand
                addition); prior points with no mark = recorded under
                'removed_points' (candidate banned positions for the
                audit file), NOT in gt_boundaries.
  --boundaries  boundaries.json-shaped file (per_part / time_quarter_notes
                / measure / beat) so boundaries_diff.py can diff any
                pipeline run directly against the GT.
  --report      human-readable edit list (added / removed / moved) in
                measure+beat, plus warnings (marks on tied-forward notes,
                duplicates).

Conventions: boundary qn = release of the carrying note; if the carrying
note ties forward, the chain's final release is used and a warning is
printed. Part indexing: score-parts in order, one index per staff
(matches boundaries.json).

Usage:
  python gt_from_score.py gt_rendered_corrected.musicxml \\
      --prior gt_liz_E0b_draft.json \\
      --gt gt_liz_v2.json --boundaries gt_boundaries_v2.json \\
      --report gt_v2_report.txt
"""

import argparse
import json
import xml.etree.ElementTree as ET

TOL = 0.02
MOVE_WINDOW = 8.0   # remove+add within this window pair up as "moved"


def parse_parts(root):
    """Return (flat_parts, disp) where flat_parts[i] = dict with
    name, notes=[(start, rel, tie_fwd, has_breath)], and disp(qn)
    formats measure+beat from the first part's measure map."""
    pl = root.find('part-list')
    names = {sp.get('id'): sp.find('part-name').text
             for sp in pl.findall('score-part')}
    flat = []
    mm = []
    for pi, part in enumerate(root.findall('part')):
        divisions, beats, beat_type = 1, 4, 4
        meas_start = 0.0
        staves = {}
        last_by_staff = {}
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
            if pi == 0:
                mm.append((meas_start, int(meas.get('number'))))
            cursor = 0.0
            for el in meas:
                if el.tag == 'note':
                    dur_el = el.find('duration')
                    d = (int(dur_el.text) / divisions
                         if dur_el is not None else 0.0)
                    st = el.find('staff')
                    staff = int(st.text) if st is not None else 1
                    is_chord = el.find('chord') is not None
                    is_rest = el.find('rest') is not None
                    br = el.find('.//breath-mark') is not None
                    tie_fwd = any(t.get('type') in ('start',)
                                  for t in el.findall('tie'))
                    tie_stop = any(t.get('type') == 'stop'
                                   for t in el.findall('tie'))
                    if dur_el is not None and not is_rest:
                        if is_chord and staff in last_by_staff:
                            rec = last_by_staff[staff]
                            rec[3] = rec[3] or br
                            rec[2] = rec[2] or tie_fwd
                        else:
                            start = meas_start + cursor
                            rec = [start, start + d, tie_fwd, br, tie_stop]
                            staves.setdefault(staff, []).append(rec)
                            last_by_staff[staff] = rec
                    if dur_el is not None and not is_chord:
                        cursor += d
                elif el.tag == 'backup':
                    cursor -= int(el.find('duration').text) / divisions
                elif el.tag == 'forward':
                    cursor += int(el.find('duration').text) / divisions
            meas_start += beats * 4.0 / beat_type
        for staff in sorted(staves):
            flat.append({'name': names[part.get('id')],
                         'notes': staves[staff]})

    def locate(qn):
        prev = mm[0]
        for off, num in mm:
            if off > qn + 1e-6:
                break
            prev = (off, num)
        off, num = prev
        return num, qn - off + 1.0

    def disp(qn):
        for off, num in mm:
            if abs(qn - off) <= 1e-6 and num > mm[0][1]:
                return f"m.{num - 1} end"
        num, beat = locate(qn)
        return f"m.{num} b{beat:g}"
    return flat, disp, locate


def chain_release(notes, k):
    """Follow tie-forward from notes[k] to the chain's final release."""
    rel = notes[k][1]
    j = k
    while notes[j][2]:  # tie_fwd
        nxt = next((m for m in range(j + 1, len(notes))
                    if abs(notes[m][0] - notes[j][1]) <= TOL), None)
        if nxt is None:
            break
        j = nxt
        rel = notes[j][1]
    return rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('musicxml')
    ap.add_argument('--prior', default=None,
                    help='prior GT JSON for status inheritance + edit diff')
    ap.add_argument('--gt', required=True)
    ap.add_argument('--boundaries', required=True)
    ap.add_argument('--report', default=None)
    args = ap.parse_args()

    tree = ET.parse(args.musicxml)
    flat, disp, locate = parse_parts(tree.getroot())

    prior = json.load(open(args.prior)) if args.prior else None
    prior_pts = {}
    if prior:
        for p in prior['per_part']:
            prior_pts[p['index']] = list(p['gt_boundaries'])

    log = [f"gt_from_score: {args.musicxml}", "=" * 64]
    gt_parts, bnd_parts = [], []
    n_marks = n_added = n_removed = n_inherit = 0
    for i, fp in enumerate(flat):
        notes = fp['notes']
        marks = []
        for k, rec in enumerate(notes):
            if not rec[3]:
                continue
            rel = rec[1]
            if rec[2]:  # tie forward
                rel = chain_release(notes, k)
                log.append(f"  WARN {fp['name']:<18} mark at {disp(rec[0])} "
                           f"is on a tied-forward note; using chain "
                           f"release {disp(rel)}")
            marks.append(rel)
        marks = sorted(set(round(m, 6) for m in marks))
        n_marks += len(marks)

        gt_b, removed = [], []
        pri = list(prior_pts.get(i, []))
        used = [False] * len(pri)
        for m in marks:
            hit = next((j for j, x in enumerate(pri)
                        if not used[j] and
                        abs(float(x['time_quarter_notes']) - m) <= TOL),
                       None)
            if hit is not None:
                used[hit] = True
                st = pri[hit]['status']
                n_inherit += 1
            else:
                st = 'required'
                n_added += 1
            gt_b.append({'time_quarter_notes': m, 'status': st,
                         'release_ok': True})
        for j, x in enumerate(pri):
            if not used[j]:
                removed.append(dict(x))
                n_removed += 1

        # pair removed+added into "moved" for the report
        added_pts = [b for b in gt_b if b['status'] == 'required'
                     and not any(abs(float(x['time_quarter_notes']) -
                                     b['time_quarter_notes']) <= TOL
                                 for x in pri)]
        rem_left = list(removed)
        for a in added_pts:
            near = next((x for x in rem_left
                         if abs(float(x['time_quarter_notes']) -
                                a['time_quarter_notes']) <= MOVE_WINDOW),
                        None)
            if near is not None:
                rem_left.remove(near)
                log.append(f"  MOVED {fp['name']:<18} "
                           f"{disp(float(near['time_quarter_notes'])):<12} -> "
                           f"{disp(a['time_quarter_notes'])}")
            else:
                log.append(f"  ADDED {fp['name']:<18} "
                           f"{disp(a['time_quarter_notes'])}")
        for x in rem_left:
            log.append(f"  REMOVED {fp['name']:<16} "
                       f"{disp(float(x['time_quarter_notes']))} "
                       f"(was {x['status']})")

        gt_parts.append({'index': i, 'name': fp['name'],
                         'gt_boundaries': gt_b,
                         'removed_points': removed})
        bnd_parts.append({'index': i, 'name': fp['name'],
                          'num_boundaries': len(gt_b),
                          'boundaries': [
                              {'time_quarter_notes': b['time_quarter_notes'],
                               'measure': locate(b['time_quarter_notes'])[0],
                               'beat': round(locate(b['time_quarter_notes'])[1], 4),
                               'measure_beat': disp(b['time_quarter_notes'])}
                              for b in gt_b]})

    gt_doc = {
        'source_score': args.musicxml,
        'compiled_by': 'gt_from_score v1 (hand-corrected score is GT)',
        'prior_gt': args.prior,
        'per_part': gt_parts,
        'constraints': (prior or {}).get('constraints', []),
    }
    with open(args.gt, 'w', encoding='utf-8') as f:
        json.dump(gt_doc, f, indent=2, ensure_ascii=False)
    with open(args.boundaries, 'w', encoding='utf-8') as f:
        json.dump({'parameters': {'gt': True, 'source': args.musicxml},
                   'per_part': bnd_parts}, f, indent=2, ensure_ascii=False)

    log.append("=" * 64)
    log.append(f"marks in score: {n_marks}  (inherited status: {n_inherit}, "
               f"new->required: {n_added}, prior points removed: {n_removed})")
    text = "\n".join(log)
    print(text)
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as f:
            f.write(text + "\n")


if __name__ == '__main__':
    main()
