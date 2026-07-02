# GOAL: Best-possible LOCAL OCR + field extraction for the EPDCL HT-bill PDF
*(Finalized after adversarial codex review — see `metrics/CODEX_REVIEW.md`. Read that file too.)*

## Mission
Iterate autonomously, all night, until you have the **cheapest, highest-accuracy, fully-local** pipeline that turns `Issue-4.pdf` (262 scanned monthly electricity bills) into **accurate text + provenance-tracked structured fields**, measured by **field-level exact match vs vision pseudo-ground-truth** (primary) and **full-accounting reconciliation** (secondary), with **two independent sign-offs** (your own self-review + codex) that it can't be beaten locally — then try alternates to beat it.

**SCOPE THIS RUN: OCR / extraction ONLY.** No dashboard, no RAG yet.

---

## HARD CONSTRAINTS
- **Production pipeline = 100% local, offline, deterministic.** No cloud OCR/LLM APIs, no paid services, ever, at runtime. RapidOCR/Paddle/Tesseract only.
- Runs on: Intel Core Ultra 9 285H, 32 GB RAM, **Intel Arc 140T iGPU, no CUDA**, Windows 11. CPU or iGPU (DirectML/OpenVINO) only.
- **Build-time exception (explicit):** your own Claude vision + codex may be used for GRADING, ground-truth, and review only. They are NOT local and must NEVER be a runtime dependency of the monthly extractor. Label this clearly wherever used.
- **Never lose the champion.** Snapshot to `best/` + git commit before risky changes.
- **No guessing.** Every scored value must come from a real OCR box (provenance). Verify faint digits against the page image with your own eyes.

## ENVIRONMENT (set up — don't rediscover)
- Dir: `C:\Users\Amarsh\OneDrive\Documents\Personal\OCR`, project `ocr_lab/`. Git initialized.
- Python 3.12 (Win Store). `pip`/`winget` usable unattended.
- Installed: `rapidocr-onnxruntime` (CPU ONNX PP-OCR), `pypdf`, `PIL`, `opencv-python`, `numpy`, `pandas`, `onnxruntime` (CPU only).
- Codex CLI v0.135.0 on PATH (`codex exec "..." -s workspace-write`).
- Cache: `cache/p{n}.json` = OCR boxes `[ycenter,xmin,xmax,text]` for 19 sampled pages. Inner loop reads cache = instant.

## ESTABLISHED FACTS (proven — build on these)
1. Embedded PDF text layer is garbage for numbers → OCR the images directly.
2. RapidOCR (CPU) reads numbers verbatim: 14/14 key fields on hardest page (p8). ~13–16 s/page.
3. Real problem = **binding** numbers to fields, not recognition.
4. Composition: ~85% one EPDCL HT-bill template, monthly 01/2024→05/2026; ~2–3 non-bill pages; p262 = a DIFFERENT sparse bill layout.
5. **Bills carry real adjustments** — arrears, grid support, pooled-cost, NetIcd, TCS, negative FPPCA components, TOD incentive. The accounting model MUST handle all of them (evidence in CODEX_REVIEW.md §1).

---

## OBJECTIVE (revised — this is the reward)
Optimize in this priority order:
1. **PRIMARY: field-level exact-match accuracy vs a fixed vision pseudo-GT set** — reported separately for {money fields, consumption fields, dates, IDs, text}. This is the real target.
2. **SECONDARY: accounting-reconciliation rate** using the FULL accounting graph (below) — a strong consistency check, NOT the primary reward.
3. **COVERAGE (required, in every denominator):** % of all expected bill pages AND all 262 PDF pages successfully parsed. Skipped/unknown/failed pages count against you — you cannot inflate scores by excluding hard pages.
4. **NO-IMPUTATION RULE (required):** a field only counts as extracted if it has a source OCR box. Derived/backfilled values (e.g. `total := subtotal+customer`) may be reported as helper calcs but MUST NOT count as extraction success or satisfy reconciliation.
5. **PROVENANCE (required):** every accepted field carries `{value, raw_text, bbox, source_boxes, confidence, rule, observed:true/false, candidates[]}`.

PAGE-OK reconcile rate stays as a fast **diagnostic/guardrail**, never the optimization target.

---

## PHASE 0 — FOUNDATIONS (mandatory BEFORE any optimization loop)
Codex review = **no-go until these exist.** Do them first, commit each.

**0a. Full accounting graph** (replace the 4 naive checks in `reconcile.py`):
- `sub_total` = Σ upper charge rows *with signs*: demand-normal, demand-penal, energy, excess-energy, duty, fuel-surcharge, FPPCA (may be multi-component incl. negatives), TOD charges, TOD incentive(−).
- `total` = `sub_total` + customer charges + every nonzero pre-total lower-panel row (grid support, wheeling, transmission, RKVAH HYDEL/WIND, open-access cross-subsidy, ACD, late payment, interest-on-ED, penal interest, transformer hire, difference-voltage, load-factor-incentive(−), MATS dev, …) with label-driven signs.
- `net_bill` = `total` + TCS/TCSS-F + rebates + subsidies + pooled-cost-adj + NetIcd + other-credit + export + loss/gain.
- `net_payable` = `net_bill` + previous-year arrears + current-year arrears (signed).
- Each check reports: expected, observed, delta, rows-included, rows-missing, source-boxes. Tolerance = paise-level (0.01) for printed rows; explicit rounding only where the bill rounds.
- Add **row-level** checks: for each billing row, `rate × quantity ≈ amount` (printed). This is what actually catches swapped/duplicate/same-sum false passes.

**0b. Provenance-carrying extractor output** — change `extract()` from `field→value` to `field→{value, raw_text, bbox, source_boxes, confidence, rule, observed, candidates}`. Reconciliation passes ONLY on `observed` values with source boxes. Ambiguous (multiple candidates satisfy geometry/arithmetic) → FAIL the field, don't silently pick.

**0c. Vision pseudo-GT set** (use YOUR OWN eyes — free, no external API): `python render.py <p>` → Read the PNG → hand-transcribe fields → save `samples/gt/p<n>.json`. Build GT for the hard/representative pages codex identified: **8 (clean), 16 (arrears), 32 (grid+pooled, negative payable), 48 (NetIcd), 128 (large arrears), 160 (negative FPPCA), 256 (2026 drift), 262 (sparse alt template), 1 or 144 (non-bill)**. Label money + dates/IDs + core consumption fields. Codex already transcribed many key values in CODEX_REVIEW.md §Evidence — use as a starting reference but confirm with your own read.

**0d. Enforced dev/test/coverage evaluator** — add `TEST_BILLS` (held-out, NOT in dev), and `eval.py --split {dev,test,full,all}`. Denominator includes expected bill pages + skipped/unknown pages. Log field-level metrics, missing-field counts, coverage, and false-pass risk — not just page-level. Add unit tests for the accounting graph using pages 8/16/32/48/128/160/256.

Only after 0a–0d are green do you enter the optimization loop.

---

## PHASE 1 — OPTIMIZATION LOOP
```
while not (plateaued on dev AND test AND both self-review + codex say optimal):
    1. Pick the lowest field-level-accuracy field / highest-value failure.
    2. If known-type problem, SEARCH ONLINE first (invoice KV extraction, PP-Structure
       table recognition, RapidOCR params, deskew) — trace the SPECIFIC symptom, don't guess.
    3. Implement ONE surgical change (lever below).
    4. Run eval on dev; if win + no regression, validate on TEST; spot-check 2-3 pages with
       your own vision. Keep -> snapshot best/ + scoped git commit. Else revert.
    5. Log everything.
```
Inner loop = cached dev pages (no OCR). Changing OCR/preprocessing → re-OCR into a new `variant=` cache to compare. Run full 262 only for final metrics.

**Levers (in order of expected leverage):**
- **A. Deterministic TABLE PARSER (not isolated lookups):** normalize coords by real image W/H (not `max(xmax)`); register to anchors (header, bill-month line, money column); join split boxes into line tokens; detect money column; parse billing rows into `(label,rate,qty,unit,amount)` and lower rows into `(label,signed_amount)`; derive fields from records. Exact/anchored label match (kill `Total` vs `Total Consumption`); version-tolerant label aliases for drift.
- **B. Preprocessing:** deskew, orientation detect, binarize, upscale small-font rows, 300–400 DPI render vs embedded JPEG — compare.
- **C. Engine cross-check:** keep RapidOCR as champion; use Tesseract/PaddleOCR as a **cross-checker** on disputed money rows (agree→trust, differ→flag). Don't burn the night installing heavy engines before the parser is strong. PP-Structure/Docling only as a separate alternate branch, strictly compared.
- **D. Speed:** `onnxruntime-directml`/OpenVINO on the Arc iGPU; parallelize across cores. Only if accuracy holds.
- **E. Non-numeric fields:** service no., billing month, bill/due dates, consumer/category/location, CMD/RMD, KWH/KVAH/KVA totals, PF, LF%, meter readings. Needed to support the "structured fields" claim.

## GRADING & REVIEW — free vision + reasoning (build-time only)
- **You ARE Claude Opus 4.8 with vision.** Read rendered PNGs yourself to build pseudo-GT, adjudicate cross-engine disputes, and diagnose mis-binds (often faster than blind rule-tuning). Trust your read over OCR; zoom (higher render scale) or ask codex if unsure.
- **Codex** = independent second opinion / tie-breaker / final review.
- Neither may enter the production runtime path.

## GUARDRAILS
- **Git = rollback net.** Commit each accepted win with a SCOPED add (`git add ocr_lab/<files>`, NOT `git add -A`; don't sweep in caches/GT/user files). Prefer `git revert`/checkout of specific files over blind `git reset --hard`.
- `best/` = champion code + `best/MANIFEST.json` {git commit, approach, run command, dep versions, cache variant, dev/test/full metrics, pseudo-GT version, known failures}. Copying code alone is insufficient.
- `metrics/leaderboard.jsonl` auto-logs; include commit hash + split + field metrics. `RESULTS.md` = human running log (hypothesis→delta→keep/revert→source).
- Research must not block a known local fix or stall under restricted network. Time-box it.
- Version approaches by name. Never overwrite history.

## STOP criteria (objective)
Stop the primary approach when: field-level accuracy on DEV **and** held-out TEST plateaus over several iterations at a high level, coverage is complete, reconciliation rate (full graph) is high, **and BOTH** your own critical self-review **and** codex agree it can't be meaningfully improved locally. Record both verdicts + the strongest remaining weakness. THEN keep the champion safe and spawn ≥1 alternate (table-structure model path, or template-zone path) to try to beat it; adopt only on a strict win.

## DELIVERABLES (`metrics/RESULTS.md`)
1. Champion pipeline in `best/` + MANIFEST, one command to run on full PDF, emitting the **full 262-page extracted table (CSV/JSON) with provenance** — the artifact the future dashboard/RAG will consume.
2. **Metrics table:** field-level exact-match (money/consumption/dates/IDs/text, dev+test), accounting-reconcile rate (full graph), coverage %, CER/WER/numeric-exact vs vision pseudo-GT, cross-engine agreement %, throughput (pages/min), peak RAM.
3. Ranked leaderboard of all approaches.
4. Two final verdicts (self-review + codex) + strongest remaining weakness.
5. Alternate approaches tried and whether they beat the champion.
6. "How others solve this" notes + sources.

## Run
```
cd ocr_lab
python eval.py --split dev            # fast inner loop (cached)
python render.py <page>               # PNG for your vision grading
```
Do Phase 0 first (metric+provenance+pseudo-GT+splits). Then climb. Don't give up.
