# Final verdicts (two independent sign-offs)

Per the loop-engineering rule WRITER≠GRADER: the OBJECTIVE score is field-exact
match vs the *frozen* vision GT (98.0% dev, all fields, provenance-enforced) plus
full-accounting reconciliation. These verdicts are *judgment*, not scoring.

## Verdict 1 — Critical self-review (Claude Opus 4.8)
**Is the champion near the local optimum? Largely yes, for BINDING; the ceiling is now RECOGNITION.**

Strengths (evidence-backed):
- Field-exact vs frozen GT = **201/205 (98.0%)** over ALL frozen fields with provenance enforced
  (observed + source boxes + not-ambiguous). 5 of 8 GT bill pages are 100%.
- Full accounting graph reconciles **14/16 dev** to the paise; sub_total/total/net_bill = 100% dev.
  The 2 dev reconcile misses are OCR-garbled inputs, not model error.
- Binding is shear-proof (rank alignment), drift-tolerant (2024→2026 labels, MATS/Captive rows),
  and handles every adjustment codex flagged (arrears, grid, pooled, NetIcd, neg-FPPCA, TOD).
- No-imputation is real: every scored value traces to an OCR box; derived values are excluded.

The 4 remaining GT misses are ALL OCR RECOGNITION failures, unfixable by binding:
- p8 / p256 `cons_lf` — the LF% digit is faint/absent in the scan.
- p160 `arrears_curr` — the value is physically overprinted by the anti-bribery watermark.
- p160 `category` — OCR dropped the 'i' from 'IIA(i)' → 'IIA()'.

**Strongest remaining weakness:** RECOGNITION on degraded regions (watermark overlap, faint small
font, single dropped characters). This is an OCR-engine limit, not a binding limit. Secondary:
held-out TEST reconcile is 5/9 — the failures are the same class (misspelled labels p56, misread
digit p136) plus one just-left-of-column amount (p72). Rank-zip retains a residual silent-shift
risk under simultaneous one-missed + one-spurious amount (codex #4), bounded but not eliminated.

**Can it be beaten locally?** Not on BINDING by much. The next real gains need a RECOGNITION lever —
image preprocessing (tested: pixel upscale/otsu did not recover p136), a local second engine
(Tesseract/Paddle) as a digit cross-checker on disputed money rows, or component-expression recovery
for FPPCA — all deferred as they are re-OCR / cross-engine work, not binding logic, and one risks the
no-imputation rule. I judge the deterministic template binder at/near its local ceiling.

## Verdict 2 — Codex (independent, gpt-5 class) — see CODEX_REVIEW2.md
Found the evaluator initially scored a field SUBSET and did not enforce provenance in scoring
(both **fixed** → honest 98.0% all-fields), plus MF-anchor and dead-code hardenings (**fixed**).
Residual documented risks: reconcile sums can't prove field identity (secondary metric), rank-zip
silent-shift edge, decimal-comma edge (correct for Indian format). No correctness regression found
in the champion after fixes.

## Consensus
Both reviewers agree the champion is sound and near the local BINDING optimum; the binding metric
is now honest and provenance-enforced; the remaining ceiling is OCR RECOGNITION on degraded text,
which is out of scope for a deterministic binder and was explicitly deferred.
