# RESULTS — running log

## Established facts (pre-goal)
- 262-page scanned PDF; ~85% one EPDCL HT-bill template; monthly 01/2024→05/2026; ~2-3 non-bill pages.
- Embedded text layer is unusable for numbers → OCR images directly.
- RapidOCR (CPU) reads numbers verbatim: 14/14 key fields on hardest page (p8). ~13-16 s/page.
- Real problem = field BINDING, not reading.

## Accounting model (hand-verified, paise-exact on p8/16/32/48/128/160/256/262)
- `sub_total` = Σ upper charge amounts (demand normal/penal, energy, excess, elec duty, fuel, trueup, FPPCA[signed], TOD charges, −TOD incentive).
- `total` = sub_total + customer + all pre-total lower rows (grid support, wheeling, …; signed by label).
- `net_bill` = total + TCS/rebate/subsidy/pooled/NetIcd/export/loss(signed).
- `net_payable` = net_bill + prev-year + current-year arrears. **Bill rounds net_payable to whole rupee.**
- Sign rule: printed minus wins; else label `(-)`/incentive/subsidy/rebate ⇒ subtract.

## PHASE 0 — DONE (harness before optimization)
- **0b parse.py**: money-column detection (right-aligned, value-terminal, width-bounded) + shear-tolerant
  monotonic order-matching for the upper charge table + nearest-line label binding for lower panel/totals.
  Provenance per field: {value, raw_text, bbox, source_boxes, confidence(None on base cache), rule, observed, candidates}.
- **0a reconcile.py**: full signed accounting graph, observed-only, paise tol (0.02; net_payable 0.51 for rounding),
  expected/observed/delta/rows per check + loose rate×qty row diagnostic.
- **0c samples/gt/**: FROZEN vision pseudo-GT for 9 pages (Claude Opus vision, cross-checked vs accounting). IMMUTABLE.
- **0d eval.py + test_accounting.py**: `--split dev|test|full`, `--gt` field-exact by category, coverage; 13 unit tests
  green (5 stable bill pages locked; p48/p256 xfail = optimization frontier).

## Leaderboard (see leaderboard.jsonl for machine log)
| approach            | GT field-exact (dev) | money | cons | dates | ids | reconcile chain_ok dev / test |
|---------------------|----------------------|-------|------|-------|-----|-------------------------------|
| v1_shear_parser     | 80.0% (148/185)      | 85%   | 43%  | 95%   | 86% | 10/16 / 3/9                   |
| v2_rank_consumption | 93.5% (173/185)      | 93%   | 100% | 95%   | 86% | 14/16 / —                     |
| v5 (subset score)   | 98.9% (183/185)      | 99%   | 100% | 100%  | 95% | 14/16 / 5/9                   |
| **v6 (ALL fields)** | **98.0%** (201/205)  | 99%   | 94%  | 100%  | 96% | **14/16 / 5/9** (+other 100%) |

**v6 is the HONEST headline** (codex review #2): scores EVERY frozen GT field (adds cons_lf,
contracted_md, amount_words) and REQUIRES provenance (observed + source_boxes + not ambiguous)
— a value without provenance scores as a miss even if correct. See metrics/CODEX_REVIEW2.md.
v6 reconcile per-check — dev: sub_total 16/16, total 16/16, net_bill 15/15, net_payable 14/16.
The 4 dev misses (p8/p256 cons_lf faint; p160 arrears under watermark + category dropped 'i')
are all OCR RECOGNITION failures, not binding — 5/8 bill pages are 100% field-exact.
Alternate: sparse.py handles the p262 sparse template (9/9 fields) as a separate class.

## Iterations (hypothesis → change → delta → keep/revert)
1. **Rank-align upper table** (shear-proof) + wide y_lo margin + split margin + trailing-OCR-noise + width 0.40 +
   drop date/arrears label boxes. GT 80→84.9%, chain_ok 10→14, net_payable 62→88%. KEEP.
2. **MF-anchored Total-Consumption** (key off Multiplying-Factor equal-row, take row below; +LF%; column map).
   consumption 43→100%, GT →93.5%. KEEP.
3. **Geometric arrears** (between Net Bill & Net Payable rows) + bare-month box + label-anchored category.
   GT 93.5→97.8%. KEEP. +case-insensitive category & single-arrears sign → 98.9%. KEEP.
4. **net_bill OCR-typo fallback** (netb..amount) + **arrears glued into label box** (strip date). test net_payable 44→56%. KEEP.
5. **Gated fuzzy charge-label recovery** (difflib vs 10-row template, decoy-rejected; only when exact labels < amounts).
   Fixes OCR-misspelled labels ('Dcmand'/'Exccss', p56). dev untouched; test chain_ok 4→5, sub_total 56→67%. KEEP.
   - Reverted: ungated fuzzy (regressed dev 98.9→93.5, over-matched decoys). Gating fixed it.

## Alternates tried (did any beat the champion?)
- **sparse.py (p262 sparse template)** — SEPARATE class, not a champion replacement. 9/9 fields on p262.
  Adopted as an additive route in run_full (routes `is_sparse()` pages), improves coverage. KEEP.
- **Lever B preprocessing (preprocess.py: upscale/otsu/clahe/deskew)** — tested re-OCR on p136's misread
  fppca digit. Did NOT recover it (OCR consistently misreads that amount box). The value IS recoverable
  by summing the printed FPPCA component expression `(15488.25+33724.00+19856.74)=69068.99`, but that
  edges into the derived-value concern (codex #3) and p136 has no frozen GT — DEFERRED, not adopted.
  Verdict: pixel preprocessing alone does not beat the champion here.

## Remaining known failures (honest)
- **p136** fppca OCR-misread ('6689069' for ~69069) — recognition error, not binding; needs Lever B (preprocess/re-OCR).
- **p72** excess-energy amount xmax just left of money column (0.90·maxX); frac sweep didn't help aggregate → left as-is.
- **p56** residual stray '20' in money column (−20 on sub); **p104** arrears delta.
- **p160** arrears value physically overwritten by anti-bribery watermark → unreadable by any OCR.
- **p262** sparse alt template + **p144** statement page: out-of-HT-template (separate class; counted vs coverage).

## How others solve this (prior art) + why our choice
- **Cloud KV extractors** (AWS Textract AnalyzeExpense, Azure Doc Intelligence prebuilt-invoice,
  Google Doc AI) — highest accuracy, but violate the hard 100%-local/offline constraint. Excluded.
- **Layout LLMs / VLMs** (Donut, LayoutLMv3, Qwen2-VL, docTR+LLM) — strong on unseen layouts but
  heavy, non-deterministic, and (for VLMs) effectively cloud/GPU. Not a deterministic runtime for
  exact money fields. Our build-time vision GT is a bounded, frozen use of a VLM (grading only).
- **PP-Structure / Docling table recognition** — good generic tables, but this is ONE fixed template
  with heavy vertical shear; a template-aware deterministic binder is more accurate + cheaper here.
- **Chosen: RapidOCR (CPU ONNX) + deterministic template binder.** Recognition is near-perfect
  already (numbers verbatim); the hard part was BINDING under shear, solved by rank-alignment +
  MF-anchored consumption + geometric arrears. 100% local, deterministic, ~instant on cached OCR.
- Remaining ceiling is OCR RECOGNITION on faint/overwritten text (watermark, dropped chars) — the
  next lever is preprocessing (upscale/binarize/deskew) → re-OCR, or a local digit cross-checker
  (Tesseract) on disputed money rows; explicitly deferred as it needs re-OCR, not binding logic.

## Known scope notes
- p262 sparse alt template + p144 statement page are non-HT-template → separate class / out-of-scope for the HT parser
  (counted honestly against coverage). Possible alternate branch later.
