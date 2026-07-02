"""NAIVE smoke-test metric — REPLACE in Phase 0 (see GOAL.md 0a + CODEX_REVIEW.md).

These 4 checks are a floor/diagnostic ONLY. Codex review proved they:
  - FALSE-FAIL correct bills with adjustments (arrears/grid-support/NetIcd/neg-FPPCA)
    e.g. p16 net_bill != net_payable due to arrears; p32 total omits grid support.
  - FALSE-PASS wrong bindings (commutative sums, duplicate 0.00 rows, same value
    bound to two fields with no provenance check).
Phase 0 must replace this with the FULL accounting graph (signed rows, coverage,
row-level rate*qty==amount, provenance, no-imputation). Do NOT optimize against
this naive version.

Current checks:
 1. charges_sum : demand+energy+duty+fppca+tod == sub_total
 2. total_calc  : sub_total + customer_charges == total
 3. net_round   : round(net_bill) == net_payable
 4. words_match : amount-in-words == net_payable
"""
from extract import to_float

def _close(a, b, tol=1.0):
    if a is None or b is None: return None   # can't test -> not a pass, not a fail
    return abs(a - b) <= tol

def reconcile(fields):
    f = {k: to_float(v) for k, v in fields.items()}
    checks = {}
    charges = [f.get(k) for k in ("demand_charges","energy_charges","elec_duty","fppca","tod_charges")]
    if all(c is not None for c in charges) and f.get("sub_total") is not None:
        checks["charges_sum"] = _close(sum(charges), f["sub_total"], 1.0)
    else:
        checks["charges_sum"] = None
    if f.get("sub_total") is not None and f.get("customer_charges") is not None and f.get("total") is not None:
        checks["total_calc"] = _close(f["sub_total"] + f["customer_charges"], f["total"], 1.0)
    else:
        checks["total_calc"] = None
    checks["net_round"] = _close(f.get("net_bill"), f.get("net_payable"), 1.0)
    checks["words_match"] = _close(f.get("net_payable_words"), f.get("net_payable"), 0.5)
    passed = sum(1 for v in checks.values() if v is True)
    testable = sum(1 for v in checks.values() if v is not None)
    return {
        "checks": checks,
        "passed": passed,
        "testable": testable,
        "score": passed / len(checks),          # of 4
        "page_ok": passed >= 3 and checks.get("words_match") is not False,
    }
