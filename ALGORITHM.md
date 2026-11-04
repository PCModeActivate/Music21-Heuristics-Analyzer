# Sectioning: an explainable algorithm for phrase/section boundary detection in polyphonic symbolic music

**Pipeline version:** `sectioning_v2_11_A.py`. Since 2026-11-04 its CLI defaults are the X7 configuration (§16c(13)); `--legacy_defaults` reproduces `sectioning_v2_10_F1c.py` exactly. Validated reference kept untouched: `sectioning_v2_10_F1b.py`.
**Reference runs:** B3 — `--f1_fermata_weight 1.0 --f1_dim_end_weight 0.6 --rest_seam_policy seam`; C1 — B3 + `--slur_end_release`. v2.11-A candidates in §16c.
**Reference outputs:** `output_v2_10_F1b/liz_seam_B3_all`, `output_v2_10_F1c/liz_seam_C1_slur_release` (regenerable; not in git)
**Input:** `Liz_and_the_Blue_Bird_III-1.2_colored.mxl` (sha256 `2f4090f999e36d64…`), music21 10.5.2 reproduces every number here
**Test score:** *Liz and the Blue Bird III*, 10 parts, 94 measures, 390 qn
**Held out:** Dvořák 9/iv — unsealed 2026-11-04 for a first qualitative run (no GT yet; §16c(15))
**Last revised:** 2026-11-03 — F1c(a) measured (PENDING blocks filled); v2.11-A structural fixes (§16c); two experiments rejected and recorded

> All mathematics below is written in plain text inside code blocks. No LaTeX,
> no math-renderer dependency: it reads identically in GitHub, a plain editor,
> `cat`, and every markdown viewer.

---

## 0. Roadmap status — the whole letter set

File letters (`v2_10_A/B/.../F1`) track **delivery batches**. Roadmap letters
track **features**. They do not correspond. This table is the roadmap.

| Item | Feature | Status |
|---|---|---|
| **A** | Phrase material / shape report (`phrase_material.py`) | **Done**, passive — nothing consumes the flags yet |
| **B** | Chroma interval-kernel switch (`--chroma_kernel interval`) | **Delivered, musically untested** — rides along any run free |
| **C** | Same-offset polyphonic event grouping (`--lbdm_polyphony_mode`) | **Done and applied** |
| **D** | Structural/gesture events: dedup + fermata extraction | **Done** |
| **D1** | Typed channels `{change, endpoint, continuation}` — the keystone | Not started. **E leans on it; F1b did not.** Now also the general form of a defect hit three times — see §7 |
| **E** | Conditional ensemble alignment (snap arbitration + shape veto) | Not started |
| **E1** | Cross-support attribution (which part lent evidence, at what similarity) | **Shipped** in `v2_10_D` |
| **F** | Gesture endpoint targeting | **F1 and F1b shipped and validated** (§11, §16). F1b(d) lexicon completion outstanding |
| **F1c** | Slur edge semantics — three stages (§16b) | **(a)** endpoint bump at chain release: **measured** (C1: audit 128/62, exact 198/262), `--slur_end_release` default off pending Robert's call. **(b)** mask 0 at slur start: **tried, rejected** 2026-11-03 (§16c). **(c)** mask to chain release: specified, not built |
| **v2.11-A** | Structural fixes from `fail_trace.py` (§16c) | `--peak_grouping nms` (FM2), `--tie_open_start`, `--filter_after_anchor` (FM3): **shipped default off**, measured; defaults await the review lists in `review/` |
| **G0** | One-note wedge spans the note's duration | **Done** |
| **G1/G2** | Direction-text lexicon, Line-spanner association, unclassified-text report, rehearsal marks | **Partly absorbed by F1**; report + rehearsal marks outstanding (§17) |
| **H** | Ornament continuation spans (trill / tremolo / glissando) | Not started, probe first, default-off (§20) |
| **S0/S1** | Provenance hardening: `all_knobs` + input sha256; `rest_seam_policy` flag | **Shipped** |
| — | Repetition-mask retrial (instrumented) | Authorised, default 0.0 (§21) |
| — | Breathability limit (physical seconds) | Not started (§19) |
| — | Trumpet-48 trace (every drop must log) | **Resolved 2026-09-02** — `boundary_target_info[6][0]` shows qn 48 resolving cleanly (`fallback_previous_note`, not in a rest) and the audit passes it. The original violation, whatever it was, is not reproducible on B3 |
| — | Short-phrase removal records name no endpoint | **Closed** — records carry `segment_start_qn`, `segment_end_qn`, `removed_side` (verified in B3 and C1 pickles, 2026-11-03) |
| — | `gt_from_score.py` drops prior bans on recompile | **Fixed** 2026-11-03 (`89c3551`); recompiling against the 09-02 GT reproduces it exactly |

Sequencing constraint: **F must stabilise, then E.** Dvořák stays sealed
until Liz is stable through both.

---

## 1. Explainability contract

Every quantity below is a **closed-form function of score-derived features**
with **named, serialized parameters**. No learned weights, no latent
representations, no gradient-fit components. Consequences that are
load-bearing:

- Any boundary decomposes into its channel contributions at a single frame
  (`explain.py`, ~2 ms against `result.pkl` versus ~9.6 s for a rerun).
- Any parameter change is a diff against a previous run (`boundaries_diff.py`).
- Any dropped boundary leaves a record.

Standing invariants:

| Invariant | Statement |
|---|---|
| **Penalize, never ban** | Entry-onset boundaries and their kin are down-weighted, never hard-removed. A fermata whole note between long rests is a legitimate one-note section. |
| **Arbitration, not generation** | Event neighbourhoods and ensemble alignment may *move* or *rank* a boundary. They may never *create* one. |
| **Default-off** | Every new mechanism ships at weight 0.0 for one validation run before earning a nonzero default. Bug-fix completions are exempt, and say so. |
| **Release semantics** | A boundary time is the **release instant** of the phrase-final note, not its attack. |
| **Full provenance** | Every output-affecting knob serialized; every moved or dropped boundary recorded; every patch ships a pre-registered falsifiable diff band. |

---

## 2. Notation and the discretisation

```
i          part index, 0..N-1        (N = 10 for Liz)
D          frames per quarter note   (division = 8)
t          frame index, 0..T-1       (T = D · 390 = 3120)
tau(t)     = t / D                   frame t in quarter notes
norm(x)    min-max rescale of a signal to [0,1]
ind_X(t)   binary indicator over frames, part i
```

Internal time is always **quarter notes from score start**. Measure/beat is a
presentation layer built by `measure_map.py` v2 from the real time signatures.
Liz has an 18/4 at m.93; nothing anywhere may assume 4/4.

**Boundaries are per-part.** The output is a family `{B_0, ..., B_9}`, one
boundary set per instrument, because breath is an instrument-local physical
act. Ensemble agreement is a *constraint* (roadmap E), not the representation.

---

## 3. Stage 0 — parse and normalise the note stream

Intuition: before any signal processing, make the note list say what a
musician would say it says.

Each note carries `offset`, `duration`, `pitch`, `staccato`, `tie_type`,
`in_tuplet_interior`. Three normalisations, in this order:

1. **Same-offset grouping** (roadmap C). Simultaneous events in one part become
   one event with `top_pitch`, `bass_pitch`, `pitch_set`, `onset_count`.
   `polyphony_mode` in `{top, bass, outer}`, default `top`, picks which voice
   the melodic profile follows. Affects harp only.

2. **Tie-chain merging**, *before* any interval computation. A maximal chain of
   tied notes — natural ties **and** same-pitch "tie-like" slurs — collapses:

   ```
   offset(chain)   = offset(first segment)
   duration(chain) = sum of segment durations
   ```

   Ordering matters. Compute intervals first and LBDM reads every tie-internal
   seam as an event.

3. **`boundary_offset`**: for a merged chain, the *onset of the final tied
   segment*. All note-level evidence anchors here rather than at chain start.

Frame-level:

```
a_i(t)  = 1 if part i sounds at frame t, else 0
abar_i  = (1/T) · sum_t a_i(t)
tacet_i = (abar_i < 0.05)
```

Tacet parts produce no evidence and receive none.

---

## 4. Stage 1 — frame features

Two independent streams per part. Kept separate deliberately: pitch content and
rhythmic surface change at different moments, and a doubling partner may share
one without the other.

### Chroma, 13-dimensional

```
                | ( c_i(t) / ||c_i(t)|| ,  0 )     if a_i(t) = 1
phi_chr_i(t) =  |
                | ( 0,0,...,0          ,  1 )     if a_i(t) = 0
```

where `c_i(t)` in R^12 counts sounding pitch classes. Dimension 12 is an
explicit **rest dimension**: silence is a state, not an absence, so
rest-to-sound transitions register in the SSM.

### Rhythm, 3-dimensional

```
                  | (w_att, 0,     0    )   onset at t
phi_rhy_i(t)  =   | (0,     w_sus, 0    )   sounding, no onset
                  | (0,     0,     w_rst)   silent
```

Pitch-independent by design: two parts playing different notes on the same
attack pattern must read as rhythmically similar. `w_rst < w_att, w_sus` so
shared long rests do not dominate. The vector is **never zero** — this matters
for the cosine in §8.

---

## 5. Stage 2 — self-similarity and novelty

Intuition: a section boundary is a point where the recent past resembles
itself, the near future resembles itself, and the two do not resemble each
other. That geometry is exactly what a checkerboard kernel measures along the
diagonal of a self-similarity matrix.

### 5.1 SSM

```
S_i = Phi_i · K · transpose(Phi_i)          Phi_i is T x d
```

- `K = I` (`chroma_kernel = 'exact'`, default): plain cosine, since phi is
  unit-norm.
- `K = K_ic` (`chroma_kernel = 'interval'`, roadmap B): a 13x13 interval-class
  table.

```
K_ic[a][b] = iota( min( |a-b| mod 12 , 12 - (|a-b| mod 12) ) )

iota =  { 0: 1.00   unison/octave
          1: 0.05   semitone / major 7th
          2: 0.25   whole tone / minor 7th
          3: 0.70   minor 3rd / major 6th
          4: 0.75   major 3rd / minor 6th
          5: 0.55   fourth / fifth
          6: 0.10   tritone      }

K_ic[12][12] = 1.0     (rest dimension)
```

Under `interval`, a transposition or sequence reads as *similar*, so chroma
novelty stops firing on transposed restatements and fires on harmonic turns
instead. **Delivered, musically untested.**

Two SSMs per part: `S_chr_i` and `S_rhy_i`.

### 5.2 Checkerboard kernel

Half-width `L = kernel_size_frames / 2 = 32`, i.e. ±4 qn, an 8 qn analysis
window.

```
Kern(u,v) = eps · sign(u) · sign(v) · exp( -(u^2 + v^2) / (2·sigma^2) )

    u, v in [-L, L]      sigma = L/2
    Kern(0, ·) = Kern(·, 0) = 0        middle row/col zeroed, so the
                                       trivial SSM diagonal contributes
                                       nothing
    eps = -1  convention 'muller'      (matches FMP K_Box)
    eps = +1  convention 'foote'
```

The sign is undone downstream so peaks come out positive either way.

### 5.3 Novelty

```
nu_i(t) = eps · sum_{u=-L..L} sum_{v=-L..L}  Kern(u,v) · S_i(t+u, t+v)
```

Computed for both streams: `nu_chr_i`, `nu_rhy_i`. Edges trimmed where the
kernel does not fit. Tacet parts get zeros.

---

## 6. Stage 3 — LBDM (Cambouropoulos local boundary detection)

Intuition: a note is a boundary candidate to the degree that it is *locally
exceptional* — a big leap next to small ones, a long gap next to short ones.
Novelty is global-comparative; LBDM is local-comparative. They fail
differently, which is why both are present.

On the merged note list, for k = 1 .. m-1:

```
p[k] = |pitch[k+1] - pitch[k]|
       (or max(|delta top|, |delta bass|) under same-offset grouping)

o[k] = offset[k+1] - offset[k]                             inter-onset interval

r[k] = 0                                        if note k is staccato
     = max(0, offset[k+1] - (offset[k] + dur[k]))   otherwise
```

The staccato rule encodes that a written staccato gap is articulation, not a
phrase gap.

**Degree of change** on a profile x:

```
rho[k](x) = |x[k] - x[k+1]| / (x[k] + x[k+1])    if x[k]+x[k+1] > 0
                                                 and x[k] != x[k+1]
          = 0                                    otherwise
```

**Boundary strength**, then divided by its max:

```
s[k](x) = x[k] · ( rho[k-1](x) + rho[k](x) )      rho[-1] = rho[m-1] = 0
```

**Combination**, with Cambouropoulos's literature weights:

```
sigma[k] = w_p·s[k](p) + w_o·s[k](o) + w_r·s[k](r)

    (w_p, w_o, w_r) = (0.25, 0.50, 0.25)          IOI carries the most
    sigma[k] := 0   if note k is tuplet-interior
```

The tuplet zeroing stops a triplet fragmenting on its internal pitch variation.

**Projection to frames:** place `sigma[k]` at `round(D · boundary_offset[k])`,
smooth with a Gaussian of 0.5 qn, normalise:

```
Lambda_i(t)
```

---

## 7. Stage 4 — note-level arrival support

Two grids answering "does a phrase plausibly *land* here?", independent of any
similarity computation. Both anchor at `boundary_offset`, Gaussian-smoothed
with 0.25 qn, then max-normalised.

```
Long-note arrival    d_min = 1.0 qn,  d_full = 2.5 qn

    Long_i[ round(D · boundary_offset[k]) ]
        = min( (dur[k] - d_min) / (d_full - d_min), 1 )    for dur[k] >= d_min


Following gap        g_full = 1.0 qn

    gap[k] = offset[k+1] - (offset[k] + dur[k])

    Gap_i[ round(D · boundary_offset[k]) ] = min( gap[k] / g_full, 1 )
```

> ### The E0 discovery, stated formally
>
> `Long_i`, `Gap_i`, `Lambda_i` and the slur bumps of §7 are all projected at
> note **onsets** — `boundary_offset` is the *onset* of the final tied segment.
> But a boundary time is a **release**. So the entire note-level evidence stack
> fired one note-duration early, systematically.
>
> Probe at Fl1 mm.7–8: `Long = Gap = 1.0`, `Sel = 1.44` at the whole note's
> *attack*; `0, 0, 0.26` at its *release* — below the 0.30 gate.
>
> A separate annotation bug (target chosen by onset proximity) had been
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
> Until that is done, assume any endpoint-like channel is wrong until checked.

---

## 8. Stage 5 — notated marking channels

All produced by the same recipe: deltas at event offsets, Gaussian of 0.5 qn,
normalise to max 1.

| Signal | Source | Role |
|---|---|---|
| `slur_i(t)` | slur interior, `[first onset, last onset)` | continuation |
| `SlurEnd_i(t)` | slur end — last slurred note's **onset**; its tie-chain **release** under `--slur_end_release` (F1c(a), default off) | boost |
| `hp_i(t)` | hairpin interior | continuation |
| `tup_i(t)` | tuplet interior | continuation |
| `tie_i(t)`, `ntie_i(t)` | tie-like / natural-tie interior | **hard veto** |
| `Struct_i(t)` | structural events | boost |

**Structural events** are typed, with per-kind weights:

```
dynamic 0.80    tempo 1.00    tempo_text 1.00
key     0.80    time  1.00    fermata    1.00
```

**Dedup** (window 2.0 qn, sliding): within a same-kind run keep only the first,
and slide the reference forward so a long cascade collapses to one event.
MuseScore unrolls a *rit.* into per-beat tempo marks; that burst is one
gesture, anchored where it begins. Anchoring at the burst *end* — the *a tempo*
— is roadmap F work, and the sliding window already knows where the end is.

**G0 (done):** a wedge spanning a single note spans that note's full duration,
rather than collapsing to a zero-length span. Roughly 27 one-note wedges in Liz
were silently dropped before this.

> Note the asymmetry that motivates roadmap F: hairpins currently receive
> **interior attenuation only**. Their endpoints get no positive treatment at
> all. Same for *rit.* spans.

> **Failure mechanism 4 (F1c).** The slur interval `[first onset, last onset)`
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
> real `(start, end, release)` triples; nothing may zip the two lists again.

---

## 9. Stage 6 — soft cross-part rhythmic support

Intuition: if the euphonium is doubling the clarinet, the clarinet's evidence
is partial evidence for the euphonium — but only where they are actually doing
the same thing, and only as *support*, never as an instruction to breathe in
the same place.

Computed in **two passes**.

```
Pass 1   B_pre_j  =  the §10 signal computed with eta = 0
                    (no cross term — this breaks the circularity)

Tolerance          s = round(D · max_shift_qn),  max_shift_qn = 0.5

    Bmax_j(t) = max over |u| <= s of B_pre_j(t+u)

Windowed similarity    h = round(D · window_qn / 2),  window_qn = 4.0
                       W(t) = [t-h, t+h]

    sim_ij(t) = cosine( phi_rhy_i restricted to W(t),
                        phi_rhy_j restricted to W(t) )

Support            theta = 0.85

    Cross_i(t) = mean over { j != i, j active, sim_ij(t) >= theta }
                      of  sim_ij(t) · Bmax_j(t)

               = 0 if that set is empty

    then normalised per part
```

Guards: tacet parts neither give nor receive; a part must have at least
`min_active_qn` of sounding material inside `W(t)` to participate.

**E1 (shipped):** `sim_ij` and each contribution are stored, so `explain.py`
can say *"source: Harp, similarity 0.91, peak at +1.0 qn"*. This was demanded
as a first-class deliverable, not a nice-to-have — borrowed evidence that
cannot be attributed cannot be argued with.

---

## 10. Stage 7 — the per-part boundary signal

This is the core equation.

```
B_i(t) = [ ( B_raw_i(t) + boost_i(t) + F1_i(t) ) · Mult_i(t) ] · veto_i(t)
```

with

```
B_raw_i  = a_chr · norm(nu_chr_i) + a_rhy · norm(nu_rhy_i) + beta · norm(Lambda_i)

           (a_chr, a_rhy, beta) = (0.20, 0.35, 0.45)


boost_i  = gamma · SlurEnd_i  +  zeta · Struct_i  +  eta · norm(Cross_i)

           (gamma, zeta, eta)   = (0.40, 0.40, 0.20)


Mult_i   = (1 - d_hp  · hp_i)
         · (1 - d_sl  · slur_i)
         · (1 - d_tup · tup_i)
         [ · (1 - d_rep · Rep_i) ]              bracketed = experimental, off

           (d_hp, d_sl, d_tup)  = (0.50, 0.70, 0.80)


veto_i   = 1 if tie_i(t) = 0 and ntie_i(t) = 0
         = 0 otherwise


F1_i     = the expressive release grid of §11
```

Three design choices worth stating explicitly:

- **Boosts sit inside the multiplier**: `(B_raw + boost) · Mult`, not
  `B_raw · Mult + boost`. A weak slur-end bump in the middle of a longer slur
  must not punch through the phrase context saying "we are still inside a
  gesture."
- **F1 sits inside it too, as of F1b(c).** Until F1b, F1 was a post-multiplier
  addend — the only evidence channel exempt from hairpin/slur/tuplet
  attenuation and from the tie veto. The legacy identity
  `(B_raw + boost) · Mult · veto + F1` remains reachable via
  `_F1B['multiplier_routing'] = False` or `--f1b_no_multiplier_routing`;
  `explain.py` prints whichever branch is live. Measured cost of the change on
  Liz: **−1 exact** (Cl2 m.18 end, a mask defect not a routing defect — §16b).
  Kept on the structural argument, not the score.
- **Continuation is multiplicative; veto is a mask.** Slurs, hairpins and
  tuplets are *contexts that argue against* a break. Ties are *physical
  identity* — one sustained note cannot be broken — so they zero the signal.
- **Product, not sum, over continuation sources.** A frame inside both a slur
  and a hairpin damps once per source and can never drive `B_i` negative.

---

## 11. Stage 8 — F1: expressive release evidence

Intuition: an accompaniment part of whole notes has almost no rhythmic surface
and almost no melodic profile. Everything the composer said about its phrasing
is in the markings. F1 reads those markings and puts evidence exactly where the
gesture ends.

Events are extracted per part with **tie-chain release anchors**, following the
E0b/E0c convention that the breath follows the carrying note.

Since F1b(a), an anchor falling strictly inside a slur is **deferred** to that
slur's chain release before injection — moved, not masked. The deferred value
is what enters the grid and the anchor registry; the original is preserved as
`anchor_pre_slur_deferral` in `f1_events.json`, with a `[slur-deferred a->b]`
detail tag.

| Kind | Anchor | A/B1 weight | Proposed |
|---|---|---|---|
| `fermata_release` | release of the fermata note's tie chain | **1.0** | 1.0 |
| `dim_end` | release of the last note under a `Diminuendo` wedge, or under *dim./decresc.* text + co-starting dashed `Line` | **0.6** | 0.6 |
| `cresc_end` | same, for `Crescendo` / *cresc.* | 0.0 | 0.25 |
| `text_start` | release of the note sounding under a bare dictionary word; *a tempo* takes the **preceding** release | 0.0 | 0.25 |
| ornaments — trill, tremolo, arpeggio, mordent, turn | — | 0.0 | recorded only |
| character words — marcato, dolce, espress., cantabile, legato | — | 0.0 | recorded only |

```
F1_i(t) = sum over events e in part i of
              w[kind(e)]   if t = round( D · anchor(e) )
              0            otherwise
```

Deliberately **exact frame deltas**: no Gaussian smearing, no normalisation, no
coupling to `zeta`. The weights are absolute and read directly against the
acceptance gate:

```
w >= 0.30   can fire alone
w <  0.30   supporting-only, by construction
```

That is the entire meaning of "sub-gate." A 0.25 weight can never create a
boundary on its own; it can only tip a candidate that already carries
corroborating selection mass.

Two containment rules:

1. `F1_i` enters **only** the main-loop `B_i`, never `B_pre_j` — injected
   evidence must not propagate through cross-rhythm support.
2. Injected boundaries pass through the **same** validation as every other
   channel. An outgoing tie still vetoes a fermata target.

Every event is written to `f1_events.json` with kind, raw offset, anchor,
weight, and fate in `{injected, zero_weight_recorded, off_grid, skipped:*}`.

Dry-run coverage against GT (`f_events.py`): fermata claims 7 misses, `dim_end`
8, `cresc_end` 18 — 42 novel anchors, including the Trumpet m.12-end sentinel
and an independent recovery of the m.93 unison ruling.

---

## 12. Stage 9 — the candidate / selection / acceptance triad

Intuition: three different questions deserve three different scores. *Where may
a candidate come from?* *Which of several nearby candidates is the musically
better landing?* *Is the winner good enough to keep at all?*

```
Continuation penalty — the additive analogue of Mult_i, used for ranking

  Pen_i = pi_sl·slur_i + pi_hp·hp_i + pi_tup·tup_i + pi_rep·Rep_i

          (pi_sl, pi_hp, pi_tup, pi_rep) = (0.35, 0.25, 0.45, 0.0)


Selection score — ranks candidates inside a group

  Sel_i = max( 0,  B_i
                 + 0.30·norm(Lambda_i)
                 + 0.30·norm(Long_i)
                 + 0.20·norm(Gap_i)
                 + 0.25·norm(Cross_i)
                 - Pen_i )


Note-anchor score — lets a strong physical landing compete with a taller spike

  Anch_i = norm( 0.50·norm(Long_i)
               + 0.35·norm(Lambda_i)
               + 0.25·norm(Gap_i)
               + 0.15·norm(Cross_i)
               - Pen_i )


The triad

  Cand_i   = max( B_i, 0.65 · Anch_i )       where candidates may originate
  Sel_i                                      how they are ranked
  Acc_i    = max( B_i, Sel_i )               whether the winner survives
  Forbid_i = max( tie_i, ntie_i )            hard removal
```

### Peak picking with grouped arbitration

```
h_cand = 0.22       h_accept = 0.30       d = floor(2.5 · D) = 20 frames

1.  P = { t : t is a local maximum of Cand_i,  Cand_i(t) >= h_cand }
2.  P = { t in P : Forbid_i(t) <= 0 }
3.  group transitively:  sorted, t joins the current group iff
                         t - t_last <= d
4.  winner per group:    t* = argmax over t in group of Sel_i(t)
5.  accept iff Acc_i(t*) >= h_accept ;  emit tau(t*)
```

> **Failure mechanism 2.** Step 3 is *transitive*, not a fixed exclusion window.
> A chain of peaks each within 2.5 qn of the next collapses to a single winner
> however long the chain runs. Where the ground truth holds two legitimate
> breaths inside 2.5 qn, at most one can survive. Known open defect.
>
> **Measured 2026-11-03 — the largest single cause of missed breaths.** The
> two-breaths-within-2.5-qn case is rare (2 GT pairs on Liz). The chaining is
> not: groups run up to 29 qn (Harp-up 119.6–148.6, 17 peaks; Fl1 9.9–32.9,
> 14 peaks). On C1, `fail_trace.py` attributes **30 of 51 required misses** to
> a peak lost to its group, and 28 of those 30 pass the acceptance gate on
> their own; 7 of F1c(a)'s 11 losses are the same. Repair: §16c(1).

---

## 13. Stage 10 — release anchoring (E0b / E0c)

Intuition: the evidence stack points at the note; the breath goes *after* the
note. This maps evidence positions to breath positions.

```
eps = 0.02 qn        ev_min = 0.3
rel(n) = offset(n) + duration(n)          on merged chains

for each boundary b:

  if  exists n with  offset(n) + eps < b < rel(n) - eps
        b := rel(n)                            reason: mid_note

  elif exists n with  |offset(n) - b| <= eps
       and  max( Long_i, Gap_i ) at frame round(D·b)  >  ev_min
        b := rel(n)                            reason: seam_arrival_evidence
                                                    or entry_onset  (E0c)
  else
        b unchanged                            rest-seam boundaries pass through

then deduplicate: boundaries within eps merge, recorded as merged_duplicate
```

Case 1 catches the x.125 / x.625 / x.875 smear family and mid-tie leaks.
Case 2 catches note-to-note seams **and** entries from silence (E0c, settled
empirically by the hand-corrected GT: the final chord at m.94 takes a comma in
six parts; Oboe is excluded by its tie).

Measured evidence separation on Liz: movers ≥ 0.3 (mostly exactly 1.0), stayers
≤ 0.14. Clean.

Verified shift census in `result['e0b_shift_info']`: 80 `mid_note` + 121 `seam`
+ 24 `entry_onset` + 13 `merged`.

**One step only.** Cascade iteration was tested and rejected:

```
unbounded fixpoint           12 fix / 18 break
    (runs away along consecutive evidenced seams:
     Euph 200 -> 216, Harp 64 -> 80)

depth-2, restricted to values shifted this run
                             11 fix / 23 break / 18 neutral
    evidence strength does NOT discriminate:
    breaks at ev = 1.00, fixes at ev = 0.53
```

The attractive remaining cases are **phrase-extent** questions, which a
convention layer cannot answer. They are E and F workload.

> **Failure mechanism 1 — REPAIRED in F1b(b), 2026-08-19.** Case 2 used to fire
> whenever arrival evidence cleared `ev_min`, regardless of what followed. It is
> now conditioned:
>
> ```
> shift  iff  max(Long_i, Gap_i) at round(D·b) > ev_min
>        AND  ( b is not an F1 anchor  OR  restAfter(b) )
>
> restAfter(b) = no note onset coincides with the shift target
> ```
>
> Declines are logged as `f1_seam_shift_declined_attacca`. Six fired on Liz,
> across Oboe, Cl1, Cl2 and Euphonium — see §16.

> **Provenance caveat.** The predicate tests whether a boundary *sits at* an F1
> anchor time within `eps`, not whether F1 *created* it. A baseline boundary
> coinciding with an anchor also declines the shift. Defensible — F1 contributed
> to `B_i` at that frame either way — but it is a conflation, and it is the
> first thing to check when an unexpected part moves.

> **Case 2 cannot rescue slur-end boundaries, by construction.** The predicate
> requires arrival evidence, and a phrase ending on a short slurred note has
> none: `Long = 0` for `dur < d_min = 1.0`, and `Gap = 0` whenever the music
> continues attacca. This is why F1c(a) moves the *projection* rather than
> adding a case here — no conditioning of this rule could reach those six
> boundaries (§8 Failure mechanism 5).

> **Scoped exception to the E0c ruling.** `HANDOVER_sectioning_v2_10_E0c.md` §3
> states that the breath follows the note whose arrival/gap evidence created the
> boundary. At Cl2 m.18 end that rule pushes 72 → 74; GT v2 requires 72 and bans
> 74. F1b(b) resolves in GT's favour **for F1 anchors in attacca passages only**.
> This is a scoped exception, not a repudiation of E0b. A reader of E0c §3 alone
> would reconstruct the wrong behaviour.

---

## 14. Stages 11–13 — filter, validate, annotate

**Short-phrase filter.** For consecutive boundaries define the segment
`(b_k, b_k+1]`, rests excluded, tempo-mapped to real seconds:

```
sounding_sec(k) = total seconds of note-sounding overlap with (b_k, b_k+1]
count(k)        = number of note onsets in (b_k, b_k+1]

if sounding_sec(k) < 1.25  AND  count(k) <= 1:
    remove the weaker neighbouring boundary, ranked by Sel_i
repeat to fixpoint
```

Rests never count as material. This is not "quarter note bad."

> **Failure mechanism 3 — DIAGNOSIS CORRECTED 2026-09-02.** The mechanism is
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
>
> **Priority corrected 2026-11-03.** Every fix that moves evidence to the
> release (F1c(a), and anything after it) makes more boundaries reach the
> filter already anchored, where the `(start, end]` onset count misreads them.
> F1c(a)'s one required loss (Harp-up m.82 end) is exactly this. Repaired in
> §16c(3): 6 FILTER misses → 0, +8 GT, −1 GT.

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
> sufficient to reverse-engineer the decision (§1, full provenance).

**Validation.** Each surviving boundary resolves to a breath target and is
rejected if:

- `boundary_lies_in_rest` — under `rest_seam_policy = 'seam'`, strictly inside
  a rest only; an at-seam boundary is kept, and a near-seam boundary within
  0.25 qn snaps to the seam. Under `'legacy'` the exact seam falls inside the
  rejection interval and the outcome is a frame-parity lottery.
- `target_has_outgoing_tie` — the target sustains into the next event.

Rejects are recorded, not silently dropped.

**Annotation.** The comma attaches to the note **releasing** at b
(`_ANNOT_RELEASE_RETARGET = True`), not the note starting at b.

**Outputs.** `sectioned.musicxml`, `boundaries.json`, `diagnostics.png`,
`phrase_material.json`, `f1_events.json`, `result.pkl`.

---

## 15. The objective function

No differentiable loss. The objective is agreement with a hand-authored ground
truth.

**GT v2** (`gt_liz_v2`), compiled from the hand-corrected score, which is the
authority:

```
263 points   —  136 required, 127 kept
 53 banned   —  removed_points: positions that must NOT receive a mark
  4 unison constraints  —  sets of parts that must agree
```

> **Reconciliation, 2026-08-19.** Earlier revisions of this section carried
> "263 points — 135 required, 127 kept" and "52 banned", which does not add up:
> 135 + 127 = 262. Those were the **pre-correction** figures. The 2026-08-07
> Oboe pass moved GT from 262 to 263: required qn 262.5 (m.66 b3.5) removed and
> reclassified banned; required qn 382.0 (m.93 b15) and qn 390.0 (m.94 b5)
> added. Hence 136 required, 127 kept, 53 banned. Applied across
> `gt_boundaries_v2.json`, `gt_liz_v2_2026-07-15.json` and
> `audit_cases_gt_v2_2026-07-19.json`.

Workflow: `gt_render.py` → hand-correct in MuseScore → `gt_from_score.py`.
MuseScore export strips colours, so status recovery by prior-matching is a
permanent part of the loop.

```
exact       = # GT points g with some boundary b in part(g),  |b - g| <= 0.1
violations  = # required misses + # banned hits     (audit_check.py exit code)
```

### Two metrics, not interchangeable

This distinction was absent from earlier revisions and is what let the bad
denominator sit unnoticed.

| Metric | Instrument | Denominator | Covers |
|---|---|---|---|
| Exact-match scoreboard | `score_run.py <run>` (or `boundaries_diff.py gt_boundaries_v2.json <run>/boundaries.json`) | 262 (263 before 2026-09-02) | required + kept |
| Hard-violation audit | `audit_check.py <run>/boundaries.json --audit audit_cases_gt_v2_2026-09-02.json --musicxml gt_rendered.musicxml` | 190 (189 on the superseded 07-19 file) | required + banned only |

Kept points are **not encoded in the audit file**, so audit-invisible changes
are routine and are not evidence of no effect. The Oboe m.93 b9/b12 pair and
the Euphonium m.29/m.30 pair are both kept-point changes; neither appears in
`audit_check` output.

### Measured audit progression

| Run | PASS | FAIL | Required PASS | Banned violated | Points |
|---|---|---|---|---|---|
| E0c (2026-07-19 dry run) | 92 | 95 | 61 / 135 | 21 / 52 | 187 |
| F1 `liz_seam_F1` | 100 | 89 | 69 / 136 | 22 / 53 | 189 |
| F1b `liz_seam_B3_all` | **107** | **82** | **72 / 136** | **18 / 53** | 189 |

Three unison violations persist across all three runs (§22b).

### Exact-match scoreboard

**191/263** at F1. **194/263 derived** for B3 — obtained by scoring the staged
`boundaries_diff` output against GT by hand, *not measured directly*. Measure
it and replace this note:

```
python boundaries_diff.py gt_boundaries_v2.json \
    output_v2_10_F1b/liz_seam_B3_all/boundaries.json
```

The earlier figure "191/261 exact" was wrong in its denominator only; the
numerator stands.

Evaluation discipline:

- `boundaries_diff.py` — run-to-run drift with parameter checking. GT first:
  `REMOVED` = pipeline miss, `ADDED` = pipeline extra.
- `audit_check.py --audit audit_cases_gt_v2_2026-09-02.json` — hard-violation
  scoring; exit code is the metric.
- `annotation_check.py` — rendered score versus `boundaries.json`.
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

> **Re-baselined 2026-11-03** (was PENDING 2026-09-02). GT is 262 points
> (Oboe m.86 b4.75 removed and banned; 54 bans), audit file
> `audit_cases_gt_v2_2026-09-02.json` (190 points; supersedes the 07-19 file
> and the 189 figure above). Measured, music21 10.5.2:
>
> | Run | Exact | Extras | Boundaries | Audit PASS/FAIL | Unison viol. |
> |---|---|---|---|---|---|
> | B3 `liz_seam_B3_all` | 194/262 | 49 | 243 | 107/83 | 3 |
> | C1 `liz_seam_C1_slur_release` | 198/262 | 40 | 238 | 128/62 | 3 |
>
> `python score_run.py RUN_DIR ...` prints this line for any run.

---

## 15b. Defect register and tooling hazards

Numbered failure mechanisms live with their stages (§7, §8, §12, §13, §14).
This section collects the ones that belong to no single stage.

### Bug-compensating-bug: now a pattern, not an incident

Two instances, both discovered only when the first defect was fixed.

1. **E0 / E0b.** Note-level evidence fired one note-duration early, and a
   separate annotation bug (target chosen by onset proximity) silently
   compensated. Months of eye-approved renders looked right (§7).
2. **E0b-seam / slur-deferral, at Oboe m.93 b9.** The dim_end anchor sits at
   the onset of a note carrying `slur_end` and running 3.00 qn, releasing at
   m.93 b12 — the slur's chain release, which is GT. E0b's *unconditioned*
   seam shift was pushing b9 → b12 and landing correctly **for the wrong
   reason**. F1b(b) removed the accident and exposed the raw anchor; F1b(a)
   put it back on principle.

Standing consequence: **when a fix causes a regression, check whether the prior
behaviour was accidental before reverting.** A regression against a
bug-compensated baseline is not necessarily a regression against the music.

### Module-level state leak — CLOSED 2026-09-02

`_F1_ANCHOR_SETS` was a module-level dict, never cleared, so a second
`run_sectioning` call in one process would leak run 1's anchors into run 2's
seam decisions. Fixed by `_F1_ANCHOR_SETS.clear()` at the top of
`_f1_build_release_grids` (line ~2391), and the call site at line ~3020 is
confirmed **unconditional** — no weight guard that could skip the clear.
Retained here as precedent: module-level mutable state shared "to avoid
threading an argument through every call site" needs an explicit reset, the
same lesson as the unserialized `delta_repetition` that motivated S0.

### The diagnostic disagreed with the pipeline — CAUSE CORRECTED 2026-09-02

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
before it reports anything.

### Stale-import hazard

`explain.py` imports the pipeline module by name. After F1b it still imported
`sectioning_v2_10_F1`. Second occurrence. Consider a `CURRENT_PIPELINE`
indirection rather than editing the import each version.

**Resolved 2026-11-03** (`3d6d68a`): `explain.py` resolves `CURRENT_PIPELINE`
(default `sectioning_v2_10_F1c`; override with the `SECTIONING_PIPELINE`
environment variable). Also fixed: `--cross` was silently ignored with
`--time`. Set `SECTIONING_PIPELINE=sectioning_v2_11_A` for v2.11-A runs.

### Non-copy-pasteable commands are a real cost

Two validation runs were lost when `...` shorthand in a command block was
parsed as a literal input path by `music21`. Commands in this document, in
handovers, and in patch docstrings are always written complete.

---

# Planned work

§16 is **shipped**, retained as the record of what was built and how it was
validated. §16b is specification detailed enough to build from. §17–§20 are
banked designs with open questions marked.

---

## 16. F1b — SHIPPED and validated (2026-08-19)

Three corrections, each independently disableable, all shipping **active**
(they are bug-fix completions, exempt from default-off per §1) and all three
serialized in `all_knobs`:

```
--f1b_no_slur_deferral        disables (a)
--f1b_no_seam_condition       disables (b)
--f1b_no_multiplier_routing   disables (c)
```

(d) is **outstanding**.

**(a) Slur deferral at extraction time.** Not masking — *moving*. For an F1
event whose anchor falls inside a slur:

```
anchor'(e) = rel( last note of the slur containing anchor(e) )
```

Rationale: most fermata notes in the affected passage end where their slur
ends. The evidence is real; its position was wrong.

**(b) Conditioned seam shift.** Add a predicate to §13 case 2, **for
F1-originated anchors only**:

```
shift  iff  max(Long_i, Gap_i) at round(D·b) > ev_min
       AND  ( e is not an F1 anchor  OR  restAfter(b) )

restAfter(b) = the event following the target note is a rest
```

**(c) Route F1 through the continuation multiplier.**

```
was:  B_i = (B_raw + boost) · Mult · veto + F1
is:   B_i = (B_raw + boost + F1) · Mult · veto
```

This makes F1 obey the same phrase-context discipline as every other boost.

> **Interaction warning.** (a) and (c) partly cancel. Once anchors defer to slur
> *ends*, they sit outside slur interiors, so the multiplier rarely bites. That
> may be the correct relationship — the multiplier becomes a safety net for
> anchors that (a) does not relocate — but it means (a) and (c) cannot be
> validated independently on the same run. Sequence them, or accept a
> confounded band.

**(d) Lexicon completion — NOT YET BUILT.** Register the full expressive
vocabulary — trills, exotic ornaments — at weight 0.0. Register bare dictionary
text at note start even when no span end resolves: a word without a dashed line
is still a word.

### Staged validation, 2026-08-19

Reference `output_v2_10_F1/liz_seam_F1`; each stage adds one correction.

**B1 — seam condition alone.** Pre-registered band: *Euphonium only*, +m.27 end
+m.29 end −m.28 end −m.30 end. **Band exceeded** — six declines across four
parts, not two.

| Part | Change | GT v2 | Effect |
|---|---|---|---|
| Euph | +m.27 end / −m.28 end | 108 required, 112 banned | +1 exact, −1 banned |
| Euph | +m.29 end / −m.30 end | 116 kept, 120 not GT | +1 exact, −1 extra |
| Euph | +m.35 end / −m.36 b3 | 140 required, 142 banned | +1 exact, −1 banned |
| Cl2 | +m.18 end / −m.19 b3 | 72 required, 74 banned | +1 exact, −1 banned |
| Cl1 | +m.18 end / −m.19 end | both GT | wash |
| Oboe | +m.93 b9 / −m.93 b12 | 379 kept, 376 not GT | −1 exact, +1 extra |

The `f_events.py` survey had found 5 anchor ∩ seam-shift cases; there are at
least 9. Cause not established. Candidates: (i) the survey enumerated only
`fermata_release` anchors and missed `dim_end`; (ii) the provenance conflation
in §13.

> **Recorded protocol override.** §1 and §15 both say an exceeded band is a
> stop. We did not stop. Four of the six declines were gains, and both anomalies
> were traced to root cause within the same session. This is logged as a
> deliberate, reasoned exception so that it does not become silent precedent.

**B2 — adds (c), multiplier routing.** One change: Cl2 loses m.18 end, the point
B1 had just recovered. Diagnosed to the slur-mask left edge, not to routing:

```
in_slur_interior = 1   (qn 72 IS the slur start; slur 72.0 -> 76.0)
in_hairpin       = 0
(0.185 + 0.066 + 0.600) · 0.30 = 0.255  <  0.30 acceptance gate
```

Short by 0.045. F1b(a) cannot rescue it — deferral tests `s < a < rel` strictly,
and here `a == s`. Repair is §16b (F1c-left).

**B3 — adds (a), slur deferral.** Two changes: Oboe reverts m.93 b9 → b12,
restoring the GT kept point; Cl1 drops m.41 b4, a banned position.

**Net: +7 PASS / −7 FAIL on the audit, zero regressions.** Every other audit
line is identical between `liz_seam_F1` and `liz_seam_B3_all`.

| Part | Point | F1 | F1b |
|---|---|---|---|
| Cl1 | m.18 end required | FAIL | PASS |
| Cl1 | m.41 b4 banned | FAIL | PASS |
| Cl2 | m.19 b3 banned | FAIL | PASS |
| Euph | m.27 end required | FAIL | PASS |
| Euph | m.35 end required | FAIL | PASS |
| Euph | m.28 end banned | FAIL | PASS |
| Euph | m.36 b3 banned | FAIL | PASS |

### Cl2 m.18 end reproduces a hand correction

GT v2 `removed_points` for part 4 records
`74.0, migrated_from: 72.0, migrate_reason: seam_arrival_evidence` — that is
`gt_migrate_e0b` applying the seam shift and Robert correcting it back in
MuseScore. F1b(b) now declines that exact shift from first principles, having
never been shown the correction. This is the strongest single piece of evidence
that the mechanism is right rather than merely tuned.

### The interaction warning held

(a) and (c) could not be validated independently, exactly as predicted. The
Oboe case is the proof: (b) exposed a raw anchor that (a) then relocated, so the
two corrections are entangled through a third. See §15b.

---

## 16b. F1c — slur edge semantics

Three stages against one defect family. File letter `F1c` covers all three,
following the F1b precedent where (a)(b)(c) shipped together and (d) trailed.

| Stage | Change | Status |
|---|---|---|
| **(a)** | endpoint bump at the chain release | measured 2026-11-03: band exceeded, net positive; default off pending decision |
| **(b)** | mask 0 at slur start (was "F1c-left") | tried 2026-11-03 (generalised to hairpin and tuplet), **rejected** — §16c |
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

**Pre-registered band (2026-09-02), from `slur_release_probe.py`:**

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

**Measured (C1, 2026-11-02; reproduced 2026-11-03).** Band **exceeded**: 41
changes against 13 predicted (10 moved, 18 removed, 13 added); audit +21
(107/83 → 128/62), exact +4 (194 → 198/262). C0 (flag off) is identical to B3:
the `phrase_spans` half is behaviour-neutral. 15 GT gains, 11 losses (10 kept,
1 required). The run stopped as the protocol requires: the flag ships default
off.

Root causes of the 11 losses (`fail_trace.py`): 7 lost to a transitive group
(FM2), 3 removed by the short-phrase filter (FM3), 1 shifted away by E0b.
The required loss, **Harp-up m.82 end**, is neither of the hypotheses in the
handover: Fl2's relocated bump lowers Harp-up's *raw cross-support maximum*
at qn 255 (1.033 → 0.864); per-part min-max normalisation then lifts Harp-up's
`cross_n` everywhere by ×1.2 (0.453 → 0.541 at 328), so 328 out-ranks 326 in
its group, and the filter removes 328 because `(328, 336]` counts the entry
note at 336. In B3 the 326 winner survived the filter and E0b moved it to 328:
**right by accident, the third bug-compensating-bug** (§15b). ASax 171→172
and Oboe 382 are both the **tie mask including the chain's first onset**
(§16c(2)); ASax 172 is additionally under a hairpin starting there.

Why the probe undercounted: it modelled only boundaries *at* a last-slurred
onset. Real collateral comes from (i) regrouping (a moved peak bridges or
splits a chain) and (ii) **cross-part normalisation coupling** — a change in
one part rescales another part's `cross_n` globally, here 73 qn away. No
position-count probe can see either. Future bands should predict direct
changes only, and classify every change after the run as direct or
collateral with `fail_trace.py` / `group_trace.py`.

---

### (b) and (c) — the mask edges

See Failure mechanism 4 (§8). Summary:

| Position | Musical reading | Current mask | Correct |
|---|---|---|---|
| slur start | breath *before* the first slurred note | 1 (penalised) | 0 |
| strictly interior | splits the slur | 1 | 1 |
| last slurred note's onset | detaches the final slurred note | 0 (allowed) | 1 |
| chain release | breath *after* the slur | 0 | 0 |

Both errors observed: Cl2 m.18 end is the left edge, Oboe m.93 b9 the right.

### Derivation — not a new ruling

It follows from three sources already on the books:

1. `patch_E0_annotation_release_target.py` — the comma attaches to the note
   whose **release** equals the boundary.
2. `HANDOVER_addendum_2026-07-19.md` §3 — breath is always *after* the carrying
   note.
3. Standard engraving — a breath comma is placed after the note it follows.

So `n1 breathe | n2 slur … n' breathe` maps to: comma on n1, boundary at
`rel(n1) = onset(n2) = slur_start`; and comma on n', boundary at
`rel(n') = chain_release`. Neither breath touches the slur.

This closes an item open since the May 2026 implementation review, recorded
there as *"semantic ambiguity in breath mark placement (whether the boundary is
'ends before' or 'ends after' the marked note)."*

### Predicate

```
slur_i(t) = 1  iff  exists slur s in part i with
                    start(s) < tau(t) < chain_release(s)
```

Open at both ends. Nesting falls out: with slur A = (64, 76) and B = (68, 72)
nested, qn 72 is B's release but strictly inside A, so 1. Correct.

This is the same predicate F1b(a)'s deferral already computes. Mask, deferral
and `explain` must share **one** function; the current divergence is what
produced the two contradictory explain flags (§15b).

Cl2 m.18 end is a useful consistency check: qn 72 is simultaneously the chain
release of slur 64 → A4 and the start of slur 72 → 76. Both rules independently
say 0.

### Two patches, not one — opposite risk

- **(b)** — mask 0 at slur start. *Permissive*: only unmasks instants
  currently penalised. Can add boundaries, cannot remove any. Recovers Cl2
  m.18 end, the eighth audit flip.
  **Falsified 2026-11-03:** under grouping, an unmasked peak can out-rank and
  remove an existing boundary. Measured −13 GT / +5 GT (§16c, rejected).
- **(c)** — extend to chain release. *Restrictive*: newly masks the last
  slurred note's onset **and its entire interior**. Can silently kill
  boundaries that currently pass, including GT ones.

> **(c) may be redundant after (a).** Moving the positive evidence off the
> last-note onset removes the peak that (c) exists to suppress. Shipping both
> risks double-correcting the same displacement. Re-probe after C1 and only
> then decide. `phrase_spans` already carries the release values (c) needs, so
> no second extraction pass is required.

`slur_i` feeds `Mult_i` and `Pen_i` for **every** channel, not just F1. Both
ship default-off for one validation run (§1).

### Probe required before either patch

Two counts off the B3 pickle, so each ships a real pre-registered band:

1. B3 boundaries sitting exactly at a slur start — F1c-left's upside.
2. B3 boundaries in `[last_slurred_onset, chain_release)` — F1c-right's blast
   radius, and how many are GT points.

---

## 16c. v2.11-A — structural fixes found by attribution (2026-11-03)

`fail_trace.py` labels every audit FAIL with the first stage that lost it.
On C1 (62 FAILs): **GROUP_LOST 30**, BANNED_HIT 11, FILTER 6, WEAK 5,
VALIDATION 3 (all `inside_natural_tie_span`), SHIFTED_AWAY 2, GATE 2,
NOT_SHIFTED 2, NEAR_MISS 1. That ranking, not the old queue, set the order
below. Priority is by *mistake class a musician would reject*, fixed at the
cause; exact-match points are a consequence, not the target.

All flags live in `sectioning_v2_11_A.py`, default off. The control (C1 flags,
no new flag) is identical to C1 (238 unchanged), and `group_trace.py --verify`
passes in 10/10 parts for every run below. All runs use C1's flags.

| Run | Added flags | Exact | Extras | Boundaries | Audit P/F | Unison |
|---|---|---|---|---|---|---|
| C1 | — | 198 | 40 | 238 | 128/62 | 3 |
| T1 | `--tie_open_start` | 201 | 40 | 241 | 131/59 | 3 |
| F1 | `--filter_after_anchor` | 204 | 46 | 250 | 133/57 | 2 |
| F2 | both | **207** | 46 | 253 | 136/54 | 2 |
| A1 | `--peak_grouping nms` (d = 2.5) | 224 | 102 | 326 | 144/46 | 2 |
| A1 | `--peak_grouping nms --peak_distance_qn 4.0` | 203 | 58 | 261 | 141/49 | 3 |
| F3 | F2 + nms d = 4.0 | **214** | 61 | 275 | **151/39** | 2 |

Precision / recall: C1 83% / 76%; F2 82% / 79%; F3 78% / 82%.

### (1) `--peak_grouping nms` — Failure mechanism 2

Non-maximum suppression: visit peaks by `Sel`, best first; accept a peak iff
`Acc >= 0.30` and no accepted boundary lies within `peak_distance`. Chains no
longer collapse; minimum spacing is preserved.

At the legacy 2.5 qn it over-segments: +26 exact but +62 extras, and F-measure
*falls* (0.79 → 0.76). No local feature separates the new GT hits from the new
extras (both are mostly long notes released attacca); **spacing** does. GT has
only 4 of 252 same-part gaps under 4 qn; NMS at 2.5 qn produces 36. At 4 qn
(≈ 3.7 s at Liz's tempo — one bar, one breath) the extras split into 9 on
banned spots (C1: 11), 1 misplaced, and **48 at positions no GT pass has
reviewed** (C1: 29). The radius is a fit to one piece, so it must be checked
on Dvořák before it becomes a default, and expressed in seconds if it holds
(cf. the breathability limit, §19).

### (2) `--tie_open_start`

The natural-tie mask, the tie-like mask and validation covered
`[chain start, final onset)`. The chain's first onset is the previous note's
release — a breath *before* the tied note. Now `(start, final onset)`. T1 vs
C1: 238 unchanged, **+3 required, 0 lost, 0 extras** (Cl2 m.60 end, Euph m.74
end, m.76 end). The two motivating cases stay blocked by other defects: ASax
172 by a hairpin starting there; Oboe 382 by grouping plus **discretisation**
— D = 8 frames per qn cannot represent the 0.2 qn quintuplets of m.93, so the
evidence lands at 381.75 and anchors to the banned 381.8.

### (3) `--filter_after_anchor` — Failure mechanism 3

Anchoring runs before the filter; segments count onsets in `[start, end)`;
across an all-rest segment the closing entry instant is removed (E0c); the
weaker-neighbour test uses `Sel` at the E0b *source*. F1 vs C1: **+8 GT**
(required Harp-up m.82 end, Harp-low m.7 b3.5 and m.34 b3, Fl2 m.94 end —
which clears the final-chord unison violation), **−1 GT** (ASax 232: the
filter now sees the eighth-note fragment between 232 and 232.5 and keeps
232.5 on `Sel`; 232.5 is the pickup split of §18, inflated by wrong-type
cross-support). FILTER causes 6 → 0.

### (4) Late landings — E0b seam shift (open)

In F3, 8 of 39 FAILs are E0b `seam_arrival_evidence` moving a correct
boundary one note late (Oboe and Trumpet m.82 end → m.83 b2, Harp-up m.80 end
→ m.81 b2, Euph 232 → 236, Harp-low 180 → 183). Pattern in three: a long note
ends, one short note carrying a **new dynamic** follows, then a rest; GT
breathes before the short note. E0b reads the gap after that note as "this
note ends the phrase".

**Rejected 2026-11-03: hold the seam at a dynamic/key/time change.** 14 holds:
4 right (Ob 328, Harp-up 320, Euph 108, Cl2 56), **7 wrong**, 3 between two GT
points. The wrong ones include four parts at m.93 b1 (368 → 370), against the
m.93 ruling: a dynamic on a note does not mean a new phrase starts there.
Reverted, not shipped. The real discriminator is which evidence *created* the
peak — onset-typed vs release-typed — i.e. D1.

### (5) Rejected 2026-11-03: `--continuation_open_start` (F1c(b), generalised)

Slur, hairpin and tuplet masks with the start frame unmasked. Alone: −13 GT,
+5 GT, extras +15 (exact 198 → 190). With F3: exact 214 → 207, extras 61 → 82.
Newly unmasked slur starts (often a pickup 1.5–2 qn after the breath) out-rank
the real breath in its group: Fl1/Oboe 148 → 149.5, Oboe 140 → 141.5, Cl1
208 → 210. Reverted. The ruling ("a breath at a slur start is allowed") still
stands; what fails is *rewarding* the start with an unpenalised peak. Revisit
after D1, where the start edge can carry change-typed evidence without
competing as an endpoint.

### Review lists — what only Robert can decide

`review_list.py BASE NEW` lists the conflicts with GT a run adds relative to a
base run. Exact-match counts them only as extras and the audit not at all, so
whether each is objectionable needs a musician. `review/v2_11_A_candidate_vs_C1.md`
holds the 33 for F3, with verdicts (below).

### Review outcome (2026-11-03)

Robert reviewed F3 on his own run (identical, 275/275). Framing, his: any
boundary that disagrees with GT is a **conflict**; bans are warnings from an
earlier iteration and "not banned" means little. He marked the conflicts he
finds **objectionable**; the rest pass as acceptable. Of the 33 new conflicts,
12 are objectionable and 21 acceptable; he also objected to 4 boundaries that
were already in C1 (Fl1 m.85 b3, Harp-up m.54 b3, Cl2 m.71 b4, Harp-low
m.91 b3). The set is in `review/objections_2026-11-03.json`. The 07-10
audit's "Recommended" rulings at ASax and Harp end of m.55 are overturned.

`score_run.py` now reports **objectionable = required missed + banned hit +
objected hit**, the count a musician would reject:

| Run | Objectionable | Required missed | Banned hit | Objected |
|---|---|---|---|---|
| B3 | 87 | 64 | 19 | 4 |
| C1 | 66 | 51 | 11 | 4 |
| T1 (tie) | 63 | 48 | 11 | 4 |
| F1 (filter) | 64 | 46 | 11 | 7 |
| F2 (tie + filter) | 61 | 43 | 11 | 7 |
| nms d = 4.0 | 62 | 40 | 9 | 13 |
| **F3** (F2 + nms d = 4.0) | **55** | 31 | 8 | 16 |

On this measure F3 is the best configuration. The review covered F3's
boundaries, so counts for runs with boundaries F3 lacks are lower bounds.
Objections cluster in two patterns: breaths that split a short pickup from
its downbeat (m.54 b2.5, m.55 b4.5, m.75 b3.75) and accompaniment breaths
after a long note with no phrase end (Euph m.9, m.15, m.63) -- both evidence
typing problems (D1).

### (6) `--endpoint_release` — D1 step 2 (2026-11-03)

**Typing measured, not assumed.** At the 213 GT breaths whose releasing note is
>= 1 qn (F3 run), each channel's value at the note's onset vs its release:

| Channel | Higher at onset | Placement |
|---|---|---|
| chroma novelty / rhythm novelty | 25% / 20% | release (correct) |
| SlurEnd (`--slur_end_release`) | 11% | release (correct) |
| **LBDM / Long / Gap** | **87% / 85% / 94%** | **onset — wrong** |
| Struct | 66% | mixed (dynamics = change, fermata = endpoint) |
| Cross | 40% | mixed (borrowed) |

LBDM, Long and Gap describe how a note *ends* but were projected at its final
segment's onset: the E0 defect, compensated downstream by E0b case 2 but never
fixed at source. It is also the **mechanism of the late landings** (16c(4)):
at a correct boundary g, Long/Gap at frame g describe the *next* note, so case
2 pushes the breath past it.

The flag projects LBDM, Long, Gap **and fermata structural bumps** at the
note's (chain) release; E0b case 2 is kept for **entry onsets only** (E0c),
reading the entering note's evidence at its release, and disabled at seams.
Case 1 (mid-note) is unchanged.

| Run (C1 flags) | Exact | Extras | Audit P/F | Objectionable (missed / banned / objected) |
|---|---|---|---|---|
| F3 | 214 | 61 | 151/39 | 55 (31 / 8 / 16) |
| **E3** = F3 + `--endpoint_release` | 213 | 63 | **153/37** | **45** (33 / 4 / 8) |
| F2 + `--endpoint_release` | 192 | 60 | 141/49 | 54 (43 / 6 / 5) |

It pays off with NMS; without it (vs F2) it costs 15 exact. **E3's 45 is a
lower bound:** it drops 30 of F3's conflicts (8 objected) and adds 31 that
nobody has reviewed — `review/E3_endpoint_vs_F3.md`. At F3's objection rate
(12/33) those would add ~11, i.e. level with F3. Firm gains: banned hits 8 → 4.

### (7) `--f1_printed_breath_weight` (2026-11-03)

The pipeline never read breath marks already printed in the input score. Liz
prints 3 (Oboe m.40, m.41, m.93; qn 159, 163, 379), all GT. New F1 kind
`printed_breath` at the marked note's release, exempt from slur deferral.
At weight 1.0 it changes nothing on Liz: F3 already has all three, and in E3
Oboe 159 loses NMS to 163 (Sel 0.758 vs 0.812, 4 qn apart). A weight makes a
printed breath likely, not certain; whether the composer's marks should bypass
suppression is Robert's call.

### NMS radius: inclusive 4.0 vs 3.9

`|p - c| <= 4 qn` suppresses breaths exactly one bar apart; GT has 31 such
same-part gaps (and only 4 under 3.9). Radius 3.9 qn: F3 exact 214 → 227 but
extras 61 → 87; E3 213 → 220, extras 63 → 90 — a breath nearly every bar.
Kept at 4.0.

### (8) `--peak_grouping soft` — penalise, never ban (2026-11-03)

Robert's question: does GT itself obey a 4 qn spacing? **No: 35 same-part
pairs are <= 4 qn apart** (31 exactly one bar, 4 under), clustered where the
music breathes every bar (m.40-43 and m.58-60, fermatas and rit.). Hard NMS
at 4 qn can find only one of each pair (F3 finds both in 7/35), and it breaks
§1's own invariant. Soft grouping instead scales each remaining peak's `Sel`
and `Acc` by `(distance / radius) ** p` after every acceptance; a peak is
kept if its penalised `Acc` still clears the gate.

All with C1 flags + `--filter_after_anchor --tie_open_start --endpoint_release`:

| Grouping | Exact | Extras | Total | Audit P/F | Unison | Objectionable* | close GT pairs found | unreviewed vs F3 |
|---|---|---|---|---|---|---|---|---|
| hard NMS 4 (= E3) | 213 | 63 | 276 | 153/37 | 2 | 45 | 9/35 | 32 |
| soft r 4, p 1 | 229 | 126 | 355 | 156/34 | 2 | 46 | | |
| soft r 4, p 2 | 226 | 116 | 342 | 155/35 | 2 | 47 | | |
| soft r 6, p 1 | 218 | 81 | 299 | 154/36 | 1 | 43 | 15/35 | 47 |
| **soft r 6, p 2** | 208 | **56** | 264 | **154/36** | **1** | **41** | 6/35 | 25 |
| soft r 8, p 1 | 210 | 60 | 270 | 152/38 | 1 | 43 | | |
| soft r 8, p 2 | 201 | 51 | 252 | 152/38 | 1 | 43 | | |

*Lower bounds where a run has conflicts F3 does not (unreviewed). No setting
dominates: soft r 6 p 2 has the fewest conflicts and best audit but recovers
fewer close pairs; r 6 p 1 recovers more but adds conflicts. The close pairs
need local evidence (fermata/rit. passages), not a better uniform spacing
rule. Review sheet for r 6 p 2: `review/S_d6_p2_vs_F3.md`.

### (9) Multi-voice rest check — bug fix (2026-11-04, unconditional)

Validation rejected a boundary as `boundary_lies_in_rest` when a rest in
*another voice* covered it, though a note released exactly there (Harp-low
m.65 b2.25). Under `rest_seam_policy seam`, a note releasing at the boundary
now makes it a seam. Control unchanged (238); soft r6 p2 gains exactly that
GT point: 209 exact, audit 155/35, objectionable 40.

### (10) `--ensemble` — minimal ensemble alignment, roadmap E (2026-11-04)

One pass after all parts have boundaries; arbitration only. **Snap:** a
boundary moves to a note release in the same part within 1.5 qn when >= 3
other parts breathe there and fewer breathe at its current spot; never away
from the part's own F1 anchor (fermata / printed breath / dim. end: Oboe
m.41 b4 must not follow the clarinets to m.41 end). **Gate relief:** a
candidate peak that failed the gate with acc >= 0.15 is accepted at its note
release when >= 3 other parts breathe there and the part has none within
2 qn. Changed parts are re-validated (earlier rejection records kept);
changes are in `result['ensemble_info']`; `group_trace --verify` applies them
(9/10 parts; Harp-up differs only by validation's own seam snap 187.75 -> 188,
recorded at the snapped time).

On soft r6 p2: exact 209 -> 211, extras 56 -> 60, audit 155/35 -> **159/31**,
objectionable 40 -> **36** (28 / 3 / 5). Relief is the gain (Cl2 m.80 end,
Euph m.37 end). **Snap is a wash:** +4 GT (Fl1 256, Cl1 272, Harp-up 320,
Euph 279) and -4 GT (Fl1 273 and 312.5, Cl2 257, Harp-up 280) -- places where
a part legitimately breathes a beat off the ensemble.

**Own-evidence check (same day).** The part's own `Sel` at target / current
separates the two sets cleanly: good snaps 0.74-1.0, bad 0.20-0.48. Snap now
requires `Sel(target) >= 0.6 * Sel(current)`: the ensemble breaks near-ties
and never overrides a clear preference of the part. Result (X2): **exact 215,
extras 56, audit 159/31, objectionable 36** -- +6 GT over soft r6 p2 with no
added conflicts. Similarity weighting (§19) was not adopted: at these instants
most supporters have windowed rhythm similarity 0, including every supporter
of a correct snap, so weighting by it would discard good support.

**Relief for suppressed peaks — the every-bar passages (same day).** Most
missed close-pair GT breaths have their own peak (acc 0.4-1.4) one bar from a
found breath; soft r6 p2 scales a peak 4 qn away by (4/6)^2 = 0.44, under the
gate. The ensemble is the local evidence that a passage breathes every bar, so
`--ensemble_relief_suppressed` extends gate relief to peaks that cleared the
gate but were suppressed by grouping (support >= 3, no own boundary within
`--ensemble_clear_qn`, 3.5 qn so bar-spaced breaths pass). X3:

| Run | Exact | Extras | Audit P/F | Objectionable (missed/banned/objected) |
|---|---|---|---|---|
| X2 `--ensemble` | 215 | 56 | 159/31 | 36 (28/3/5) |
| **X3** + `--ensemble_relief_suppressed --ensemble_clear_qn 3.5` | **227** | 66 | **165/25** | **31** (22/3/6) |

+12 GT for +10 conflicts (F 0.81 -> 0.82; clear 2.0 gives the same within 2).

### (11) `--e0b_compare` — one-note-early breaths (2026-11-04)

With endpoint evidence at releases, a seam can be tested properly: evidence
at b describes the note ending at b; evidence at rel(n) describes the note n
starting at b. Under `--endpoint_release`, `--e0b_compare` moves a seam
boundary to rel(n) only when n has endpoint evidence (> ev_min) **and the
note ending at b is a short passing note (Long(b) < 0.2)** -- after a long
arrival note a breath at b is natural. A first version with an evidence
margin re-created the late landings (Oboe/Trumpet m.82 end -> m.83 b2);
on its 12 shifts, every good one had Long(b) <= 0.18 and every harmful one
>= 0.35. Threshold fitted on one piece: check on Dvořák.

| Run | Exact | Extras | Audit P/F | Unison | Objectionable |
|---|---|---|---|---|---|
| X3 | 227 | 66 | 165/25 | 1 | 31 (22/3/6) |
| **X4** = X3 + `--e0b_compare` | **230** | **64** | **167/23** | **0** | **29** (20/3/6) |

X4 verifies 10/10 and renders 294/294 (the one annotation "extra" is a
printed Oboe comma in the input). All GT unison constraints pass.

### (12) Ensemble consensus refinements (2026-11-04)

- Relief maps a candidate peak to a breath instant as E0b does (the release
  of the note sounding at the peak), not "nearest release within +0.5 qn":
  a peak at 319.375 inside a note ending at 320 was unmappable.
- `--ensemble_passes N`: support is recomputed from the previous pass. At
  m.80 end only 3 parts breathed before the pass and 4 joined during it, so
  Cl1 never saw the consensus it belonged to. Bounded, arbitration-only
  passes -- not the open-ended cascade rejected for E0b.
- `--ensemble_strong_support K`: with >= K other parts breathing at a
  candidate, the relief floor drops from 0.5 to 0.33 of the gate.

X6 = X4 + `--ensemble_passes 2 --ensemble_strong_support 5`: **exact 231,
extras 64, audit 168/22, 0 unison violations, objectionable 28 (19/3/6)**;
verifies 10/10. Each refinement alone changes nothing on Liz; together they
recover Cl1 m.80 end.

### (13) `--slur_seam_open` — m.31 end (2026-11-04)

At m.31 end (qn 124) Cl1, Cl2 and Euph each have one slur ending and the next
beginning, plus a hairpin starting there. The start-edge masks turned strong
evidence (slur-end bump 0.79, dim. end 0.6) into Sel 0, and `explain` printed
"INSIDE SLUR (breath forbidden)" at a point the slur rulings allow. Unmasking
every slur start was rejected in (5); this flag unmasks only **slur seams**:
one slur's chain release == the next slur's start, with no slur spanning
the point. `--e0b_compare` never shifts away from a seam (it had pushed Cl2
m.31 end to the banned m.32 b3; guarding every slur release instead cost
3 GT).

Robert's 2026-11-04 verdicts are now in `review/objections_2026-11-03.json`:
ASax m.38 end objected; Euph and Harp-low m.38 end and Harp-up m.66 end
**accepted** (banned in GT, not counted). Harp-low misses matter less;
m.31 end matters.

| Run | Exact | Extras | Audit P/F | Unison | Objectionable (missed/banned/objected) |
|---|---|---|---|---|---|
| X6 | 231 | 64 | 168/22 | 0 | 26 (19/0/7) |
| **X7** = X6 + `--slur_seam_open` | **237** | **63** | **171/19** | **0** | **22** (16/0/6) |

X7 gains Cl1 and Euph m.31 end, the printed Oboe m.40 breath, Cl2 m.20 b3 and
ASax m.39 b3; verifies 10/10 and renders 300/300 with no extras.

### (14) Defaults (2026-11-04)

The CLI defaults of `sectioning_v2_11_A.py` are now X7: `--slur_end_release
--filter_after_anchor --tie_open_start --endpoint_release --e0b_compare
--slur_seam_open --ensemble --ensemble_relief_suppressed` on;
`--peak_grouping soft --peak_distance_qn 6.0 --soft_power 2
--ensemble_passes 2 --ensemble_strong_support 5 --ensemble_clear_qn 3.5
--rest_seam_policy seam --f1_fermata_weight 1.0 --f1_dim_end_weight 0.6`.
Printed breath weight stays 0. Each boolean has a `--no-` form;
`--legacy_defaults` restores F1c (verified identical, 105/105 and with C1
flags 238/238). Defaults are CLI-level: code calling `run_sectioning()`
directly still gets the module globals' legacy values.

### (15) Dvořák 9/iv, first run (2026-11-04, unsealed by Robert)

`Dvorak_no9_colored_cut.mxl`: 15 parts (winds, brass, timpani, strings),
608 qn, no GT, no printed breath marks. Runs in ~60 s; replay verifies 15/15.

| Run | Boundaries | Median same-part gap | Gaps < 4 qn | Gaps < 2 qn | Ensemble changes | annotation_check |
|---|---|---|---|---|---|---|
| C1 settings (`--legacy_defaults` + C1 flags) | 553 | 8.0 qn | 33 | 11 | 0 | 531 ok, 4 late, 18 missing, 17 extra |
| **X7 defaults** | 777 | 8.0 qn | 2 | 1 | 156 | 765 ok, 2 late, 10 missing, 10 extra |

Findings to check, before any tuning on Dvořák:
- **Ensemble support threshold does not scale.** `min_support = 3` other parts
  is far easier with 15 parts than with 10; 156 changes over two passes.
  Likely needs a fraction of active parts (e.g. >= 30%) instead of a count.
- **Entry-instant boundaries after short rests** (e.g. strings qn 64, m.16
  end): no note releases there, so the comma renders on the note before the
  rest -- musically plausible, but the boundary time sits one rest late. E0c
  says the written rest is the separator: such a boundary should snap to
  the release before the rest (the 0.25 qn seam snap does not reach a
  quarter rest).
- Whether 777 is over-segmentation is Robert's call from the score.

### (16) Dvořák ensemble agreement and the doubling vote (2026-11-04)

Robert's read of m.1-35: good, a bit extraneous; most breaths here should be
unison and most unison ones are present. `ensemble_report.py` clusters breath
instants across parts and labels each UNISON (>= 60% of the parts sounding
there breathe), LONE (<= 2 parts and <= 25%), or partial. X7, m.1-35: 37
clusters, 16 unison, 10 partial, 11 lone; whole excerpt 197 / 49 / 49 / 99
(`review/dvorak_X7_ensemble_*.md`).

- Tutti unison points are found: m.9 end 14/15, m.13 b2 12/15, m.15 b2 13/15,
  m.19 b2 13/15, m.23 b2 13/15, m.25 b3.5 13/15.
- 7 of the 11 lone breaths are in Horns III-IV, Trumpets and Trombone III at
  m.12 b3, m.15 end, m.19 b2.5, m.23 b2.5 -- the theme-carrying brass, which
  are exactly the parts "sounding but not breathing" at the tutti points. They
  may be the theme's own phrase ends (relevant to melody detection), or a
  near-miss of the tutti breath one eighth earlier. Robert's call.
- Strings-only passages split: m.6-7 the five string parts play identical
  onsets and slurs (qn 20-28) yet breathe at 19.75 / 20 / 21.5 / 27.5 / 29;
  m.26-32 Vn1 and Viola share a rhythm but not breaths (Vc = Cb agree).

**Rejected: `--doubling_vote`** (kept, default off). Parts with identical
onsets within +/-4 qn vote, Sel-weighted, to breathe together. Dvořák: lone
clusters 99 -> 75, unison 49 -> 55. But it does not unify m.6-7 (the window
spans the preceding bar, where the strings' figures differ), and on Liz it
costs: 8 of its 9 additions are conflicts and it removes one GT breath
(exact 237 -> 236, extras 63 -> 71, objectionable 22 -> 24). In Liz, parts
with identical rhythm (Tpt/Euph, the two harp staves) are often given
different breaths in GT: rhythmic doubling is not phrase identity.

### Remaining violations, soft r6 p2 (2026-11-04, `violations_report.py`)

| Group | Count | Fix |
|---|---|---|
| Ensemble seams m.80 end, m.31 end + bans m.38 end, m.81 b2 + Harp-low with no own evidence | ~15 | **E** (§19) |
| Every-bar passages (close GT pairs, m.40-43, m.58-60) | ~10 | local spacing relief where fermata/rit./repeated phrases signal it |
| Breath one note early (stuck at final note's onset) | 5 | finish D1: type Struct and Cross |
| Oboe m.93 b15 (quintuplets vs D = 8), m.94 end (gate) | 2 | snap boundaries to real note releases |
| Harp-up m.61 b3 (short entry note after rest, no shift) | 1 | E0c entry shift when the entering note is short |

### Tools added

| Tool | Purpose |
|---|---|
| `group_trace.py RUN [PART QN] [--vs RUN2] [--verify]` | Offline replay of peak grouping (both modes) from `result.pkl`; `--verify` proves the replay equals the pipeline |
| `fail_trace.py RUN FAILS.txt` | Attributes each audit FAIL to its stage |
| `score_run.py RUN ...` | Exact, extras, audit, unison, FAIL causes on one line |
| `review_list.py BASE NEW` | New conflicts with GT relative to a base run, as a fill-in table |
| `history_check.py TABLE.md` | What every GT and audit file ever recorded at a set of positions |
| `review/objections_2026-11-03.json` | Robert's objectionable set, read by `score_run.py` |

---

## 17. G1 / G2 — direction-text lexicon and rehearsal marks

F1 has already absorbed the load-bearing half of G1: *cresc./dim./decresc.* as
typed events, and Line-spanner span association for the dashed extensions. Two
pieces remain.

**Unclassified-text report.** Every `TextExpression` that the lexicon does not
recognise gets listed, with part, offset, and text. This is a proof-of-life
instrument, not a feature: the cue text *"If no trumpet, play"* in Liz should
appear there. If the report is empty, the extractor is broken, not the score.

**Rehearsal-mark extraction.** The boxed letters (E, F, ...) are strong section
evidence and are currently **unread**. Design:

```
kind        rehearsal
side        before-side      (a rehearsal letter starts a section)
typing      neighborhood-typed, per D1
weight      default 0.0, one validation run
```

Probe `music21`'s `RehearsalMark` support before writing anything. Note that
the "before-side" placement makes this the first channel where the start-edge /
end-edge distinction (§18) is not optional — a rehearsal letter marks where the
*next* section begins, and the breath belongs to the *previous* one.

---

## 18. D1 — typed channels (the keystone)

Replace the scalar `zeta · Struct_i` with a **typed decomposition**. Each
structural event carries a type:

```
dynamic / key / time / tempo   ->  change
fermata                        ->  endpoint
rit. / rall. text              ->  continuation over the gesture span
                                   PLUS endpoint at the span end
                                   (the dedup slide already knows the end)
```

```
boost_i = gamma·SlurEnd_i
        + zeta_chg·Struct_change_i
        + zeta_end·Struct_endpoint_i
        + eta·norm(Cross_i)

Mult_i := Mult_i · (1 - d_struct · Struct_cont_i)
Pen_i  := Pen_i  + pi_struct · Struct_cont_i
```

Each channel additionally carries a `{type, precision/window, side}` record.
Three consequences make this the keystone:

1. **Start-edge versus end-edge.** A gap produces both. The breath lives on the
   end-edge; sectioning legitimately cares about both. This is the prerequisite
   for the entry-onset *penalty* (currently only a diagnostic field).
2. **Borrowed cross-support must carry channel type.** The m.59 diagnosis is the
   proof: the ASax boundary at qn 232.5 splits a two-eighth pickup, and it was
   reinforced by five parts contributing 0.3–0.6 each — all of it long-note
   *arrival* evidence at qn 232–233. Cross-support amplified a consensus of the
   wrong evidence type. Untyped borrowing is not evidence, it is noise with a
   quorum.
3. **Dynamic arcs as one gesture.** Cl1 mm.18–19, `mf` → `p`, is currently two
   unrelated point events rather than one shaped span.

---

## 19. E — conditional ensemble alignment, plus breathability

### Snap arbitration

For a boundary b in part i, over other parts' boundaries within tolerance
`tau` in [1.0, 1.5] qn:

```
b* = argmax over b' in Neighbourhood(b, tau) of

         sum over j != i of
             [ 1 if some b_j in B_j has |b_j - b'| <= eps else 0 ] · sim_ij
```

Tolerance is data-backed: the mm.40–42 near-misses are ~1.0 qn, while the
current cross-support `max_shift` is only 0.5. Cl2's boundary at qn 167.0 has
one supporter (Cl1, sim 0.887) whose peak sits at 166.0 — outside the window,
so only slope was borrowed (0.405 of 0.592).

Subject to:

1. **Arbitration only.** `b*` must be an existing candidate of part i. E may
   never generate a boundary where none was proposed.
2. **Shape veto.** Reject `b*` if the phrase-material report flags the resulting
   segment as degenerate ("awkward 3 notes").
3. **Tacet parts contribute nothing**, in either direction.
4. **Attribution is first-class** (E1, already shipped): which parts voted, at
   what similarity.
5. Lonely-weak-peak downweight ships default-off.

**Honestly parked limitation.** Harp qn 212 (end of m.53): *zero* parts pass the
similarity gate at the musically correct breath. The evidence is
call-and-response — Cl1 m.50 → ASax+Harp m.51 → Cl1 m.52 — and a synchronous
rhythm-window cosine is structurally blind to sequential imitation. Snap cannot
fix this case. It needs a lagged similarity, which is not in scope.

Test set: ensemble seam rulings at ends of mm. 45/59/74/76/80/82/84/88;
Cl1/Cl2/ASax mm.40–42; Trumpet+Euph mm.56–57; m.93 unison, where four parts
already hold qn 370 and a unison constraint exists. Poster child: the
Trumpet/Euphonium desert.

### Breathability limit

Consume the `too_long_to_breathe` flags already produced (passively) by
`phrase_material.py`:

```
if elapsed_sec(segment) > Theta_breath:
    force the best interior candidate, ranked by Sel_i
```

Physical **seconds**, not quarter notes — the constraint is lung capacity, and
it is tempo-dependent.

---

## 20. H — ornament continuation spans

Trill, tremolo, glissando given **tuplet-style semantics**: interior
suppression, endpoints eligible.

```
Mult_i := Mult_i · (1 - d_orn · orn_i)
Pen_i  := Pen_i  + pi_orn · orn_i

d_orn, pi_orn  default 0.0
```

**Probe first.** The unprotected case is a *sequence of separately-attacked
trilled notes*: each carries its own `Trill` expression, so there is no spanner
to define an interior, and the run reads as a burst of independent ornaments.
Whether `music21` exposes anything span-like there decides whether H is a
five-line change or a whole extraction problem. F1 already registers ornament
events at weight 0.0, so the inventory exists — read `f1_events.json` before
writing code.

---

## 21. The repetition mask (experimental, default 0.0)

Origin: ASax m.54 (qn 212.5–226), slurred three-eighth cells recurring every
2 qn. Transitive peak-grouping picked an arbitrary first-cell winner on a
near-tie (0.828 vs 0.801). Musical ruling: it is *one* phrase — "this is
basically a tuplet and you are breaking it."

```
Rep_i(t) = max over lag in [0.5, 3.0] qn of

               min( sim_fwd(t, lag),
                    max( sim_back(t, lag), rest_back(t, lag) ) )

    cosine on phi_rhy rows, windowed +/- 1 qn
    best_lag per frame is the explanation
```

`rest_back` is deliberately **one-sided**: silence *behind* counts as interior
(a phrase cannot end one cell after a rest); silence *ahead* never counts (the
last cell before a rest is a legitimate ending).

`Rep_i` enters `Mult_i` (via `d_rep`) and `Pen_i` (via `pi_rep`), and
multiplicatively discounts the gap grid `Gap_i` — but never `Long_i`, since
texture exits arrive on long notes and must survive.

**Demoted to experimental.** It devastates accompaniment parts where rhythmic
repetition is the baseline texture, not an exceptional signal. Retrial is
authorised but must be instrumented (diff + audit series), with role-gating
melody-versus-accompaniment as the fallback variant. The correct path for those
parts is **E + breathability**, not repetition masking.

Two delivery lessons worth not relearning:

1. Masking rhythm novelty *at source* is distorted by internal renormalisation.
   Mask **post**-normalisation, inside `compute_per_part_boundary_signal`.
2. The dominant evidence at m.54 was the slur-endpoint bump at 0.979 per cell —
   each cell individually slurred. Periodic *articulation* must be masked too,
   not just periodic rhythm.

---

## 22. Summary — the algorithm in one page

For each part independently:

```
 1  parse; group same-offset events; merge tie chains; record boundary_offset
 2  frame features: phi_chr (13-d, rest dimension), phi_rhy (3-d)
 3  two self-SSMs; checkerboard convolution along the diagonal
        -> nu_chr, nu_rhy
 4  LBDM on the merged note list (pitch / IOI / rest; degree of change;
    boundary strength)                              -> Lambda
 5  arrival grids                                   -> Long, Gap
 6  marking channels: slur interior + endpoints, hairpin, tuplet,
    tie vetoes, typed and deduplicated structural events
 7  two-pass cross-part rhythmic support            -> Cross
 8  F1 expressive events at tie-chain releases      -> F1  (exact deltas)

 9  B = (B_raw + boost + F1) · Mult · veto

10  form Cand (seed), Sel (rank), Acc (gate);
    pick peaks, group transitively within 2.5 qn,
    winner-take-all by Sel, accept on Acc >= 0.30

11  filter degenerate segments            <- runs FIRST (legacy order);
                                              --filter_after_anchor swaps
                                              11 and 12 (v2.11-A, §16c(3))
12  re-anchor onset-landed boundaries to note releases (one step, gated)
13  validate rests and outgoing ties; resolve breath targets
13  emit commas at the note releasing at each boundary,
    plus a full record of every decision
```

**Where the current work sits (2026-11-03).** v2.11-A ships opt-in repairs for
step 10 (transitive grouping, `--peak_grouping nms`), step 6's tie masks
(`--tie_open_start`) and the 11/12 ordering (`--filter_after_anchor`); defaults
await Robert's review of `review/v2_11_A_candidate_vs_C1.md`. The dominant
remaining defect class is **evidence typing** (D1): onset-typed vs
release-typed evidence decides whether E0b should move a boundary (late
landings, §16c(4)) and whether borrowed cross-support is relevant (ASax
232.5). Two shortcuts around D1 were tried and rejected (§16c). Next: D1, then
E; G1/G2 and H remain cheap and unstarted.

---

## 22b. Open items surfaced by the B3 audit

**m.41 unison still violated.** `gtv2_errata_m41_unison` at qn 164: Fl2, Cl2 and
ASax present; Fl1 and Cl1 absent, Cl1's nearest at m.40 end. B3 cleared Cl1's
banned m.41 b4 but produced nothing at m.41 end — the deferred anchor vanished
rather than relocating. This is the passage F1b(a)'s docstring is built on. E's
ensemble alignment is the designed fix, but run one `explain` first to confirm
the anchor is not being lost at extraction.

**Oboe m.93 b14.8 is a two-for-one.** It is a banned FAIL (present) *and* it
blocks required m.93 b15 — nearest 381.8, off by 0.2. `release_ok: false`,
mid-note. One fix clears two audit points.

**`gt_rendered.musicxml` is clean — caveat withdrawn 2026-09-02.**
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
mark is a mistake, removed from `gt_rendered.musicxml` (commit `f278d9f`).
Re-baselined in §15. Ruling recorded in §23.

**Remaining unison violations.** `gtv2_ensemble_seam_m80_end` (Fl1 absent, Fl2
at 319.75) and `gtv2_unison_final_chord_release` (Fl2 absent at qn 390). Both
are E workload. `gtv2_unison_m93_fermata_release` passes in all five parts.

---

## 23. Rulings ledger

Consolidated from `HANDOVER_sectioning_v2_10_E0c.md` §3 and
`HANDOVER_addendum_2026-07-19.md` §3, plus the 2026-08-19 slur rulings. **Do not
re-litigate.** Robert holds all musical authority; these are his calls.

### Breath placement convention

- A boundary time is the **release instant** of the phrase-final note.
- The comma attaches to the note **releasing** at the boundary — i.e. a mark
  "on note n" means *breathe after n*.
- The breath follows the note whose arrival/gap evidence created the boundary,
  at seams and at entries from silence alike.
- **No comma at entry instants**; the written rest is the separator.
- One-step anchoring only. Cascade iteration tested and rejected (§13).

### Slurs (2026-08-19)

- **Breath at a slur start is allowed.** The comma attaches to the note
  *before* the slur; the breath separates that note from the slurred phrase and
  does not split it.
- **Breath at a slur's chain release is allowed.** The comma attaches to the
  last slurred note.
- **Breath strictly inside a slur is forbidden**, including at the last slurred
  note's onset — that placement detaches the final slurred note.
- An F1 anchor landing strictly inside a slur **defers** to the chain release.
  Deferral, not masking: the evidence is real, its position was wrong.

### Scoped exceptions

- **F1 anchors decline the E0b seam shift in attacca passages** (F1b-b). Scoped
  to F1-originated anchors only; E0b is otherwise unchanged.

### Score-specific

- **m.93 unison**: breath after the first note of m.93, release at b3, in Fl1,
  Fl2, Cl1, Cl2, Euph — constraint parts [0,1,3,4,7].
- **m.94 final chord**: comma after it, m.94 end, required in [0,1,2,3,7,8,9].
  **Oboe unbanned 2026-11-04** (Robert): the earlier ban (its last m.93 note
  ties into m.94) is withdrawn; GT carries Oboe m.94 end as required, matching
  the hand-corrected score.
- **Euphonium m.89 end → m.90 end**: Robert's manual GT edit, intentional.
- **Oboe m.93 b14.8 stays banned.** 0.2 qn off is wrong and wrong.
- **Oboe m.86 b4.75 (qn 343.75) is not a breath** (2026-09-02). The GT mark sat
  at the onset of a slur's last note, which the slur rulings forbid; removed
  from the score and banned.
- GT v2 supersedes all per-case rulings in the deprecated audit file.
- The **hand-corrected score is the authority**, not any compiled artifact.
