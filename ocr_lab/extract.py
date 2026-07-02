"""Spatial, label-anchored field extraction for the EPDCL HT bill template.
Deterministic. No LLM, no cloud. Reads cached OCR boxes -> field dict.

This is the BASELINE the overnight goal must improve. Known weaknesses to beat:
 - far-right money column sits in its own y-band (widen/target x-band)
 - multi-word labels split across boxes (join adjacent)
 - substring label collisions ('Total' vs 'Total Consumption')
"""
import re
from common import norm

NUM = re.compile(r"-?\d[\d,]*\.?\d+|-?\d+")

def _num(t):
    m = NUM.findall(t.replace(" ", ""))
    return m[-1] if m else None

def _rows(boxes, band=22):
    boxes = sorted(boxes, key=lambda b: (b[0], b[1]))
    rows, cur, y = [], [], None
    for b in boxes:
        if y is None or abs(b[0] - y) <= band:
            cur.append(b); y = b[0] if y is None else y
        else:
            rows.append(cur); cur = [b]; y = b[0]
    if cur: rows.append(cur)
    return rows

def _find_label_row(boxes, label, band=22):
    """Return (rowboxes, label_xmax) for the row containing label as a prefix-ish match."""
    lab = norm(label)
    for row in _rows(boxes, band):
        row = sorted(row, key=lambda b: b[1])
        joined = norm("".join(b[3] for b in row))
        if lab in joined:
            # xmax of the label text within the row
            acc = ""; lx = row[0][2]
            for b in row:
                acc = norm(acc + b[3])
                lx = b[2]
                if lab in acc:
                    break
            return row, lx
    return None, None

def value_on_row(boxes, label, xmin_frac=0.0, band=22):
    """Rightmost numeric on the label's row with xmin beyond xmin_frac*width and past the label."""
    row, lx = _find_label_row(boxes, label, band)
    if not row:
        return None
    W = max(b[2] for b in boxes) if boxes else 1700
    cands = []
    for y, xmn, xmx, t in row:
        if xmn >= max(lx - 5, xmin_frac * W):
            n = _num(t)
            if n is not None:
                cands.append((xmn, n))
    return sorted(cands)[-1][1] if cands else None

FIELDS = {
    "demand_charges":   ("Demand Charges Normal Rate", 0.75),
    "energy_charges":   ("Energy Charges Rate", 0.75),
    "elec_duty":        ("Electricity Duty Charges", 0.75),
    "fppca":            ("FPPCA", 0.75),
    "tod_charges":      ("TODCharges", 0.0),
    "sub_total":        ("Sub Total", 0.0),
    "customer_charges": ("Customer Charges", 0.0),
    "total":            ("Total", 0.0),
    "net_bill":         ("Net Bill Amount", 0.0),
    "net_payable":      ("Net Payable", 0.0),
}

WORDS = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,
         "nine":9,"ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,
         "fifteen":15,"sixteen":16,"seventeen":17,"eighteen":18,"nineteen":19,
         "twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,
         "eighty":80,"ninety":90,"hundred":100,"thousand":1000,"lakh":100000,
         "lakhs":100000,"crore":10000000,"crores":10000000}

def words_to_amount(boxes):
    blob = " ".join(b[3] for b in boxes).lower()
    m = re.search(r"\(?\s*rs\.?\s*([a-z ]+?only)", blob)
    if not m:
        return None
    toks = re.findall(r"[a-z]+", m.group(1))
    total = cur = 0
    for w in toks:
        if w == "only": continue
        v = WORDS.get(w)
        if v is None: continue
        if v == 100: cur = (cur or 1) * 100
        elif v >= 1000:
            total += (cur or 1) * v; cur = 0
        else:
            cur += v
    return total + cur

def extract(boxes):
    out = {}
    for k, (lab, frac) in FIELDS.items():
        out[k] = value_on_row(boxes, lab, frac)
    out["net_payable_words"] = words_to_amount(boxes)
    return out

def to_float(s):
    if s is None: return None
    try: return float(str(s).replace(",", ""))
    except: return None
