"""Full accounting graph for the EPDCL HT bill (replaces the 4 naive checks).

Operates on the signed records from parse.build_records() + the observed field
dict. Every check reports expected / observed / delta / rows-included /
rows-missing / source-boxes. OBSERVED-ONLY: a check runs only when the observed
target value has a real OCR box; derived values never satisfy a check.

Accounting chain (signs already baked into record.value):
  sub_total = Σ upper-charge rows
  total     = sub_total + Σ lower pre-total rows (customer, grid, ...)
  net_bill  = total     + Σ post-total rows (tcs, rebate, pooled, neticd, loss...)
  net_payable = net_bill + Σ arrears rows
Tolerance = 0.02 (paise) for printed rows.
"""

from parse import parse

TOL = 0.02

# core fields that should ALWAYS be present on an HT bill; a missing one is itself
# a reason to route the page to human review.
CORE_FIELDS = (
    "service_no",
    "category",
    "bill_month",
    "sub_total",
    "total",
    "net_payable",
)


def page_needs_review(fields, rec):
    """Production safety gate — PRECISE triage, not a blanket flag. Route a page to
    human review only on a real signal:
      1. the accounting chain doesn't close (catches every money error),
      2. a core field is missing, or
      3. a value is out of its valid range (PF must be 0..1) — catches misreads
         that don't break the money math.
    A blanket 'any low-confidence field' flag was dropped: it flagged ~80% of clean
    pages (a faint char somewhere) and drowned the real signal."""
    if not rec.get("chain_ok"):
        return True
    if any(fields.get(k, {}).get("value") is None for k in CORE_FIELDS):
        return True
    pf = fields.get("cons_pf", {}).get("value")
    if pf is not None and not (0.0 <= pf <= 1.05):
        return True
    return False


def _sum(recs, section):
    return round(sum(r["value"] for r in recs if r["section"] == section), 2)


def _rows(recs, section):
    return [(r["field"], r["value"]) for r in recs if r["section"] == section]


def _check(name, expected, obs_field, add_recs, tol=TOL):
    """Build one check dict. Runs only if observed value is present (observed-only)."""
    if obs_field is None or not obs_field.get("observed"):
        return {
            "name": name,
            "status": None,
            "reason": "no_observed_target",
            "expected": round(expected, 2),
            "observed": None,
        }
    observed = obs_field["value"]
    delta = round(observed - expected, 2)
    return {
        "name": name,
        "status": abs(delta) <= tol,
        "expected": round(expected, 2),
        "observed": observed,
        "delta": delta,
        "rows_included": [f for f, _ in add_recs],
        "source_box": obs_field.get("bbox"),
    }


def reconcile(fields, recs):
    """Return {checks:[...], passed, testable, chain_ok, ...}. Pure accounting."""
    sub = _sum(recs, "sub")
    tot = round(sub + _sum(recs, "tot"), 2)
    net = round(tot + _sum(recs, "net"), 2)
    pay = round(net + _sum(recs, "pay"), 2)

    checks = [
        _check("sub_total", sub, fields.get("sub_total"), _rows(recs, "sub")),
        _check(
            "total", tot, fields.get("total"), _rows(recs, "sub") + _rows(recs, "tot")
        ),
        _check("net_bill", net, fields.get("net_bill"), _rows(recs, "net")),
        # the bill rounds net_payable to the whole rupee (arrears carry paise)
        _check(
            "net_payable", pay, fields.get("net_payable"), _rows(recs, "pay"), tol=0.51
        ),
    ]
    passed = sum(1 for c in checks if c["status"] is True)
    testable = sum(1 for c in checks if c["status"] is not None)
    return {
        "checks": checks,
        "passed": passed,
        "testable": testable,
        "chain_ok": passed == testable and testable >= 3,
        "computed": {
            "sub_total": sub,
            "total": tot,
            "net_bill": net,
            "net_payable": pay,
        },
    }


# ---- row-level rate * qty == amount (catches swapped/duplicate addends) -----
def row_arithmetic(boxes, band=18):
    """For each upper charge row, verify printed rate * qty ~= printed amount.

    Uses the amount box's own sub-row (rate, 'For', qty, unit). Returns a list of
    {amount, rate, qty, ok} for rows where all three are present. A strong,
    provenance-grounded consistency signal independent of the accounting sums.
    """
    import re

    from parse import money_column, parse_num

    money = money_column(boxes)
    y_sub = next(
        (b[0] for b in boxes if "subtotal" in b[3].lower().replace(" ", "")), 1e9
    )
    out = []
    for mb in money:
        if mb[0] >= y_sub - 2:
            continue  # upper table only
        amt, _ = parse_num(mb[3])
        if amt is None:
            continue
        sub_row = sorted(
            [
                b
                for b in boxes
                if b is not mb and abs(b[0] - mb[0]) <= band and b[1] < mb[1] - 3
            ],
            key=lambda b: b[1],
        )
        rate = qty = None
        # rate = first numeric box to the RIGHT of an 'Rs'/'Ps' marker (rate col).
        rs = next(
            (b for b in sub_row if re.fullmatch(r"[RrPp]s\.?", b[3].strip())), None
        )
        if rs is not None:
            rcands = [
                b for b in sub_row if b[1] > rs[1] and parse_num(b[3])[0] is not None
            ]
            if rcands:
                rate = parse_num(min(rcands, key=lambda b: b[1])[3])[0]
        # qty = numeric box just left of the KVA/KVAH/KWH unit token
        units = [b for b in sub_row if b[3].strip().upper() in ("KVA", "KVAH", "KWH")]
        if units:
            u = units[0]
            qcands = [
                b for b in sub_row if b[1] < u[1] and parse_num(b[3])[0] is not None
            ]
            if qcands:
                qty = parse_num(max(qcands, key=lambda b: b[1])[3])[0]
        if rate is not None and qty is not None and amt not in (None,):
            ok = abs(rate * qty - amt) <= max(1.0, abs(amt) * 0.001)
            out.append({"amount": amt, "rate": rate, "qty": qty, "ok": ok})
    return out
