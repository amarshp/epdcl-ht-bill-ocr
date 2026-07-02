# Codex Review #2 (post-optimization champion v5) + resolution

Independent adversarial review by codex (gpt-5 class, read-only) of the champion
after the optimization loop. Codex is a BUILD-TIME reviewer only — never a runtime
dependency. Raw verdict + how each finding was resolved.

## Codex verdict
"The metric is useful, but not sound as a correctness proof. It can still
false-pass and false-fail."

## Findings and resolution
1. **GT score omitted frozen fields** (cons_lf, contracted_md, amount_words, trueup) —
   "183/185 means selected fields, not all GT fields."
   → **FIXED.** `eval.score_gt` now scores EVERY key present in each frozen GT file.
   Added extraction of contracted_md, amount-in-words (glued-OCR segmentation), cons_lf.
   Honest all-fields dev score: **201/205 = 98.0%** (was reporting a subset).

2. **No-imputation / provenance not enforced by scoring.**
   → **FIXED.** `eval._provenance_ok` requires `observed is True` + non-empty
   `source_boxes` + not `ambiguous`; a value lacking provenance scores as a MISS
   even if numerically correct. reconcile already trusts only `observed` targets.

3. **Reconcile sums by section → can't prove field identity.**
   → Acknowledged, documented as the known secondary-metric limitation. `row_arithmetic`
   remains a loose diagnostic. Primary correctness signal is field-exact vs frozen GT.

4. **Rank-zip brittle under count-matched errors (one missed + one spurious shifts silently).**
   → Real residual risk. Mitigated by: reconcile cross-check (a silent shift breaks
   sub_total unless amounts coincidentally re-sum), gated fuzzy recovery, and the
   frozen-GT field-exact score. Not fully eliminable geometrically.

5. **MF consumption anchor not bounded to the consumption table.**
   → **FIXED.** Equal-value row search now restricted to y above the Demand-Normal
   label, so a charge row can't masquerade as the Multiplying-Factor row.

6. **Arrears identity swap risk + dead `used` var.**
   → Dead var removed. prev/curr-by-position remains a documented heuristic; sums stay
   valid; field-identity risk noted (arrears prev is ~always 0, current the real value).

7. **Decimal-comma bug (strips ',' as thousands).**
   → Correct for this dataset (Indian format: ',' = thousands, '.' = decimal, e.g.
   '1,406.00'). Left as-is; noted as an edge for non-Indian inputs.

## Net effect
Headline metric is now the honest, provenance-enforced, all-frozen-fields score
(98.0% dev). The two soundness-critical findings (1, 2) and two correctness
hardenings (5, 6) are fixed; the rest are documented residual risks.
