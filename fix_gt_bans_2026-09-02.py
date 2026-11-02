#!/usr/bin/env python3
"""
fix_gt_bans_2026-09-02.py

Repairs the two loose ends left by the Oboe m.86 b4.75 GT correction.

(1) gt_liz_v2_2026-09-02.json lost 53 banned positions.
    gt_from_score.py builds removed_points only from PRIOR GT points that lost
    their mark in THIS run; it never carries the prior's own removed_points
    forward. So the new file holds just 343.75. Merge the prior's bans back,
    skipping any that have since become GT points again. Edited in place, with
    a .bak copy alongside.

(2) The audit file never learned about 343.75.
    Writes a NEW audit_cases_gt_v2_2026-09-02.json -- the 07-19 file is left
    untouched -- with 343.75 added to gtv2_banned_p2. The new point is cloned
    from the existing Oboe 262.5 entry (also a deleted GT mark, 2026-08-07
    pass) so it has exactly the same schema. Tolerance follows the 07-19 rule:
    0.1, shrunk to 0.05 if an Oboe GT point sits within 0.2 qn.

Prints every change. Nothing is guessed silently: any schema surprise aborts.

Usage:
    python fix_gt_bans_2026-09-02.py
"""

import copy
import json
import os
import shutil
import sys

PRIOR = 'gt_liz_v2_2026-07-15.json'
NEW = 'gt_liz_v2_2026-09-02.json'
GT_BND = 'gt_boundaries_v2.json'
AUDIT_OLD = 'audit_cases_gt_v2_2026-07-19.json'
AUDIT_NEW = 'audit_cases_gt_v2_2026-09-02.json'

PART, QN, MEAS, BEAT = 2, 343.75, 86, 4.75
TEMPLATE_QN = 262.5           # Oboe m.66 b3.5, deleted in the 2026-08-07 pass
EPS = 0.01


def qn_of(p):
    for k in ('time_quarter_notes', 'qn'):
        if k in p:
            return float(p[k])
    raise SystemExit('ABORT: point has no time field: %r' % (p,))


def main():
    for f in (PRIOR, NEW, GT_BND, AUDIT_OLD):
        if not os.path.exists(f):
            sys.exit('ABORT: %s not found' % f)
    if os.path.exists(AUDIT_NEW):
        sys.exit('ABORT: %s already exists -- already run?' % AUDIT_NEW)

    prior = json.load(open(PRIOR, encoding='utf-8'))
    new = json.load(open(NEW, encoding='utf-8'))

    # ------------------------------------------------------------- (1) bans
    prior_by = {p['index']: p for p in prior['per_part']}
    added = skipped = 0
    for p in new['per_part']:
        i = p['index']
        gt_now = [qn_of(b) for b in p.get('gt_boundaries', [])]
        have = [qn_of(r) for r in p.get('removed_points', [])]
        for r in prior_by.get(i, {}).get('removed_points', []):
            q = qn_of(r)
            if any(abs(q - h) <= EPS for h in have):
                continue
            if any(abs(q - g) <= EPS for g in gt_now):
                print('  skip part %d qn %.3f -- it is a GT point again' % (i, q))
                skipped += 1
                continue
            p.setdefault('removed_points', []).append(copy.deepcopy(r))
            have.append(q)
            added += 1
        p['removed_points'].sort(key=qn_of)

    total = sum(len(p.get('removed_points', [])) for p in new['per_part'])
    print('(1) %s: merged %d prior bans back (%d skipped); banned now %d'
          % (NEW, added, skipped, total))
    if total != 54:
        print('    NOTE: expected 54 (53 prior + 343.75). Check before trusting.')

    shutil.copy2(NEW, NEW + '.bak')
    json.dump(new, open(NEW, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print('    written in place; original kept as %s.bak' % NEW)

    # ------------------------------------------------------------ (2) audit
    audit = json.load(open(AUDIT_OLD, encoding='utf-8'))
    case = next((c for c in audit.get('cases', [])
                 if c.get('id') == 'gtv2_banned_p2'), None)
    if case is None:
        sys.exit('ABORT: no case gtv2_banned_p2 in %s' % AUDIT_OLD)
    pts = case.get('diagnostic_points', [])

    tmpl = None
    for pt in pts:
        m = pt.get('measure')
        b = pt.get('beat')
        if m is not None and int(m) == 66 and b is not None \
                and abs(float(b) - 3.5) <= EPS:
            tmpl = pt
            break
    if tmpl is None:
        sys.exit('ABORT: template point (Oboe m.66 b3.5) not found; '
                 'points are:\n  ' + '\n  '.join(repr(x) for x in pts))
    if any(int(pt.get('measure', -1)) == MEAS and pt.get('beat') is not None
           and abs(float(pt['beat']) - BEAT) <= EPS for pt in pts):
        sys.exit('ABORT: m.%d b%g already present in gtv2_banned_p2' % (MEAS, BEAT))

    gt_bnd = json.load(open(GT_BND, encoding='utf-8'))
    oboe = next(p for p in gt_bnd['per_part'] if p['index'] == PART)
    near = [qn_of(b) for b in oboe['boundaries'] if abs(qn_of(b) - QN) <= 0.2]
    tol = 0.05 if near else 0.1

    prior_status = '?'
    for g in prior_by[PART].get('gt_boundaries', []):
        if abs(qn_of(g) - QN) <= EPS:
            prior_status = g.get('status', '?')

    newpt = copy.deepcopy(tmpl)
    newpt['measure'] = MEAS
    newpt['beat'] = BEAT
    newpt['tol'] = tol
    for k in ('time_quarter_notes', 'qn'):
        if k in newpt:
            newpt[k] = QN
    newpt['why'] = ('Robert deleted this GT mark in the 2026-09-02 correction '
                    'pass (was %s, qn %g): breath at the onset of a slur\'s '
                    'last note detaches that note (§23).' % (prior_status, QN))
    pts.append(newpt)

    audit.setdefault('notes', [])
    if isinstance(audit['notes'], list):
        audit['notes'].append('2026-09-02: Oboe m.86 b4.75 (qn 343.75) added '
                              'to gtv2_banned_p2 after GT correction.')
    json.dump(audit, open(AUDIT_NEW, 'w', encoding='utf-8'),
              indent=2, ensure_ascii=False)

    print('(2) wrote %s (07-19 file untouched)' % AUDIT_NEW)
    print('    template : %r' % (tmpl,))
    print('    added    : %r' % (newpt,))
    print('    tol %.2f (Oboe GT within 0.2 qn: %s)' % (tol, near or 'none'))
    print('\nVerify: audit_check must print the new point as target qn 343.750.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
