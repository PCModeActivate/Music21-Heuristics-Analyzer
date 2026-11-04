# Explainable phrase sectioning for polyphonic symbolic scores

**Status:** v2.11-A, 4 November 2026 · **Code:** `sectioning_v2_11_A.py` (branch `v2`)
**Development log and full derivations:** `ALGORITHM.md` · **Handover:** `HANDOVER_v2_11_A_2026-11-04.md`

All mathematics is plain text, readable in any viewer.

---

## 1. What it does

Given a MusicXML score, the sectioner proposes, **for every part
independently**, the instants where that part's phrase ends, i.e. where a
player would breathe or a phrase would break. It writes them as breath marks
(red commas) into a copy of the score and as a JSON list per part.

It exists to give melody detection phrase-level segments. It is built to be
**explainable**: every quantity is a closed-form function of score features
with named, serialised parameters. There are no learned weights. Any
boundary can be decomposed into the evidence that produced it, and any
dropped boundary leaves a record.

Two conventions run through everything:

- **A boundary is a release instant.** It is the moment the phrase-final note
  stops sounding, not its attack. The comma is drawn on the note releasing
  there and means "breathe after this note".
- **Boundaries are per part.** Breathing is instrument-local. Ensemble
  agreement is used as evidence and arbitration (§3.7), not as the
  representation.

## 2. Inputs, time base and ground truth

Time is measured in quarter notes (qn) from the start of the score and
discretised at D = 8 frames per qn. Measure/beat is only a display layer;
nothing assumes 4/4.

The development piece is *Liz and the Blue Bird* III (10 parts, 94 measures,
390 qn). Its ground truth (GT) is compiled from a hand-corrected score, which
is the authority:

| Item | Count |
|---|---|
| GT breaths (136 required, 126 kept) | 262 |
| Banned positions (marks deliberately removed in earlier passes) | 54 |
| Unison constraints (sets of parts that must agree) | 4 |
| Hard-violation audit points (required + banned) | 190 |

The held-out piece is Dvořák, Symphony No. 9, IV (excerpt, 15 parts, 608 qn).
It has no GT yet and is evaluated qualitatively (§5.3).

## 3. Method

The pipeline runs per part, in stages. Each stage is listed with its role.
Parameter values are the current defaults.

### 3.1 Note stream

Simultaneous events in a part are grouped into one event. Tied notes, and
same-pitch notes under a slur, are merged into one sustained event before
any interval is computed. Otherwise every tie seam would read as a melodic
event.

### 3.2 Evidence channels

Each channel is a frame signal in [0, 1]. Each is either **change-typed**
(something new begins: it belongs at an onset) or **endpoint-typed**
(something ends: it belongs at a release). Getting this placement right was
the largest single correction in v2.11 (§4.4).

| Channel | What it measures | Type / placement |
|---|---|---|
| Chroma novelty | Checkerboard-kernel novelty on a pitch-class self-similarity matrix (13-d chroma incl. a rest dimension; kernel +/- 4 qn) | change, at the transition |
| Rhythm novelty | Same, on a 3-d attack / sustain / rest feature | change, at the transition |
| LBDM | Cambouropoulos local boundary detection on pitch interval, inter-onset interval and following rest (weights 0.25 / 0.50 / 0.25) | endpoint, at the note's release |
| Long-note arrival | Note length: 0 below 1 qn, saturating at 2.5 qn | endpoint, at the release |
| Following gap | Silence after the note, saturating at 1 qn | endpoint, at the release |
| Slur end | Bump at the last slurred note's chain release | endpoint |
| Structural events | Dynamics, tempo, key and time changes (onset); fermatas (release) | typed per event |
| Cross-part support | Other parts' evidence, borrowed where their rhythm is similar (window 4 qn, cosine >= 0.85, shift <= 0.5 qn) | mixed |
| F1 expressive events | Fermata release (weight 1.0), end of a diminuendo (0.6), at the tie-chain release | endpoint |

### 3.3 Continuation contexts

Slurs, hairpins and tuplets argue *against* a break inside them, so they
damp the signal multiplicatively. Ties are physical identity, so they veto
it:

```
B_raw = 0.20 chroma + 0.35 rhythm + 0.45 LBDM
boost = 0.40 SlurEnd + 0.40 Struct + 0.20 Cross
B     = (B_raw + boost + F1) * (1 - 0.5 hairpin) * (1 - 0.7 slur) * (1 - 0.8 tuplet) * tie_veto
```

Masks cover the inside of a span. A breath at a slur's start or at its
chain release is allowed, and so is a breath before a tied note. Where one
slur ends exactly where the next begins (a *slur seam*), the masks are open.

### 3.4 Candidates, ranking and acceptance

Three scores answer three questions:

```
Cand = max(B, 0.65 * Anchor)          where a candidate may originate
Sel  = B + 0.30 LBDM + 0.30 Long + 0.20 Gap + 0.25 Cross - Penalty   how candidates rank
Acc  = max(B, Sel)                    whether a winner is kept (gate 0.30)
```

`Anchor` is a note-level landing score built from Long, LBDM, Gap and Cross.
`Penalty` is the additive counterpart of the continuation contexts.
Candidates are the local maxima of `Cand` above 0.22 that no tie forbids.

**Grouping: penalise, never ban.** Candidates are accepted greedily by
`Sel`. After each acceptance, every remaining candidate within 6 qn has its
`Sel` and `Acc` scaled by `(distance / 6) ^ 2`. A candidate survives only if
its scaled `Acc` still clears the gate. Breaths close together therefore
need strong evidence, but are never forbidden outright.

### 3.5 Anchoring and filtering

- **Mid-note boundaries** move to the release of the note sounding at them.
- **Entry from silence:** a boundary at the first note after a rest moves to
  that note's release when the note itself carries arrival evidence. The
  written rest is the separator; no comma goes at an entry instant.
- **One note early:** a boundary at the start of a note moves to that note's
  release only when the note just ending is a short passing note (Long <
  0.2) and the next note carries endpoint evidence. It never moves away from
  a slur seam.
- **Short-phrase filter**, run after anchoring: a segment with under 1.25 s
  of sounding material and at most one note is a fragment. The weaker
  neighbouring boundary is removed, ranked by the evidence where it
  originated. Across an all-rest gap, the entry instant is the one removed.

### 3.6 Validation and rendering

A boundary is rejected if it lies strictly inside a rest (a note releasing
there in another voice counts as a seam) or if its note sustains into a tie.
The comma is drawn on the note whose release is the boundary.

### 3.7 Ensemble alignment (arbitration only)

After every part has its boundaries, up to two passes use the other parts'
breaths as evidence. They never create a breath without a candidate of the
part's own:

- **Gate relief:** a part's own candidate that missed the gate, or was
  suppressed by grouping, is accepted at its note release when at least 3
  other parts breathe there and the part has no breath within 3.5 qn. The
  floor is half the gate, or a third of it when at least 5 parts agree.
- **Snap:** a breath moves up to 1.5 qn onto a note release where at least 3
  other parts breathe. This happens only when the part's own `Sel` there is
  at least 0.6 of its `Sel` where it is, and never away from the part's own
  fermata or diminuendo-end anchor.

## 4. What changed in v2.11, and why

Each change was diagnosed from a measured failure and validated on its own,
off by default, before becoming a default.

1. **Failure attribution first.** `fail_trace.py` labels every audit failure
   with the stage that caused it. On the v2.10 baseline, 30 of 51 missed
   required breaths came from *transitive* grouping. Chains of nearby peaks
   collapsed to one winner across up to 29 qn. Replaced by the soft grouping
   of §3.4.
2. **Tie start.** The tie mask included the chain's first onset, which is
   the previous note's release, and so forbade a breath before a tied note.
3. **Filter order.** The short-phrase filter ran before anchoring, on early
   boundary times, and deleted correct phrase ends (including a required
   breath).
4. **Evidence placement.** Measured at 213 GT breaths: LBDM, Long and Gap
   were 85–94% higher at the phrase-final note's *onset* than at its
   release, while novelty and the slur-end bump peaked at the release. The
   misplacement also caused breaths to land one note late, because Long/Gap
   at a correct boundary described the *next* note. All three now project
   at the release (§3.2).
5. **Ensemble alignment** (§3.7) and its own-evidence check. Without the
   check, snapping was break-even. Good and bad snaps separated cleanly by
   the part's own `Sel` ratio (0.74–1.0 vs 0.20–0.48).
6. **Slur seams.** At m.31 end, three parts had one slur ending and the next
   beginning. The start masks turned strong evidence (slur end + diminuendo
   end) into a score of 0.
7. **Rendering.** The comma is always drawn on the note that releases at the
   boundary, never on the note after a rest. On Liz, 300 of 300 commas now
   render correctly.

Approaches tested and rejected are recorded in `ALGORITHM.md` §16c with
their numbers:
- holding a breath before a new dynamic (4 right, 7 wrong);
- unmasking every slur start (pickups out-ranked real breaths, −13 GT);
- hard spacing at 2.5, 3.9 or 4 qn;
- guarding every slur release in the one-note-early rule;
- a vote between rhythmically identical parts (helps Dvořák's agreement,
  costs Liz 8 conflicts).

## 5. Evaluation

### 5.1 Measures

| Measure | Meaning |
|---|---|
| Exact | GT breaths matched by a run boundary in the same part within 0.1 qn (of 262) |
| Extras | Run boundaries matching no GT breath (conflicts) |
| Audit | Pass/fail on the 190 hard points (required present, banned absent) |
| Unison | Violated unison constraints (of 4) |
| Objectionable | Required breaths missed + banned positions hit + breaths the reviewer objected to. Banned positions the reviewer later accepted are not counted |

"Objectionable" is the measure that matters most for usability. A conflict
with GT is not necessarily wrong: many were reviewed and judged acceptable.
Conflicts nobody has reviewed are not in the count, so it is a lower bound
for runs with unreviewed breaths.

### 5.2 Liz (development piece)

| Configuration | Exact | Extras | Audit P/F | Unison | Objectionable |
|---|---|---|---|---|---|
| v2.10 B3 | 194 | 49 | 107/83 | 3 | 85 |
| v2.10 C1 (+ slur end at release) | 198 | 40 | 128/62 | 3 | 64 |
| + tie start, filter order, hard grouping at 4 qn (F3) | 214 | 61 | 151/39 | 2 | 53 |
| + evidence placement, soft grouping | 209 | 56 | 155/35 | 1 | 38 |
| + ensemble alignment, one-note-early rule (X6) | 231 | 64 | 168/22 | 0 | 26 |
| **+ slur seams (X7, current default)** | **237** | **63** | **171/19** | **0** | **22** |

Recall against GT rose from 76% to 90%; precision moved from 83% to 79%. All four
unison constraints now hold. The remaining 22 are 16 missed required breaths
and 6 reviewer objections:

| Remaining | Count |
|---|---|
| Lower harp, little evidence of its own | 5 |
| Bar-by-bar passages: one breath of a pair missing | 6 |
| One note early | 2 |
| Single cases (Oboe m.93 quintuplets and tied final note; Harp-up m.61 b3) | 3 |
| Reviewer objections (2 present since v2.10, 4 introduced with the newer grouping) | 6 |

### 5.3 Dvořák 9/IV (held-out, no GT)

The default configuration runs unchanged on the 15-part excerpt in about a
minute. Compared with the v2.10 settings: 777 boundaries vs 553, the same
median spacing (8 qn), and same-part gaps under 4 qn fall from 33 to 2.

`ensemble_report.py` measures agreement across parts. For m.1–35: 37 breath
instants, 16 unison (at least 60% of sounding parts), 10 partial, 11 lone.

Reviewer assessment of m.1–35: mostly serviceable for melody detection, a
little extraneous. Specifically:

- **Found:** the tutti unison breaths (m.9 end 14 of 15 parts; m.13, m.15,
  m.19, m.23 b2 12–13 of 15; m.25 b3.5 13 of 15).
- **Right:** the theme-carrying brass phrasing on their own (Horns III–IV,
  Trumpets, Trombone III at m.12 b3, m.15 end, m.19 b2.5, m.23 b2.5).
- **Wrong, in the strings-only passages:**
  - m.5: Violin I has no breath, and Violin II has an extraneous one.
  - m.26–27: Violins I and II and Cello should breathe only at the end of
    m.25.
  - m.31–32: should be one unison breath at the end of m.31; the run splits
    it between m.31 end and m.32 b3.

## 6. Limitations

- **Fitted to one piece.** Several thresholds were chosen on a handful of Liz
  cases:
  - the grouping radius and power;
  - the ensemble support counts;
  - the 0.6 own-evidence ratio;
  - the Long < 0.2 short-note test.

  Dvořák is the first independent check and has no GT.
- **Ensemble support is a count, not a share.** "3 other parts" is a much
  lower bar with 15 parts than with 10. On Dvořák the ensemble pass made 156
  changes.
- **Doubled lines are not recognised as one phrase.** Parts playing the same
  material can breathe at different points (the Dvořák strings). A plain
  rhythm-identity vote did not fix it and hurt Liz.
- **Entry instants after short rests.** On Dvořák, a boundary sometimes sits
  at the first note after a short rest. The comma is drawn on the note before
  the rest, which is musically sensible, but the stored time is one rest late.
- **Frame grid.** At 8 frames per qn, quintuplets (0.2 qn) cannot be
  represented exactly.
- **Defaults live on the command line.** Code calling `run_sectioning()`
  directly still gets the v2.10 behaviour.

## 7. Using it

Run with the current defaults:

```bash
python sectioning_v2_11_A.py SCORE.mxl -o OUTPUT_DIR
```

It writes `sectioned.musicxml` (commas drawn), `boundaries.json` (per-part
boundary times) and `result.pkl` (every signal and decision). Each mechanism
can be switched off with its `--no-...` form, and `--legacy_defaults`
reproduces v2.10 exactly.

Inspection tools, all reading the run directory:

| Tool | Purpose |
|---|---|
| `score_run.py RUN` | Exact, extras, audit, unison, objectionable, failure causes |
| `violations_report.py RUN` | Every objectionable breath, with the note it is on and its cause |
| `ensemble_report.py RUN` | Agreement of breaths across parts; works without GT |
| `explain.py RUN PART --time QN` | Evidence decomposition at one instant |
| `fail_trace.py`, `group_trace.py` | Stage attribution and grouping replay (`--verify`) |
| `review_list.py BASE NEW` | Breaths new relative to a base run, as a review sheet |
