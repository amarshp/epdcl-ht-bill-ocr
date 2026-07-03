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
  net_bill, net_payable, arrears_curr, loss_gain,
  cons_kwh, cons_kvah, cons_kva, cons_pf, cons_lf.
category is the printed tariff code like IIA(i), IB, IIIA, IIB.
arrears_curr is the '(Current Years) Arrears after ...' amount (signed; may be negative or 0).
loss_gain is 'Loss (or) Gain' (signed).
cons_pf is Power Factor (between 0 and 1). cons_lf is Load Factor % (integer, or null if blank).
If a value is genuinely unreadable, use null."""

def qc_page(page, img):
    """Ask Gemini to read the page. Returns dict of fields (or {} on failure)."""
    resp = client().models.generate_content(
        model=_MODEL,
        contents=[PROMPT, img],
        config=types.GenerateContentConfig(temperature=0.0,
                                            response_mime_type="application/json"),
    )
    try:
        return json.loads(resp.text)
    except Exception:
        return {}

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
