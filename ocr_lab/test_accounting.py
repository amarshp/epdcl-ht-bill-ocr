"""Unit tests for the accounting graph + parser, using cached OCR for the
codex-identified adjustment-heavy pages. Run: python -m pytest test_accounting.py -q

These lock in the Phase-0 invariants so the optimization loop can't silently
regress the money chain. Expected values come from the frozen vision GT.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import pytest

from common import ocr
from parse import parse
from reconcile import reconcile

GT = os.path.join(os.path.dirname(__file__), "samples", "gt")


def gt(p):
    return json.load(open(os.path.join(GT, f"p{p}.json"), encoding="utf-8"))


# Stable pages: invariants locked in (loop must never regress these).
# Frontier pages: known parser gaps (shear off-by-one on p48; drift + subtotal
# leak on p256) — the optimization loop's first target. xfail(strict) so the
# suite goes RED the moment they're fixed, prompting promotion to stable.
BILL_PAGES = [8, 16, 32, 48, 128, 160, 256]
FRONTIER = []


@pytest.mark.parametrize(
    "p",
    BILL_PAGES
    + [
        pytest.param(
            q, marks=pytest.mark.xfail(strict=True, reason="optimization frontier")
        )
        for q in FRONTIER
    ],
)
def test_observed_totals_match_gt(p):
    """Observed sub_total/total/net_bill/net_payable equal the frozen GT (paise)."""
    fields, _ = parse(ocr(p))
    m = gt(p)["money"]
    for k in ("sub_total", "total", "net_bill", "net_payable"):
        if k not in m:
            continue
        got = fields.get(k, {}).get("value")
        assert got is not None, f"p{p}: {k} not extracted"
        tol = 0.51 if k == "net_payable" else 0.02
        assert abs(got - m[k]) <= tol, f"p{p}: {k} got {got} exp {m[k]}"


@pytest.mark.parametrize(
    "p",
    BILL_PAGES
    + [
        pytest.param(
            q, marks=pytest.mark.xfail(strict=True, reason="optimization frontier")
        )
        for q in FRONTIER
    ],
)
def test_chain_reconciles(p):
    """Full accounting chain closes for pages whose arrears OCR cleanly.

    p160 current-year arrears is OCR-garbled -> net_payable legitimately fails;
    every other check must still pass (no false pass allowed either)."""
    fields, recs = parse(ocr(p))
    r = reconcile(fields, recs)
    for c in r["checks"]:
        if p == 160 and c["name"] == "net_payable":
            continue  # known OCR gap on arrears value
        assert c["status"] is not False, f"p{p}: {c['name']} FAILED {c}"


def test_signed_upper_sum_equals_subtotal():
    """Signed upper-charge records sum to the observed sub_total on the neg-FPPCA page."""
    fields, recs = parse(ocr(160))
    sub = round(sum(r["value"] for r in recs if r["section"] == "sub"), 2)
    assert abs(sub - gt(160)["money"]["sub_total"]) <= 0.02


def test_no_imputation_all_scored_are_observed():
    """Every extracted field carries observed=True + a source box (no derived values)."""
    fields, _ = parse(ocr(8))
    for k, v in fields.items():
        assert v.get("observed") is True, f"{k} not observed"
        assert v.get("source_boxes"), f"{k} has no source boxes"


def test_pooled_cost_is_negative_on_p32():
    """Label-driven sign: PooledCost Adj (-) subtracts even though value prints positive."""
    _, recs = parse(ocr(32))
    pc = [r for r in recs if r["field"] == "pooled_cost"]
    assert pc and pc[0]["value"] < 0
