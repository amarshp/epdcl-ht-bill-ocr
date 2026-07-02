# RESULTS — running log

## Established facts (pre-goal)
- 262-page scanned PDF; ~85% one EPDCL HT-bill template; monthly 01/2024→05/2026; ~2-3 non-bill pages.
- Embedded text layer is unusable for numbers → OCR images directly.
- RapidOCR (CPU) reads numbers verbatim: 14/14 key fields on hardest page (p8). ~13-16 s/page.
- Real problem = field BINDING, not reading. Metric = internal arithmetic reconciliation (self-supervised).

## Leaderboard (see leaderboard.jsonl for machine log)
| approach   | PAGE-OK (dev) | charges_sum | total_calc | net_round | words | notes |
|------------|---------------|-------------|------------|-----------|-------|-------|
| baseline_v0| 0/16          | 6/9         | 0/15       | n/a       | n/a   | net_payable=None, "Total" collides w/ "Total Consumption" |

## Iterations
- _(agent appends: hypothesis → change → metric delta → keep/revert → source)_

## Known baseline bugs to fix first
1. `net_payable` = None → multi-word label + glued `Rs317001.00` value.
2. `total_calc` 0/15 → "Total" substring-collides with "Total Consumption"; need anchored label.
3. energy/fppca money column in own y-band → target money x-band, nearest-in-y.
