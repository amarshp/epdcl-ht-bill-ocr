"""Eval harness. Runs extract+reconcile over the cached dev bills, prints a
per-page + per-check report, and appends one line to metrics/leaderboard.jsonl.

Inner loop uses ONLY cached pages (no OCR) -> fast iteration.
Usage:  python eval.py [approach_name]
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from common import ocr, classify, DEV_BILLS
from extract import extract
from reconcile import reconcile

APPROACH = sys.argv[1] if len(sys.argv) > 1 else "baseline_rapidocr_spatial"
CHECKS = ["charges_sum", "total_calc", "net_round", "words_match"]

def main():
    rows, per_check = [], {c: [0, 0] for c in CHECKS}  # [pass, testable]
    pages_ok = 0
    for p in DEV_BILLS:
        boxes = ocr(p)                       # cached
        if classify(boxes) not in ("HT_BILL", "BILL?"):
            continue
        fields = extract(boxes)
        rec = reconcile(fields)
        pages_ok += rec["page_ok"]
        for c in CHECKS:
            v = rec["checks"][c]
            if v is not None:
                per_check[c][1] += 1
                per_check[c][0] += (v is True)
        rows.append((p, rec, fields))

    n = len(rows)
    print(f"\n== {APPROACH} ==  dev bills: {n}")
    print(f"{'page':>5} {'ok':>3} {'chgSum':>7} {'totCalc':>7} {'netRnd':>7} {'words':>7}   net_payable")
    for p, rec, f in rows:
        c = rec["checks"]
        sym = lambda v: "  ." if v is None else (" OK" if v else "  x")
        print(f"{p:>5} {'Y' if rec['page_ok'] else 'n':>3} "
              f"{sym(c['charges_sum']):>7} {sym(c['total_calc']):>7} "
              f"{sym(c['net_round']):>7} {sym(c['words_match']):>7}   {f.get('net_payable')}")
    page_ok_rate = pages_ok / n if n else 0
    print(f"\nPAGE-OK rate : {pages_ok}/{n} = {page_ok_rate:.1%}")
    for c in CHECKS:
        pw, tt = per_check[c]
        print(f"  {c:12}: {pw}/{tt}" + (f" = {pw/tt:.0%}" if tt else " (untestable)"))

    rec_line = {
        "approach": APPROACH,
        "dev_pages": n,
        "page_ok": pages_ok,
        "page_ok_rate": round(page_ok_rate, 4),
        "per_check": {c: per_check[c] for c in CHECKS},
        "ts": int(time.time()),
    }
    lb = os.path.join(os.path.dirname(__file__), "metrics", "leaderboard.jsonl")
    os.makedirs(os.path.dirname(lb), exist_ok=True)
    with open(lb, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec_line) + "\n")
    print(f"\nlogged -> {lb}")
    return page_ok_rate

if __name__ == "__main__":
    main()
