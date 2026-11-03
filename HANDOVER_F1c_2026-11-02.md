# HANDOVER — F1c(a) validation, 2026-11-02

Read with `ALGORITHM.md` (1566-line revision, F1b merge + F1c provisional),
which carries the design. This file carries only what changed since and what
to do next. `ALGORITHM.md` still has four `PENDING (2026-09-02)` blocks; the
numbers below are what fills them.

---

## 1. State of the repo

| Item | State |
|---|---|
| `sectioning_v2_10_F1b.py` | Validated reference. Untouched. |
| `sectioning_v2_10_F1c.py` | Built by `patch_F1c_slur_release.py`. `--slur_end_release` **default OFF**. |
| `explain.py` | Must import `sectioning_v2_10_F1c` (stale-import hazard, 3rd time). |
| GT | 262 points. Oboe m.86 b4.75 (qn 343.75) removed, now banned. |
| `gt_liz_v2_2026-09-02.json` | 54 banned after `fix_gt_bans_2026-09-02.py` restored the 53 that `gt_from_score.py` dropped. |
| Audit file | **`audit_cases_gt_v2_2026-09-02.json`** — 190 points. The 07-19 file is superseded. |

**Known tool defect:** `gt_from_score.py` builds `removed_points` only from prior
GT points that lost their mark *this run* and never carries the prior's own
bans forward. Every future GT correction will drop them again until fixed
(about three lines: carry `prior['per_part'][i]['removed_points']` forward).

---

## 2. Measured results

All against the 262-point GT and the 09-02 audit file.

| Run | Audit PASS/FAIL | Exact | Moved | Extras |
|---|---|---|---|---|
| B3 `output_v2_10_F1b/liz_seam_B3_all` | 107 / 83 | 194 / 262 | 11 | 38 |
| C0 `output_v2_10_F1c/liz_seam_C0_control` | identical to B3 — 243 unchanged, 0 changes | | | |
| C1 `output_v2_10_F1c/liz_seam_C1_slur_release` | **128 / 62** | **198 / 262** | 5 | 35 |

C0 = B3 confirms the `phrase_spans` half of the patch is behaviour-neutral.

**Band verdict: exceeded.** Predicted 13 moves, +6 required, 0 losses, ~+12
audit. Actual: 41 changes (10 moved, 18 removed, 13 added C0→C1), +21 audit.
Cause of the undercount: `slur_release_probe.py` counted only boundaries
*at* a last-slurred-note onset. The bump is Gaussian-smoothed (σ 0.5 qn), so
moving it later by a note duration also changes which peak wins each 2.5 qn
transitive group — collateral the probe never saw. Same lesson as F1b's B1.

### Gains (15 GT points), by part

Fl1 148, 164, 170 · Fl2 170, 204 · Ob 148, 296, 320 · Cl1 236 ·
Cl2 72, 124, 160, 296 · ASax 160 · Harp-lo 124.

Banned positions cleared: Fl1 147 · Fl2 199.5, 203.5 · Ob 147, 262, 339.75,
343.75, 381.8.

### Losses (11 GT points) — 10 kept, 1 required

| Part | qn | measure | status |
|---|---|---|---|
| Harp-up (8) | **328** | m.82 end | **required** |
| Harp-up (8) | 256 | m.64 end | kept |
| Cl2 (4) | 78, 236, 257 | m.20 b3, m.59 end, m.65 b2 | kept |
| ASax (5) | 154, 281 | m.39 b3, m.71 b2 | kept |
| Fl1 (0) | 155 | m.39 b4 | kept |
| Fl2 (1) | 164 | m.41 end | kept |
| Ob (2) | 232 | m.58 end | kept |
| Cl1 (3) | 232 | m.58 end | kept |

### Confirmed cases that did NOT resolve

- **ASax 171 → 172.** Still moved. Bump relocated, but other evidence
  (struct 0.420, cross 0.561 at 171 in B3) may hold the peak.
- **Oboe 382 (m.93 b15).** Banned 381.8 is gone but 382 did not appear.
  Hypothesis: the release lands on the onset of the tied D6 (dur 8.00), and
  the natural-tie veto zeros it.

### Unison constraints

Still 3 violations, composition changed: m.80 seam now has Fl2 at 320.0 but
Fl1 absent; m.41 now has Fl1 but lost Fl2.

---

## 3. Next actions, in order

**1. Explain the required loss and the two non-resolutions.**

```bash
python explain.py output_v2_10_F1c/liz_seam_C1_slur_release 8 83 1 --window 6
python explain.py output_v2_10_F1b/liz_seam_B3_all          8 83 1 --window 6
python explain.py output_v2_10_F1c/liz_seam_C1_slur_release 5 43 4 --window 6
python explain.py output_v2_10_F1c/liz_seam_C1_slur_release 2 93 15 --window 4
```

Harp-up m.82 end in B3 vs C1 shows whether a relocated bump stole its peak
group. ASax and Oboe test the two hypotheses above.

**2. Classify the 10 kept losses** as regrouping collateral versus genuine
evidence loss. If most are regrouping, the problem is §12 Failure mechanism 2
(transitive grouping), not F1c(a).

**3. Decide `--slur_end_release` default.** Robert's call: +21 audit / +4
exact, against 10 kept points and 1 required point.

**4. Fill the four `PENDING (2026-09-02)` blocks** in `ALGORITHM.md` with §2
above, and add the §23 ruling for m.86 b4.75.

**5. Then the queue, unchanged:** re-probe F1c(c) (may be redundant after
(a)) → F1c(b) slur-start mask → the three late-landing moved boundaries
(Ob 328→329, Cl2 184→185, Harp-up 320→321) → **E** (five barline clusters)
→ FM3 trio (2 points) → F1b(d) → `gt_from_score.py` ban-carry fix.

---

## 4. Hazards observed this thread — do not repeat

- **Read the writer before reading the data.** Four probes returned
  confidently wrong numbers from guessed `result.pkl` schemas. New probes dump
  the schema first.
- **`slur_starts` / `slur_ends` are not index-parallel.** Use `phrase_spans`.
- **No placeholders in commands.** `<audit cases>` in the F1c patch's printed
  NEXT block cost a run. Every command complete and copy-pasteable.
- **Project docs ≠ git.** The F1b `ALGORITHM.md` merge sat in project docs for
  two months while git held the 971-line pre-merge copy. Commit what you merge.
