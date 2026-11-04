#!/usr/bin/env python3
"""
patch_ALGORITHM_F1c_provisional.py   (2026-09-02)

Documentation patch for ALGORITHM.md, covering everything found during the
F1b validation and F1c diagnosis sessions.

PROVISIONAL. Split deliberately into two classes:

  FINAL      -- findings already measured or read from source. These are
                correct regardless of what the F1c(a) validation run does.

  PENDING    -- anything that depends on the C1 result or on the Oboe
                m.86 b4.75 GT correction. Written as explicit
                "PENDING (2026-09-02)" blocks carrying the pre-registered
                band, so the document never states a prediction as a result.
                Grep for "PENDING (2026-09-02)" after C1 to find them all.

Applies against the 1353-line merged ALGORITHM.md (post patch_F1b merge).
Every hunk aborts with its tag if the anchor is missing; nothing is written
on a partial match.

Usage:
    python patch_ALGORITHM_F1c_provisional.py [--in ALGORITHM.md] [--out ALGORITHM.md]
"""

import argparse
import io
import os
import sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', default='ALGORITHM.md')
    ap.add_argument('--out', dest='dst', default=None)
    args = ap.parse_args()
    dst = args.dst or args.src

    if not os.path.exists(args.src):
        sys.exit('ABORT: %s not found' % args.src)
    s = io.open(args.src, encoding='utf-8').read()

    if 'PENDING (2026-09-02)' in s:
        sys.exit('ABORT: %s already patched.' % args.src)

    applied = []

    def rep(tag, old, new, count=1):
        nonlocal s
        n = s.count(old)
        if n != count:
            sys.exit('ABORT [%s]: expected %d occurrence(s), found %d.\n'
                     'Document has drifted. Nothing written.' % (tag, count, n))
        s = s.replace(old, new)
        applied.append(tag)

    # ================================================================ §0
    rep('A1 roadmap D1',
"| **D1** | Typed channels `{change, endpoint, continuation}` — the keystone | Not started. **E leans on it; F1b did not** — F1b shipped without typed channels |",
"| **D1** | Typed channels `{change, endpoint, continuation}` — the keystone | Not started. **E leans on it; F1b did not.** Now also the general form of a defect hit three times — see §7 |")

    rep('A2 roadmap F1c',
"| **F1c** | Slur mask edge convention — open at both ends | Not started; two independent patches, probe first (§16b) |",
"""| **F1c** | Slur edge semantics — three stages (§16b) | **(a)** endpoint bump at chain release: patched, validation PENDING (2026-09-02). **(b)** mask 0 at slur start, **(c)** mask to chain release: specified |""")

    rep('A3 roadmap trumpet',
"| — | Trumpet-48 trace (every drop must log) | Open invariant violation |",
"""| — | Trumpet-48 trace (every drop must log) | **Resolved 2026-09-02** — `boundary_target_info[6][0]` shows qn 48 resolving cleanly (`fallback_previous_note`, not in a rest) and the audit passes it. The original violation, whatever it was, is not reproducible on B3 |
| — | Short-phrase removal records name no endpoint | Open provenance gap (§14, §15b) |""")

    # ================================================================ §7
    rep('B1 e0 box',
"""> A separate annotation bug (target chosen by onset proximity) had been
> silently compensating, which is why months of eye-approved renders looked
> right. §14 is the repair.""",
"""> A separate annotation bug (target chosen by onset proximity) had been
> silently compensating, which is why months of eye-approved renders looked
> right. §14 is the repair.

> **The repair was partial, and this is the document's most load-bearing
> correction (2026-09-02).** E0 fixed *boundaries*, downstream, by anchoring.
> It never fixed the *projections*. And §13 case 2 can only shift a boundary
> when `max(Long, Gap) > ev_min`, which is unreachable for a phrase ending on
> a short slurred note: `Long = 0` because `dur < d_min`, `Gap = 0` because
> the music continues attacca. Such a boundary is stranded at the onset with
> no mechanism able to move it.
>
> Three instances of the same defect are now on record:
>
> | # | Channel | Found | Fixed by |
> |---|---|---|---|
> | 1 | `Long`, `Gap`, `Lambda` | E0 | anchoring, downstream |
> | 2 | F1 expressive anchors | F1b | F1b(a), deferral at extraction |
> | 3 | `SlurEnd` endpoint bumps | F1c | F1c(a), projection at the release |
>
> These are not three bugs. They are one missing distinction: **a channel
> marking a *change* belongs at the onset; a channel marking an *endpoint*
> belongs at the release**, and nothing in the code records which is which.
> That is exactly D1's `{change, endpoint, continuation}` typing (§18). D1 is
> filed as a keystone for E; it is equally the general form of this defect.
>
> **Every remaining channel in §8's table needs an onset-or-release audit.**
> Until that is done, assume any endpoint-like channel is wrong until checked.""")

    # ================================================================ §8
    rep('C1 slurend row',
"| `SlurEnd_i(t)` | slur **end** offsets | boost |",
"| `SlurEnd_i(t)` | slur end — last slurred note's **onset**; its tie-chain **release** under `--slur_end_release` (F1c(a), default off) | boost |")

    rep('C2 fm4',
"""> **Failure mechanism 4 (F1c).** The slur interval `[first onset, last onset)`
> is wrong at **both** edges against breath semantics, in opposite directions.
> At `first onset` the mask reads 1, penalising a breath placed *before* the
> slurred phrase — which does not split it. At `last onset` the mask reads 0,
> permitting a breath that *detaches the final slurred note*, and it stops
> short of the chain release, where a breath is legitimate. Both errors are
> observed on Liz. The correct interval is the **open** interval
> `(first onset, chain release)`. Repair specified in §16b.""",
"""> **Failure mechanism 4 (F1c).** The slur interval `[first onset, last onset)`
> is wrong at **both** edges against breath semantics, in opposite directions.
> At `first onset` the mask reads 1, penalising a breath placed *before* the
> slurred phrase — which does not split it. At `last onset` the mask reads 0,
> permitting a breath that *detaches the final slurred note*, and it stops
> short of the chain release, where a breath is legitimate. Both errors are
> observed on Liz. The correct interval is the **open** interval
> `(first onset, chain release)`. Repair specified in §16b(b), §16b(c).

> **Failure mechanism 5 (F1c(a)).** `endpoints_raw[end_idx] = 1.0` places the
> bump at the last slurred note's **onset**. The breath goes after that note.
> Confirmed six for six by `explain` on `liz_seam_B3_all` — in every case the
> boundary sits at the onset of a note carrying `slur_end`, GT is that note's
> release, and `slur_endpoint_bump` (0.403–0.978) exceeds `B_raw`:
>
> | Part | Run lands | dur | release | GT |
> |---|---|---|---|---|
> | Fl2 | 203.50 | 0.50 | 204.0 | m.51 end |
> | Ob | 295.75 | 0.25 | 296.0 | m.74 end |
> | Ob | 319.75 | 0.25 | 320.0 | m.80 end |
> | Ob | 381.80 | 0.20 | 382.0 | m.93 b15 |
> | Fl1 | 147.00 | 1.00 | 148.0 | m.37 end |
> | ASax | 171.00 | 1.00 | 172.0 | m.43 end |
>
> `Long = 0` in all six (`min((dur−1.0)/1.5, 1)`; the two at exactly 1.00 give
> zero) and `Gap = 0` in all six (next note begins at the release). So §13
> case 2 declines every shift and anchoring cannot reach them. Repair is
> `patch_F1c_slur_release.py`, §16b(a).

> **`slur_starts` and `slur_ends` are NOT index-parallel.** They are appended
> under separate `not start_nested` / `not end_nested` conditions and returned
> independently `sorted()`. Zipping them pairs one slur's start with another's
> end and truncates the tail. `phrase_spans`, added by the same patch, carries
> real `(start, end, release)` triples; nothing may zip the two lists again.""")

    # ================================================================ §13
    rep('D1 s13 note',
"""> **Scoped exception to the E0c ruling.** `HANDOVER_sectioning_v2_10_E0c.md` §3""",
"""> **Case 2 cannot rescue slur-end boundaries, by construction.** The predicate
> requires arrival evidence, and a phrase ending on a short slurred note has
> none: `Long = 0` for `dur < d_min = 1.0`, and `Gap = 0` whenever the music
> continues attacca. This is why F1c(a) moves the *projection* rather than
> adding a case here — no conditioning of this rule could reach those six
> boundaries (§8 Failure mechanism 5).

> **Scoped exception to the E0c ruling.** `HANDOVER_sectioning_v2_10_E0c.md` §3""")

    # ================================================================ §14
    rep('E1 fm3',
"""> **Failure mechanism 3.** An all-rest span has `sounding_sec = 0` and
> `count = 0`, so it is treated as a fragment and triggers a removal. It is not
> a fragment; it is silence between two legitimate sections.""",
"""> **Failure mechanism 3 — DIAGNOSIS CORRECTED 2026-09-02.** The mechanism is
> real: an all-rest span has `sounding_sec = 0` and `count = 0` and is treated
> as a fragment. **But the stated conclusion — "it is silence between two
> legitimate sections" — is false on Liz, and the repair it implies would make
> the score worse.**
>
> Census of `liz_seam_B3_all` (`short_phrase_census.py`): 72 removals,
> **30 all-rest**, **0 of which cost a GT point**. A blanket guard would
> reinstate up to 30 boundaries for zero gain and push extras from 37 to ~65.
>
> The reason is visible in the data. Most all-rest removals are at **entry
> instants** — Fl2 qn 54.75 with segment `(0, 54.75]`, Fl1 qn 115.875 with
> `(108, 115.875]` — which the E0c ruling already says to suppress: no comma
> at entry instants, the written rest is the separator. The filter is doing
> correct work there.
>
> The wrong case is narrow: a boundary at the **start** of an all-rest span,
> i.e. a phrase ending followed by silence. Only two on Liz, both Harp lower
> (m.7 b3.5 and m.34 b3), and **neither presents as all-rest to the filter**
> because of the ordering bug below.
>
> Correct repair is therefore three coupled changes, none of which works
> alone:
>   1. record `segment_start_qn` / `segment_end_qn` / `removed_side`;
>   2. run anchoring **before** the filter;
>   3. never remove the boundary that *opens* an all-rest span.
> Total value: 2 exact points. Priority accordingly low.

> **Stage order is the reverse of §22's summary.** `postprocess_short_phrases`
> is called at line ~3162, `release_anchor_boundaries` at ~3182. The filter
> therefore measures segments using **unanchored** boundary times, which are
> systematically early by up to one note duration — the E0 family again, one
> stage later. Harp lower qn 26.25 is the worked case: the early boundary sits
> inside a note, so its segment picks up a 0.25 qn sliver and reads
> `note_count = 1` instead of `0`.

> **The removal record names no endpoint.** `postprocess_short_phrases` logs
> the removed time plus `compute_phrase_material(prev, cur)` for the flagged
> segment, but not which endpoint was removed — `remove_idx` is `idx` or
> `idx-1` depending on `selection_score`. The segment cannot be reconstructed
> from the log. Same species as Trumpet-48: a record that exists but is not
> sufficient to reverse-engineer the decision (§1, full provenance).""")

    # ================================================================ §15
    rep('F1 tools',
"""- `annotation_check.py` — rendered score versus `boundaries.json`.
- Every patch ships a **simulated, falsifiable diff band**. Materially outside
  the band: stop.""",
"""- `annotation_check.py` — rendered score versus `boundaries.json`.
- `score_geometry_check.py` — measure durations against their time signatures,
  per-part totals, and cross-file offset divergence. Separates float
  accumulation (~1e-5 qn) from real corruption (a 32nd is 0.125). Run it
  before trusting any derived or hand-edited score.
- `drop_trace.py` — traces a part/time through every stage that can move or
  remove a boundary, since the records are scattered across four `result.pkl`
  keys with different shapes.
- `short_phrase_census.py` — every short-phrase removal scored against GT,
  netting out reinstatements by anchoring.
- `slur_release_probe.py` — boundaries sitting at a slur's last-note onset,
  and whether GT sits at the onset or the release.
- Every patch ships a **simulated, falsifiable diff band**. Materially outside
  the band: stop.

> **Recorded override, 2026-08-19.** F1b(b)'s B1 run exceeded its band (six
> declines across four parts, predicted two in one). We did not stop. Four of
> six were gains and both anomalies were traced to root cause in-session. That
> was a judgement call, logged here so it does not become silent precedent.

> **PENDING (2026-09-02).** The exact-match figures above are stated against a
> 263-point GT. The Oboe m.86 b4.75 correction takes GT to 262 and moves that
> point into `removed_points`; the run currently sits on it, so expect
> 195/263 → 194/262 and audit 82 → 83 FAIL *before* F1c(a) lands. Re-baseline
> `liz_seam_B3_all` against the regenerated GT and replace these numbers.""")

    # ================================================================ §15b
    rep('G1 anchor sets',
"""### Module-level state leak

`_F1_ANCHOR_SETS` is a module-level dict populated by `_f1_build_release_grids`
and read by the conditioned seam shift. It is never cleared. Harmless for a
single CLI invocation; wrong the moment `run_sectioning` is called twice in one
process, when run 1's anchors silently leak into run 2's seam decisions. Same
species as the unserialized `delta_repetition` that motivated S0. One-line fix:
`_F1_ANCHOR_SETS.clear()` at the top of `_f1_build_release_grids`.""",
"""### Module-level state leak — CLOSED 2026-09-02

`_F1_ANCHOR_SETS` was a module-level dict, never cleared, so a second
`run_sectioning` call in one process would leak run 1's anchors into run 2's
seam decisions. Fixed by `_F1_ANCHOR_SETS.clear()` at the top of
`_f1_build_release_grids` (line ~2391), and the call site at line ~3020 is
confirmed **unconditional** — no weight guard that could skip the clear.
Retained here as precedent: module-level mutable state shared "to avoid
threading an argument through every call site" needs an explicit reset, the
same lesson as the unserialized `delta_repetition` that motivated S0.""")

    rep('G2 diagnostic',
"""### The diagnostic disagrees with the pipeline

`_f1_explain_slur_status` reported **no flag** at Oboe m.93 b9 (covered by slur
370 → 376; the deferral fired) and **"INSIDE SLUR"** at Cl2 m.18 end (a slur
*start*; the deferral correctly did not fire). The pipeline is right in both
cases and the diagnostic is wrong in both directions, because it uses the
half-open convention while the deferral uses the open one. Fix before F1c, or
F1c will be audited against a bad readout. Once §16b lands, mask, deferral and
explain must all call **one** predicate.""",
"""### The diagnostic disagreed with the pipeline — CAUSE CORRECTED 2026-09-02

`_f1_explain_slur_status` reported **no flag** at Oboe m.93 b9 (covered by slur
370 → 376; the deferral fired) and **"INSIDE SLUR"** at Cl2 m.18 end (a slur
*start*; the deferral correctly did not fire) — wrong in both directions while
the pipeline was right in both.

An earlier revision of this section blamed a half-open/open convention
mismatch. **That was wrong.** Reading the source: `slur_starts` and
`slur_ends` are appended under separate `not start_nested` / `not end_nested`
conditions in `extract_slur_indicators` and returned independently `sorted()`.
Two callsites zipped them —

    line ~2102  `_f1_explain_slur_status`  "AT LAST-SLURRED-NOTE ONSET"
    line ~3899  `explain`                  "Currently INSIDE slur(s)"

— pairing one slur's start with an unrelated slur's end, and `zip` truncating
to the shorter list so tail entries vanished silently. Oboe 381.8 disappearing
from `slur_release_probe.py`'s first run was the same truncation.

Fixed by `phrase_spans`, real `(start, end, release)` triples, in
`patch_F1c_slur_release.py`. Diagnostics only — no pipeline output ever
depended on the zip. **Lesson: a diagnostic that contradicts the pipeline is
evidence about the diagnostic first.** Two turns were spent theorising about
convention semantics before anyone read the function that built the lists.

### Data-structure inference is not free

Four tools written this session returned confidently wrong numbers because
their author guessed a `result.pkl` schema instead of reading it: a GT loader
keyed on `parts` when the file uses `per_part` (reported "0 GT points lost",
the answer being 2); a segment-material recomputation that disagreed with the
pipeline's own recorded fields; a `per_part_boundaries` reader that rejected
ndarray and printed "0 final boundaries"; and a slur-span builder that zipped
the two non-parallel lists above. Standing rule: **read the writer before
reading the data**, and have any new probe dump the schema it depends on
before it reports anything.""")

    # ================================================================ §16b
    rep('H1 f1c head',
"## 16b. F1c — slur mask edge convention (specification)",
"""## 16b. F1c — slur edge semantics

Three stages against one defect family. File letter `F1c` covers all three,
following the F1b precedent where (a)(b)(c) shipped together and (d) trailed.

| Stage | Change | Status |
|---|---|---|
| **(a)** | endpoint bump at the chain release | patched, validation PENDING (2026-09-02) |
| **(b)** | mask 0 at slur start (was "F1c-left") | specified below |
| **(c)** | mask extends to chain release (was "F1c-right") | specified; re-probe after (a) |

---

### (a) Endpoint bump at the chain release — `patch_F1c_slur_release.py`

Diagnosis in §8 Failure mechanism 5; why anchoring cannot substitute, in §13.
`endpoints_raw[end_idx]` becomes `endpoints_raw[release_idx]` under
`--slur_end_release`, default off, using `_slur_chain_release`, which mirrors
`_rel` in `_f1_extract_part_events` so bump, deferral and mask share one
definition.

The same patch adds `phrase_spans` unconditionally (§15b). That half is
diagnostics-only, so the control run must be identical to `liz_seam_B3_all`
apart from the new serialized key.

**PENDING (2026-09-02) — pre-registered band, from `slur_release_probe.py`:**

```
boundaries at a slur last-note onset   13   (undercount: zip truncation)
GT at the RELEASE  -- gain              6
GT at the ONSET    -- loss              1   (Ob 343.75, being deleted from GT)
neither position is GT                  6
```

Four of the six gains also vacate a banned position (Fl1 m.37 b4, Fl2 m.51
b4.5, Ob m.37 b4, ASax m.43 b4), and two "churn" rows clear a banned position
without touching a GT point (Fl2 199.5, Ob 339.75). Fl2 319.75 → 320.0 may
also clear `gtv2_ensemble_seam_m80_end`.

    expected  +6 required, +6 banned = ~12 audit points; +5 exact
    materially outside this band -> STOP

Replace this block with the measured C1 result.

---

### (b) and (c) — the mask edges""")

    rep('H2 f1c body',
"""### The defect

See Failure mechanism 4 (§8). Summary:""",
"""See Failure mechanism 4 (§8). Summary:""")

    rep('H3 f1c two',
"""### Two patches, not one — opposite risk

- **F1c-left** — mask 0 at slur start. *Permissive*: only unmasks instants
  currently penalised. Can add boundaries, cannot remove any. Recovers Cl2
  m.18 end, the eighth audit flip.
- **F1c-right** — extend to chain release. *Restrictive*: newly masks the last
  slurred note's onset **and its entire interior**. Can silently kill
  boundaries that currently pass, including GT ones.""",
"""### Two patches, not one — opposite risk

- **(b)** — mask 0 at slur start. *Permissive*: only unmasks instants
  currently penalised. Can add boundaries, cannot remove any. Recovers Cl2
  m.18 end, the eighth audit flip.
- **(c)** — extend to chain release. *Restrictive*: newly masks the last
  slurred note's onset **and its entire interior**. Can silently kill
  boundaries that currently pass, including GT ones.

> **(c) may be redundant after (a).** Moving the positive evidence off the
> last-note onset removes the peak that (c) exists to suppress. Shipping both
> risks double-correcting the same displacement. Re-probe after C1 and only
> then decide. `phrase_spans` already carries the release values (c) needs, so
> no second extraction pass is required.""")

    # ================================================================ §22
    rep('I1 summary order',
"""11  re-anchor onset-landed boundaries to note releases (one step, gated)
12  filter degenerate segments; validate rests and outgoing ties;
    resolve breath targets""",
"""11  filter degenerate segments            <- line ~3162, runs FIRST
12  re-anchor onset-landed boundaries to note releases (one step, gated)
                                           <- line ~3182
13  validate rests and outgoing ties; resolve breath targets""")

    # ================================================================ §22b
    rep('J1 measure map',
"""**The audit's measure map derives from `gt_rendered.musicxml`.** That is the
hand-edited GT render, carrying the m.73 corruption (partially fixed) and the
unresolved harp m.66 overshoot. Part 8 output prints `m.73 b4.99997`, precisely
where the corruption sat. Probably float noise, but the measure map should
arguably come from the pipeline's own input rather than a derived, hand-edited
artifact.

**`gt_rendered.musicxml` must not be recompiled** until the harp m.66 overshoot
is resolved.""",
"""**`gt_rendered.musicxml` is clean — caveat withdrawn 2026-09-02.**
`score_geometry_check.py` against the source score: every measure in every
part matches its time signature, all eleven parts total 390.0 qn, and
cross-file offset divergence is **exactly 0.000e+00**. The `m.73 b4.99997`
in audit output is 3e-5 qn of float accumulation, four orders of magnitude
away from the 0.125 qn stray-32nd drift, and is consistent with that fix
having worked. The harp m.66 overshoot does not reproduce. The
"do not recompile" instruction is void and the GT render loop is open again.

The check did find two under-filled bars in the **source** score, Harp lower
m.7 (content ends 2.5 into a 4.0 bar) and m.34 (2.0 into 4.0) — MusicXML
`<forward>` with no rest object. Cosmetic: offsets and totals are unaffected,
and the pipeline builds gaps from note offsets, so it reads them correctly.
Both were briefly suspected of causing the two Harp-lower GT misses at
qn 26.5 and 134.0; `explain` refuted that — evidence there is strong
(`B_i` 0.626 and 0.506 against a 0.30 gate) and the cause is §14's filter.

**GT correction, Oboe m.86 b4.75 (qn 343.75).** GT placed a breath at the
onset of a slur's last note, contradicting the §23 ruling. Robert's call: the
mark is a mistake, being removed from `gt_rendered.musicxml`. Consequences are
tracked in the PENDING block in §15.""")

    io.open(dst, 'w', encoding='utf-8').write(s)
    print('wrote %s' % dst)
    for t in applied:
        print('  applied %s' % t)
    print('\nAfter C1, grep for:  PENDING (2026-09-02)')
    print('  §15   exact-match figures against the 262-point GT')
    print('  §16b  replace the band with the measured result')
    print('  §0    F1c(a) status')
    print('Still to add once ruled: §23 entry for Oboe m.86 b4.75.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
