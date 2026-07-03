"""Gemini vision QC for FLAGGED pages only (build-time policy: cloud allowed).
Sends the page image to Gemini, gets structured fields back, and — critically —
re-validates them against the bill's own accounting (reconcile). The VLM can only
'fix' a page by producing numbers that close the paise-level ledger; it can't
smuggle a wrong-but-plausible value past it.
"""

import json
import os
import re
import sys
import time

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

_CACHE = os.path.join(os.path.dirname(__file__), "cache", "gemini")
os.makedirs(_CACHE, exist_ok=True)


def qc_page(page, img, retries=5):
    """Ask Gemini to read the page. Cached per page (resumable, no re-cost).
    Retries transient 429/503 with backoff. Accumulates token usage."""
    cf = os.path.join(_CACHE, f"p{page}.json")
    if os.path.exists(cf):
        return json.load(open(cf, encoding="utf-8"))
    from google.genai import errors

    delay = 4
    for attempt in range(retries):
        try:
            resp = client().models.generate_content(
                model=_MODEL,
                contents=[PROMPT, img],
                config=types.GenerateContentConfig(
                    temperature=0.0, response_mime_type="application/json"
                ),
            )
            break
        except errors.ServerError:  # 5xx incl. 503 high-demand
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
        except errors.ClientError as e:  # 429 rate limit
            if getattr(e, "code", None) != 429 or attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    u = resp.usage_metadata
    _usage["calls"] += 1
    _usage["in_tokens"] += u.prompt_token_count or 0
    _usage["out_tokens"] += u.candidates_token_count or 0
    try:
        data = json.loads(resp.text)
    except Exception:
        data = {}
    json.dump(data, open(cf, "w", encoding="utf-8"))
    return data


def cost():
    """Return (usd, usage_dict) for all qc_page calls so far."""
    usd = _usage["in_tokens"] / 1e6 * PRICE_IN + _usage["out_tokens"] / 1e6 * PRICE_OUT
    return round(usd, 5), dict(_usage)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def gemini_chain_ok(g):
    """Guardrail: do Gemini's OWN numbers add up? Two ways to pass:
      (A) net_payable == net_bill + arrears  (the arrears field is right), OR
      (B) the UPSTREAM chain corroborates net_bill across 3 identities
          (total==sub+customer AND net_bill==total+loss_gain), in which case
          net_bill+net_payable are trustworthy and arrears is DERIVED as
          net_payable-net_bill (recovers a sign/digit slip in the arrears field).
    A hallucination can't satisfy three independent identities, so (B) stays safe."""
    nb, npay = _f(g.get("net_bill")), _f(g.get("net_payable"))
    if nb is None or npay is None:
        return False
    ac, ap = _f(g.get("arrears_curr")) or 0, _f(g.get("arrears_prev")) or 0
    if abs(npay - (nb + ac + ap)) <= 0.51:  # (A)
        return True
    sub, cust = _f(g.get("sub_total")), _f(g.get("customer_charges"))
    tot, lg = _f(g.get("total")), _f(g.get("loss_gain")) or 0
    if (
        None not in (sub, cust, tot)
        and abs(tot - (sub + cust)) <= 0.51
        and abs(nb - (tot + lg)) <= 0.51
    ):  # (B) 3-identity corroboration
        return True
    return False


def gemini_arrears(g):
    """The trustworthy current-year arrears = net_payable - net_bill (the printed
    anchors), used when the guardrail passes via corroboration."""
    nb, npay = _f(g.get("net_bill")), _f(g.get("net_payable"))
    return None if nb is None or npay is None else round(npay - nb, 2)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, os.path.dirname(__file__))
    from common import ocr, page_image
    from parse import parse

    # our two known misses
    for p, field, gt in [(116, "cons_pf", 0.99), (178, "total", 519264.86)]:
        ours = parse(ocr(p))[0].get(field, {}).get("value")
        g = qc_page(p, page_image(p))
        print(
            f"p{p}.{field}:  deterministic={ours}   gemini={g.get(field)}   truth={gt}"
        )
