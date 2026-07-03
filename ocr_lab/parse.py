"""Provenance-carrying table parser for the EPDCL HT-bill template.

Deterministic. Local. No LLM / cloud at runtime.
Input: cached OCR boxes [ycenter, xmin, xmax, text].
Output: records (label->signed amount w/ source box) + a field dict where each
value is {value, raw_text, bbox, source_boxes, confidence, rule, observed, candidates}.

Design (from CODEX_REVIEW.md P1):
 - detect the far-right MONEY COLUMN (rightmost numeric cluster), scale-robust.
 - group boxes into rows by y-band; bind each money box to its row label.
 - classify label -> canonical field via drift-tolerant keyword catalog.
 - sign rule: if the printed value already carries a minus, trust it; else apply
   the label's semantic sign (rebate/subsidy/incentive/(-) rows subtract).
 - NO IMPUTATION: every field value comes from a real OCR money box.
"""

import re

from common import norm

# ---- numeric parsing -------------------------------------------------------
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def parse_num(text):
    """Return (float, raw_token) of the LAST number in text, or (None, None)."""
    toks = _NUM.findall(text.replace(" ", ""))
    toks = [t for t in toks if re.search(r"\d", t)]
    if not toks:
        return None, None
    raw = toks[-1]
    try:
        return float(raw.replace(",", "")), raw
    except ValueError:
        return None, None


def _nonnum_prefix(text):
    """Leading non-numeric label glued into a money box, e.g. 'Total 317001.06'->'total'."""
    m = re.match(r"[^0-9\-]+", text)
    return norm(m.group(0)) if m else ""


# ---- row grouping ----------------------------------------------------------
def rows(boxes, band=16):
    """Group boxes into visual rows by y-center proximity. band is scale-tolerant."""
    bs = sorted(boxes, key=lambda b: (b[0], b[1]))
    out, cur, y0 = [], [], None
    for b in bs:
        if y0 is None or abs(b[0] - y0) <= band:
            cur.append(b)
            y0 = b[0] if y0 is None else (y0 + b[0]) / 2
        else:
            out.append(cur)
            cur = [b]
            y0 = b[0]
    if cur:
        out.append(cur)
    return out


# ---- money column detection ------------------------------------------------
# an amount box VALUE ends with its number (allow trailing ')' or spaces).
# This rejects full-width prose (NOTE line), label-only rows ('25%Rebate...'),
# and split labels ('NetIcdAmt...(0.00-') that merely contain a digit.
_ENDS_NUM = re.compile(
    r"-?\d[\d,]*\.?\d*\)?[A-Za-z]{0,2}\s*$"
)  # allow trailing OCR noise ('364356.50M')
# date/label boxes that merely end in a year ('...01-Apr-2024') are NOT amounts
_DATE_LABEL = re.compile(r"arrears|before|after|dated|\d{1,2}-[A-Za-z]{3}-\d", re.I)


def money_column(boxes, frac=0.90, max_w_frac=0.40):
    """Rightmost right-aligned amount column. Returns money_boxes.

    money box := numeric, right-aligned (xmax >= frac*page_right), value-terminal
    (ends with the number), and not a full-width text line (width < max_w_frac).
    Scale-robust: uses the page's own right edge, not a hardcoded pixel.
    """
    if not boxes:
        return []
    max_x = max(b[2] for b in boxes)
    money = []
    for b in boxes:
        v, _ = parse_num(b[3])
        if v is None:
            continue
        if b[2] < frac * max_x:
            continue
        if (b[2] - b[1]) >= max_w_frac * max_x:
            continue
        if not _ENDS_NUM.search(b[3]):
            continue
        if _DATE_LABEL.search(
            b[3]
        ):  # arrears/date label ending in a year, not an amount
            continue
        money.append(b)
    return money


# ---- label catalog ---------------------------------------------------------
# (canonical_field, section, sign, [keyword aliases]).  First match wins, so
# order more-specific labels before generic ones.  Keywords are normalized
# (lowercase, alnum+% only) and matched as substrings against the row label.
CATALOG = [
    # --- upper charge table -> sub_total (all +, tod_incentive -) ---
    ("demand_penal", "sub", +1, ["demandchargespenal", "demandpenal"]),
    ("demand_normal", "sub", +1, ["demandchargesnormal", "demandnormal"]),
    ("excess_energy", "sub", +1, ["excessenergycharges"]),
    ("energy_charges", "sub", +1, ["energychargesrate"]),
    ("elec_duty", "sub", +1, ["electricityduty"]),
    ("fuel_surcharge", "sub", +1, ["fuelsurchargeadjustment"]),
    ("trueup", "sub", +1, ["trueupcharge"]),
    ("fppca", "sub", +1, ["fppcacharge", "fppca"]),
    ("tod_incentive", "sub", -1, ["todincentive"]),
    ("tod_charges", "sub", +1, ["todcharges"]),
    # --- lower pre-total panel -> total ---
    ("customer_charges", "tot", +1, ["customercharges"]),
    ("grid_support", "tot", +1, ["gridsupport"]),
    ("wheeling", "tot", +1, ["wheelingcharges"]),
    ("transmission", "tot", +1, ["transmissioncharges"]),
    ("rkvah_hydel", "tot", +1, ["rkvahsurchargehydel", "surchargehydel"]),
    ("rkvah_wind", "tot", +1, ["rkvahsurchargewind", "surchargewind"]),
    ("open_access", "tot", +1, ["openaccess"]),
    ("acd_surcharge", "tot", +1, ["acdsurcharge"]),
    ("late_payment", "tot", +1, ["latepayment"]),
    ("interest_ed", "tot", +1, ["interestoned"]),
    ("penal_interest", "tot", +1, ["penalinterest"]),
    ("transformer_hire", "tot", +1, ["transformerhire"]),
    ("diff_voltage", "tot", +1, ["differencevoltage"]),
    ("load_factor_inc", "tot", -1, ["loadfactorincentive"]),
    # --- post-total -> net_bill ---
    ("tcssf", "net", +1, ["tcssf", "tcss"]),
    ("tcs", "net", +1, ["tcs"]),
    ("rebate", "net", -1, ["rebateapplication", "rebate"]),
    ("ferro_subsidy", "net", -1, ["ferrosubsidy"]),
    ("pooled_cost", "net", -1, ["pooledcost"]),
    ("neticd", "net", -1, ["neticd"]),
    ("other_credit", "net", +1, ["othercredit"]),
    ("export_amount", "net", -1, ["exportamount", "export"]),
    ("loss_gain", "net", +1, ["lossorgain", "lossgain"]),
    # --- arrears -> net_payable ---
    ("arrears_prev", "pay", +1, ["arrearsbefore", "previousyears"]),
    ("arrears_curr", "pay", +1, ["arrearsafter", "currentyears"]),
    # --- totals themselves (observed printed values) ---
    ("sub_total", "val", +1, ["subtotal"]),
    ("net_bill", "val", +1, ["netbillamount", "netbill"]),
    ("net_payable", "val", +1, ["netpayable"]),
    ("total", "val", +1, ["total"]),  # generic 'total' LAST
]

# 'Net Bill Amount' OCR typos: 'Net Bll'(i->l), 'Nct Bill'(e->c) -> n.t b .. am..t
_NETBILL_FUZZY = re.compile(r"n.tb\w{0,4}am\w{0,3}t")


def classify(label):
    n = norm(label)
    if not n:
        return None
    for field, section, sign, keys in CATALOG:
        for k in keys:
            if k in n:
                return field, section, sign
    if _NETBILL_FUZZY.search(n):
        return "net_bill", "val", +1
    return None


# ---- record building -------------------------------------------------------
def signed_value(value, raw_token, sign):
    """Combine OCR sign + label sign without double-negating."""
    if raw_token is not None and raw_token.strip().startswith("-"):
        return value  # OCR already signed -> trust it
    return sign * value


def _row_label(boxes, mb, band):
    """Label text on the NEAREST line to the left of amount box mb.

    Picks the closest label box by |Δy| (not every box in the band), then joins
    only boxes on that same visual line. Prevents a neighbouring line (arrears,
    time-block) from bleeding into a total's classification.
    """
    cands = [
        b
        for b in boxes
        if b is not mb and b[1] < mb[1] - 3 and abs(b[0] - mb[0]) <= band
    ]
    if not cands:
        return _nonnum_prefix(mb[3]), []
    y_star = min(cands, key=lambda b: abs(b[0] - mb[0]))[0]
    line = sorted([b for b in cands if abs(b[0] - y_star) <= 7], key=lambda b: b[1])
    text = "".join(b[3] for b in line) + " " + _nonnum_prefix(mb[3])
    return text, line


def _nearest_classifiable(boxes, mb, band):
    """Return (hit, label_text, left) for the nearest label LINE (to the left of mb,
    within band) that classifies. Falls back to the plain nearest line if none
    classifies, preserving prior behaviour."""
    cands = [
        b
        for b in boxes
        if b is not mb and b[1] < mb[1] - 3 and abs(b[0] - mb[0]) <= band
    ]
    if not cands:
        return None, _nonnum_prefix(mb[3]), []
    fallback = None
    for c in sorted(cands, key=lambda b: abs(b[0] - mb[0])):
        line = sorted([b for b in cands if abs(b[0] - c[0]) <= 7], key=lambda b: b[1])
        text = "".join(b[3] for b in line) + " " + _nonnum_prefix(mb[3])
        if fallback is None:
            fallback = (text, line)
        h = classify(text)
        if h is not None:
            return h, text, line
    return None, fallback[0], fallback[1]


def _rec(field, section, sign, mb, label_text, left, rule):
    v, raw = parse_num(mb[3])
    if v is None:
        return None
    return {
        "field": field,
        "section": section,
        "value": signed_value(v, raw, sign),
        "raw_text": mb[3],
        "amount_bbox": [mb[0], mb[1], mb[2]],
        "label_text": label_text.strip(),
        "source_boxes": [[b[0], b[1], b[2], b[3]] for b in left] + [list(mb)],
        "rule": rule,
    }


# canonical normalized labels for the 10 upper charge rows (template order)
_SUB_CANON = [
    ("demand_normal", +1, "demandchargesnormalrate"),
    ("demand_penal", +1, "demandchargespenalrate"),
    ("energy_charges", +1, "energychargesrateallunits"),
    ("excess_energy", +1, "excessenergychargesrate"),
    ("elec_duty", +1, "electricitydutycharges"),
    ("fuel_surcharge", +1, "fuelsurchargeadjustment"),
    ("trueup", +1, "trueupcharge"),
    ("fppca", +1, "fppcacharge"),
    ("tod_charges", +1, "todcharges"),
    ("tod_incentive", -1, "todincentive"),
]
# non-charge rows that resemble charge labels -> must NOT fuzzy-match to one
_SUB_DECOYS = [
    "colonychargesrates",
    "landfchargesrate",
    "lfchargesrate",
    "energychargesincludefuelcostadj",
    "supplyername",
    "maincomsumption",
    "monthlyminconsumption",
    "totalconsumption",
]


def _sub_fuzzy(text):
    """OCR-noise-tolerant charge-label match ('Dcmand','Exccss'). Rejects decoys."""
    from difflib import SequenceMatcher

    n = norm(text)
    if len(n) < 6:
        return None

    def r(a, b):
        return SequenceMatcher(None, a[: len(b) + 4], b).ratio()

    field, sign, canon = max(_SUB_CANON, key=lambda c: r(n, c[2]))
    best = r(n, canon)
    if best < 0.84:
        return None
    if any(r(n, d) >= best for d in _SUB_DECOYS):
        return None
    return field, sign


def _upper_labels(boxes, y_lo, y_hi, fuzzy=False):
    """Charge labels (section 'sub') between y_lo and y_hi, sorted top->down.
    fuzzy=True adds OCR-noise-tolerant matches for boxes exact matching missed."""
    max_x = max(x[2] for x in boxes)
    out, seen = [], set()
    for b in boxes:
        if not (y_lo <= b[0] < y_hi) or b[2] >= 0.85 * max_x:
            continue
        hit = classify(_nonnum_prefix(b[3]) or norm(b[3]))
        if hit and hit[1] == "sub":
            out.append((b[0], hit[0], hit[2], b))
            seen.add(hit[0])
    if fuzzy:
        for b in boxes:
            if not (y_lo <= b[0] < y_hi) or b[2] >= 0.85 * max_x:
                continue
            fh = _sub_fuzzy(b[3])
            if fh and fh[0] not in seen:
                out.append((b[0], fh[0], fh[1], b))
                seen.add(fh[0])
    out.sort(key=lambda t: t[0])
    return out


def _assign(amounts, labels, delta):
    """Greedy monotonic assignment of amounts->labels given vertical offset delta.
    Returns (pairs, residual). Each label used at most once (strictly increasing)."""
    pairs, residual, li = [], 0.0, 0
    for ay, mb in amounts:
        target = ay - delta
        if li >= len(labels):  # exhausted: reuse last label, penalize
            pairs.append((mb, labels[-1]))
            residual += 100.0
            continue
        best = None
        for j in range(li, len(labels)):
            d = abs(labels[j][0] - target)
            if best is None or d < best[0]:
                best = (d, j)
            if (
                labels[j][0] > target
                and best is not None
                and labels[j][0] - target > best[0]
            ):
                break
        pairs.append((mb, labels[best[1]]))
        residual += best[0]
        li = best[1] + 1
    return pairs, residual


def bind_upper(boxes, upper_amounts, y_lo, y_hi):
    """Bind the upper charge table amounts to their labels.

    The charge rows always appear in a FIXED template order, top-to-bottom. When
    the amount count equals the label count, rank alignment (i-th amount <-> i-th
    label) is exact and shear-proof — it beats visual y-matching, which the
    per-page vertical shear otherwise fools (e.g. p256 FPPCA value sits at the
    True-up row's y). If counts differ (dropped/extra OCR box), fall back to a
    grid-searched vertical-offset greedy match.
    """
    labels = _upper_labels(boxes, y_lo, y_hi)
    amounts = sorted(upper_amounts, key=lambda t: t[0])
    # GATED fuzzy recovery: only when exact labels are FEWER than amounts (OCR
    # dropped a charge label). Never runs when exact already count-matches, so the
    # proven dev path is untouched.
    if len(labels) < len(amounts):
        fl = _upper_labels(boxes, y_lo, y_hi, fuzzy=True)
        if len(labels) < len(fl) <= len(amounts):
            labels = fl
    if not labels or not upper_amounts:
        return []
    if len(amounts) == len(labels):
        pairs = [(mb, lab) for (_, mb), lab in zip(amounts, labels)]
        rule_tag = "rank"
    else:
        best = None
        for d10 in range(-300, 501, 10):  # delta in [-30, 50]
            delta = d10 / 10.0
            pr, res = _assign(amounts, labels, delta)
            score = res + abs(delta) * 0.01
            if best is None or score < best[0]:
                best = (score, delta, pr)
        _, delta, pairs = best
        pairs = [(mb, lab) for mb, lab in pairs]
        rule_tag = f"shear:d={delta:.0f}"
    recs = []
    for mb, lab in pairs:
        _, field, sign, lbox = lab
        r = _rec(field, "sub", sign, mb, lbox[3], [lbox], f"upper_{rule_tag}:{field}")
        if r:
            recs.append(r)
    return recs


def build_records(boxes, band=16):
    """Bind each money-column box to its label -> list of records.

    Upper charge table (above Sub Total) uses shear-tolerant order matching;
    the lower panel + totals use tight same-row binding.
    """
    money = money_column(boxes)
    if not money:
        return []
    # locate Sub Total to split upper table from lower panel
    y_sub = None
    for b in boxes:
        if "subtotal" in norm(b[3]):
            y_sub = b[0]
            break
    if y_sub is None:
        y_sub = max(b[0] for b in money)  # degrade: treat all as lower
    # top of charge table = Demand Charges Normal Rate label. Wide margin: the
    # demand amount can sit ~30px ABOVE its label under negative shear (p48/p256).
    y_lo = (
        min((b[0] for b in boxes if "demandchargesnormal" in norm(b[3])), default=0)
        - 40
    )
    # margin keeps the Sub Total value box (same row as its label) out of the
    # upper table, where it would otherwise be mis-bound as a charge amount.
    upper = [(mb[0], mb) for mb in money if y_lo < mb[0] < y_sub - 12]
    lower = [mb for mb in money if mb[0] >= y_sub - 12]

    recs = []
    recs += bind_upper(boxes, upper, y_lo, y_sub)
    for mb in lower:
        # a glued box ('Total 317001.06') classifies by its OWN prefix first, so a
        # neighbouring label (e.g. arrears line) can't bleed in and mis-bind it.
        prefix = _nonnum_prefix(mb[3])
        hit = classify(prefix) if len(prefix) >= 3 else None
        if hit is not None:
            label_text, left, rule = prefix, [], f"glued:{hit[0]}"
        else:
            # nearest label LINE THAT CLASSIFIES (skip a numeric detail line that
            # sits between the value and its real label, e.g. NetIcd on 2026 bills)
            hit, label_text, left = _nearest_classifiable(boxes, mb, band)
            rule = f"row:{hit[0]}" if hit else ""
        if hit is None:
            continue
        field, section, sign = hit
        r = _rec(field, section, sign, mb, label_text, left, rule)
        if r:
            recs.append(r)
    recs = _fix_arrears(recs, lower, boxes)
    recs = _recover_fppca_swap(recs, boxes)
    return recs


def _recover_fppca_swap(recs, boxes):
    """FPPCA amount MUST equal its printed component sum. If it doesn't but another
    upper-charge record DOES hold that value, the two boxes were swapped by the
    row-offset — swap them back. Uses the component sum only as an ARBITER to pick
    the right OBSERVED box (no imputation: values stay real OCR boxes)."""
    comp, _ = fppca_components(boxes)
    if comp is None:
        return recs
    fr = next((r for r in recs if r["field"] == "fppca"), None)
    if fr is None or abs(fr["value"] - comp) <= 0.02:
        return recs
    r2 = next(
        (
            r
            for r in recs
            if r["section"] == "sub" and r is not fr and abs(r["value"] - comp) <= 0.02
        ),
        None,
    )
    if r2 is None:
        return recs  # true box misread -> Tesseract layer handles it
    for k in ("value", "raw_text", "amount_bbox", "source_boxes"):
        fr[k], r2[k] = r2[k], fr[k]
    fr["rule"] = "fppca_swap_corrected"
    r2["rule"] = r2["rule"] + "|swapped"
    return recs


def _fix_arrears(recs, lower_money, all_boxes):
    """Re-bind arrears by geometry: the prev/current arrears value boxes are the
    money boxes strictly BETWEEN the Net Bill and Net Payable value rows, top->down
    (prev then current). Robust to the offset that mis-binds them to labels."""
    nb = next((r for r in recs if r["field"] == "net_bill"), None)
    npay = next((r for r in recs if r["field"] == "net_payable"), None)
    if not nb or not npay:
        return recs
    y_nb, y_np = nb["amount_bbox"][0], npay["amount_bbox"][0]
    lo, hi = min(y_nb, y_np), max(y_nb, y_np)
    between = sorted(
        [mb for mb in lower_money if lo + 2 < mb[0] < hi - 2], key=lambda b: b[0]
    )
    if not between:
        return recs
    recs = [r for r in recs if r["field"] not in ("arrears_prev", "arrears_curr")]
    if len(between) >= 2:
        picks = between
    elif between:
        v0 = parse_num(between[0][3])[0]
        picks = (
            [between[0], None]
            if (v0 is not None and abs(v0) < 0.005)
            else [None, between[0]]
        )
    else:
        picks = [None, None]
    for fld, mb in zip(["arrears_prev", "arrears_curr"], picks[:2]):
        if mb is not None:
            v, raw = parse_num(mb[3])
            if v is not None:
                recs.append(
                    {
                        "field": fld,
                        "section": "pay",
                        "value": signed_value(v, raw, 1),
                        "raw_text": mb[3],
                        "amount_bbox": [mb[0], mb[1], mb[2]],
                        "label_text": fld,
                        "source_boxes": [list(mb)],
                        "rule": f"arrears_geom:{fld}",
                    }
                )
    recs = _arrears_from_labels(recs, all_boxes)
    return recs


_DATE_STRIP = re.compile(r"\d{1,2}-[A-Za-z]{3}-\d{4}")


def _arrears_from_labels(recs, all_boxes):
    """Some bills glue the arrears amount into its label box
    ('(CurrentYears)Arrears after01-Apr-2023 201909.00'). If a slot is still empty,
    strip the date and read the trailing amount from the label box itself."""
    if all_boxes is None:
        return recs
    have = {r["field"] for r in recs}
    for fld, key in (
        ("arrears_prev", "arrearsbefore"),
        ("arrears_curr", "arrearsafter"),
    ):
        if fld in have:
            continue
        for b in all_boxes:
            if key in norm(b[3]):
                rest = _DATE_STRIP.sub("", b[3])
                v, raw = parse_num(rest)
                if v is not None and abs(v) > 4:  # skip stray year fragments
                    recs.append(
                        {
                            "field": fld,
                            "section": "pay",
                            "value": signed_value(v, raw, 1),
                            "raw_text": b[3],
                            "amount_bbox": [b[0], b[1], b[2]],
                            "label_text": fld,
                            "source_boxes": [list(b)],
                            "rule": f"arrears_label:{fld}",
                        }
                    )
                break
    return recs


# ---- field dict with provenance -------------------------------------------
def _prov(rec, rule=None):
    return {
        "value": rec["value"],
        "raw_text": rec["raw_text"],
        "bbox": rec["amount_bbox"],
        "source_boxes": rec["source_boxes"],
        "confidence": None,  # base cache has no conf (noted; v2 cache TODO)
        "rule": rule or rec["rule"],
        "observed": True,
        "candidates": [],
    }


def fields_from_records(recs):
    """Collapse records to a field dict, flagging ambiguity (multiple money boxes
    classify to the same field) as candidates -> caller may FAIL that field."""
    by_field = {}
    for r in recs:
        by_field.setdefault(r["field"], []).append(r)
    out = {}
    for field, rs in by_field.items():
        if len(rs) == 1:
            out[field] = _prov(rs[0])
        else:
            # ambiguous: keep the first but attach all candidates + mark it
            p = _prov(rs[0])
            p["candidates"] = [
                {
                    "value": r["value"],
                    "bbox": r["amount_bbox"],
                    "label": r["label_text"],
                }
                for r in rs
            ]
            p["ambiguous"] = True
            out[field] = p
    return out


# ---- non-money fields (dates / ids / consumption) --------------------------
def _canon_category(s):
    """Canonicalize a category code: uppercase the class, roman-ize the paren index
    (OCR reads i/ii/iii as 1/11/111). 'IIA(1)'->'IIA(i)', 'IIIA'->'IIIA', 'IB'->'IB'."""
    s = s.strip().replace(" ", "")
    m = re.match(r"^(I{1,3}[ABC]?)(\((.*)\))?$", s, re.I)
    if not m:
        return s
    base = m.group(1).upper()
    inner = m.group(3)
    if inner is None:
        return base
    return f"{base}({inner.lower().replace('1', 'i')})"


def _find(boxes, pat, flags=0):
    rx = re.compile(pat, flags)
    for b in boxes:
        m = rx.search(b[3])
        if m:
            return m, b
    return None, None


def nonmoney_fields(boxes):
    out = {}

    def add(key, m, b, rule):
        if m:
            out[key] = {
                "value": m.group(1) if m.groups() else m.group(0),
                "raw_text": b[3],
                "bbox": [b[0], b[1], b[2]],
                "source_boxes": [list(b)],
                "confidence": None,
                "rule": rule,
                "observed": True,
                "candidates": [],
            }

    m, b = _find(boxes, r"month\s*of[:\s]*[:：]?\s*(\d{2}/\d{4})", re.I)
    if not m:
        m, b = _find(boxes, r"[:：]\s*(\d{2}/\d{4})")
    if not m:
        m, b = _find(
            boxes, r"^\s*(\d{2}/\d{4})\s*$"
        )  # bare '02/2024' box (split label)
    add("bill_month", m, b, "regex:month")
    m, b = _find(boxes, r"[Dd]ated[:\s]*([0-3]?\d-[A-Za-z0-9]{2,}-\d{4})")
    add("bill_date", m, b, "regex:dated")
    # due date = the date on the 'Payable on or before' row (NOT the DISC.DT date).
    # month is case-insensitive ('18-NoV-2025' OCR).
    pay = next(
        (x for x in boxes if "payable" in norm(x[3]) and "before" in norm(x[3])), None
    )
    if pay is not None:
        dc = [
            x
            for x in boxes
            if abs(x[0] - pay[0]) <= 20
            and re.search(r"\d{1,2}-[A-Za-z]{3}-\d{4}", x[3])
        ]
        if dc:
            db = min(dc, key=lambda x: x[1])
            add(
                "due_date",
                re.search(r"(\d{1,2}-[A-Za-z]{3}-\d{4})", db[3]),
                db,
                "row:duedate",
            )
    if "due_date" not in out:
        m, b = _find(
            boxes, r"\b(\d{1,2}-[A-Za-z]{3}-\d{4})\b"
        )  # fallback (skip DISC.DT)
        if b is not None and "disc" not in norm(b[3]):
            add("due_date", m, b, "regex:duedate")
    m, b = _find(boxes, r"\b(VSP\s?\d+)\b", re.I)
    add("service_no", m, b, "regex:serviceno")
    m, b = _find(boxes, r"(APEPDC\d+)")
    add("van_id", m, b, "regex:vanid")
    # category: value box on the 'Category' label's row (handles IIA(i), IB, IIIA).
    # OCR often reads the roman numeral in parens as a digit -> accept [ivx0-9] and
    # canonicalize (e.g. 'IIA(1)' -> 'IIA(i)').
    from difflib import SequenceMatcher

    catlab = next(
        (
            x
            for x in boxes
            if SequenceMatcher(None, norm(x[3]), "category").ratio() > 0.8
        ),
        None,
    )
    if catlab is not None:
        rowcands = [
            x
            for x in boxes
            if x[1] > catlab[2]
            and abs(x[0] - catlab[0]) <= 22
            and re.match(
                r"^I{1,3}[ABC]?(\([ivx0-9]+\))?$", x[3].strip().replace(" ", ""), re.I
            )
        ]
        if rowcands:
            cb = min(rowcands, key=lambda x: x[1])
            out["category"] = {
                "value": _canon_category(cb[3]),
                "raw_text": cb[3],
                "bbox": [cb[0], cb[1], cb[2]],
                "source_boxes": [list(cb)],
                "confidence": None,
                "rule": "row:category",
                "observed": True,
                "candidates": [],
            }
    if "category" not in out:
        m, b = _find(boxes, r"\b(I{1,3}[ABC]?\s?\([iv]+\))")
        add("category", m, b, "regex:category")
    # contracted MD: value box on the 'Contracted MD' / 'Contract MD' row
    # anchor on 'md'+'hp' (the '/HP' survives even when 'KVA' garbles to 'VA'/'RVA'
    # and 'Contracted'->'Cncracted')
    mdlab = next(
        (
            x
            for x in boxes
            if "md" in norm(x[3]) and "hp" in norm(x[3]) and len(norm(x[3])) < 25
        ),
        None,
    )
    if mdlab is not None:
        # pure-integer box on the label's row (avoid dates/VAN IDs like '-2024')
        cand = [
            x
            for x in boxes
            if x[1] > mdlab[2]
            and abs(x[0] - mdlab[0]) <= 18
            and re.fullmatch(r"\d{2,6}", x[3].strip())
        ]
        if cand:
            cb = min(cand, key=lambda x: x[1])
            out["contracted_md"] = {
                "value": parse_num(cb[3])[0],
                "raw_text": cb[3],
                "bbox": [cb[0], cb[1], cb[2]],
                "source_boxes": [list(cb)],
                "confidence": None,
                "rule": "row:contracted_md",
                "observed": True,
                "candidates": [],
            }
    wv, wb = _words_value(boxes)
    if wv is not None:
        out["amount_words_value"] = {
            "value": wv,
            "raw_text": wb[3],
            "bbox": [wb[0], wb[1], wb[2]],
            "source_boxes": [list(wb)],
            "confidence": None,
            "rule": "words:amount",
            "observed": True,
            "candidates": [],
        }
    out.update(consumption_fields(boxes))
    return out


_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
    "lakh": 100000,
    "lakhs": 100000,
    "lac": 100000,
    "lacs": 100000,
    "crore": 10000000,
    "crores": 10000000,
}

_WORDS_BY_LEN = sorted(_WORDS, key=len, reverse=True)


def _words_value(boxes):
    """Parse the '(Rs ... only)' amount-in-words line into a number (magnitude).

    OCR glues the words ('LakhsSeventeenThousandOne'), so we greedily segment the
    normalized string by longest-matching number word rather than splitting on
    spaces. Anchored to the box containing 'only'."""
    wb = next((b for b in boxes if "only" in norm(b[3]) and "rs" in norm(b[3])), None)
    if wb is None:
        return None, None
    s = norm(wb[3])
    s = re.sub(r"^rs", "", s)
    s = re.sub(r"only$", "", s)
    total = cur = 0
    seen = False
    i = 0
    while i < len(s):
        for w in _WORDS_BY_LEN:
            if s.startswith(w, i):
                v = _WORDS[w]
                seen = True
                if v == 100:
                    cur = (cur or 1) * 100
                elif v >= 1000:
                    total += (cur or 1) * v
                    cur = 0
                else:
                    cur += v
                i += len(w)
                break
        else:
            i += 1  # skip OCR noise char
    return (total + cur, wb) if seen else (None, None)


def consumption_fields(boxes):
    """Total-Consumption row values by column (KWH/KVAH/KVA/PF/LF%).

    Table shear makes the 'Total Consumption' label unreliable as a row anchor.
    Instead we key off the Multiplying-Factor row — the only value row whose
    KWH==KVAH==KVA (e.g. 1/1/1 or 1000/1000/1000) — and take the value row
    immediately below it as Total Consumption."""
    out = {}
    cols = {}
    for b in boxes:
        t = norm(b[3])
        cx = (b[1] + b[2]) / 2
        for key, ok in (
            ("cons_kwh", t == "kwh"),
            ("cons_kvah", t == "kvah"),
            ("cons_kva", t == "kva"),
            ("cons_pf", t == "pf"),
            ("cons_lf", t.startswith("lf")),
        ):
            if ok and key not in cols:
                cols[key] = cx
    if not all(k in cols for k in ("cons_kwh", "cons_kvah", "cons_kva")):
        return out
    # bound the search to the consumption block: above the charge table (Demand
    # Normal label) so an equal-valued charge row can't be mistaken for MF.
    y_charges = min(
        (b[0] for b in boxes if "demandchargesnormal" in norm(b[3])), default=1e9
    )

    def col_of(b):
        c = (b[1] + b[2]) / 2
        best = min(cols, key=lambda k: abs(cols[k] - c))
        return best if abs(cols[best] - c) <= 60 else None

    # cluster numeric boxes that fall in a known column into value rows
    vals = [
        (b, col_of(b))
        for b in boxes
        if parse_num(b[3])[0] is not None and b[0] < y_charges
    ]
    vals = [(b, c) for b, c in vals if c is not None]
    vals.sort(key=lambda t: t[0][0])
    rows_, cur, y0 = [], [], None
    for b, c in vals:
        if y0 is None or abs(b[0] - y0) <= 12:
            cur.append((b, c))
            y0 = b[0] if y0 is None else (y0 + b[0]) / 2
        else:
            rows_.append(cur)
            cur = [(b, c)]
            y0 = b[0]
    if cur:
        rows_.append(cur)

    def rowmap(row):
        d = {}
        for b, c in row:
            d.setdefault(c, b)
        return d

    # Multiplying-Factor row := KWH==KVAH==KVA present and equal
    # Multiplying-Factor row = KWH==KVAH (the only value row where they're equal).
    # Only 2 of 3 required — the KVA MF cell is sometimes not OCR'd (p126).
    mf_i = None
    for i, row in enumerate(rows_):
        d = rowmap(row)
        if "cons_kwh" in d and "cons_kvah" in d:
            a = parse_num(d["cons_kwh"][3])[0]
            b2 = parse_num(d["cons_kvah"][3])[0]
            if a is not None and b2 is not None and abs(a - b2) < 1e-6 and a < 2000:
                mf_i = i
    if mf_i is None or mf_i + 1 >= len(rows_):
        return out
    tc = rowmap(rows_[mf_i + 1])  # Total Consumption = next row
    for key, b in tc.items():
        v, _ = parse_num(b[3])
        out[key] = {
            "value": v,
            "raw_text": b[3],
            "bbox": [b[0], b[1], b[2]],
            "source_boxes": [list(b)],
            "confidence": None,
            "rule": "row_after_mf:total_consumption",
            "observed": True,
            "candidates": [],
        }
    return out


# ---- top-level API ---------------------------------------------------------
def fppca_components(boxes):
    """Sum the printed FPPCA breakdown '(a+b+(-c))' -> float (or None). The bill
    prints FPPCA as a component expression; summing it is an independent read of
    the SAME printed value (not imputation from other fields)."""
    b = next((x for x in boxes if "fppca" in norm(x[3])), None)
    if b is None:
        return None, None
    t = b[3].replace("（", "(").replace("）", ")")
    m = re.search(r"charge\s*\((.*)\)", t, re.I)
    if not m:
        return None, b
    expr = (
        m.group(1)
        .replace("+(-", "-")
        .replace("(-", "-")
        .replace(")", "")
        .replace("(", "")
    )
    vals = [
        float(n) for n in re.findall(r"[+-]?\d+\.?\d*", expr) if re.search(r"\d", n)
    ]
    return (round(sum(vals), 2), b) if vals else (None, b)


def _crosscheck_fppca(fields, boxes):
    """Annotate the FPPCA field confidence by cross-checking the amount against its
    own printed component sum. Does NOT change the value (no imputation) — records
    agreement + the component sum as a candidate for downstream review."""
    fp = fields.get("fppca")
    if not fp or fp.get("value") is None:
        return
    comp, cb = fppca_components(boxes)
    if comp is None:
        return
    agree = abs(fp["value"] - comp) <= 0.02
    fp["confidence"] = "components_agree" if agree else "components_DISAGREE"
    fp["cross_check"] = {
        "component_sum": comp,
        "agree": agree,
        "source": [cb[0], cb[1], cb[2]] if cb else None,
    }


def _apply_confidence(fields):
    """Fill each field's OCR confidence from its value box (last source box) and
    set low_confidence when the recognizer itself was unsure (< 0.9)."""
    from common import conf_of

    for fp in fields.values():
        sb = fp.get("source_boxes") or []
        confs = [conf_of(b) for b in sb if conf_of(b) is not None]
        if confs:
            c = round(min(confs), 3)
            if fp.get("confidence") in (
                None,
                "components_agree",
                "components_DISAGREE",
            ):
                # keep any semantic cross-check confidence but record the numeric one too
                fp["ocr_confidence"] = c
                if fp.get("confidence") is None:
                    fp["confidence"] = c
            fp["low_confidence"] = c < 0.9


def parse(boxes):
    """Return (fields, records). fields = provenance dict; records feed reconcile."""
    recs = build_records(boxes)
    fields = fields_from_records(recs)
    fields.update(nonmoney_fields(boxes))
    _crosscheck_fppca(fields, boxes)
    _apply_confidence(fields)
    return fields, recs
