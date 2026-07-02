# GOAL: Best-possible LOCAL OCR + field extraction for the EPDCL HT-bill PDF

## Mission (one line)
Iterate — RL-style, autonomously, all night — until you have the **cheapest, highest-accuracy, fully-local** pipeline that turns `Issue-4.pdf` (262-page scanned monthly electricity bills) into **accurate text + structured fields**, self-graded with no ground truth, and **codex-signed-off that it can't be beaten** — then try alternate approaches to beat it anyway.

**SCOPE THIS RUN: OCR / extraction ONLY.** Do NOT build the dashboard or RAG agent yet. Just make extraction excellent and measured.

---

## Hard constraints (do not violate)
- **100% local. No cloud OCR/LLM APIs. No paid services.** Codex CLI is allowed (it's local-invoked) for grading/diagnosis/vision only — never as the production OCR engine.
- Runs on this laptop: **Intel Core Ultra 9 285H, 32 GB RAM, Intel Arc 140T iGPU, no NVIDIA/CUDA, Windows 11.** CPU or iGPU (DirectML/OpenVINO) only.
- **Deterministic extraction preferred** over generative — a wrong digit that looks right is the #1 enemy. Detection-based OCR (RapidOCR/Paddle/Tesseract) does not hallucinate numbers; keep it that way.
- **Never lose the best pipeline.** Snapshot champion into `ocr_lab/best/` before trying anything risky. Keep it green.
- **Don't guess numbers.** Verify against the actual page image (via codex vision or your own image read). No fabricated values in metrics.

## Environment (already set up — don't rediscover)
- Working dir: `C:\Users\Amarsh\OneDrive\Documents\Personal\OCR`, project in `ocr_lab/`.
- Python 3.12 (Windows Store build). `pip`/`winget` usable for unattended installs.
- Installed & verified: `rapidocr-onnxruntime` (CPU ONNX PP-OCR), `pypdf`, `PIL`, `opencv-python`, `numpy`, `pandas`, `onnxruntime` (CPU+Azure providers only).
- Codex: `codex` CLI v0.135.0 on PATH. Check `codex --help` for image/vision invocation before relying on it.
- Cache: `ocr_lab/cache/p{n}.json` holds OCR boxes for 19 sampled pages `[ycenter,xmin,xmax,text]`. Inner-loop eval reads cache = instant.

## What is ALREADY ESTABLISHED (build on this — proven, don't relitigate)
1. **The PDF's embedded text layer is garbage for numbers** (baked-in bad OCR / missing). Must OCR the page images directly. Confirmed on pp.8 & 51.
2. **RapidOCR reads numbers near-perfectly**: on the hardest page (p8, pure scan) it got **14/14 key numeric fields verbatim** incl. `315595.06`, `152342.10`, `11930.96`, amount-in-words. ~13–16 s/page on CPU.
3. **The real problem is BINDING** — associating each number to its field. Raw OCR flattens the table (reading order scrambles columns). This is the thing to optimize.
4. **Document composition** (19-page sample): ~**85% is ONE identical template** (EPDCL HT bill), a monthly series **01/2024 → 05/2026**. ~2–3 non-bill pages (correspondence: p1, p144) + 1 sparse (p262). So: one dominant fixed template + a few outliers.
5. **The accuracy metric is the bill's own arithmetic** (see below) — self-supervising, no labels.

## The METRIC (self-supervised — this is your reward signal)
`reconcile.py` checks each page's internal math (all must be independently true on a correct read):
1. `charges_sum`: demand+energy+duty+fppca+tod == sub_total
2. `total_calc` : sub_total + customer_charges == total
3. `net_round`  : round(net_bill) == net_payable
4. `words_match`: amount-in-words == net_payable
**Primary reward = PAGE-OK rate** (≥3/4 checks pass, words not contradicted) across bill pages. A page that reconciles is almost certainly bound correctly. Rising PAGE-OK rate = real progress.

Baseline already logged: `metrics/leaderboard.jsonl` → `baseline_v0` = PAGE-OK 0/16, but `charges_sum` 6/9 (signal exists). Known baseline bugs to fix first:
- `net_payable` returns None → "Net Payable" label match / value adjacency broken (multi-word split; value may be glued as `Rs317001.00`).
- `total_calc` 0/15 → "Total" collides with "Total Consumption" (need exact/anchored label, not substring).
- Far-right money column (energy/fppca) sits in its own y-band → target the money x-band, nearest-in-y, not tight-row rightmost.

Also produce **classic OCR metrics** for the final report (see Deliverables): **transcribe a held-out sample of pages with your own vision** (Read the rendered PNGs; codex as backup) to build **pseudo-ground-truth**, then compute **CER, WER, and numeric-field exact-match** of your pipeline vs that. Plus throughput (pages/min) and peak RAM.

## The LOOP (run this until stop criteria)
```
while not (plateaued AND codex_says_optimal):
    1. Pick the highest-leverage failing check (read eval.py output + inspect boxes).
    2. Form a hypothesis. If it's a known-type problem, SEARCH ONLINE first
       (WebSearch/Exa/HF) — electricity-bill OCR, invoice KV extraction,
       PP-Structure table recognition, ICDAR/DocVQA, RapidOCR params, deskew.
       Trace the SPECIFIC failure; do not guess.
    3. Implement ONE change (a lever below). Keep diffs surgical.
    4. Run `python eval.py <approach_name>`  (fast, cached dev set).
    5. If PAGE-OK improved and nothing regressed -> snapshot to best/, update RESULTS.md.
       Else revert. Always keep best/ green.
    6. Every few wins: verify on the HELD-OUT test bills (not dev) to check you're
       not overfitting rules to dev pages. Use codex vision to spot-check 2-3 pages.
    7. Log metrics every iteration (leaderboard.jsonl auto-appends).
```
Fast inner loop = cached dev pages only. When you change OCR/preprocessing (not just binding), re-OCR affected pages with a new cache `variant=` so you can compare. Expand OCR cache to more bill pages as confidence grows; run the FULL 262 only for final metrics.

**Dev/test discipline:** tune on `DEV_BILLS` (in common.py). Hold out a separate set for validation, e.g. `TEST_BILLS = [24,40,56,72,104,136,168,200,232,248]` — OCR these once, never tune against them, report final numbers on them.

## LEVERS to explore (hyperparameters + approaches — this is the search space)
**A. Binding logic (start here — biggest, cheapest wins):**
- Exact/anchored label matching; join adjacent boxes for multi-word labels; split glued `label+value`.
- Column-aware extraction: detect header x-positions (`KWH/KVAH/KVA/PF/LF%`) and assign the consumption-row values to the right column. Same idea for the money column.
- Template zones: since layout is fixed, calibrate approximate (x,y) regions per field from a few reconciling pages, then snap — but make it scale/offset-tolerant (align by an anchor like the "EASTERN POWER" header or page bounds).
**B. Preprocessing (feed cleaner pixels):**
- deskew, binarize (Otsu/adaptive), denoise, upscale small-font regions, try rendering the PDF page at 300–400 DPI vs using the embedded JPEG (compare which OCRs better). `ocrmypdf`/opencv.
**C. OCR engine bake-off (cross-check + maybe upgrade):**
- RapidOCR model variants/params (det_db params, rec model, use_angle_cls). Then benchmark **PaddleOCR / PP-StructureV3** (native table-structure → HTML grid), **Tesseract** (winget install; `--psm` tuning; strong when preprocessed), **docTR**, **EasyOCR**. Use a SECOND engine as a **cross-checker**: where two independent engines agree on a number, trust it; where they differ, flag. Cross-engine agreement is a second free metric.
**D. Speed (enables more iterations):**
- Try `onnxruntime-directml` or OpenVINO to run OCR on the **Arc 140T iGPU** (target: 15s → few s/page). Parallelize pages across CPU cores. Only pursue if it doesn't cost accuracy.
**E. Table-structure models:** PP-StructureV3 / Docling TableFormer to recover the grid directly, then map cells → fields. Heavier; evaluate cost/benefit.

## RESEARCH mandate
Many of these problems are solved. Before hand-rolling, search: "PaddleOCR table structure recognition", "invoice key-value extraction OCR bounding boxes", "electricity bill OCR pipeline", "RapidOCR det parameters small text", "OpenVINO onnxruntime Arc iGPU". Trace the exact failing symptom to a known cause. Cite what you adopt in RESULTS.md.

## GRADING & GROUND-TRUTH — use YOUR OWN free vision + reasoning (no external API)
**You (the agent running this goal) ARE Claude Opus 4.8 with vision.** That is a free "eyes + brain" you can use for grading, ground-truth, adjudication, and review — it is NOT an external API and costs the pipeline nothing. Use it as the PRIMARY judge. Codex is a free SECOND opinion.

**Hard rule:** self-vision/codex are for BUILD-TIME grading & review only. The **production pipeline must stay 100% local/offline** (RapidOCR/Paddle/Tesseract). Never make Claude-vision or codex a runtime dependency of the monthly extractor.

- **Pseudo-ground-truth (primary):** `python render.py <p>` → PNG, then **Read the PNG yourself** and transcribe the fields/numbers by eye. Save to `samples/gt/p<n>.json`. Use these as ground truth to compute **CER / WER / numeric exact-match** for your pipeline. Build GT for the held-out TEST bills + a few outliers. Trust your own read over OCR when they conflict — but if unsure on a faint digit, zoom (render at higher scale) and/or ask codex to confirm.
- **Adjudication:** when two OCR engines disagree on a number, Read the page image yourself and decide the truth. Codex = tie-breaker if you're uncertain.
- **Diagnosis:** stuck >2 iterations on a check? Read the page PNG + your extracted fields + the OCR boxes and reason about what's mis-bound. This is often faster than blind rule-tuning.
- **Final review (two independent gates):** when plateaued, (1) do your own critical self-review reading several pages against the pipeline output, AND (2) ask codex *"can this be more accurate or cheaper, locally? strongest remaining failure?"*. Treat the goal as done only when BOTH agree it's near-optimal. Record both verdicts.

## STOP criteria
Stop the primary approach when: PAGE-OK rate plateaus (no gain over several iterations across DEV **and** held-out TEST), per-field accuracy is high on the vision pseudo-GT sample, **and** BOTH your own critical self-review AND codex review say it can't be meaningfully improved locally. THEN: keep the champion safe in `best/` and **spawn ≥1 alternate approach** (e.g. PP-StructureV3 table-grid path, or a template-zone path) to try to beat the champion. Adopt an alternate only if it strictly wins. Repeat until alternates stop beating the champion.

## GUARDRAILS
- **Git is initialized.** Commit after every accepted improvement (`git add -A && git commit -m "<approach>: PAGE-OK x/16 -> y/16"`). This is your rollback net — if a change wrecks the env or metric, `git reset --hard` to the last green commit. Never force-push; never delete history.
- `ocr_lab/best/` = current champion, always runnable. Snapshot before risky changes.
- Every eval auto-logs to `metrics/leaderboard.jsonl`. Keep `RESULTS.md` as the human-readable running log: what tried, metric delta, why kept/reverted, sources.
- Version approaches by name (`baseline_v0`, `bind_v1_exactlabel`, `pp_structure_v1`, ...). Never overwrite history.
- Don't break the working loop. Small surgical diffs. If an install wedges the env, back it out.

## DELIVERABLES (produce `metrics/RESULTS.md` at the end)
1. **Champion pipeline** in `best/`, one command to run on the full PDF.
2. **Metrics table**: PAGE-OK reconcile rate (dev + held-out), per-check pass %, per-field accuracy, **CER / WER / numeric exact-match vs your vision pseudo-GT**, cross-engine agreement %, throughput (pages/min), peak RAM, coverage (% pages parsed).
3. **Leaderboard** of every approach tried, ranked.
4. **Two final verdicts**: your own self-review + codex ("can't do better locally" + strongest remaining weakness).
5. **Alternate approaches** tried and whether they beat the champion.
6. Short **"how others solve this"** notes with the sources you used.

## Run
```
cd ocr_lab
python eval.py <approach_name>      # fast inner loop (cached)
python render.py <page>             # PNG for codex vision grading
# expand OCR: common.ocr(page, variant="deskew", preprocess=fn)
```
Begin by fixing the three known baseline binding bugs, re-run eval, and climb from there. Don't give up.
