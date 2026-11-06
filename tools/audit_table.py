#!/usr/bin/env python3
"""
audit_table.py -- render an audit case file against a boundaries.json as a
single-file HTML review table.

v3 (2026-07-10)
    Soft verdicts (strength "recommended"): MISSING? / SPURIOUS? in amber,
    excluded from nothing but visually distinct. Unison constraints render
    as rows under their case band with per-part mark sets.

v2 (2026-07-10)
    Plain-language verdicts per Robert's review needs:
      expectation column: MARK REQUIRED / NO MARK ALLOWED / needs verdict
      verdict column:     OK / MISSING (required mark not found)
                          / SPURIOUS (forbidden mark found) / blank
    Filters: all / problems / needs verdict / flagged.
    (audit_check.py PASS/FAIL semantics are unchanged; this is a viewer.)

v1 (2026-07-10)
    New tool. One row per diagnostic point, grouped by case, verdicts
    computed exactly like audit_check.py, with automated review flags:
      DUP       same part+target+expect appears in another case
      OPPOSED   an opposing expect targets the same part within 4.5 qn
                in another case (intended wrong/right pairs also show
                this -- surfaced for human judgment, not auto-resolved)
      NO-CATCH  an 'absent' point whose window contains no mark while a
                mark exists within 5 qn -- window probably mistargeted

Conventions match audit_check.py: qn = (measure-1)*4 + (beat-1);
beat "end" means the barline release instant, qn = measure*4.

Usage:
    python audit_table.py boundaries.json --audit audit_cases.json \
        [--out audit_table.html] [--tol 2.0]
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import measure_map as _mm


def qn_of(measure: int, beat) -> float:
    return _mm.qn_of(measure, beat)


def fmt_qn(qn: float) -> str:
    m, b = _mm.locate(qn)
    return f"m.{m} end" if b == 'end' else f"m.{m} b{b:g}"


def load_boundaries(path: str):
    doc = json.loads(Path(path).read_text())
    per_part, names = {}, {}
    for e in doc.get('per_part', []):
        i = int(e['index'])
        names[i] = e.get('name', f'part {i}')
        per_part[i] = sorted(float(b['time_quarter_notes'])
                             for b in e.get('boundaries', []))
    p = doc.get('parameters', {})
    label = "{}  [policy={} sha={}]".format(
        path, p.get('rest_seam_policy', '?'), p.get('input_sha256', '?'))
    return per_part, names, label


def nearest(bqns, target):
    if not bqns:
        return None, None
    best = min(bqns, key=lambda q: abs(q - target))
    return best, best - target


EXPECT_TXT = {'present': 'MARK REQUIRED', 'absent': 'NO MARK ALLOWED',
              None: 'needs verdict'}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('boundaries')
    ap.add_argument('--audit', required=True)
    ap.add_argument('--out', default='audit_table.html')
    ap.add_argument('--tol', type=float, default=2.0)
    ap.add_argument('--musicxml', required=True,
                    help='score file; provides the real measure map')
    args = ap.parse_args()

    _mm.load(args.musicxml)
    _mm.verify_against_boundaries(
        json.loads(Path(args.boundaries).read_text()))
    per_part, names, run_label = load_boundaries(args.boundaries)
    audit = json.loads(Path(args.audit).read_text())

    rows = []
    for case in audit.get('cases', []):
        for p in case.get('diagnostic_points', []):
            part = int(p['part_index'])
            target = qn_of(int(p['measure']), p.get('beat', 1.0))
            tol = p.get('tol') or args.tol
            q, d = nearest(per_part.get(part, []), target)
            hit = q is not None and abs(d) <= tol
            expect = p.get('expect')
            soft = p.get('strength') == 'recommended'
            if expect == 'present':
                verdict = 'OK' if hit else ('MISSING?' if soft else 'MISSING')
            elif expect == 'absent':
                verdict = ('SPURIOUS?' if soft else 'SPURIOUS') if hit else 'OK'
            else:
                verdict = ''
            rows.append(dict(
                case=case.get('id', '?'), tags=case.get('tags', []),
                summary=case.get('summary', ''), part=part,
                target=target, tol=tol, expect=expect, verdict=verdict,
                near=q, delta=d, why=p.get('why', ''), flags=[]))

    for i, a in enumerate(rows):
        for j, b in enumerate(rows):
            if i >= j or a['part'] != b['part'] or a['case'] == b['case']:
                continue
            same_spot = abs(a['target'] - b['target']) < 1e-6
            if same_spot and a['expect'] and a['expect'] == b['expect']:
                a['flags'].append(f"DUP:{b['case']}")
                b['flags'].append(f"DUP:{a['case']}")
            if (a['expect'] and b['expect'] and a['expect'] != b['expect']
                    and abs(a['target'] - b['target']) <= 4.5):
                a['flags'].append(f"OPPOSED:{b['case']}@{fmt_qn(b['target'])}")
                b['flags'].append(f"OPPOSED:{a['case']}@{fmt_qn(a['target'])}")
    for r in rows:
        if r['expect'] == 'absent' and r['verdict'] == 'OK':
            near5 = [q for q in per_part.get(r['part'], [])
                     if r['tol'] < abs(q - r['target']) <= 5.0]
            if near5:
                r['flags'].append(
                    "NO-CATCH: mark at "
                    + ", ".join(fmt_qn(q) for q in near5)
                    + " outside window")

    n_ok = sum(r['verdict'] == 'OK' for r in rows)
    n_missing = sum(r['verdict'] == 'MISSING' for r in rows)
    n_spur = sum(r['verdict'] == 'SPURIOUS' for r in rows)
    n_softv = sum(r['verdict'].endswith('?') for r in rows)
    n_nv = sum(r['verdict'] == '' for r in rows)

    # unison constraints -> pseudo-rows keyed by case
    con_rows = {}
    for case in audit.get('cases', []):
        for con in case.get('constraints', []):
            if con.get('type') != 'unison':
                continue
            lo, hi = con['qn_lo'], con['qn_hi']
            sets = {pi: [q for q in per_part.get(pi, [])
                         if lo <= q <= hi] for pi in con['parts']}
            vals = list(sets.values())
            same = all(len(v) == len(vals[0]) and
                       all(abs(a - b) <= 0.1 for a, b in zip(v, vals[0]))
                       for v in vals)
            detail = "; ".join(
                f"p{pi} {names.get(pi,'?')}: "
                f"{', '.join(fmt_qn(q) for q in s) or 'none'}"
                for pi, s in sets.items())
            con_rows.setdefault(case.get('id','?'), []).append(
                (same, f"qn [{lo:g}, {hi:g}]", detail))
    n_cviol = sum(1 for L in con_rows.values() for ok_, *_ in L if not ok_)
    n_flag = sum(bool(r['flags']) for r in rows)

    e = html.escape
    body = []
    last_case = None
    for r in rows:
        if r['case'] != last_case:
            tags = " ".join(f'<span class="tag">{e(t)}</span>'
                            for t in r['tags'])
            body.append(
                f'<tr class="case"><td colspan="8"><span class="cid">'
                f'{e(r["case"])}</span> {tags}<div class="sum">'
                f'{e(r["summary"])}</div></td></tr>')
            last_case = r['case']
            for ok_, rng, detail in con_rows.get(r['case'], []):
                v = 'UNISON OK' if ok_ else 'UNISON VIOLATION'
                cls2 = 'ok' if ok_ else 'missing'
                body.append(
                    f'<tr class="pt {cls2}" data-p="{0 if ok_ else 1}" '
                    f'data-nv="0" data-f="0">'
                    f'<td class="v">{v}</td>'
                    f'<td class="exp">UNISON</td>'
                    f'<td class="mono" colspan="4">{rng}</td>'
                    f'<td></td><td class="why">{e(detail)}</td></tr>')
        near_txt = ('&mdash;' if r['near'] is None else
                    f'{fmt_qn(r["near"])} <span class="d">'
                    f'({r["delta"]:+.3f})</span>')
        flags = " ".join(f'<span class="flag">{e(f)}</span>'
                         for f in r['flags'])
        vcls = (r['verdict'] or 'nv').rstrip('?').lower()
        if r['verdict'].endswith('?'):
            vcls = 'soft'
        cls = vcls + (' flagged' if r['flags'] else '')
        problem = 1 if r['verdict'].rstrip('?') in ('MISSING', 'SPURIOUS') else 0
        body.append(
            f'<tr class="pt {cls}" data-p="{problem}" '
            f'data-nv="{0 if r["expect"] else 1}" '
            f'data-f="{1 if r["flags"] else 0}">'
            f'<td class="v">{r["verdict"] or "&mdash;"}</td>'
            f'<td class="exp {"nv" if not r["expect"] else ""}">'
            f'{EXPECT_TXT[r["expect"]]}</td>'
            f'<td class="mono">p{r["part"]} {e(names.get(r["part"], "?"))}'
            f'</td>'
            f'<td class="mono tgt">{fmt_qn(r["target"])}'
            f'<span class="d"> qn {r["target"]:g}</span></td>'
            f'<td class="mono">{r["tol"]:g}</td>'
            f'<td class="mono">{near_txt}</td>'
            f'<td>{flags}</td>'
            f'<td class="why">{e(r["why"])}</td></tr>')

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Audit review table</title>
<style>
:root {{
  --ink:#1c211e; --paper:#f4f6f3; --line:#d8ddd6;
  --ok:#256b45; --missing:#a63226; --spur:#8a4b9c; --nv:#6d7570;
  --flagbg:#f6ecd2; --flagink:#7a5a00; --band:#242e2a; --bandink:#e9eee9;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink);
  font:14px/1.45 system-ui, sans-serif; padding:1.5rem; }}
h1 {{ font:600 1.05rem/1.3 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing:.06em; text-transform:uppercase; margin:0 0 .25rem; }}
.meta {{ font:12px ui-monospace, Menlo, monospace; color:var(--nv);
  margin-bottom:1rem; }}
.meta b.m {{ color:var(--missing); }} .meta b.s {{ color:var(--spur); }}
.filters button {{ font:12px ui-monospace, Menlo, monospace;
  border:1px solid var(--line); background:#fff; padding:.3rem .7rem;
  cursor:pointer; margin-right:.4rem; border-radius:3px; }}
.filters button.on {{ background:var(--band); color:var(--bandink);
  border-color:var(--band); }}
table {{ border-collapse:collapse; width:100%; margin-top:.8rem;
  background:#fff; }}
td {{ border-bottom:1px solid var(--line); padding:.42rem .55rem;
  vertical-align:top; }}
tr.case td {{ background:var(--band); color:var(--bandink);
  padding:.55rem .7rem; border-bottom:none; }}
.cid {{ font:600 13px ui-monospace, Menlo, monospace; }}
.sum {{ font-size:12px; opacity:.82; margin-top:.15rem; max-width:70rem; }}
.tag {{ font:10px ui-monospace, Menlo, monospace; border:1px solid
  rgba(233,238,233,.4); border-radius:2px; padding:0 .3rem;
  margin-left:.35rem; }}
.mono {{ font:12.5px ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric:tabular-nums; white-space:nowrap; }}
.tgt {{ font-weight:600; }}
.d {{ color:var(--nv); font-weight:400; }}
.v {{ font:700 11px ui-monospace, Menlo, monospace; width:4.6rem; }}
.exp {{ font:600 11px ui-monospace, Menlo, monospace; width:8.2rem; }}
.exp.nv {{ color:var(--nv); font-weight:400; font-style:italic; }}
tr.ok td.v {{ color:var(--ok); }}
tr.missing td.v {{ color:var(--missing); }}
tr.spurious td.v {{ color:var(--spur); }}
tr.ok {{ border-left:4px solid var(--ok); }}
tr.missing {{ border-left:4px solid var(--missing); }}
tr.spurious {{ border-left:4px solid var(--spur); }}
tr.soft td.v {{ color:var(--flagink); }}
tr.soft {{ border-left:4px solid var(--flagink); }}
tr.nv {{ border-left:4px solid var(--line); }}
tr.flagged td {{ background:var(--flagbg); }}
.flag {{ display:inline-block; font:10.5px ui-monospace, Menlo, monospace;
  color:var(--flagink); border:1px solid var(--flagink); border-radius:2px;
  padding:0 .25rem; margin:.15rem .2rem 0 0; }}
.why {{ font-size:12px; color:#3c443f; max-width:24rem; }}
</style></head><body>
<h1>Audit review table</h1>
<div class="meta">run: {e(run_label)}<br>
audit: {e(args.audit)} &nbsp;&middot;&nbsp; default tol {args.tol} qn<br>
{n_ok} OK &nbsp;&middot;&nbsp; <b class="m">{n_missing} MISSING</b>
&nbsp;&middot;&nbsp; <b class="s">{n_spur} SPURIOUS</b>
&nbsp;&middot;&nbsp; {n_softv} soft &nbsp;&middot;&nbsp;
<b class="m">{n_cviol} unison violations</b> &nbsp;&middot;&nbsp;
{n_nv} need a verdict &nbsp;&middot;&nbsp; {n_flag} flagged</div>
<div class="filters">
<button class="on" data-k="all">all</button>
<button data-k="problems">problems</button>
<button data-k="nv">needs verdict</button>
<button data-k="flagged">flagged</button>
</div>
<table><tbody>
{''.join(body)}
</tbody></table>
<script>
document.querySelectorAll('.filters button').forEach(b =>
  b.addEventListener('click', () => {{
    document.querySelectorAll('.filters button')
      .forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    const k = b.dataset.k;
    document.querySelectorAll('tr.pt').forEach(tr => {{
      let show = true;
      if (k === 'problems') show = tr.dataset.p === '1';
      if (k === 'nv') show = tr.dataset.nv === '1';
      if (k === 'flagged') show = tr.dataset.f === '1';
      tr.style.display = show ? '' : 'none';
    }});
  }}));
</script>
</body></html>"""
    Path(args.out).write_text(page)
    print(f"wrote {args.out}: {len(rows)} points -- {n_ok} OK, "
          f"{n_missing} MISSING, {n_spur} SPURIOUS, {n_softv} soft, "
          f"{n_cviol} unison violations, {n_nv} need verdict, "
          f"{n_flag} flagged")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
