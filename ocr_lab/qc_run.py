"""Tier-2 end-to-end: run Gemini QC on every FLAGGED bill page, validate its read
against the accounting, and report the final human-review queue + Gemini cost.

Usage: python qc_run.py [max_pages]   (default: all flagged bill pages)
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from common import classify, ocr, page_image
from parse import parse
from qc_gemini import cost, gemini_chain_ok, qc_page
from reconcile import page_needs_review, reconcile

try:
    from tess_check import recover_fppca as _tess
except Exception:

    def _tess(*a, **k):
        return False


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    flagged = []
    for p in range(1, 263):
        b = ocr(p)
        if classify(b) not in ("HT_BILL", "BILL?"):
            continue
        f, r = parse(b)
        _tess(f, r, b, p)
        if page_needs_review(f, reconcile(f, r)):
            flagged.append(p)
    flagged = flagged[:limit]
    print(f"Flagged bill pages to QC with Gemini: {len(flagged)}\n")

    resolved = human = 0
    t0 = time.time()
    for i, p in enumerate(flagged, 1):
        g = qc_page(p, page_image(p))
        ok = gemini_chain_ok(g)
        if ok:
            resolved += 1
        else:
            human += 1
        if i % 10 == 0 or i == len(flagged):
            usd, u = cost()
            print(
                f"  [{i}/{len(flagged)}] resolved={resolved} human={human} "
                f"| ${usd:.4f} so far ({time.time()-t0:.0f}s)"
            )

    usd, u = cost()
    print(f"\n=== TIER-2 RESULT ===")
    print(f"  flagged pages QC'd:      {len(flagged)}")
    print(f"  Gemini-resolved (numbers self-consistent): {resolved}")
    print(f"  still need a human:      {human}")
    print(f"\n=== GEMINI COST ===")
    print(f"  calls:        {u['calls']}")
    print(f"  input tokens: {u['in_tokens']:,}  |  output tokens: {u['out_tokens']:,}")
    print(f"  total cost:   ${usd:.4f}   (= ${usd/max(len(flagged),1):.5f}/page)")
    print(f"  monthly est.  ${usd:.4f} for this batch of {len(flagged)} flagged pages")


if __name__ == "__main__":
    main()
