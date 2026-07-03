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
try:
    from tess_check import recover_fppca as _tess_recover
except Exception:
    def _tess_recover(*a, **k):
        return False

ROOT = os.path.dirname(__file__)
GT_DIR = os.path.join(ROOT, "samples", "gt")
# category buckets ONLY decide reporting; the scored field set is derived per page
# from ALL keys present in the frozen GT (so nothing is silently excluded).
CONS_KEYS = {"cons_kwh","cons_kvah","cons_kva","cons_pf","cons_lf"}
DATE_KEYS = {"bill_month","bill_date","due_date"}
ID_KEYS = {"service_no","van_id","category","contracted_md"}

def _bucket(key):
    if key in CONS_KEYS: return "consumption"
    if key in DATE_KEYS: return "dates"
    if key in ID_KEYS: return "ids"
    if key == "amount_words_value": return "other"
    return "money"

def _num_eq(a, b, tol=0.01):
    try: return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError): return False

def _str_eq(a, b):
    n = lambda s: "".join(ch for ch in str(s).lower() if ch.isalnum())
    return n(a) == n(b)

def match(field, got, exp):
    if got is None: return False
    if field in DATE_KEYS or field in {"service_no","van_id","category"}:
        return _str_eq(got, exp)
    return _num_eq(got, exp)

def gt_pages():
    out = {}
    for f in glob.glob(os.path.join(GT_DIR, "p*.json")):
        o = json.load(open(f, encoding="utf-8"))
        out[o["page"]] = o
    return out

def _provenance_ok(fp):
    """A field counts as extracted ONLY if it is observed with real source boxes
    and is not flagged ambiguous. Enforces the no-imputation / provenance rule."""
    return bool(fp) and fp.get("observed") is True and fp.get("source_boxes") \
        and not fp.get("ambiguous")

def score_gt():
    """Field-exact vs frozen GT over ALL frozen fields (nothing hard-coded out).
    Provenance is REQUIRED: a value with observed!=True or no source boxes scores
    as a miss even if it matches."""
    gts = gt_pages()
    agg = {c: [0, 0] for c in ("money", "consumption", "dates", "ids", "other")}
    per_page = []
    for p in sorted(gts):
        gt = gts[p]
        boxes = ocr(p)
        kind = classify(boxes)
        if gt["doc_type"] != "ht_bill":
            per_page.append((p, gt["doc_type"], kind, None))
            continue
        fields, recs = parse(boxes)
        exp_all = {}
        for sec in ("money", "consumption", "dates", "ids"):
            exp_all.update(gt.get(sec, {}))
        if "amount_words_value" in gt:
            exp_all["amount_words_value"] = gt["amount_words_value"]
        hits = tot = 0
        for k, exp in exp_all.items():
            if exp is None:                      # GT explicitly has no value (e.g. cons_lf None)
                continue
            fp = fields.get(k)
            gv = fp.get("value") if _provenance_ok(fp) else None
            ok = match(k, gv, exp)
            c = _bucket(k)
            agg[c][0] += ok; agg[c][1] += 1
            hits += ok; tot += 1
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
        _tess_recover(fields, recs, boxes, p)   # gated Tesseract fppca recovery
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
        print("\n== FIELD-EXACT vs FROZEN GT (all frozen fields, provenance-enforced) ==")
        cats = [c for c in ("money", "consumption", "dates", "ids", "other") if agg[c][1]]
        for c in cats:
            h, t = agg[c]
            print(f"  {c:12}: {h}/{t}" + (f" = {h/t:.0%}" if t else ""))
        tot_h = sum(agg[c][0] for c in cats); tot_t = sum(agg[c][1] for c in cats)
        print(f"  {'OVERALL':12}: {tot_h}/{tot_t}" + (f" = {tot_h/tot_t:.1%}" if tot_t else ""))
        print("  per-page:", [(p, k, f"{s[0]}/{s[1]}" if s else "-") for p, d, k, s in per_page])
        log["gt"] = {c: agg[c] for c in cats}

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
