"""Production runner: OCR + extract all 262 pages -> provenance JSONL + flat CSV
+ coverage/reconcile report. 100% local, deterministic, no cloud.

Usage: python run_full.py [n_pages]   (default 262)
Outputs (outputs/):
  extract.jsonl  — one row/page: {page, doc_type, fields{...provenance}, reconcile}
  table.csv      — flat key fields per bill page
  coverage.json  — classification counts + reconcile pass rates
"""
import sys, os, json, csv, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from common import ocr, classify
from parse import parse
from reconcile import reconcile
from sparse import is_sparse, sparse_parse
try:
    from tess_check import recover_fppca as _tess_recover
except Exception:
    def _tess_recover(*a, **k):           # Tesseract optional; degrade gracefully
        return False

ROOT = os.path.dirname(__file__)
OUT = os.path.join(ROOT, "outputs")
os.makedirs(OUT, exist_ok=True)

FLAT = ["bill_month", "bill_date", "due_date", "service_no", "van_id", "category",
        "cons_kwh", "cons_kvah", "cons_kva", "cons_pf",
        "demand_normal", "energy_charges", "elec_duty", "fppca", "tod_charges",
        "sub_total", "customer_charges", "total", "net_bill", "net_payable"]

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 262
    kinds = {}
    chain_ok = bills = 0
    t0 = time.time()
    with open(os.path.join(OUT, "extract.jsonl"), "w", encoding="utf-8") as jf, \
         open(os.path.join(OUT, "table.csv"), "w", newline="", encoding="utf-8") as cf:
        cw = csv.writer(cf); cw.writerow(["page"] + FLAT + ["chain_ok", "doc_type"])
        for p in range(1, n + 1):
            boxes = ocr(p)                         # cached or OCRs on first touch
            kind = classify(boxes)
            kinds[kind] = kinds.get(kind, 0) + 1
            row = {"page": p, "doc_type": kind}
            if kind in ("HT_BILL", "BILL?") and is_sparse(boxes):
                fields = sparse_parse(boxes)          # alternate sparse template
                row["doc_type"] = "sparse_bill"; row["fields"] = fields
                cw.writerow([p] + [fields.get(k, {}).get("value") for k in FLAT]
                            + [None, "sparse_bill"])
            elif kind in ("HT_BILL", "BILL?"):
                fields, recs = parse(boxes)
                _tess_recover(fields, recs, boxes, p)   # gated Tesseract fppca recovery
                rec = reconcile(fields, recs)
                bills += 1; chain_ok += rec["chain_ok"]
                row["fields"] = fields
                row["reconcile"] = {"chain_ok": rec["chain_ok"],
                                    "checks": {c["name"]: c["status"] for c in rec["checks"]}}
                cw.writerow([p] + [fields.get(k, {}).get("value") for k in FLAT]
                            + [rec["chain_ok"], kind])
            else:
                cw.writerow([p] + [None] * len(FLAT) + [None, kind])
            jf.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            if p % 20 == 0:
                print(f"  ...{p}/{n}  ({time.time()-t0:.0f}s)")

    cov = {"pages": n, "kinds": kinds, "bill_pages": bills,
           "chain_ok": chain_ok, "chain_ok_rate": round(chain_ok / bills, 4) if bills else 0,
           "seconds": round(time.time() - t0, 1)}
    json.dump(cov, open(os.path.join(OUT, "coverage.json"), "w"), indent=2)
    print("\nCOVERAGE:", json.dumps(cov, indent=2))
    print("wrote outputs/{extract.jsonl,table.csv,coverage.json}")

if __name__ == "__main__":
    main()
