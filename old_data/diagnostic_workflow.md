# Diagnostic workflow for Liz v2 audit cases

This is the intended workflow before v2.10 feature work.

## 1. Run sectioning

```bash
python sectioning_v2_9.py Liz_and_the_Blue_Bird_III-1.2_colored.mxl -o output_v2_9/liz
```

## 2. Run serialized explain diagnostics

Run only the user's target part for each case:

```bash
python run_explain_series.py \
  --audit audit_cases_v2.json \
  --output-dir output_v2_9/liz \
  --explain-script explain_v2_9.py \
  --out diagnostics/liz_v2_default
```

Run with reference parts too, useful for consensus cases:

```bash
python run_explain_series.py \
  --audit audit_cases_v2.json \
  --output-dir output_v2_9/liz \
  --explain-script explain_v2_9.py \
  --out diagnostics/liz_v2_default_with_refs \
  --include-reference
```

Run only a tag subset:

```bash
python run_explain_series.py \
  --audit audit_cases_v2.json \
  --output-dir output_v2_9/liz \
  --explain-script explain_v2_9.py \
  --out diagnostics/liz_v2_consensus \
  --tag consensus \
  --include-reference
```

Dry-run to create command list without executing:

```bash
python run_explain_series.py \
  --audit audit_cases_v2.json \
  --output-dir output_v2_9/liz \
  --explain-script explain_v2_9.py \
  --out diagnostics/liz_v2_default \
  --dry-run
```

## 3. What to send back

Send back:

- `audit_cases_v2.json`
- `diagnostics/liz_v2_default/manifest.json`
- the `diagnostics/liz_v2_default/*.txt` explain outputs
- optionally the `--include-reference` diagnostics for consensus cases

## 4. What we inspect

For each case, we want to know:

- Was there a boundary at the exact measure or nearby?
- Which signal created it: chroma SSM, rhythm SSM, LBDM, cross-rhythm, structural bump?
- Was the target inside a tie/slur/hairpin/tuplet/rhythmic run?
- Was it a tiny phrase fragment by sounding material?
- Did nearby reference parts choose a better aligned boundary?

## 5. Hypotheses to test from diagnostics

1. Ensemble consensus is the dominant remaining issue.
2. Phrase-material scoring is better than raw elapsed-time short-phrase filtering.
3. Hairpin endpoints need explicit phrase-end candidates/rewards.
4. Natural tie violations should remain hard invalid.
5. Rhythmic-run spans are useful but targeted, not the main cause.
