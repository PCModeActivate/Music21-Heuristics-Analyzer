# Review: breaths new in the v2.11-A candidate (all three fixes) vs C1

Base: `output_v2_10_F1c/liz_seam_C1_slur_release`  
New: `output_v2_11_A/liz_F3_filter_tie_nms4`

Listed: boundaries in the new run that are not GT, not banned, and not in the base run, i.e. **new conflicts with GT**. The comma sits after the note releasing at that instant. Fill in **ok** or **no**. "Earlier record" comes from `history_check.py` over every GT and audit file; per ALGORITHM.md 23 the 2026-07-10 audit rulings are superseded by GT v2, so they are evidence, not decisions. Where each comma is drawn: `v2_11_A_candidate_vs_C1_where.md` (same row order).

| part | instrument | position | qn | rest after (qn) | earlier record | ok / no |
|---|---|---|---|---|---|---|
| 0 | Flute 1 | m.4 b3.0 | 14.000 | 0.00 |  | ok (not objected to) |
| 0 | Flute 1 | m.16 b3.5 | 62.500 | 0.00 |  | ok (not objected to) |
| 0 | Flute 1 | m.18 b2.5 | 69.500 | 0.50 | **renders on the wrong note** (E6 after the rest); judge the breath at m.18 b2.5 | ok as position; renderer must draw it on the note before the rest |
| 0 | Flute 1 | m.87 b1.0 | 344.000 | 0.00 | 2026-07-10 audit: present ("Recommended") | ok (not objected to) |
| 0 | Flute 1 | m.88 b1.0 | 348.000 | 0.00 |  | no |
| 1 | Flute | m.75 b4.0 | 299.000 | 0.00 |  | no |
| 2 | Oboe | m.17 b1.0 | 64.000 | 0.00 |  | ok (not objected to) |
| 3 | Clarinet in B♭  1 | m.40 b1.0 | 156.000 | 0.50 |  | ok (not objected to) |
| 3 | Clarinet in B♭  1 | m.88 b1.0 | 348.000 | 0.00 | 2026-07-10 audit: **absent** ("Cl1 m.87-end mark not allowed") | ok (not objected to) |
| 4 | B♭ Clarinet | m.45 b1.0 | 176.000 | 0.00 | 2026-07-10 audit: **absent** ("no m.44-end mark allowed") | no (soft: "understandable somewhat") |
| 4 | B♭ Clarinet | m.73 b1.0 | 288.000 | 0.00 |  | ok (not objected to) |
| 4 | B♭ Clarinet | m.75 b4.0 | 299.000 | 0.00 |  | no |
| 5 | Alto Saxophone | m.56 b1.0 | 220.000 | 0.50 | 2026-07-10 audit: present ("Recommended") | no |
| 5 | Alto Saxophone | m.58 b1.0 | 228.000 | 0.00 | 2026-07-10 audit: present ("Recommended") | ok (soft: "more understandable") |
| 6 | Trumpet in B♭ 1 | m.11 b1.0 | 40.000 | 0.00 |  | ok (not objected to) |
| 6 | Trumpet in B♭ 1 | m.54 b3.0 | 214.000 | 0.00 |  | no |
| 6 | Trumpet in B♭ 1 | m.57 b1.0 | 224.000 | 0.00 | context: "Trumpet mm.56-57 misalignment" (review 2026-07) | ok (soft: "more understandable") |
| 7 | Euphonium | m.9 b3.0 | 34.000 | 0.00 |  | no |
| 7 | Euphonium | m.16 b1.0 | 60.000 | 0.00 | 2026-07-10 audit: **absent** ("Not allowed (existing qn 60)") | no |
| 7 | Euphonium | m.55 b1.0 | 216.000 | 0.00 | context: reference boundary (audit v2 LIZV2-021) | no |
| 7 | Euphonium | m.58 b1.0 | 228.000 | 0.00 | context: reference boundary (audit v2 LIZV2-022) | ok (soft: "more understandable") |
| 7 | Euphonium | m.63 b4.0 | 251.000 | 0.00 |  | no |
| 7 | Euphonium | m.67 b3.0 | 266.000 | 0.00 |  | ok ("67 is understandable"; corrected 2026-11-03) |
| 7 | Euphonium | m.71 b4.0 | 283.000 | 0.00 |  | no |
| 7 | Euphonium | m.73 b1.0 | 288.000 | 0.00 |  | ok (not objected to) |
| 8 | Harp | m.24 b1.0 | 92.000 | 0.00 |  | ok (not objected to) |
| 8 | Harp | m.26 b1.0 | 100.000 | 0.00 |  | ok (not objected to) |
| 8 | Harp | m.41 b1.0 | 160.000 | 0.00 |  | ok (not objected to) |
| 8 | Harp | m.42 b1.0 | 164.000 | 0.00 |  | ok (not objected to) |
| 8 | Harp | m.56 b1.0 | 220.000 | 0.50 | 2026-07-10 audit: present ("Recommended") | no |
| 8 | Harp | m.63 b1.0 | 248.000 | 1.00 |  | ok ("62 end is understandable"; same breath as the m.63 b1 instant) |
| 8 | Harp | m.93 b1.0 | 368.000 | 18.00 |  | ok (not objected to) |
| 9 | Harp | m.92 b3.0 | 366.000 | 20.00 |  | ok ("fine") |

33 positions.

## Reviewer verdicts, 2026-11-03 (Robert)

Reviewed on his own F3 run (boundaries identical to ours: 275/275). Every
listed row conflicts with GT; he marked the ones he finds objectionable and
lets the rest pass as acceptable. "Not banned" carries no weight: bans are
warnings from an earlier iteration, and any disagreement with GT is a
conflict. The objectionable set is machine-readable in
`review/objections_2026-11-03.json` and scored by `score_run.py`.

Outside the 33, on boundaries already present in C1:

| part | comma on | breath instant | qn | verdict |
|---|---|---|---|---|
| Flute 1 (0) | G4, m.85 b1 | m.85 b3 | 338.000 | no |
| Harp upper (8) | A5, m.54 b2.5 | m.54 b3 | 214.000 | no |
| B-flat Clarinet (4) | E-flat4, m.71 b1 | m.71 b4 | 283.000 | no |
| Harp lower (9) | A-flat3+C4, m.91 b1 | m.91 b3 | 362.000 | no |
| Alto Saxophone (5) | F#5, m.54 b2.5 | m.54 b3 | 214.000 | no (already banned in GT v2) |

Totals for the 33: 12 objectionable, 21 acceptable (#23 corrected from no to ok). Note that the 2026-07-10 audit's
"Recommended" rulings at ASax and Harp end of m.55 are overturned here.
