"""Gemini vision QC for FLAGGED pages only (build-time policy: cloud allowed).
Sends the page image to Gemini, gets structured fields back, and — critically —
re-validates them against the bill's own accounting (reconcile). The VLM can only
'fix' a page by producing numbers that close the paise-level ledger; it can't
smuggle a wrong-but-plausible value past it.
"""
import os, re, json, sys
from google import genai
from google.genai import types

_ENV = r"C:\Users\Amarsh\OneDrive\Documents\Personal\Projects\NativelyAI\natively-cluely-ai-assistant\.env"
_MODEL = "gemini-2.5-flash"

def _load_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    for line in open(_ENV, encoding="utf-8"):
        m = re.match(r"\s*GEMINI_API_KEY\s*=\s*[\"']?([^\"'\s]+)", line)
        if m:
            return m.group(1)
    raise RuntimeError("no GEMINI_API_KEY")

_client = None
def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=_load_key())
    return _client

PROMPT = """You are auditing a scanned Andhra Pradesh EPDCL HT electricity bill.
Read the printed values EXACTLY as shown (ignore faint noise; trust the printed digits).
Return ONLY JSON with these keys (numbers as plain numbers, no commas, no currency):
  service_no, category, bill_month, sub_total, customer_charges, total,
  net_bill, net_payable, arrears_prev, arrears_curr, loss_gain,
  cons_kwh, cons_kvah, cons_kva, cons_pf, cons_lf.
category is the printed tariff code like IIA(i), IB, IIIA, IIB.
arrears_curr is the '(Current Years) Arrears after ...' amount (signed; may be negative or 0).
loss_gain is 'Loss (or) Gain' (signed).
cons_pf is Power Factor (between 0 and 1). cons_lf is Load Factor % (integer, or null if blank).
If a value is genuinely unreadable, use null."""

# Gemini 2.5 Flash public pricing (USD per 1M tokens), as of 2025.
PRICE_IN, PRICE_OUT = 0.30, 2.50
_usage = {"calls": 0, "in_tokens": 0, "out_tokens": 0}

def qc_page(page, img):
    """Ask Gemini to read the page. Returns dict of fields (or {} on failure).
    Accumulates token usage in the module-level _usage counter."""
    resp = client().models.generate_content(
        model=_MODEL,
        contents=[PROMPT, img],
        config=types.GenerateContentConfig(temperature=0.0,
                                            response_mime_type="application/json"),
    )
    u = resp.usage_metadata
    _usage["calls"] += 1
    _usage["in_tokens"] += (u.prompt_token_count or 0)
    _usage["out_tokens"] += (u.candidates_token_count or 0)
    try:
        return json.loads(resp.text)
    except Exception:
        return {}

def cost():
    """Return (usd, usage_dict) for all qc_page calls so far."""
    usd = _usage["in_tokens"] / 1e6 * PRICE_IN + _usage["out_tokens"] / 1e6 * PRICE_OUT
    return round(usd, 5), dict(_usage)

def gemini_chain_ok(g):
    """Guardrail: do Gemini's OWN returned numbers add up? net_payable must equal
    net_bill + arrears (the identity we can check without every adjustment row).
    A hallucinated total/payable fails this and is sent to a human instead."""
    nb, npay = g.get("net_bill"), g.get("net_payable")
    ac = g.get("arrears_curr") or 0
    ap = g.get("arrears_prev") or 0
    if nb is None or npay is None:
        return False
    try:
        return abs(float(npay) - (float(nb) + float(ac) + float(ap))) <= 0.51
    except (TypeError, ValueError):
        return False

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, os.path.dirname(__file__))
    from common import page_image
    from parse import parse
    from common import ocr
    # our two known misses
    for p, field, gt in [(116, "cons_pf", 0.99), (178, "total", 519264.86)]:
        ours = parse(ocr(p))[0].get(field, {}).get("value")
        g = qc_page(p, page_image(p))
        print(f"p{p}.{field}:  deterministic={ours}   gemini={g.get(field)}   truth={gt}")
