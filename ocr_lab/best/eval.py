"""Eval harness — PRIMARY: field-exact vs frozen vision GT (by category);
SECONDARY: full-accounting reconcile rate; REQUIRED: coverage over all pages.

Usage:
  python eval.py --split dev            # cached dev bills (fast inner loop)
  python eval.py --split test           # held-out bills (OCRs on first run)
  python eval.py --split full           # all 262 pages (OCRs everything; slow)
  python eval.py --gt                   # field-exact vs frozen GT (the real target)
  python eval.py --all                  # gt + dev reconcile + coverage summary
No-imputation is enforced upstream: only observed OCR-boxed values are scored.
"""
import sys, os, json, time, argparse, glob
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from common import ocr, classify, DEV_BILLS, TEST_BILLS
from parse import parse
from reconcile import reconcile

ROOT = os.path.dirname(__file__)
GT_DIR = os.path.join(ROOT, "samples", "gt")
CATS = {
    "money": ["demand_normal","demand_penal","energy_charges","excess_energy","elec_duty",
              "fppca","tod_charges","tod_incentive","sub_total","customer_charges","grid_support",
              "pooled_cost","neticd","total","loss_gain","net_bill","arrears_prev","arrears_curr",
              "net_payable"],
    "consumption": ["cons_kwh","cons_kvah","cons_kva","cons_pf"],
    "dates": ["bill_month","bill_date","due_date"],
    "ids": ["service_no","van_id","category"],
}

def _num_eq(a, b, tol=0.01):
    try: return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError): return False

def _str_eq(a, b):
    n = lambda s: "".join(ch for ch in str(s).lower() if ch.isalnum())
    return n(a) == n(b)

def match(field, got, exp):
    if got is None: return False
    if field in CATS["dates"] or field in CATS["ids"]:
        return _str_eq(got, exp)
    return _num_eq(got, exp)

def gt_pages():
    out = {}
    for f in glob.glob(os.path.join(GT_DIR, "p*.json")):
        o = json.load(open(f, encoding="utf-8"))
        out[o["page"]] = o
    return out

def score_gt():
    """Field-exact vs frozen GT, per category. Only ht_bill GT pages are scored
    field-by-field; sparse/statement report classification correctness."""
    gts = gt_pages()
    agg = {c: [0, 0] for c in CATS}          # [hit, total]
    per_page = []
    for p in sorted(gts):
        gt = gts[p]
        boxes = ocr(p)
        kind = classify(boxes)
        if gt["doc_type"] != "ht_bill":
            per_page.append((p, gt["doc_type"], kind, None))
            continue
        fields, recs = parse(boxes)
        got = {}
        for c, keys in CATS.items():
            for k in keys:
                if k not in gt.get("money", {}) and k not in gt.get("consumption", {}) \
                   and k not in gt.get("dates", {}) and k not in gt.get("ids", {}):
                    continue
                exp = (gt.get("money", {}) | gt.get("consumption", {}) |
                       gt.get("dates", {}) | gt.get("ids", {})).get(k)
                gv = fields.get(k, {}).get("value") if k in fields else None
                ok = match(k, gv, exp)
                agg[c][0] += ok; agg[c][1] += 1
                got[k] = (gv, exp, ok)
        hits = sum(1 for v in got.values() if v[2]); tot = len(got)
        per_page.append((p, "ht_bill", kind, (hits, tot)))
    return agg, per_page

def score_reconcile(pages):
    """Full-accounting reconcile over a page list. Returns per-check + chain stats."""
    checks = {c: [0, 0] for c in ("sub_total","total","net_bill","net_payable")}
    chain_ok = bills = 0
    for p in pages:
        boxes = ocr(p)
        if classify(boxes) not in ("HT_BILL", "BILL?"):
            continue
        bills += 1
        fields, recs = parse(boxes)
        r = reconcile(fields, recs)
        chain_ok += r["chain_ok"]
        for c in checks:
            ch = next(x for x in r["checks"] if x["name"] == c)
            if ch["status"] is not None:
                checks[c][1] += 1; checks[c][0] += (ch["status"] is True)
    return {"bills": bills, "chain_ok": chain_ok, "checks": checks}

def score_coverage(pages):
    """Classify every page; coverage = successfully-parsed bills / expected bills."""
    kinds = {}
    for p in pages:
        boxes = ocr(p)
        k = classify(boxes)
        kinds[k] = kinds.get(k, 0) + 1
    return kinds

def git_hash():
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=ROOT, text=True).strip()
    except Exception:
        return "?"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test", "full"], default="dev")
    ap.add_argument("--gt", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--approach", default="v1_shear_parser")
    a = ap.parse_args()

    pages = {"dev": DEV_BILLS, "test": TEST_BILLS,
             "full": list(range(1, 263))}[a.split]

    log = {"approach": a.approach, "commit": git_hash(), "split": a.split, "ts": int(time.time())}

    if a.gt or a.all:
        agg, per_page = score_gt()
        print("\n== FIELD-EXACT vs FROZEN GT (primary) ==")
        for c in CATS:
            h, t = agg[c]
            print(f"  {c:12}: {h}/{t}" + (f" = {h/t:.0%}" if t else ""))
        tot_h = sum(agg[c][0] for c in CATS); tot_t = sum(agg[c][1] for c in CATS)
        print(f"  {'OVERALL':12}: {tot_h}/{tot_t}" + (f" = {tot_h/tot_t:.1%}" if tot_t else ""))
        print("  per-page:", [(p, k, f"{s[0]}/{s[1]}" if s else "-") for p, d, k, s in per_page])
        log["gt"] = {c: agg[c] for c in CATS}

    rec = score_reconcile(pages)
    print(f"\n== FULL RECONCILE ({a.split}) ==  bills={rec['bills']} chain_ok={rec['chain_ok']}/{rec['bills']}")
    for c, (pw, tt) in rec["checks"].items():
        print(f"  {c:12}: {pw}/{tt}" + (f" = {pw/tt:.0%}" if tt else " (untestable)"))
    log["reconcile"] = rec

    if a.all or a.split == "full":
        kinds = score_coverage(pages)
        print(f"\n== COVERAGE ({a.split}) ==  {sum(kinds.values())} pages: {kinds}")
        log["coverage"] = kinds

    lb = os.path.join(ROOT, "metrics", "leaderboard.jsonl")
    os.makedirs(os.path.dirname(lb), exist_ok=True)
    with open(lb, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(log) + "\n")
    print(f"\nlogged -> {lb}")

if __name__ == "__main__":
    main()
