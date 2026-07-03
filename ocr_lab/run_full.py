"""Production runner: OCR + extract all 262 pages -> provenance JSONL + flat CSV
+ coverage/reconcile report. Deterministic core is 100% local; optional tier-2 QC.

Usage: python run_full.py [n_pages] [--qc uocr|gemini]   (default 262, no QC)
  --qc uocr    local Baidu Unlimited-OCR re-reads flagged pages (offline, slow)
  --qc gemini  cloud Gemini re-reads flagged pages (fast, ~pennies)
Either way the QC read is accepted ONLY if its numbers self-reconcile; pages it
can't close stay flagged for a human. Outputs (outputs/):
  extract.jsonl  — one row/page: {page, doc_type, fields{...provenance}, reconcile, qc}
  table.csv      — flat key fields per bill page (+ qc_resolved)
  coverage.json  — classification counts + reconcile + QC resolution rates
"""

import csv
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from common import classify, ocr
from parse import parse
from reconcile import page_needs_review, reconcile
from sparse import is_sparse, sparse_parse

try:
    from tess_check import recover_fppca as _tess_recover
except Exception:

    def _tess_recover(*a, **k):  # Tesseract optional; degrade gracefully
        return False


ROOT = os.path.dirname(__file__)
OUT = os.path.join(ROOT, "outputs")
os.makedirs(OUT, exist_ok=True)


def get_qc(mode):
    """Return (read_fn, chain_ok_fn) for the chosen tier-2 backend, or (None, None).
    Both backends return the SAME accounting-field dict, validated by the SAME
    self-consistency guardrail (net_payable == net_bill + arrears, corroborated)."""
    if mode not in ("uocr", "gemini"):
        return None, None
    from common import page_image
    from qc_gemini import gemini_chain_ok  # generic accounting self-check

    if mode == "gemini":
        from qc_gemini import qc_page

        return (lambda p: qc_page(p, page_image(p))), gemini_chain_ok
    import uocr  # local Unlimited-OCR (lazy: heavy)

    return (
        lambda p: uocr.parse_fields(uocr.transcribe(page_image(p)))
    ), gemini_chain_ok


FLAT = [
    "bill_month",
    "bill_date",
    "due_date",
    "service_no",
    "van_id",
    "category",
    "cons_kwh",
    "cons_kvah",
    "cons_kva",
    "cons_pf",
    "demand_normal",
    "energy_charges",
    "elec_duty",
    "fppca",
    "tod_charges",
    "sub_total",
    "customer_charges",
    "total",
    "net_bill",
    "net_payable",
]


def main():
    argv = sys.argv[1:]
    qc_mode = None
    if "--qc" in argv:
        i = argv.index("--qc")
        qc_mode = argv[i + 1]
        del argv[i : i + 2]
    n = int(argv[0]) if argv else 262
    qc_read, qc_ok = get_qc(qc_mode)
    kinds = {}
    chain_ok = bills = needs_review = 0
    qc_attempted = qc_resolved = 0
    t0 = time.time()
    with open(os.path.join(OUT, "extract.jsonl"), "w", encoding="utf-8") as jf, open(
        os.path.join(OUT, "table.csv"), "w", newline="", encoding="utf-8"
    ) as cf:
        cw = csv.writer(cf)
        cw.writerow(["page"] + FLAT + ["chain_ok", "doc_type", "qc_resolved"])
        for p in range(1, n + 1):
            boxes = ocr(p)  # cached or OCRs on first touch
            kind = classify(boxes)
            kinds[kind] = kinds.get(kind, 0) + 1
            row = {"page": p, "doc_type": kind}
            if kind in ("HT_BILL", "BILL?") and is_sparse(boxes):
                fields = sparse_parse(boxes)  # alternate sparse template
                row["doc_type"] = "sparse_bill"
                row["fields"] = fields
                cw.writerow(
                    [p]
                    + [fields.get(k, {}).get("value") for k in FLAT]
                    + [None, "sparse_bill", None]
                )
            elif kind in ("HT_BILL", "BILL?"):
                fields, recs = parse(boxes)
                _tess_recover(fields, recs, boxes, p)  # gated Tesseract fppca recovery
                rec = reconcile(fields, recs)
                bills += 1
                chain_ok += rec["chain_ok"]
                row["fields"] = fields
                row["reconcile"] = {
                    "chain_ok": rec["chain_ok"],
                    "checks": {c["name"]: c["status"] for c in rec["checks"]},
                }
                # actionable review signal: low-confidence fields OR a broken math line
                row["low_confidence_fields"] = [
                    k for k, v in fields.items() if v.get("low_confidence")
                ]
                review = page_needs_review(fields, rec)
                if qc_read and review:  # tier-2: re-read only flagged pages
                    qf = qc_read(p)
                    resolved = qc_ok(qf)
                    row["qc"] = {"mode": qc_mode, "resolved": resolved, "fields": qf}
                    qc_attempted += 1
                    if resolved:
                        review = False
                        qc_resolved += 1
                row["needs_review"] = review
                needs_review += review
                cw.writerow(
                    [p]
                    + [fields.get(k, {}).get("value") for k in FLAT]
                    + [rec["chain_ok"], kind, bool(row.get("qc", {}).get("resolved"))]
                )
            else:
                cw.writerow([p] + [None] * len(FLAT) + [None, kind, None])
            jf.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            if p % 20 == 0:
                print(f"  ...{p}/{n}  ({time.time()-t0:.0f}s)")

    cov = {
        "pages": n,
        "kinds": kinds,
        "bill_pages": bills,
        "qc_mode": qc_mode,
        "qc_attempted": qc_attempted,
        "qc_resolved": qc_resolved,
        "needs_review": needs_review,  # residual after QC (human queue)
        "auto_verified": bills - needs_review,  # deterministic-clean + QC-resolved
        "chain_ok": chain_ok,
        "chain_ok_rate": round(chain_ok / bills, 4) if bills else 0,
        "seconds": round(time.time() - t0, 1),
    }
    json.dump(cov, open(os.path.join(OUT, "coverage.json"), "w"), indent=2)
    print("\nCOVERAGE:", json.dumps(cov, indent=2))
    print("wrote outputs/{extract.jsonl,table.csv,coverage.json}")


if __name__ == "__main__":
    main()
