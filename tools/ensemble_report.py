#!/usr/bin/env python3
"""
ensemble_report.py -- how well a run's breaths agree across the ensemble.

No GT needed. Every boundary instant in every part is clustered (instants
within --tol qn merge). For each cluster:
  breathing  parts with a boundary in the cluster
  sounding   parts playing near it (a note overlapping [t - 1, t + 1] qn)
  share      breathing / sounding
  label      UNISON  share >= --unison (default 0.6)
             LONE    <= 2 parts breathing and share <= --lone (default 0.25)
             partial otherwise
Lone breaths are the likeliest extraneous ones in tutti writing; for each,
the part's own selection score at the breath and whether the ensemble pass
created it are shown.

Usage:
    python ensemble_report.py RUN_DIR [--from_m 1] [--to_m 35] [--md OUT.md]
"""
import argparse
import bisect
import collections
import os
import pickle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--from_m', type=int, default=1)
    ap.add_argument('--to_m', type=int, default=10 ** 6)
    ap.add_argument('--tol', type=float, default=0.25)
    ap.add_argument('--unison', type=float, default=0.6)
    ap.add_argument('--lone', type=float, default=0.25)
    ap.add_argument('--md', default=None)
    a = ap.parse_args()
    r = pickle.load(open(os.path.join(a.run_dir, 'result.pkl'), 'rb'))
    names = r['part_names']
    D = r['parameters'].get('division', 8)
    mo = [(float(o), m) for o, m in r['measure_offsets']]
    starts = [o for o, _ in mo]

    def mb(q):
        k = max(bisect.bisect_right(starts, q + 1e-6) - 1, 0)
        o, m = mo[k]
        if abs(q - o) < 1e-6 and k > 0:
            return 'm.%d end' % mo[k - 1][1], mo[k - 1][1]
        return 'm.%d b%g' % (m, round(q - o + 1, 3)), m

    ens_made = collections.defaultdict(set)
    for i, ch in enumerate(r.get('ensemble_info') or []):
        for c in ch:
            if c.get('to') is not None:
                ens_made[i].add(round(float(c['to']), 3))

    pts = []
    for i, b in enumerate(r['per_part_boundaries']):
        if r['is_tacet'][i]:
            continue
        for t in b:
            pts.append((float(t), i))
    pts.sort()
    clusters = []
    for t, i in pts:
        if clusters and t - clusters[-1][-1][0] <= a.tol:
            clusters[-1].append((t, i))
        else:
            clusters.append([(t, i)])

    def sounding(t):
        out = []
        for j, notes in enumerate(r['notes_per_part']):
            if r['is_tacet'][j]:
                continue
            if any(float(n['offset']) < t + 1 and float(n['offset']) + float(n['duration']) > t - 1
                   for n in notes):
                out.append(j)
        return out

    lines, counts, lone_rows = [], collections.Counter(), []
    per_part_lone = collections.Counter()
    for c in clusters:
        t = sorted(x[0] for x in c)[len(c) // 2]
        where, m = mb(t)
        if not (a.from_m <= m <= a.to_m):
            continue
        br = sorted({i for _, i in c})
        snd = sounding(t)
        share = len(br) / max(len(snd), 1)
        lab = ('UNISON' if share >= a.unison else
               'LONE' if (len(br) <= 2 and share <= a.lone) else 'partial')
        counts[lab] += 1
        missing = [j for j in snd if j not in br]
        lines.append('| %s | %.2f | %s | %d/%d | %s | %s |' % (
            where, t, lab, len(br), len(snd),
            ', '.join(names[i].split()[0][:6] for i in br),
            ', '.join(names[j].split()[0][:6] for j in missing) if lab != 'LONE' else ''))
        if lab == 'LONE':
            for tt, i in c:
                d = r['per_part_candidate_diagnostics'][i] or {}
                sel = d.get('selection_score')
                f = min(max(int(round(tt * D)), 0), len(sel) - 1) if sel is not None else None
                src = 'ensemble pass' if round(tt, 3) in ens_made[i] else 'own evidence'
                lone_rows.append('| %s | %s | %.3f | %s | %s |' % (
                    names[i], mb(tt)[0], tt,
                    '%.2f' % float(sel[f]) if f is not None else '?', src))
                per_part_lone[names[i]] += 1

    md = ['# Ensemble agreement: `%s` (m.%d-%s)\n' % (a.run_dir, a.from_m,
                                                       a.to_m if a.to_m < 10 ** 6 else 'end'),
          'Clusters of breath instants across parts (merged within %.2f qn). '
          'UNISON = at least %d%% of the parts sounding there breathe; LONE = at most 2 parts '
          'and at most %d%% of those sounding.\n' % (a.tol, a.unison * 100, a.lone * 100),
          '**%d clusters: %d unison, %d partial, %d lone.**\n' % (
              sum(counts.values()), counts['UNISON'], counts['partial'], counts['LONE']),
          '| at | qn | label | breathing/sounding | breathing | sounding but not breathing |',
          '|---|---|---|---|---|---|'] + lines
    md += ['\n## Lone breaths (likeliest extraneous)\n',
           '| part | at | qn | own Sel at breath | created by |', '|---|---|---|---|---|'] + lone_rows
    md += ['\nLone breaths per part: ' + ', '.join('%s %d' % kv for kv in per_part_lone.most_common())]
    text = '\n'.join(md) + '\n'
    print(text)
    if a.md:
        open(a.md, 'w', encoding='utf-8').write(text)


if __name__ == '__main__':
    main()
