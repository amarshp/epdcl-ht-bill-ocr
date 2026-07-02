# Codex Review: Overnight OCR/Extraction Plan

Verdict: do not run the overnight loop as written. The direction is mostly right
(RapidOCR plus deterministic binding), but the current reward and evaluation are
not sound enough to drive autonomous optimization. The plan can converge to a
pipeline that "reconciles" while still binding important fields incorrectly, and
it can reject correct pages because the bill accounting model is incomplete.

The highest priority fix is to replace the four-check metric with a full
accounting graph that includes every monetary row, preserves source-box
provenance, and scores field-level exactness plus coverage. Use PAGE-OK as a
diagnostic, not as the primary optimization target.

## Evidence Reviewed

Files read fully:

- `GOAL.md`
- `reconcile.py`
- `extract.py`
- `eval.py`
- `common.py`

Additional inspection:

- cached OCR boxes for dev pages
- current extractor output and reconciliation behavior
- `render.py`, because the plan depends on visual pseudo-ground-truth

Concrete observations from cached OCR:

- Page 8 has the simple chain:
  `Sub Total 315595.06`, `Customer Charges 1406.00`,
  `Total 317001.06`, `Loss(or) Gain -0.06`,
  `NetBillAmount 317001.00`, `NetPayableRs317001.00`.
- Page 16 has legitimate net payable divergence:
  `Net Bill Amount 5185123.00`, current-year arrears `-4771.00`,
  `Net Payable Rs5180352.00`.
- Page 32 has a nonzero pre-total charge:
  `Sub Total 133670.35`, `Customer Charges 1406.00`,
  `Grid support charges 7500.00`, `Total142576.35`;
  later it has `PooledCostAdj (-)142576.00`, `NetBill Amount 0.00`,
  current-year arrears `-37450.00`, `NetPayableRs-37450.00`.
- Page 48 has a nonzero NetIcd adjustment:
  `Total 365762.50`, `NetIcdAmt(Icd-Tds)(80413.00-8041.00)(-)72372.00`,
  `Loss(or) Gain 0.50`, `Net Bill Amount 293391.00`,
  current-year arrears `-355.00`, `NetPayableRs293036.00`.
- Page 128 has `NetBillAmount 2114376.00`,
  current-year arrears `-702496.99`, and
  `NetPayableRs1411879.00`.
- Page 256 shows 2026-specific label drift, including
  `(Previous Years)Arrears before 31-Mar-2026`, `MATS Dev Charges`,
  and line labels split across rows.
- Page 262 is classified as `BILL?` but is a sparse, different bill-like
  layout, not the dominant HT bill template.

## 1. Reconciliation Metric Soundness

The current metric in `reconcile.py` is useful as a smoke test, but it is not a
sound self-supervised correctness proof.

### False Pass Risks

1. The addend checks are commutative, so they cannot prove binding identity.

`charges_sum` only proves that a set of numbers adds to `sub_total`; it cannot
prove that demand, energy, duty, FPPCA, and TOD were bound to their correct
labels. Demand and energy could be swapped and the check still passes. FPPCA
and TOD could be swapped and the check still passes. For structured extraction,
that is a serious false pass, not a harmless detail.

2. Repeated zeros make wrong bindings look valid.

The lower monetary panel contains many `0.00` rows: grid support, wheeling,
transmission, RKVAH surcharge, ACD surcharge, late payment, interest, penal
interest, transformer hire, difference voltage, load factor incentive, TCS,
subsidies, pooled cost, NetIcd, other credit, export amount, arrears. A spatial
rule that grabs the wrong `0.00` can satisfy formulas while being attached to
the wrong field. This is especially dangerous for optional adjustment fields.

3. Repeated equal values can hide wrong provenance.

On page 8, `NetBillAmount 317001.00` and `NetPayableRs317001.00` are equal.
A bad extractor could bind both fields from the same OCR box and pass
`net_round`. The metric has no source-box provenance or uniqueness check, so it
cannot distinguish "two labels with the same value" from "one value copied into
two fields."

4. Same numeric value can appear in multiple semantic contexts.

On page 128, `27600` appears both as the TOD billing amount and in the TOD
details/table area. A zone-insensitive extractor can bind the right number from
the wrong location. The arithmetic check passes, but the extraction is not
really bound to the bill row.

5. `words_match` is not independent enough.

`words_match` uses the same OCR output as the numeric fields. If the extractor
derives or patches `net_payable` from the amount-in-words parse, numeric and
words checks can agree without proving the printed numeric `Net Payable` was
read correctly. The plan must forbid derived values from being used as extracted
observations in reconciliation.

6. The tolerance is too loose for money fields.

`_close(..., tol=1.0)` allows differences up to Rs 1.00 for subtotal and total
checks. That can hide a wrong paise value or a one-rupee OCR/binding error. Use
cent-level tolerance for printed currency rows, and use explicit rounding only
where the bill itself rounds, such as total to net bill or net bill to net
payable after adjustments.

7. Missing checks do not penalize enough.

`page_ok = passed >= 3 and words_match is not False` means amount-in-words can
be missing and still not block a page. For final extraction, a missing field
should be a coverage failure even if page arithmetic passes.

8. The metric can be gamed by imputation.

An optimizer can learn to set `total = sub_total + customer_charges`, set
`net_payable = round(net_bill)`, or set `net_payable` from words. That would
increase PAGE-OK while no longer extracting observed values. Reconciliation
must operate only on observed OCR-derived fields with source boxes, not on
backfilled or formula-derived values.

### False Fail Risks

1. `charges_sum` omits real charge rows.

The bill has more charge rows than the current model:

- Demand Charges Normal Rate
- Demand Charges Penal Rate
- Energy Charges Rate
- Excess Energy Charges Rate
- Electricity Duty Charges
- Fuel Surcharge Adjustment rows
- FPPCA Charge, sometimes with multiple positive and negative components
- TOD Charges
- TOD Incentive (-)

The current formula only includes demand, energy, duty, FPPCA, and TOD. It will
reject correct pages if demand penalty, excess energy, fuel surcharge, or TOD
incentive is nonzero and not folded into one of those fields.

2. `total_calc` omits many pre-total rows.

`total_calc` assumes:

`sub_total + customer_charges == total`

That is false for correct bills when any of these rows are nonzero:

- Grid support charges
- Wheeling Charges
- Transmission Charges
- RKVAH Surcharge HYDEL
- RKVAH Surcharge WIND
- OPEN ACCESS CROSS SUBSIDY
- ACD SURCHARGE
- Late Payment Charges
- Interest On ED
- Penal Interest
- Transformer Hire Charges
- Difference Voltage Charges
- Load Factor Incentive (-)
- MATS Dev Charges or other drifted rows

Page 32 is a concrete false-fail example:

`133670.35 + 1406.00 + 7500.00 = 142576.35`

The current check would reject the correct extraction because it omits the
`Grid support charges 7500.00` row.

3. `net_round` is structurally wrong for many pages.

`round(net_bill) == net_payable` is only valid when arrears and post-net
adjustments are zero. Several dev pages show legitimate differences:

- Page 16: `5185123.00 + (-4771.00) = 5180352.00`.
- Page 32: `0.00 + (-37450.00) = -37450.00`.
- Page 48: `293391.00 + (-355.00) = 293036.00`.
- Page 128: `2114376.00 + (-702496.99) = 1411879.01`, rounded to
  `1411879.00` depending on bill rounding convention.
- Page 160: cached OCR shows `Net Bill Amount 5367455.00` and
  `Net PayableRs3250546.00`; this must involve an adjustment/arrears value that
  the current model does not capture.

The correct chain should be closer to:

`total + post_total_adjustments + loss_or_gain -> net_bill`

then:

`net_bill + previous_year_arrears + current_year_arrears -> net_payable`

with signs controlled by labels and printed signs, not hard-coded assumptions.

4. Amount-in-words parsing is too weak.

`words_to_amount` scans the whole OCR blob for `Rs...only`, does not anchor to
the amount-in-words line, and assumes clean space-separated English words. It
will false-fail on:

- glued OCR tokens such as `FiftyLakhsSixtyThousand`
- missing spaces around `Rs.`
- OCR variants like `Lacs`
- `and`, `only`, punctuation, or parentheses artifacts
- earlier `Rs.0`, `Rs.1.00`, or `Rs.50Lakhs` text elsewhere on the page
- negative net payable wording

The current outputs already show bad parses such as page 8 returning `3` for
amount-in-words and page 32 returning `0`.

## 2. PAGE-OK As RL Reward

Optimizing PAGE-OK rate is not the right primary objective. It is an attractive
inner-loop signal, but as a reward it creates blind spots and reward-hacking
paths.

Main issues:

- It does not check non-numeric fields at all: service number, billing month,
  consumer name/location, category, CMD/RMD, due date, bill date, meter number,
  or tariff.
- It does not validate the consumption table: KWH, KVAH, KVA/RMD, PF, LF%,
  previous/current readings, or TOD peak/off-peak details.
- It does not prove row-level amount correctness. A better check is
  `rate * quantity == row amount` for each billing row where rate/quantity are
  printed.
- It can be gamed by page classification. `eval.py` skips pages whose
  `classify()` result is not `HT_BILL` or `BILL?`. A changed classifier or OCR
  preprocessing can improve PAGE-OK by excluding hard pages unless coverage is
  part of the denominator.
- It can be gamed by imputation: computing missing fields from formulas rather
  than extracting printed values.
- It overfits to the 16 cached dev pages. The plan mentions held-out pages, but
  the code has no `TEST_BILLS`, no test evaluator, and no enforced
  dev/test/full split.
- It treats a page-level pass as success even if individual important fields
  are wrong but cancel out.

Recommended objective:

- Primary: field-level exact match on a fixed pseudo-GT set, with separate
  scores for money fields, consumption fields, dates, IDs, and text.
- Secondary: accounting reconciliation rate, with full accounting graph.
- Required: coverage denominator over all expected bill pages and all PDF pages.
- Required: no synthesized values counted as extracted observations.
- Required: candidate/provenance audit for every accepted value.

PAGE-OK can remain useful for fast iteration, but it should be a guardrail and
diagnostic, not the optimization reward.

## 3. Architecture Assessment

The high-level architecture is reasonable:

- RapidOCR is a good first engine given the established 14/14 hard-page numeric
  result and CPU-only constraint.
- Deterministic binding is the right bias for bills. A generative model is not
  appropriate as the production extractor for exact money fields.
- The problem is correctly identified as binding rather than OCR recognition.

But the current implementation architecture is too weak:

- `extract.py` uses substring label matching (`lab in joined`), which causes
  collisions like `Total` vs `Total Consumption`.
- Row grouping uses a fixed y-band of 22 pixels. The cached pages have
  different scales, offsets, and skew; fixed bands will keep failing.
- Field extraction returns only values, not source box IDs, coordinates,
  confidence, candidate alternatives, or rule provenance.
- `common.ocr()` discards RapidOCR confidence scores.
- `common.page_image()` uses only the first embedded image on a page. That is
  fragile for multi-image pages, overlays, rotations, or pages where the useful
  content is not the first image.
- The code uses `max(xmax)` of OCR boxes as page width. That is not the image
  width and changes when OCR misses far-right text.

What I would change:

1. Keep RapidOCR as champion OCR.

Do not spend the first overnight cycle installing heavy engines. First fix the
binding and accounting model around the OCR boxes already known to contain the
right numbers.

2. Build a template-aware table parser, not isolated field lookups.

For each page:

- normalize coordinates by actual image width/height
- register the page to anchors such as the header, bill-month line, and right
  money column
- join split OCR boxes into line tokens
- detect the right money column
- parse the billing rows into `(label, rate, quantity, unit, amount)` records
- parse the lower adjustment rows into `(label, signed_amount)` records
- extract top-level fields from these records

3. Preserve provenance.

Every extracted field should include:

- normalized bbox
- raw OCR text
- source box IDs
- OCR confidence
- extractor rule name
- observed vs derived flag
- candidate list when ambiguous

Reconciliation should only pass on observed values. Derived values may be
reported as helper calculations but must not count as extraction success.

4. Use local second engines selectively.

Tesseract or PaddleOCR can be useful as a cross-checker for disputed fields,
but a full PP-Structure/Docling path is likely slower and more fragile on this
fixed template. Try structure models only after the deterministic table parser
has a strong baseline.

5. Use row-level arithmetic.

For each charge line, validate:

- printed rate
- printed quantity
- printed unit
- printed amount
- `rate * quantity ~= amount` where the bill layout supports it

This catches swapped addends, wrong-row values, and same-sum false passes.

## 4. Missing Failure Modes And Steps

Critical missing items:

1. Complete accounting model.

The plan must explicitly model every monetary row in the upper charge table and
lower adjustment panel, including signs and optional rows. Without this,
correct pages with adjustments will be rejected.

2. Coverage accounting.

The full PDF has bill pages, statement pages, sparse pages, and likely other
outliers. The plan says "coverage" is a deliverable, but the inner loop ignores
it. Unknown/skipped pages must count in the denominator.

3. Multi-page and page-group logic.

If a bill spans multiple pages or has attachments, the current code has no
document grouping. Page-level extraction alone may lose context.

4. Rotated, skewed, cropped, or multi-image pages.

`page_image()` assumes one embedded image per page and ignores page rotation and
multiple images. Add orientation/skew detection and a fallback renderer.

5. Template drift over financial years.

The cached OCR shows drift in labels and rows:

- `before31-Mar-2023`, `before31-Mar-2024`, `before31-Mar-2025`,
  `before 31-Mar-2026`
- `TCS`, `TCSS/F`, and `MATS Dev Charges`
- split `OPEN ACCESS CROSS` / `SUBSIDY`
- split `NetIcdAmt` lines
- changing customer charges (`1406.00`, `2813.00`)
- sparse alternate layout on page 262

This needs explicit versioning or tolerant row-label normalization.

6. Multiple meters and consumption details.

The current metric ignores meter readings, TOD peak/off-peak rows, PF/LF,
and total consumption columns. If the final output claims structured fields,
these must be covered.

7. Negative and parenthesized numbers.

FPPCA and adjustment rows contain negative components and Unicode parentheses,
for example page 160:

`FPPCACharge(-308523.75+236840.00+85743.37+(-77552.32))`

The parser must distinguish component expressions from row amounts and preserve
signs.

8. Sparse/non-template bill page.

Page 262 is `BILL?` and contains a compact bill summary:

`May-2026ElectricityBill ServiceNo.VSP-1154 ... NetPayable 5060413 ...`

It will not be handled well by a fixed HT-template extractor. The plan needs a
separate template class or a conscious out-of-scope decision.

9. Full-text OCR deliverable.

The mission says "accurate text + structured fields", but the loop only
optimizes selected numeric fields. Text quality, reading order, line grouping,
and non-bill pages need their own metrics.

## 5. Dev/Test Discipline, Stop Criteria, Guardrails

The current discipline is not strong enough for an autonomous overnight run.

Problems:

- No `TEST_BILLS` exists in code. The plan mentions a held-out set, but
  `eval.py` only evaluates `DEV_BILLS`.
- `eval.py` appends to `metrics/leaderboard.jsonl` on every run, including
  exploratory and broken runs, without commit hash, config, cache variant,
  code diff, or test metrics.
- The leaderboard records only page-level metrics, not field-level exactness,
  missing field counts, coverage, or false-positive risk.
- `git add -A` after every accepted improvement may commit caches, rendered
  samples, pseudo-GT drafts, logs, or unrelated user changes.
- The plan recommends `git reset --hard` as rollback. That can destroy
  unrelated work and generated labels unless very carefully scoped.
- `best/` is not defined. It should include code, config, requirements, command,
  cache variant policy, pseudo-GT version, and commit hash.
- "Plateaued" and "codex says optimal" are not objective stop criteria.
- The research mandate can waste overnight time or fail under restricted
  network conditions. It should not block known local fixes.
- The plan's use of Claude/Codex vision should be explicitly classified as
  build-time external review, not "fully local." If privacy/locality is strict,
  this is a policy exception.

Minimum guardrails before the run:

- Add an evaluator that reports dev, test, and full-page coverage separately.
- Add per-field metrics and source provenance.
- Add unit tests for reconciliation using pages 8, 16, 32, 48, 128, 160, and
  256 examples.
- Add a no-imputation rule: fields used for scoring must have source OCR boxes.
- Add a classifier coverage report: HT bill, sparse bill, statement, other,
  failed OCR.
- Add a champion manifest instead of just copying files.
- Define numeric thresholds for stopping.

## 6. Prioritized Improvements

### P0: Fix the metric before optimizing against it

Implement a full accounting graph:

1. Upper charge subtotal:
   include normal demand, demand penalty, energy, excess energy, duty, fuel
   surcharge adjustments, FPPCA, TOD charges, and TOD incentive with correct
   signs.

2. Total:
   start from `sub_total`, then include customer charges and every pre-total
   lower-panel row up to `Total`, with signs from labels.

3. Net bill:
   start from `Total`, then include TCS/TCSS/F, rebates, subsidies, pooled cost
   adjustment, NetIcd, other credit, export amount, and loss/gain.

4. Net payable:
   start from `Net Bill Amount`, then include previous-year and current-year
   arrears.

Each check should report:

- expected value
- observed value
- delta
- included rows
- missing rows
- source boxes

### P0: Add observed-value provenance

Change extraction outputs from:

`field -> value`

to:

`field -> {value, raw_text, bbox, source_boxes, confidence, candidates, rule, observed}`

Reject PAGE-OK if a scored field is derived or lacks source boxes.

### P0: Add real holdout evaluation

Add `TEST_BILLS` to `common.py` or a config file and create:

- `eval.py --split dev`
- `eval.py --split test`
- `eval.py --split full`
- `eval.py --all-splits`

Denominators must include expected bill pages and skipped/unknown pages.

### P1: Build a deterministic table parser

Replace isolated label lookup with:

- line reconstruction
- label normalization
- money-column detection
- row association
- optional row catalog
- version-tolerant label aliases
- row-level `rate * quantity == amount` checks

This is the most likely path to high accuracy under the local/cheap constraint.

### P1: Build pseudo-GT before the all-night loop

Do not wait until the end. Create a small fixed pseudo-GT set first:

- page 8: simple clean page
- page 16: current-year arrears
- page 32: grid support, pooled cost, negative payable
- page 48: NetIcd and arrears
- page 128: large arrears
- page 160: negative FPPCA and large net/payable divergence
- page 256: 2026 label drift
- page 262: sparse alternate bill template
- page 1 or 144: statement/non-bill page

For each, label money fields, key dates/IDs, and core consumption fields.

### P1: Score non-numeric fields

At minimum:

- service number
- billing month
- due date
- consumer/category/location
- CMD/RMD or contracted demand
- KWH/KVAH/KVA totals
- PF/LF%

Without these, the final "structured fields" claim is not supported.

### P1: Add ambiguity handling

When multiple candidate numbers satisfy geometry or arithmetic, do not silently
choose one. Report ambiguity and fail the field unless a deterministic
tie-breaker is justified.

### P2: OCR/preprocessing and engine bake-off

After binding/accounting improves:

- retain OCR confidences
- try deskew/orientation detection
- test Tesseract as a digit cross-checker on cropped money rows
- test PaddleOCR/PP-Structure only as an alternate branch with strict
  throughput and accuracy comparison
- do not let engine installs consume the night before the deterministic
  baseline is strong

### P2: Operationalize champion snapshots

Create `best/MANIFEST.json` with:

- git commit
- approach name
- command
- dependency versions
- cache variant
- dev/test/full metrics
- pseudo-GT version
- known failures

Copying code without a manifest is not enough.

## Concrete Go/No-Go Recommendation

No-go for the plan as written.

Go only after these minimum changes:

1. Full accounting graph replaces the four simplistic checks.
2. Field provenance is required for every scored value.
3. Held-out test split is enforced by code.
4. Coverage is part of the denominator.
5. Pseudo-GT exists for the adjustment-heavy pages.
6. No derived/imputed values can count as extracted observations.

Once those are in place, the core strategy should work: keep RapidOCR, build a
deterministic template/table extractor, use reconciliation as a strong
secondary consistency check, and use alternate OCR/table engines only to
cross-check or challenge the champion.
