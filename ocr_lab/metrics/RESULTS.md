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
| approach            | GT field-exact (dev) | money | cons | dates | ids | reconcile chain_ok |
|---------------------|----------------------|-------|------|-------|-----|--------------------|
| v1_shear_parser     | **80.0%** (148/185)  | 85%   | 43%  | 95%   | 86% | 10/16              |

Reconcile per-check (dev): sub_total 12/12 (100%), total 12/16 (75%), net_bill 11/15 (73%), net_payable 10/16 (62%).

## Top failures to attack (optimization loop)
1. **consumption 43%** — `Total Consumption` row extraction grabs the multiplying-factor `1000` row (p16) / misses LF%.
2. **p48, p256 shear off-by-one** — upper-table δ-match drops first amount / mislabels by one; p256 sub_total value box
   leaks into upper region + 2026 drift rows (Captive Feed Mix, MATS Dev) unmodelled.
3. **total/net_bill/net_payable reconcile <80%** — driven by (2) and by arrears OCR gaps (p160 arrears garbled).

## Iterations
- _(agent appends: hypothesis → change → metric delta → keep/revert → source)_

## Known scope notes
- p262 sparse alt template + p144 statement page are non-HT-template → separate class / out-of-scope for the HT parser
  (counted honestly against coverage). Possible alternate branch later.
