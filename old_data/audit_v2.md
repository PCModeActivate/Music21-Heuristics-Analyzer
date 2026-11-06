# Liz v2 manual audit cases

This file is generated from the revised V2 list. It is **not full ground truth**; it is a compact diagnostic/regression list.

Boundary source: `boundaries.json`; detection: `None`.

## Tag counts

- `consensus`: 22
- `too_short`: 11
- `false_positive`: 11
- `hairpin_endpoint`: 7
- `cresc`: 7
- `too_little_material`: 7
- `preferred_boundary`: 6
- `rhythmic_run`: 3
- `rit`: 3
- `long_note`: 3
- `missing_boundary`: 3
- `merge_next`: 3
- `tie`: 2
- `hard_violation`: 2
- `slur`: 2
- `continuation_violation`: 2
- `ensemble_end`: 2
- `hairpin_interior`: 2
- `same_rhythm`: 2
- `follow_reference`: 1
- `recommended`: 1
- `phrase_end`: 1
- `merge_previous`: 1
- `too_frequent`: 1
- `phrase_material`: 1
- `triplet`: 1
- `breaks_cresc`: 1
- `long_rest_after`: 1
- `dynamic`: 1
- `phrase_start`: 1
- `single_sustained_note`: 1
- `tutti`: 1
- `wrong_target`: 1
- `breaks_decresc`: 1

## Cases

### LIZV2-001 — Fl.2 m74

- Part: `1` / Flute
- Summary: should follow Fl.1 here
- Expected action: `snap_or_add_consensus`
- Tags: `consensus`, `follow_reference`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m74 b2.0 (t=293.0)
- Nearby ±1 measure: m74 b2.0 (t=293.0), m75 b2.25 (t=297.25)
- Reference parts: Fl.1
- Suggested explain points:
  - part 1, m74, beat 2.0 — current/nearby boundary in this part
  - part 0, m74, beat 2.0 — reference part Fl.1 boundary
  - part 0, m74, beat 4.5 — reference part Fl.1 boundary

### LIZV2-002 — Oboe m66

- Part: `2` / Oboe
- Summary: breaks eighths rhythm / too short
- Expected action: `remove_or_move`
- Tags: `rhythmic_run`, `too_short`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m66 b4.875 (t=263.875)
- Nearby ±1 measure: m65 b1.0 (t=256.0), m66 b4.875 (t=263.875)
- Suggested explain points:
  - part 2, m66, beat 4.875 — current/nearby boundary in this part

### LIZV2-003 — Oboe m84

- Part: `2` / Oboe
- Summary: should follow A Sax. & Euph (rit. & half note), same as Harp Low, Tpt
- Expected action: `snap_or_add_consensus`
- Tags: `consensus`, `rit`, `long_note`, `preferred_boundary`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m84 b2.875 (t=333.875)
- Nearby ±1 measure: m83 b1.0 (t=328.0), m84 b2.875 (t=333.875)
- Reference parts: A. Sax, Euph, Harp low, Tpt
- Suggested explain points:
  - part 2, m84, beat 2.875 — current/nearby boundary in this part
  - part 5, m83, beat 1.0 — reference part A. Sax boundary
  - part 5, m85, beat 1.0 — reference part A. Sax boundary
  - part 7, m83, beat 2.875 — reference part Euph boundary
  - part 7, m84, beat 2.0 — reference part Euph boundary
  - part 7, m85, beat 1.0 — reference part Euph boundary
  - part 9, m84, beat 4.875 — reference part Harp low boundary
  - part 6, m84, beat 3.0 — reference part Tpt boundary

### LIZV2-004 — Oboe m93

- Part: `2` / Oboe
- Summary: later one breaks tie
- Expected action: `remove_hard_violation`
- Tags: `tie`, `hard_violation`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m93 b2.875 (t=369.875), m93 b9.0 (t=376.0), m93 b13.875 (t=380.875)
- Nearby ±1 measure: m93 b2.875 (t=369.875), m93 b9.0 (t=376.0), m93 b13.875 (t=380.875)
- Notes: Later m93 boundary; use exact m93 candidates and inspect tie mask/attachment.
- Suggested explain points:
  - part 2, m93, beat 2.875 — current/nearby boundary in this part
  - part 2, m93, beat 9.0 — current/nearby boundary in this part
  - part 2, m93, beat 13.875 — current/nearby boundary in this part

### LIZV2-005 — Cl.1 m31

- Part: `3` / Clarinet in B♭  1
- Summary: could use a breath at the end, recommended
- Expected action: `add_optional`
- Tags: `recommended`, `missing_boundary`, `phrase_end`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m31 b3.0 (t=122.0)
- Nearby ±1 measure: m30 b2.0 (t=117.0), m31 b3.0 (t=122.0)
- Suggested explain points:
  - part 3, m31, beat 3.0 — current/nearby boundary in this part

### LIZV2-006 — Cl.1 m53

- Part: `3` / Clarinet in B♭  1
- Summary: breaks slur
- Expected action: `remove_or_move`
- Tags: `slur`, `continuation_violation`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m53 b4.0 (t=211.0)
- Nearby ±1 measure: m52 b2.0 (t=205.0), m52 b4.875 (t=207.875), m53 b4.0 (t=211.0)
- Suggested explain points:
  - part 3, m53, beat 4.0 — current/nearby boundary in this part

### LIZV2-007 — Cl.1 m74

- Part: `3` / Clarinet in B♭  1
- Summary: should end here with cresc., same as Cl.2
- Expected action: `snap_or_add_consensus`
- Tags: `hairpin_endpoint`, `cresc`, `consensus`, `preferred_boundary`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m75 b1.0 (t=296.0), m75 b3.875 (t=298.875)
- Reference parts: Cl.2
- Suggested explain points:
  - part 3, m75, beat 1.0 — current/nearby boundary in this part
  - part 3, m75, beat 3.875 — current/nearby boundary in this part
  - part 4, m74, beat 3.0 — reference part Cl.2 boundary
  - part 4, m75, beat 2.25 — reference part Cl.2 boundary

### LIZV2-008 — Cl.1 m80

- Part: `3` / Clarinet in B♭  1
- Summary: should end here at end of cresc., same with Cl.2 & Harp High
- Expected action: `snap_or_add_consensus`
- Tags: `hairpin_endpoint`, `cresc`, `consensus`, `preferred_boundary`
- Boundary presence: `no_boundary_nearby_pm1`
- Exact-measure boundaries: none
- Reference parts: Cl.2, Harp high
- Suggested explain points:
  - part 3, m80, beat 1.0 — no nearby boundary; inspect requested location

### LIZV2-009 — Cl.2 m69

- Part: `4` / B♭ Clarinet
- Summary: should really be merged in with the next section (same as Euph)
- Expected action: `remove_or_merge`
- Tags: `too_little_material`, `merge_next`, `consensus`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m69 b1.0 (t=272.0)
- Nearby ±1 measure: m69 b1.0 (t=272.0), m70 b4.875 (t=279.875)
- Reference parts: Euph
- Suggested explain points:
  - part 4, m69, beat 1.0 — current/nearby boundary in this part
  - part 7, m69, beat 1.0 — reference part Euph boundary
  - part 7, m70, beat 4.875 — reference part Euph boundary

### LIZV2-010 — Cl.2 m74

- Part: `4` / B♭ Clarinet
- Summary: should end here with cresc., same as Cl.1 & Euph
- Expected action: `snap_or_add_consensus`
- Tags: `hairpin_endpoint`, `cresc`, `consensus`, `preferred_boundary`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m74 b3.0 (t=294.0)
- Nearby ±1 measure: m74 b3.0 (t=294.0), m75 b2.25 (t=297.25)
- Reference parts: Cl.1, Euph
- Suggested explain points:
  - part 4, m74, beat 3.0 — current/nearby boundary in this part
  - part 3, m75, beat 1.0 — reference part Cl.1 boundary
  - part 3, m75, beat 3.875 — reference part Cl.1 boundary
  - part 7, m75, beat 1.0 — reference part Euph boundary

### LIZV2-011 — Cl.2 m75

- Part: `4` / B♭ Clarinet
- Summary: follows from 74; should be removed, too short
- Expected action: `remove_or_merge`
- Tags: `too_short`, `false_positive`, `merge_previous`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m75 b2.25 (t=297.25)
- Nearby ±1 measure: m74 b3.0 (t=294.0), m75 b2.25 (t=297.25), m76 b1.375 (t=300.375), m76 b4.75 (t=303.75)
- Suggested explain points:
  - part 4, m75, beat 2.25 — current/nearby boundary in this part

### LIZV2-012 — Cl.2 m80

- Part: `4` / B♭ Clarinet
- Summary: should end here at end of cresc., same with Cl.1 & Harp High
- Expected action: `snap_or_add_consensus`
- Tags: `hairpin_endpoint`, `cresc`, `consensus`, `preferred_boundary`
- Boundary presence: `no_boundary_nearby_pm1`
- Exact-measure boundaries: none
- Reference parts: Cl.1, Harp high
- Suggested explain points:
  - part 4, m80, beat 1.0 — no nearby boundary; inspect requested location

### LIZV2-013 — A. Sax m(46, 50)

- Part: `5` / Alto Saxophone
- Summary: too frequent boundaries
- Expected action: `reduce_density`
- Tags: `too_frequent`, `phrase_material`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m46 b4.875 (t=183.875), m48 b1.0 (t=188.0), m49 b3.875 (t=194.875)
- Nearby ±1 measure: m45 b4.875 (t=179.875), m46 b4.875 (t=183.875), m48 b1.0 (t=188.0), m49 b3.875 (t=194.875), m51 b2.0 (t=201.0)
- Suggested explain points:
  - part 5, m46, beat 4.875 — current/nearby boundary in this part
  - part 5, m48, beat 1.0 — current/nearby boundary in this part
  - part 5, m49, beat 3.875 — current/nearby boundary in this part

### LIZV2-014 — A. Sax m49

- Part: `5` / Alto Saxophone
- Summary: breaks tie
- Expected action: `remove_hard_violation`
- Tags: `tie`, `hard_violation`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m49 b3.875 (t=194.875)
- Nearby ±1 measure: m48 b1.0 (t=188.0), m49 b3.875 (t=194.875)
- Suggested explain points:
  - part 5, m49, beat 3.875 — current/nearby boundary in this part

### LIZV2-015 — A. Sax m54

- Part: `5` / Alto Saxophone
- Summary: section too short (only a triplet)
- Expected action: `remove_or_merge`
- Tags: `too_short`, `rhythmic_run`, `triplet`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m54 b1.5 (t=212.5), m54 b4.5 (t=215.5)
- Nearby ±1 measure: m54 b1.5 (t=212.5), m54 b4.5 (t=215.5)
- Suggested explain points:
  - part 5, m54, beat 1.5 — current/nearby boundary in this part
  - part 5, m54, beat 4.5 — current/nearby boundary in this part

### LIZV2-016 — A. Sax m62

- Part: `5` / Alto Saxophone
- Summary: section too short (only a quarter note)
- Expected action: `remove_or_merge`
- Tags: `too_short`, `too_little_material`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m62 b1.875 (t=244.875)
- Nearby ±1 measure: m62 b1.875 (t=244.875)
- Suggested explain points:
  - part 5, m62, beat 1.875 — current/nearby boundary in this part

### LIZV2-017 — A. Sax m76

- Part: `5` / Alto Saxophone
- Summary: should end with many other instruments at end of bar
- Expected action: `snap_or_add_consensus`
- Tags: `consensus`, `ensemble_end`, `preferred_boundary`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m75 b1.0 (t=296.0), m77 b1.0 (t=304.0)
- Reference parts: Fl.1, Fl.2, Oboe, Tpt, Euph
- Suggested explain points:
  - part 5, m75, beat 1.0 — current/nearby boundary in this part
  - part 5, m77, beat 1.0 — current/nearby boundary in this part
  - part 0, m76, beat 4.875 — reference part Fl.1 boundary
  - part 1, m75, beat 2.25 — reference part Fl.2 boundary
  - part 1, m76, beat 1.375 — reference part Fl.2 boundary
  - part 1, m76, beat 4.875 — reference part Fl.2 boundary
  - part 2, m77, beat 1.0 — reference part Oboe boundary
  - part 6, m75, beat 1.0 — reference part Tpt boundary

### LIZV2-018 — A. Sax m83

- Part: `5` / Alto Saxophone
- Summary: too short (only an eighth), should follow Euph
- Expected action: `snap_or_merge`
- Tags: `too_short`, `rhythmic_run`, `consensus`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m83 b1.0 (t=328.0)
- Nearby ±1 measure: m83 b1.0 (t=328.0)
- Reference parts: Euph
- Suggested explain points:
  - part 5, m83, beat 1.0 — current/nearby boundary in this part
  - part 7, m82, beat 2.875 — reference part Euph boundary
  - part 7, m83, beat 2.875 — reference part Euph boundary
  - part 7, m84, beat 2.0 — reference part Euph boundary

### LIZV2-019 — A. Sax m87

- Part: `5` / Alto Saxophone
- Summary: breaks cresc., too short (quarter)
- Expected action: `remove_or_move`
- Tags: `hairpin_interior`, `breaks_cresc`, `too_short`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m87 b1.875 (t=344.875)
- Nearby ±1 measure: m87 b1.875 (t=344.875)
- Suggested explain points:
  - part 5, m87, beat 1.875 — current/nearby boundary in this part

### LIZV2-020 — Tpt m12

- Part: `6` / Trumpet in B♭ 1
- Summary: long rest after; other instruments stop here
- Expected action: `add_or_snap_consensus`
- Tags: `long_rest_after`, `consensus`, `missing_boundary`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m12 b3.0 (t=46.0)
- Nearby ±1 measure: m12 b3.0 (t=46.0)
- Reference parts: Fl.1, Oboe, Cl.1, Cl.2, A. Sax, Euph
- Suggested explain points:
  - part 6, m12, beat 3.0 — current/nearby boundary in this part
  - part 0, m11, beat 2.0 — reference part Fl.1 boundary
  - part 0, m13, beat 1.0 — reference part Fl.1 boundary
  - part 2, m12, beat 2.0 — reference part Oboe boundary
  - part 2, m13, beat 1.0 — reference part Oboe boundary
  - part 3, m13, beat 1.0 — reference part Cl.1 boundary
  - part 4, m12, beat 4.875 — reference part Cl.2 boundary
  - part 5, m11, beat 1.0 — reference part A. Sax boundary

### LIZV2-021 — Tpt m54

- Part: `6` / Trumpet in B♭ 1
- Summary: section too short (only a half note) and should follow Euph
- Expected action: `snap_or_merge`
- Tags: `too_short`, `consensus`, `too_little_material`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m54 b4.875 (t=215.875)
- Nearby ±1 measure: m53 b4.875 (t=211.875), m54 b4.875 (t=215.875)
- Reference parts: Euph
- Suggested explain points:
  - part 6, m54, beat 4.875 — current/nearby boundary in this part
  - part 7, m53, beat 1.0 — reference part Euph boundary
  - part 7, m54, beat 1.0 — reference part Euph boundary
  - part 7, m55, beat 1.0 — reference part Euph boundary

### LIZV2-022 — Tpt m57

- Part: `6` / Trumpet in B♭ 1
- Summary: should follow Euph (same rhythm/phrase here)
- Expected action: `snap_or_add_consensus`
- Tags: `consensus`, `same_rhythm`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m57 b1.0 (t=224.0), m57 b4.875 (t=227.875)
- Nearby ±1 measure: m56 b1.0 (t=220.0), m57 b1.0 (t=224.0), m57 b4.875 (t=227.875)
- Reference parts: Euph
- Suggested explain points:
  - part 6, m57, beat 1.0 — current/nearby boundary in this part
  - part 6, m57, beat 4.875 — current/nearby boundary in this part
  - part 7, m56, beat 1.0 — reference part Euph boundary
  - part 7, m57, beat 1.0 — reference part Euph boundary
  - part 7, m58, beat 1.0 — reference part Euph boundary

### LIZV2-023 — Tpt m59

- Part: `6` / Trumpet in B♭ 1
- Summary: should follow A Sax & Cl.2 here
- Expected action: `snap_or_add_consensus`
- Tags: `consensus`, `same_rhythm`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m59 b1.0 (t=232.0)
- Nearby ±1 measure: m59 b1.0 (t=232.0), m60 b1.0 (t=236.0)
- Reference parts: A. Sax, Cl.2
- Suggested explain points:
  - part 6, m59, beat 1.0 — current/nearby boundary in this part
  - part 5, m58, beat 2.0 — reference part A. Sax boundary
  - part 5, m59, beat 1.5 — reference part A. Sax boundary
  - part 5, m60, beat 1.0 — reference part A. Sax boundary
  - part 4, m59, beat 1.0 — reference part Cl.2 boundary
  - part 4, m60, beat 1.0 — reference part Cl.2 boundary

### LIZV2-024 — Tpt m69

- Part: `6` / Trumpet in B♭ 1
- Summary: should start new section because of piano (same as Cl.2)
- Expected action: `add_or_snap_structural_start`
- Tags: `dynamic`, `phrase_start`, `consensus`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m68 b4.0 (t=271.0)
- Reference parts: Cl.2
- Suggested explain points:
  - part 6, m68, beat 4.0 — current/nearby boundary in this part
  - part 4, m69, beat 1.0 — reference part Cl.2 boundary
  - part 4, m70, beat 4.875 — reference part Cl.2 boundary

### LIZV2-025 — Tpt m82

- Part: `6` / Trumpet in B♭ 1
- Summary: should end with other instruments like Flute 1, 2, Cl.1, Cl.2, Harp Hi, same as Euph
- Expected action: `snap_or_add_consensus`
- Tags: `consensus`, `ensemble_end`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m82 b2.875 (t=325.875)
- Nearby ±1 measure: m82 b2.875 (t=325.875)
- Reference parts: Fl.1, Fl.2, Cl.1, Cl.2, Harp high, Euph
- Suggested explain points:
  - part 6, m82, beat 2.875 — current/nearby boundary in this part
  - part 0, m81, beat 2.875 — reference part Fl.1 boundary
  - part 0, m82, beat 2.0 — reference part Fl.1 boundary
  - part 0, m83, beat 1.0 — reference part Fl.1 boundary
  - part 1, m82, beat 1.875 — reference part Fl.2 boundary
  - part 1, m83, beat 1.0 — reference part Fl.2 boundary
  - part 3, m82, beat 1.875 — reference part Cl.1 boundary
  - part 3, m82, beat 4.875 — reference part Cl.1 boundary

### LIZV2-026 — Tpt m84

- Part: `6` / Trumpet in B♭ 1
- Summary: should follow A Sax. & Euph (rit. & half note), same as Harp Low, Oboe
- Expected action: `snap_or_add_consensus`
- Tags: `consensus`, `rit`, `long_note`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m84 b3.0 (t=334.0)
- Nearby ±1 measure: m84 b3.0 (t=334.0)
- Reference parts: A. Sax, Euph, Harp low, Oboe
- Suggested explain points:
  - part 6, m84, beat 3.0 — current/nearby boundary in this part
  - part 5, m83, beat 1.0 — reference part A. Sax boundary
  - part 5, m85, beat 1.0 — reference part A. Sax boundary
  - part 7, m83, beat 2.875 — reference part Euph boundary
  - part 7, m84, beat 2.0 — reference part Euph boundary
  - part 7, m85, beat 1.0 — reference part Euph boundary
  - part 9, m84, beat 4.875 — reference part Harp low boundary
  - part 2, m83, beat 1.0 — reference part Oboe boundary

### LIZV2-027 — Euph m71

- Part: `7` / Euphonium
- Summary: should follow Cl.2 (too short)
- Expected action: `snap_or_merge`
- Tags: `consensus`, `too_short`, `too_little_material`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m70 b4.875 (t=279.875), m72 b4.875 (t=287.875)
- Reference parts: Cl.2
- Suggested explain points:
  - part 7, m70, beat 4.875 — current/nearby boundary in this part
  - part 7, m72, beat 4.875 — current/nearby boundary in this part
  - part 4, m70, beat 4.875 — reference part Cl.2 boundary
  - part 4, m72, beat 4.875 — reference part Cl.2 boundary

### LIZV2-028 — Euph m74

- Part: `7` / Euphonium
- Summary: should end at cresc., same with Cl.1 & Cl.2
- Expected action: `snap_or_add_consensus`
- Tags: `hairpin_endpoint`, `cresc`, `consensus`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m75 b1.0 (t=296.0)
- Reference parts: Cl.1, Cl.2
- Suggested explain points:
  - part 7, m75, beat 1.0 — current/nearby boundary in this part
  - part 3, m75, beat 1.0 — reference part Cl.1 boundary
  - part 3, m75, beat 3.875 — reference part Cl.1 boundary
  - part 4, m74, beat 3.0 — reference part Cl.2 boundary
  - part 4, m75, beat 2.25 — reference part Cl.2 boundary

### LIZV2-029 — Euph m81

- Part: `7` / Euphonium
- Summary: too short (only a quarter), should be merged into next
- Expected action: `remove_or_merge`
- Tags: `too_short`, `too_little_material`, `merge_next`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m82 b2.875 (t=325.875)
- Suggested explain points:
  - part 7, m82, beat 2.875 — current/nearby boundary in this part

### LIZV2-030 — Euph m89

- Part: `7` / Euphonium
- Summary: too few notes (only one whole note), should be merged with 90
- Expected action: `remove_or_merge`
- Tags: `too_little_material`, `single_sustained_note`, `merge_next`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m88 b4.875 (t=351.875), m90 b1.0 (t=356.0)
- Suggested explain points:
  - part 7, m88, beat 4.875 — current/nearby boundary in this part
  - part 7, m90, beat 1.0 — current/nearby boundary in this part

### LIZV2-031 — Harp high m3

- Part: `8` / Harp
- Summary: Harp low also sections here
- Expected action: `add_or_snap_consensus`
- Tags: `consensus`, `missing_boundary`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m2 b1.0 (t=4.0), m2 b4.875 (t=7.875), m4 b1.0 (t=12.0)
- Reference parts: Harp low
- Suggested explain points:
  - part 8, m2, beat 1.0 — current/nearby boundary in this part
  - part 8, m2, beat 4.875 — current/nearby boundary in this part
  - part 9, m2, beat 1.0 — reference part Harp low boundary
  - part 9, m2, beat 4.875 — reference part Harp low boundary
  - part 9, m3, beat 4.875 — reference part Harp low boundary

### LIZV2-032 — Harp high m54

- Part: `8` / Harp
- Summary: section too short and should start before tutti (same as A Sax)
- Expected action: `snap_or_merge`
- Tags: `too_short`, `tutti`, `consensus`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m53 b2.0 (t=209.0)
- Reference parts: A. Sax
- Suggested explain points:
  - part 8, m53, beat 2.0 — current/nearby boundary in this part
  - part 5, m54, beat 1.5 — reference part A. Sax boundary
  - part 5, m54, beat 4.5 — reference part A. Sax boundary

### LIZV2-033 — Harp high m80

- Part: `8` / Harp
- Summary: should end here at end of cresc., same with Cl.1, Cl.2
- Expected action: `snap_or_add_consensus`
- Tags: `hairpin_endpoint`, `cresc`, `consensus`
- Boundary presence: `no_boundary_nearby_pm1`
- Exact-measure boundaries: none
- Reference parts: Cl.1, Cl.2
- Suggested explain points:
  - part 8, m80, beat 1.0 — no nearby boundary; inspect requested location

### LIZV2-034 — Harp high m81

- Part: `8` / Harp
- Summary: should end at the cresc. before this note
- Expected action: `move_to_hairpin_endpoint`
- Tags: `hairpin_endpoint`, `cresc`, `wrong_target`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m82 b3.0 (t=326.0)
- Suggested explain points:
  - part 8, m82, beat 3.0 — current/nearby boundary in this part

### LIZV2-035 — Harp low m28

- Part: `9` / Harp
- Summary: interrupts slur
- Expected action: `remove_or_move`
- Tags: `slur`, `continuation_violation`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m28 b1.0 (t=108.0)
- Nearby ±1 measure: m28 b1.0 (t=108.0)
- Suggested explain points:
  - part 9, m28, beat 1.0 — current/nearby boundary in this part

### LIZV2-036 — Harp low m83

- Part: `9` / Harp
- Summary: too short (only a quarter)
- Expected action: `remove_or_merge`
- Tags: `too_short`, `too_little_material`
- Boundary presence: `nearby_boundary_only`
- Exact-measure boundaries: none
- Nearby ±1 measure: m84 b4.875 (t=335.875)
- Suggested explain points:
  - part 9, m84, beat 4.875 — current/nearby boundary in this part

### LIZV2-037 — Harp low m84

- Part: `9` / Harp
- Summary: should follow A Sax. & Euph (rit. & half note), same as Tpt, Oboe
- Expected action: `snap_or_add_consensus`
- Tags: `consensus`, `rit`, `long_note`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m84 b4.875 (t=335.875)
- Nearby ±1 measure: m84 b4.875 (t=335.875)
- Reference parts: A. Sax, Euph, Tpt, Oboe
- Suggested explain points:
  - part 9, m84, beat 4.875 — current/nearby boundary in this part
  - part 5, m83, beat 1.0 — reference part A. Sax boundary
  - part 5, m85, beat 1.0 — reference part A. Sax boundary
  - part 7, m83, beat 2.875 — reference part Euph boundary
  - part 7, m84, beat 2.0 — reference part Euph boundary
  - part 7, m85, beat 1.0 — reference part Euph boundary
  - part 6, m84, beat 3.0 — reference part Tpt boundary
  - part 2, m83, beat 1.0 — reference part Oboe boundary

### LIZV2-038 — Harp low m91

- Part: `9` / Harp
- Summary: breaks decresc.
- Expected action: `remove_or_move`
- Tags: `hairpin_interior`, `breaks_decresc`, `false_positive`
- Boundary presence: `boundary_in_exact_measure`
- Exact-measure boundaries: m91 b1.0 (t=360.0)
- Nearby ±1 measure: m91 b1.0 (t=360.0), m92 b2.875 (t=365.875)
- Suggested explain points:
  - part 9, m91, beat 1.0 — current/nearby boundary in this part
