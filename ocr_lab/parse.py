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
            out.append(cur); cur = [b]; y0 = b[0]
    if cur:
        out.append(cur)
    return out

# ---- money column detection ------------------------------------------------
# an amount box VALUE ends with its number (allow trailing ')' or spaces).
# This rejects full-width prose (NOTE line), label-only rows ('25%Rebate...'),
# and split labels ('NetIcdAmt...(0.00-') that merely contain a digit.
_ENDS_NUM = re.compile(r"-?\d[\d,]*\.?\d*\)?[A-Za-z]{0,2}\s*$")  # allow trailing OCR noise ('364356.50M')
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
        if _DATE_LABEL.search(b[3]):        # arrears/date label ending in a year, not an amount
            continue
        money.append(b)
    return money

# ---- label catalog ---------------------------------------------------------
# (canonical_field, section, sign, [keyword aliases]).  First match wins, so
# order more-specific labels before generic ones.  Keywords are normalized
# (lowercase, alnum+% only) and matched as substrings against the row label.
CATALOG = [
    # --- upper charge table -> sub_total (all +, tod_incentive -) ---
    ("demand_penal",   "sub", +1, ["demandchargespenal", "demandpenal"]),
    ("demand_normal",  "sub", +1, ["demandchargesnormal", "demandnormal"]),
    ("excess_energy",  "sub", +1, ["excessenergycharges"]),
    ("energy_charges", "sub", +1, ["energychargesrate"]),
    ("elec_duty",      "sub", +1, ["electricityduty"]),
    ("fuel_surcharge", "sub", +1, ["fuelsurchargeadjustment"]),
    ("trueup",         "sub", +1, ["trueupcharge"]),
    ("fppca",          "sub", +1, ["fppcacharge", "fppca"]),
    ("tod_incentive",  "sub", -1, ["todincentive"]),
    ("tod_charges",    "sub", +1, ["todcharges"]),
    # --- lower pre-total panel -> total ---
    ("customer_charges","tot", +1, ["customercharges"]),
    ("grid_support",   "tot", +1, ["gridsupport"]),
    ("wheeling",       "tot", +1, ["wheelingcharges"]),
    ("transmission",   "tot", +1, ["transmissioncharges"]),
    ("rkvah_hydel",    "tot", +1, ["rkvahsurchargehydel", "surchargehydel"]),
    ("rkvah_wind",     "tot", +1, ["rkvahsurchargewind", "surchargewind"]),
    ("open_access",    "tot", +1, ["openaccess"]),
    ("acd_surcharge",  "tot", +1, ["acdsurcharge"]),
    ("late_payment",   "tot", +1, ["latepayment"]),
    ("interest_ed",    "tot", +1, ["interestoned"]),
    ("penal_interest", "tot", +1, ["penalinterest"]),
    ("transformer_hire","tot",+1, ["transformerhire"]),
    ("diff_voltage",   "tot", +1, ["differencevoltage"]),
    ("load_factor_inc","tot", -1, ["loadfactorincentive"]),
    # --- post-total -> net_bill ---
    ("tcssf",          "net", +1, ["tcssf", "tcss"]),
    ("tcs",            "net", +1, ["tcs"]),
    ("rebate",         "net", -1, ["rebateapplication", "rebate"]),
    ("ferro_subsidy",  "net", -1, ["ferrosubsidy"]),
    ("pooled_cost",    "net", -1, ["pooledcost"]),
    ("neticd",         "net", -1, ["neticd"]),
    ("other_credit",   "net", +1, ["othercredit"]),
    ("export_amount",  "net", -1, ["exportamount", "export"]),
    ("loss_gain",      "net", +1, ["lossorgain", "lossgain"]),
    # --- arrears -> net_payable ---
    ("arrears_prev",   "pay", +1, ["arrearsbefore", "previousyears"]),
    ("arrears_curr",   "pay", +1, ["arrearsafter", "currentyears"]),
    # --- totals themselves (observed printed values) ---
    ("sub_total",      "val", +1, ["subtotal"]),
    ("net_bill",       "val", +1, ["netbillamount", "netbill"]),
    ("net_payable",    "val", +1, ["netpayable"]),
    ("total",          "val", +1, ["total"]),   # generic 'total' LAST
]

def classify(label):
    n = norm(label)
    if not n:
        return None
    for field, section, sign, keys in CATALOG:
        for k in keys:
            if k in n:
                return field, section, sign
    return None

# ---- record building -------------------------------------------------------
def signed_value(value, raw_token, sign):
    """Combine OCR sign + label sign without double-negating."""
    if raw_token is not None and raw_token.strip().startswith("-"):
        return value               # OCR already signed -> trust it
    return sign * value

def _row_label(boxes, mb, band):
    """Label text on the NEAREST line to the left of amount box mb.

    Picks the closest label box by |Δy| (not every box in the band), then joins
    only boxes on that same visual line. Prevents a neighbouring line (arrears,
    time-block) from bleeding into a total's classification.
    """
    cands = [b for b in boxes
             if b is not mb and b[1] < mb[1] - 3 and abs(b[0] - mb[0]) <= band]
    if not cands:
        return _nonnum_prefix(mb[3]), []
    y_star = min(cands, key=lambda b: abs(b[0] - mb[0]))[0]
    line = sorted([b for b in cands if abs(b[0] - y_star) <= 7], key=lambda b: b[1])
    text = "".join(b[3] for b in line) + " " + _nonnum_prefix(mb[3])
    return text, line

def _rec(field, section, sign, mb, label_text, left, rule):
    v, raw = parse_num(mb[3])
    if v is None:
        return None
    return {
        "field": field, "section": section,
        "value": signed_value(v, raw, sign),
        "raw_text": mb[3], "amount_bbox": [mb[0], mb[1], mb[2]],
        "label_text": label_text.strip(),
        "source_boxes": [[b[0], b[1], b[2], b[3]] for b in left] + [list(mb)],
        "rule": rule,
    }

def _upper_labels(boxes, y_lo, y_hi):
    """Charge labels (section 'sub') between y_lo and y_hi, sorted top->down."""
    max_x = max(x[2] for x in boxes)
    out = []
    for b in boxes:
        if not (y_lo <= b[0] < y_hi):
            continue
        hit = classify(_nonnum_prefix(b[3]) or norm(b[3]))
        # keep charge labels; skip right-aligned money-column boxes
        if hit and hit[1] == "sub" and b[2] < 0.85 * max_x:
            out.append((b[0], hit[0], hit[2], b))
    out.sort(key=lambda t: t[0])
    return out

def _assign(amounts, labels, delta):
    """Greedy monotonic assignment of amounts->labels given vertical offset delta.
    Returns (pairs, residual). Each label used at most once (strictly increasing)."""
    pairs, residual, li = [], 0.0, 0
    for ay, mb in amounts:
        target = ay - delta
        if li >= len(labels):                     # exhausted: reuse last label, penalize
            pairs.append((mb, labels[-1]))
            residual += 100.0
            continue
        best = None
        for j in range(li, len(labels)):
            d = abs(labels[j][0] - target)
            if best is None or d < best[0]:
                best = (d, j)
            if labels[j][0] > target and best is not None and labels[j][0] - target > best[0]:
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
    if not labels or not upper_amounts:
        return []
    amounts = sorted(upper_amounts, key=lambda t: t[0])
    if len(amounts) == len(labels):
        pairs = [(mb, lab) for (_, mb), lab in zip(amounts, labels)]
        rule_tag = "rank"
    else:
        best = None
        for d10 in range(-300, 501, 10):        # delta in [-30, 50]
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
            y_sub = b[0]; break
    if y_sub is None:
        y_sub = max(b[0] for b in money)     # degrade: treat all as lower
    # top of charge table = Demand Charges Normal Rate label. Wide margin: the
    # demand amount can sit ~30px ABOVE its label under negative shear (p48/p256).
    y_lo = min((b[0] for b in boxes if "demandchargesnormal" in norm(b[3])), default=0) - 40
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
            label_text, left = _row_label(boxes, mb, band)
            hit = classify(label_text)
            rule = f"row:{hit[0]}" if hit else ""
        if hit is None:
            continue
        field, section, sign = hit
        r = _rec(field, section, sign, mb, label_text, left, rule)
        if r:
            recs.append(r)
    return recs

# ---- field dict with provenance -------------------------------------------
def _prov(rec, rule=None):
    return {
        "value": rec["value"],
        "raw_text": rec["raw_text"],
        "bbox": rec["amount_bbox"],
        "source_boxes": rec["source_boxes"],
        "confidence": None,               # base cache has no conf (noted; v2 cache TODO)
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
                {"value": r["value"], "bbox": r["amount_bbox"], "label": r["label_text"]}
                for r in rs
            ]
            p["ambiguous"] = True
            out[field] = p
    return out

# ---- non-money fields (dates / ids / consumption) --------------------------
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
            out[key] = {"value": m.group(1) if m.groups() else m.group(0),
                        "raw_text": b[3], "bbox": [b[0], b[1], b[2]],
                        "source_boxes": [list(b)], "confidence": None,
                        "rule": rule, "observed": True, "candidates": []}
    m, b = _find(boxes, r"month\s*of[:\s]*[:：]?\s*(\d{2}/\d{4})", re.I)
    if not m:
        m, b = _find(boxes, r"[:：]\s*(\d{2}/\d{4})")
    add("bill_month", m, b, "regex:month")
    m, b = _find(boxes, r"[Dd]ated[:\s]*([0-3]?\d-[A-Za-z0-9]{2,}-\d{4})")
    add("bill_date", m, b, "regex:dated")
    m, b = _find(boxes, r"\b(\d{1,2}-[A-Z][a-z]{2}-\d{4})\b")     # due date
    add("due_date", m, b, "regex:duedate")
    m, b = _find(boxes, r"\b(VSP\s?\d+)\b", re.I)
    add("service_no", m, b, "regex:serviceno")
    m, b = _find(boxes, r"(APEPDC\d+)")
    add("van_id", m, b, "regex:vanid")
    m, b = _find(boxes, r"\b(I{1,3}[ABC]?\s?\([iv]+\))", 0)       # category e.g. IIA(i)
    if not m:
        m, b = _find(boxes, r"\b(II?A?\([iv]+\))")
    add("category", m, b, "regex:category")
    # Total Consumption row: KWH KVAH KVA PF (numbers to the right of the label)
    for row in rows(boxes):
        row = sorted(row, key=lambda x: x[1])
        joined = norm("".join(x[3] for x in row))
        if joined.startswith("totalconsumption"):
            nums = [(x, parse_num(x[3])) for x in row]
            nums = [(x, v) for x, (v, _) in nums if v is not None]
            keys = ["cons_kwh", "cons_kvah", "cons_kva", "cons_pf"]
            for (x, v), k in zip(nums, keys):
                out[k] = {"value": v, "raw_text": x[3], "bbox": [x[0], x[1], x[2]],
                          "source_boxes": [list(x)], "confidence": None,
                          "rule": "row:total_consumption", "observed": True,
                          "candidates": []}
            break
    return out

# ---- top-level API ---------------------------------------------------------
def parse(boxes):
    """Return (fields, records). fields = provenance dict; records feed reconcile."""
    recs = build_records(boxes)
    fields = fields_from_records(recs)
    fields.update(nonmoney_fields(boxes))
    return fields, recs
