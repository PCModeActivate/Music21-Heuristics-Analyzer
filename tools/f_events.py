#!/usr/bin/env python3
"""
f_events.py — F1 expressive-event extraction + dry-run coverage vs GT v2.

v1 (2026-07-19)
    Standalone (imports music21 only; no pipeline import). Three jobs:

    1. --inventory: dump the actual class histogram of spanners, text
       expressions, and note-attached expressions per part, so the F1
       pipeline patch is written against what MuseScore's MusicXML
       actually encodes (wedge classes, whether dashed lines survive as
       spanner.Line, etc.). Run this FIRST.

    2. Extract expressive events per part (indices 0-9):
         fermata    : note carries expressions.Fermata
                      -> anchor = that note's tie-chain release
         dim_end    : Diminuendo wedge -> last spanned note chain release
                      "dim."/"decresc." TextExpression + co-starting Line
                      spanner -> line's last element chain release;
                      bare text -> UNRESOLVED (logged, never generates)
         cresc_end  : same, for Crescendo / "cresc."
         rall_end   : "rall."/"rit."/"riten."/"allarg." text + co-starting
                      Line spanner -> line end chain release;
                      bare text -> UNRESOLVED (logged)
       Anchoring rule is the E0b/E0c convention: the breath follows the
       carrying note; all anchors are tie-chain RELEASES. Exact, no
       neighborhoods, no gaussians.

    3. Coverage vs GT: misses = GT points with no run boundary within
       tol. For each event anchor: CLAIMS-MISS (<=tol), NEAR-MISS
       (<=1 qn, report only), MATCHES-RUN (pipeline already there:
       no-op), or NOVEL (new point — candidate extra; check bans).
       Optional --gt-full checks anchors against removed_points (bans).
       The claims table IS the F1 prediction band.

Usage:
    python f_events.py score.musicxml --inventory
    python f_events.py score.musicxml --gt gt_boundaries_v2.json \
        --run output_v2_10_E0c/liz_seam/boundaries.json \
        [--gt-full gt_liz_v2_2026-07-15.json] [--tol 0.1]

No backups, no files written — report to stdout only.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict

from music21 import converter, expressions, spanner, note as m21note
from music21 import dynamics as m21dyn

EPS = 1e-3
DIM_WORDS = ('dim', 'decresc', 'dimin')
CRESC_WORDS = ('cresc',)
RALL_WORDS = ('rall', 'rit', 'riten', 'allarg')
PART_RANGE = range(0, 10)


# ---------------------------------------------------------------- measure map

def build_measure_map(score):
    """(number, start_qn, end_qn) per measure, from part 0. Handles 18/4 m.93."""
    p0 = score.parts[0]
    rows = []
    for m in p0.getElementsByClass('Measure'):
        start = float(m.getOffsetInHierarchy(p0))
        rows.append((int(m.number), start,
                     start + float(m.barDuration.quarterLength)))
    rows.sort(key=lambda r: r[1])
    return rows


def fmt_qn(qn, mmap):
    for num, start, end in mmap:
        if abs(qn - end) <= EPS:
            return f"m.{num} end"
        if start - EPS <= qn < end - EPS:
            return f"m.{num} b{qn - start + 1:g}"
    return f"qn {qn:g} (past map)"


# ------------------------------------------------------------- chain releases

def flat_notes(part):
    return sorted(part.flatten().notes, key=lambda n: float(n.offset))


def chain_release(n, notes_sorted):
    """Tie-chain release of note/chord n, walking forward by (release ==
    next onset) and pitch overlap. Pragmatic for multi-voice harp."""
    cur = n
    guard = 0
    while guard < 500:
        guard += 1
        tie = getattr(cur, 'tie', None)
        rel = float(cur.offset) + float(cur.duration.quarterLength)
        if tie is None or tie.type == 'stop':
            return rel
        pitches = {p.nameWithOctave for p in cur.pitches}
        nxt = None
        for cand in notes_sorted:
            if abs(float(cand.offset) - rel) <= EPS and \
                    pitches & {p.nameWithOctave for p in cand.pitches}:
                ct = getattr(cand, 'tie', None)
                if ct is not None and ct.type in ('continue', 'stop'):
                    nxt = cand
                    break
        if nxt is None:
            return rel
        cur = nxt
    return float(cur.offset) + float(cur.duration.quarterLength)


# ---------------------------------------------------------------- extraction

def text_kind(s):
    t = (s or '').strip().lower()
    if any(t.startswith(w) for w in RALL_WORDS):
        return 'rall_end'
    if any(t.startswith(w) for w in DIM_WORDS):
        return 'dim_end'
    if any(t.startswith(w) for w in CRESC_WORDS):
        return 'cresc_end'
    return None


def extract_part_events(part, idx):
    """Return (events, unresolved). Event: dict(part, kind, raw_qn,
    anchor_qn, detail). Unresolved: bare texts with no span end."""
    notes = flat_notes(part)
    events, unresolved = [], []

    # fermatas
    for n in notes:
        if any(isinstance(e, expressions.Fermata) for e in n.expressions):
            raw = float(n.offset)
            events.append(dict(part=idx, kind='fermata', raw_qn=raw,
                               anchor_qn=chain_release(n, notes),
                               detail=f"fermata note @{raw:g}"))

    # spanners: wedges + lines
    lines = []
    for sp in part.recurse().getElementsByClass(spanner.Spanner):
        cls = type(sp).__name__
        first, last = sp.getFirst(), sp.getLast()
        if first is None or last is None:
            continue
        try:
            f_off = float(first.getOffsetInHierarchy(part))
            l_off = float(last.getOffsetInHierarchy(part))
        except Exception:
            continue
        if isinstance(sp, m21dyn.Diminuendo):
            kind = 'dim_end'
        elif isinstance(sp, m21dyn.Crescendo):
            kind = 'cresc_end'
        elif isinstance(sp, m21dyn.DynamicWedge):
            kind = 'dim_end'  # unspecified wedge: treat as dim, flag it
        elif cls in ('Line', 'TextLine'):
            lines.append((sp, f_off, l_off, last))
            continue
        else:
            continue  # slurs etc.
        anchor = (chain_release(last, notes)
                  if isinstance(last, m21note.NotRest) else l_off)
        events.append(dict(part=idx, kind=kind, raw_qn=l_off,
                           anchor_qn=anchor,
                           detail=f"{cls} {f_off:g}->{l_off:g}"))

    # text expressions; pair with a co-starting line if one exists
    for te in part.recurse().getElementsByClass(expressions.TextExpression):
        kind = text_kind(te.content)
        if kind is None:
            continue
        t_off = float(te.getOffsetInHierarchy(part))
        paired = None
        for sp, f_off, l_off, last in lines:
            if abs(f_off - t_off) <= 1.0:
                paired = (sp, l_off, last)
                break
        if paired is not None:
            sp, l_off, last = paired
            anchor = (chain_release(last, notes)
                      if isinstance(last, m21note.NotRest) else l_off)
            events.append(dict(part=idx, kind=kind, raw_qn=l_off,
                               anchor_qn=anchor,
                               detail=f"text '{te.content}' @{t_off:g} "
                                      f"+ line ->{l_off:g}"))
        else:
            unresolved.append(dict(part=idx, kind=kind, raw_qn=t_off,
                                   detail=f"bare text '{te.content}' "
                                          f"@{t_off:g} (no span end)"))
    return events, unresolved


# ----------------------------------------------------------------- inventory

def inventory(score):
    for idx, part in enumerate(score.parts):
        if idx not in PART_RANGE:
            continue
        sp_hist = Counter(type(sp).__name__
                          for sp in part.recurse()
                          .getElementsByClass(spanner.Spanner))
        te_hist = Counter((te.content or '').strip()
                          for te in part.recurse()
                          .getElementsByClass(expressions.TextExpression))
        ferm = sum(1 for n in part.flatten().notes
                   if any(isinstance(e, expressions.Fermata)
                          for e in n.expressions))
        other_expr = Counter(type(e).__name__
                             for n in part.flatten().notes
                             for e in n.expressions
                             if not isinstance(e, expressions.Fermata))
        print(f"\n[part {idx}] {part.partName}")
        print(f"  spanners : {dict(sp_hist) or '-'}")
        print(f"  fermatas : {ferm}   other note-expr: "
              f"{dict(other_expr) or '-'}")
        print(f"  texts    : {dict(te_hist) or '-'}")


# ------------------------------------------------------------------ coverage

def load_points(path):
    d = json.load(open(path))
    out = defaultdict(list)
    for p in d.get('per_part', []):
        for b in p.get('boundaries', []):
            q = b.get('time_quarter_notes', b.get('qn'))
            if q is not None:
                out[int(p['index'])].append(float(q))
    return out


def load_bans(path):
    d = json.load(open(path))
    out = defaultdict(list)

    def walk(obj, part_hint=None):
        if isinstance(obj, dict):
            hint = obj.get('index', obj.get('part', part_hint))
            for k, v in obj.items():
                if k == 'removed_points' and isinstance(v, list):
                    for r in v:
                        q = (r.get('time_quarter_notes', r.get('qn'))
                             if isinstance(r, dict) else r)
                        if q is not None and hint is not None:
                            out[int(hint)].append(float(q))
                else:
                    walk(v, hint)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, part_hint)
    walk(d)
    return out


def near(q, pool, tol):
    return any(abs(q - x) <= tol for x in pool)


def coverage(events, unresolved, gt, run, bans, tol, mmap):
    misses = {i: [q for q in gt.get(i, [])
                  if not near(q, run.get(i, []), tol)]
              for i in PART_RANGE}
    n_miss = sum(len(v) for v in misses.values())
    print(f"\nGT misses at tol {tol}: {n_miss} "
          f"(expect 62 vs the E0c run)")

    tally = Counter()
    claimed = defaultdict(set)
    print("\n== events ==")
    for ev in sorted(events, key=lambda e: (e['part'], e['anchor_qn'])):
        i, a = ev['part'], ev['anchor_qn']
        if near(a, misses[i], tol):
            status = 'CLAIMS-MISS'
            for q in misses[i]:
                if abs(q - a) <= tol:
                    claimed[ev['kind']].add((i, round(q, 3)))
        elif near(a, run.get(i, []), tol):
            status = 'matches-run'
        elif near(a, misses[i], 1.0):
            status = 'NEAR-MISS(<=1qn)'
        else:
            status = 'novel'
        banned = ' **ON-BANNED-POINT**' if near(a, bans.get(i, []), tol) \
            else ''
        tally[(ev['kind'], status)] += 1
        if status != 'matches-run' or banned:
            print(f"  p{i} {ev['kind']:9s} anchor {a:8g} "
                  f"({fmt_qn(a, mmap):12s}) {status}{banned}  "
                  f"[{ev['detail']}]")

    print("\n== unresolved (bare text, logged only) ==")
    for u in unresolved:
        print(f"  p{u['part']} {u['kind']:9s} {u['detail']} "
              f"({fmt_qn(u['raw_qn'], mmap)})")
    if not unresolved:
        print("  none")

    print("\n== summary (kind x status) ==")
    for (kind, status), n in sorted(tally.items()):
        print(f"  {kind:9s} {status:16s} {n}")
    print("\n== prediction band input ==")
    for kind in ('fermata', 'dim_end', 'cresc_end', 'rall_end'):
        pts = claimed.get(kind, set())
        print(f"  {kind:9s} claims {len(pts)} distinct GT misses"
              + (f": {sorted(pts)}" if pts else ""))


# ----------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('score')
    ap.add_argument('--inventory', action='store_true')
    ap.add_argument('--gt')
    ap.add_argument('--run')
    ap.add_argument('--gt-full', dest='gt_full')
    ap.add_argument('--tol', type=float, default=0.1)
    args = ap.parse_args()

    score = converter.parse(args.score)
    if args.inventory:
        inventory(score)
        return

    if not (args.gt and args.run):
        sys.exit("coverage mode needs --gt and --run "
                 "(or use --inventory)")
    mmap = build_measure_map(score)
    events, unresolved = [], []
    for idx, part in enumerate(score.parts):
        if idx not in PART_RANGE:
            continue
        ev, un = extract_part_events(part, idx)
        events += ev
        unresolved += un
    gt = load_points(args.gt)
    run = load_points(args.run)
    bans = load_bans(args.gt_full) if args.gt_full else {}
    if args.gt_full and not any(bans.values()):
        print("NOTE: --gt-full parsed but no removed_points found; "
              "ban check inactive (schema mismatch?)")
    coverage(events, unresolved, gt, run, bans, args.tol, mmap)


if __name__ == '__main__':
    main()
