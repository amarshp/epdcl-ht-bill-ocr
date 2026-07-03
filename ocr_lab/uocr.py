"""Local tier-2 QC via Baidu Unlimited-OCR (fully offline alternative to Gemini).

Transcribes a flagged bill page to structured HTML, parses the accounting fields,
and hands them to the SAME reconcile guardrail. The model is GPU-first, so we force
CPU with a torch monkeypatch (no editing the HF cache file) + bf16.

Reality (measured on holdout): flawless on clean bills; on the faint/credit lower
panels it sometimes leaves the net-bill/arrears/payable cells blank -> those pages
fail reconcile and fall back (human, or Gemini if online). ~2-4 min/page on CPU.
"""

import contextlib
import io
import os
import re
import sys

import torch

# --- force CPU: Unlimited-OCR's infer() hardcodes .cuda(); neutralize it globally
torch.Tensor.cuda = lambda self, *a, **k: self  # tensors stay on CPU
if not torch.cuda.is_available():
    torch.cuda.is_available = lambda: False

_MID = "baidu/Unlimited-OCR"
_model = _tok = None


def _load():
    global _model, _tok
    if _model is None:
        from transformers import AutoModel, AutoTokenizer

        _tok = AutoTokenizer.from_pretrained(_MID, trust_remote_code=True)
        _model = AutoModel.from_pretrained(
            _MID, trust_remote_code=True, use_safetensors=True, dtype=torch.bfloat16
        ).eval()
    return _model, _tok


_TMP = os.path.join(os.path.dirname(__file__), "cache", "uocr")
os.makedirs(_TMP, exist_ok=True)


def transcribe(img):
    """Full-page image -> structured HTML/markdown transcription (string)."""
    model, tok = _load()
    p = os.path.join(_TMP, "_in.png")
    img.save(p)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        model.infer(
            tok,
            prompt="<image>OCR.",
            image_file=p,
            output_path=os.path.join(_TMP, "out"),
            base_size=1024,
            image_size=640,
            crop_mode=True,
            max_length=32768,
            no_repeat_ngram_size=35,
            ngram_window=128,
            save_results=False,
        )
    return buf.getvalue()


_NUM = r"(-?[\d,]+\.\d{2})"


def _n(m):
    return float(m.group(1).replace(",", "")) if m else None


def parse_fields(html):
    """Pull the reconcile-critical fields out of the HTML transcription.
    Tags flattened to spaces; values matched by their printed labels."""
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"\s+", " ", t)
    f = {}
    f["net_payable"] = _n(re.search(r"Net Payable\s*Rs?\.?\s*" + _NUM, t, re.I))
    f["net_bill"] = _n(re.search(r"Net Bill Amount\s+" + _NUM, t, re.I))
    f["sub_total"] = _n(re.search(r"Sub Total\s+" + _NUM, t, re.I))
    f["customer_charges"] = _n(re.search(r"Customer Charges\s+" + _NUM, t, re.I))
    f["arrears_curr"] = _n(
        re.search(r"Current Years?\)?\s*Arrears[^0-9-]*" + _NUM, t, re.I)
    )
    f["loss_gain"] = _n(re.search(r"Loss\s*\(or\)\s*Gain\s+" + _NUM, t, re.I))
    # grand Total: last "Total <num>" that isn't "Sub Total"/"Total Consumption"/"TOD..."
    tot = re.findall(r"(?<!Sub )(?<!TOD)(?<!ction )Total\s+" + _NUM, t)
    f["total"] = float(tot[-1].replace(",", "")) if tot else None
    cat = re.search(r"Category\s+([IVX]+\s?[AB]?\s?\(?[ivIVxX]+\)?)", t)
    f["category"] = cat.group(1).replace(" ", "") if cat else None
    return f


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, os.path.dirname(__file__))
    from common import page_image

    for p in (8, 32):
        fields = parse_fields(transcribe(page_image(p)))
        print(f"p{p}: {fields}")
