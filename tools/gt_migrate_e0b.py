#!/usr/bin/env python3
"""
gt_migrate_e0b.py  (v1, 2026-07-15)

Apply the E0b release-anchor rule to a compiled GT file, producing a
DRAFT GT for Robert to eye-judge (this tool has no musical authority;
it only replays the deterministic E0b mapping so the GT and the
pipeline speak the same convention).

Rule (identical to patch_E0b_release_anchor):
  mid-note point            -> containing chain's release  ('mid_note')
  note-to-note seam point   -> starting chain's release, IF the
                               starting note carries arrival/gap
                               evidence > 0.3               ('seam_arrival_evidence')
  rest-seam / entry-onset   -> untouched
  shift landing at score end-> suppressed, recorded
Post-migration duplicates within a part merge (required wins over kept).
Unison constraint windows are checked: a migrated point leaving its
window is WARNED, not auto-fixed.

Usage:
  python gt_migrate_e0b.py gt_liz_2026-07-10.json result.pkl \\
      -o gt_liz_E0b_draft.json --report gt_migrate_report.txt
result.pkl must be from the SAME input score (any recent run; the rule
uses notes and evidence grids only, which E0b does not change).
"""

import argparse
import json
import pickle

EPS = 0.02
EVIDENCE_MIN = 0.3


def load_measure_map(measure_offsets):
    mm = sorted((float(o), int(n)) for o, n in measure_offsets)

    def disp(qn):
        prev = mm[0]
        for off, num in mm:
            if off > qn + 1e-6:
                break
            prev = (off, num)
        off, num = prev
        beat = qn - off + 1.0
        # barline instant belongs to the NEXT measure's offset; render
        # as previous measure end per pipeline convention
        for off2, num2 in mm:
            if abs(qn - off2) <= 1e-6 and num2 > mm[0][1]:
                return f"m.{num2 - 1} end"
        return f"m.{num} b{beat:g}"
    return disp


def migrate_part(points, notes, long_grid, gap_grid, division,
                 score_end, disp, log, part_name):
    notes = sorted(notes, key=lambda n: float(n['offset']))
    onsets = [float(n['offset']) for n in notes]
    rels = [float(n['offset']) + float(n['duration']) for n in notes]
    T = len(long_grid)
    out = []
    for pt in sorted(points, key=lambda p: p['time_quarter_notes']):
        bt = float(pt['time_quarter_notes'])
        new_bt, reason = bt, None
        k_in = next((k for k in range(len(notes))
                     if onsets[k] + EPS < bt < rels[k] - EPS), None)
        at_rel = any(abs(v - bt) <= EPS for v in rels)
        k_on = next((k for k in range(len(notes))
                     if abs(onsets[k] - bt) <= EPS), None)
        if k_in is not None:
            new_bt, reason = rels[k_in], 'mid_note'
        elif at_rel and k_on is not None:
            f = min(max(int(round(bt * division)), 0), T - 1)
            ev = max(float(long_grid[f]), float(gap_grid[f]))
            if ev > EVIDENCE_MIN:
                new_bt, reason = rels[k_on], 'seam_arrival_evidence'
        if reason and score_end is not None and new_bt >= score_end - EPS:
            log.append(f"  {part_name:<18} {disp(bt):<12} "
                       f"suppressed (would land at score end)")
            new_bt, reason = bt, None
        npt = dict(pt)
        if reason and abs(new_bt - bt) > EPS:
            npt['time_quarter_notes'] = new_bt
            npt['migrated_from'] = bt
            npt['migrate_reason'] = reason
            log.append(f"  {part_name:<18} {disp(bt):<12} -> "
                       f"{disp(new_bt):<12} ({pt['status']}, {reason})")
        out.append(npt)
    # merge duplicates (required wins)
    out.sort(key=lambda p: p['time_quarter_notes'])
    merged = []
    for p in out:
        if merged and abs(p['time_quarter_notes'] -
                          merged[-1]['time_quarter_notes']) <= EPS:
            keep = merged[-1]
            if p['status'] == 'required':
                keep['status'] = 'required'
            keep.setdefault('merged_from', []).append(
                p.get('migrated_from', p['time_quarter_notes']))
            log.append(f"  {part_name:<18} duplicate at "
                       f"{disp(p['time_quarter_notes'])} merged")
            continue
        merged.append(p)
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('gt_json')
    ap.add_argument('result_pkl')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--report', default=None)
    args = ap.parse_args()

    gt = json.load(open(args.gt_json))
    with open(args.result_pkl, 'rb') as f:
        r = pickle.load(f)
    division = int(r['parameters'].get('division', 8))
    score_end = r['parameters'].get('all_knobs', {}).get('score_end_qn')
    score_end = float(score_end) if score_end is not None else None
    disp = load_measure_map(r['measure_offsets'])

    log = ["E0b GT migration report", "=" * 60]
    n_moved = 0
    for p in gt['per_part']:
        i = p['index']
        before = [dict(x) for x in p['gt_boundaries']]
        p['gt_boundaries'] = migrate_part(
            p['gt_boundaries'], r['notes_per_part'][i],
            r['long_note_grids'][i], r['following_gap_grids'][i],
            division, score_end, disp, log, p['name'])
        n_moved += sum(1 for x in p['gt_boundaries'] if 'migrated_from' in x)

    # unison constraint windows: warn if a migrated point left its window
    for c in gt.get('constraints', []):
        if c.get('type') != 'unison':
            continue
        lo, hi = float(c['qn_lo']), float(c['qn_hi'])
        for p in gt['per_part']:
            if p['index'] not in c['parts']:
                continue
            had = any(lo - EPS <= x.get('migrated_from',
                                        x['time_quarter_notes']) <= hi + EPS
                      for x in p['gt_boundaries'])
            has = any(lo - EPS <= x['time_quarter_notes'] <= hi + EPS
                      for x in p['gt_boundaries'])
            if had and not has:
                log.append(f"  WARNING: {p['name']} left unison window "
                           f"{c.get('case')} [{lo}, {hi}] after migration "
                           f"-- widen the window or re-rule.")

    gt['migrated_by'] = 'gt_migrate_e0b v1 (E0b release-anchor rule)'
    gt['migration_source_pkl_params'] = {
        'division': division, 'score_end_qn': score_end}
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(gt, f, indent=2)

    log.append("=" * 60)
    log.append(f"TOTAL migrated: {n_moved} of "
               f"{sum(len(p['gt_boundaries']) for p in gt['per_part'])} points")
    text = "\n".join(log)
    print(text)
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as f:
            f.write(text + "\n")


if __name__ == '__main__':
    main()
