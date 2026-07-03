# Handover — OCR Lab

Everything a new maintainer needs: what this is, why it's built this way, what's
proven, what's fragile, and how to run it every month.

---

## 1. What it does

Ingests scanned EPDCL HT electricity bills and produces, per bill:
- the full page text (structured), and
- a dictionary of accounting fields (service no, category, consumption, every
  charge line, sub-total → total → net bill → net payable, arrears),

where **every scored value traces to a real OCR box** (no imputation), and the
whole bill is **checked against its own arithmetic** before it's trusted.

The design priority is **not** "highest raw accuracy" — it's **"never silently
emit a wrong money value."** That is why the accounting guardrail, not the model,
has the final say.

---

## 2. Architecture & why

### Tier 1 — deterministic, local (the system of record)
`RapidOCR` (PP-OCR models on ONNX Runtime, CPU) reads each page into boxes
`[y, xmin, xmax, text, conf]`. `parse.py` binds labels→values using the bill's
fixed template, solving the real problems of these scans:
- **template shear** — labels and values drift per page → solved by *rank alignment*
  (the i-th amount pairs with the i-th label), not pixel positions.
- **money column detection** — right-aligned, value-terminal, width-bounded numeric cluster.
- **glued / split / OCR-typo labels** — fuzzy label matching, gated so it only fires
  when exact matching is short (ungated fuzzy *regressed* accuracy — see §5).

`reconcile.py` then runs the **full signed accounting graph** (sub = Σ charges;
total = sub + lower rows; net_bill = total + post-total rows; net_payable =
net_bill + arrears) to a **0.02 paise tolerance**. A page is flagged for review
only on a real signal: the chain doesn't close, a core field is missing, or a
value is out of range (e.g. PF ∉ [0, 1.05]).

### Tier 2 — VLM QC on flagged pages only
Re-reads *only* flagged pages (never the clean bulk). Two interchangeable backends
behind `run_full.py --qc`:
- **`gemini`** (`qc_gemini.py`) — Gemini 2.5 Flash, cloud, ~13 s/pg, ~$0.0007/pg.
- **`uocr`** (`uocr.py`) — Baidu Unlimited-OCR 3.3B, **fully local/offline**, ~2–4 min/pg on CPU.

Both return the same field dict and pass the **same guardrail** (`gemini_chain_ok`):
accept the QC read only if its numbers self-reconcile. Two ways to pass —
(A) `net_payable == net_bill + arrears`, or (B) the upstream chain corroborates
`net_bill` across 3 identities, in which case arrears is *derived* from the printed
anchors (this recovers VLM sign/digit slips). A hallucination can't satisfy three
identities, so (B) stays safe.

### Tier 3 — human
Whatever neither tier can close. On the measured batch this was **2 pages**
(with Gemini), both genuine VLM slips the accounting caught.

---

## 3. What's proven (measured, not asserted)

- **~98% field-exact** vs a frozen 9-page vision ground truth, held stable across
  three independent held-out batches (21 pages the parser never saw): 97.6% / 98.4%.
- **Flag-recall 89%, 0 silent money errors** — the one value that slips is a
  non-money Load-Factor %.
- **Gemini QC:** 105/107 flagged resolved; human queue → 0 after the 3-identity
  guardrail; cost ~$0.08/batch, ~$1/year.
- **17 accounting tests** green (`test_accounting.py`).

Methodology note: the held-out pools were **never exhausted** — ~170 pristine
pages remain, so any future change can still be measured honestly for overfit.
**Do not train/tune against `samples/gt/` — it is the frozen ground truth.**

---

## 4. Known limitations / fragile spots

- **`--qc uocr` on the hardest pages:** Unlimited-OCR is flawless on clean bills but
  **leaves the lower-right money cells blank on faint/credit lower panels** — exactly
  the flagged minority. Those don't self-reconcile → they correctly fall back (human,
  or gemini). So the local path leaves a *larger* human residue than the cloud path.
  It is safe, just less complete. Its true resolve-rate over all ~107 flagged pages
  was **not** run end-to-end (would take ~4–7 hrs at 2–4 min/pg) — good overnight job.
- **Unlimited-OCR is GPU-first.** `uocr.py` forces CPU via a `torch.Tensor.cuda`
  monkeypatch + bf16 load. It needs `transformers==4.57.x`, `torch`, `accelerate`,
  `addict`, `einops`, `timm`. On CPU it's slow; the **Arc iGPU (OpenVINO)** is the
  intended accelerator and is not yet wired.
- **`transformers` version coupling:** the local-VLM work pinned `transformers==4.49`
  then `4.57` at different points. The tier-1 pipeline does **not** use transformers
  (RapidOCR is onnxruntime), so this only affects `--qc uocr`.
- **Gemini key** is read from an external project `.env` path hard-coded in
  `qc_gemini.py` (not stored in this repo). Set `GEMINI_API_KEY` env var to override.
- **Synthetic/fabricated bills** (AI-generated) are correctly *rejected* by the
  guardrail (their numbers don't add up) — a bonus tamper signal, not a bug.

---

## 5. Lessons learned (don't re-litigate these)

- **Deskew/retilt was tested and rejected** — it *lowered* accuracy (98.0% → 96.6%).
  Measure, don't assume.
- **Ungated fuzzy label matching regressed** dev 98.9 → 93.5 → reverted to gated.
- **Tesseract blind cross-check** fixed 1 page but regressed 29 → gated to fire only
  on FPPCA component-check failures.
- **Blanket low-confidence flagging** flagged ~80% of pages → replaced with the
  precise math-fail / core-missing / PF-range gate.
- **SmolVLM-256M** is too small for money digits (3/8, drops leading digits & signs).

---

## 6. How to run a monthly batch

```bash
# 1. Drop the month's scanned bills in as a PDF (replace Issue-4.pdf or point common.py at it)
# 2. Deterministic pass (local, ~20-90 min):
python run_full.py

# 3. Clear the flagged queue. Pick ONE:
python run_full.py --qc gemini     # fast + cheap, needs internet + GEMINI_API_KEY
python run_full.py --qc uocr       # fully offline, slow, leaves a bigger human residue

# 4. Read outputs/coverage.json -> auto_verified, qc_resolved, needs_review (the human queue)
# 5. Hand the needs_review pages (needs_review=true rows in table.csv) to a person.
```

Cache: OCR results cache under `cache/` (deterministic); Gemini reads cache under
`cache/gemini/` (resumable, no re-cost). Delete a cache file to force a re-read.

---

## 7. Sensible next steps

1. **Dashboard** — turn `outputs/` into a browsable monthly view: auto-verified vs
   QC-resolved vs needs-review, each value tagged `deterministic / gemini / uocr`
   with its provenance box. (This was the original "host & share" goal.)
2. **Arc iGPU for `--qc uocr`** — OpenVINO/DirectML to bring local QC from minutes to
   seconds per page, making the fully-offline path practical at scale.
3. **Overnight `--qc uocr` full run** — measure the true local resolve-rate over all
   flagged pages.
4. **Robust Gemini key handling** — move off the hard-coded external `.env` path.

---

## 8. Git / data hygiene

- `Issue-4.pdf` contains **real bills with PII** and is currently tracked. **Do not
  push to a public remote.** Use a private remote, or remove the PDF + `samples/`
  from history before publishing.
- `samples/gt/*.json` is the **immutable** frozen ground truth — never edit.
- `best/` is the champion snapshot — restore from here if a change regresses.
