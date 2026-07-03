"""FLAG-RECALL: the production-safety metric. Over all 21 held-out pages, of the
values that are WRONG, how many land on a page we FLAG for review? A wrong value
on an UN-flagged page is a 'silent error' — the dangerous case. Goal: 0 silent
money errors (a human eyeballs every flagged page)."""

import contextlib
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from common import ocr
from eval import _bucket, _provenance_ok, match
from parse import parse
from reconcile import page_needs_review, reconcile

try:
    from tess_check import recover_fppca as _tess
except Exception:

    def _tess(*a, **k):
        return False


from bigger_exam import GT as GT1
from next_batch import GT as GT2

GT = {**GT1, **GT2}
print("\n" + "=" * 60)


def is_money(k):
    return _bucket(k) == "money"


wrong_total = flagged = silent = 0
silent_money = 0
page_needs = 0
lines = []
for p in sorted(GT):
    gt = GT[p]
    boxes = ocr(p)
    fields, recs = parse(boxes)
    _tess(fields, recs, boxes, p)
    r = reconcile(fields, recs)
    low = [k for k, v in fields.items() if v.get("low_confidence")]
    needs_review = page_needs_review(fields, r)
    page_needs += needs_review
    exp = {}
    for sec in ("money", "consumption", "dates", "ids"):
        exp.update(gt.get(sec, {}))
    exp["amount_words_value"] = gt["amount_words_value"]
    wrong = []
    for k, e in exp.items():
        if e is None:
            continue
        fp = fields.get(k)
        gv = fp.get("value") if _provenance_ok(fp) else None
        if not match(k, gv, e):
            wrong.append(k)
    for k in wrong:
        wrong_total += 1
        if needs_review:
            flagged += 1
        else:
            silent += 1
            if is_money(k):
                silent_money += 1
    if wrong:
        lines.append(
            f"  p{p}: wrong={wrong}  needs_review={needs_review} "
            f"(chain_ok={r['chain_ok']}, low_conf={low})"
        )

print(f"Held-out pages: {len(GT)}   flagged for review: {page_needs}/{len(GT)}")
print(f"\nWrong field values: {wrong_total}")
print(f"  on a FLAGGED page (caught): {flagged}")
print(f"  on an UN-flagged page (SILENT): {silent}   of which money: {silent_money}")
rec = flagged / wrong_total if wrong_total else 1.0
print(f"\nFLAG-RECALL (wrong values that get flagged): {rec:.0%}")
print(f"SILENT MONEY ERRORS: {silent_money}  <-- the number that must be 0\n")
for l in lines:
    print(l)
