"""Alternate template class: the SPARSE bill layout (e.g. p262).

Different from the dominant HT template — a compact summary where each charge is
'<label>  ... <rightmost amount>'. Deterministic, local, provenance-carrying.
Kept as a SEPARATE path so it never perturbs the HT champion.
"""

import re

from common import norm
from parse import parse_num, rows

# label keyword -> canonical field (sparse layout has fewer rows)
SPARSE_LABELS = [
    ("demand_normal", ["demandchargesnormal", "demandnormal"]),
    ("energy_charges", ["energycharges"]),
    ("excess_energy", ["excessenergy"]),
    ("elec_duty", ["electricityduty", "electricduty"]),
    ("fppca", ["fppca"]),
    ("tod_charges", ["todcharges"]),
    ("customer_charges", ["customercharges"]),
    ("net_bill", ["netbillamount", "netbill"]),
    ("net_payable", ["netpayable"]),
]


def is_sparse(boxes):
    """Signature: compact page with the 'Electricity Bill Service No' header and
    no dominant far-right money column full of HT rows."""
    blob = norm(" ".join(b[3] for b in boxes))
    return (
        "electricitybillservice" in blob or "electricitybillserviceno" in blob
    ) and "subtotal" not in blob


def _prov(b, field, rule):
    v, _ = parse_num(b[3])
    return {
        "value": v,
        "raw_text": b[3],
        "bbox": [b[0], b[1], b[2]],
        "source_boxes": [list(b)],
        "confidence": None,
        "rule": rule,
        "observed": True,
        "candidates": [],
    }


def sparse_parse(boxes):
    """field -> provenance dict for the sparse layout. Rightmost number on the
    label's row is the amount."""
    out = {}
    for row in rows(boxes, band=18):
        row = sorted(row, key=lambda b: b[1])
        label = norm(
            "".join(b[3] for b in row if parse_num(b[3])[0] is None or b[1] < 700)
        )
        # numeric boxes on the row, rightmost = amount
        nums = [b for b in row if parse_num(b[3])[0] is not None]
        if not nums:
            continue
        amt = max(nums, key=lambda b: b[2])
        for field, keys in SPARSE_LABELS:
            if field in out:
                continue
            if any(k in label for k in keys):
                out[field] = _prov(amt, field, f"sparse:{field}")
                break
    # ids / month from the header line
    hdr = next((b for b in boxes if "serviceno" in norm(b[3])), None)
    if hdr:
        m = re.search(r"(VSP-?\d+)", hdr[3], re.I)
        if m:
            out["service_no"] = {
                "value": m.group(1),
                "raw_text": hdr[3],
                "bbox": [hdr[0], hdr[1], hdr[2]],
                "source_boxes": [list(hdr)],
                "confidence": None,
                "rule": "sparse:service_no",
                "observed": True,
                "candidates": [],
            }
        mm = re.search(r"([A-Za-z]{3,9})-?(\d{4})", hdr[3])
        if mm:
            out["bill_month_text"] = {
                "value": mm.group(0),
                "raw_text": hdr[3],
                "bbox": [hdr[0], hdr[1], hdr[2]],
                "source_boxes": [list(hdr)],
                "confidence": None,
                "rule": "sparse:month",
                "observed": True,
                "candidates": [],
            }
    return out
