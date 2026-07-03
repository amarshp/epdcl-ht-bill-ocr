"""Local Tesseract digit cross-check for disputed money boxes. 100% local.
Crops the amount box region from the page scan, upscales, runs Tesseract in
digit mode, and returns its read. Compared against RapidOCR + component sums.
"""
import os, re, sys
import pytesseract
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from common import page_image

_TESS = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Tesseract-OCR", "tesseract.exe")
pytesseract.pytesseract.tesseract_cmd = _TESS
os.environ["TESSDATA_PREFIX"] = os.path.join(os.path.dirname(_TESS), "tessdata")

DIGITS = r"--psm 7 -c tessedit_char_whitelist=0123456789.,-()+"

def crop_region(p, bbox, pad_x=12, pad_y=16, scale=3.0):
    """bbox = [ycenter, xmin, xmax]. Returns an upscaled PIL crop of that money box."""
    img = page_image(p)
    if img is None:
        return None
    yc, x0, x1 = bbox
    box = (max(0, int(x0 - pad_x)), max(0, int(yc - pad_y)),
           min(img.width, int(x1 + pad_x)), min(img.height, int(yc + pad_y)))
    crop = img.crop(box)
    return crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.LANCZOS)

def tess_read(p, bbox, scale=3.0):
    """Tesseract digit read of the money box; returns (text, parsed_float|None)."""
    crop = crop_region(p, bbox, scale=scale)
    if crop is None:
        return None, None
    txt = pytesseract.image_to_string(crop, config=DIGITS).strip()
    m = re.findall(r"-?\d[\d,]*\.?\d*", txt.replace(" ", ""))
    val = None
    if m:
        try: val = float(m[-1].replace(",", ""))
        except ValueError: val = None
    return txt, val

def save_crop(p, bbox, out, scale=3.0):
    crop = crop_region(p, bbox, scale=scale)
    if crop is not None:
        crop.save(out)
    return out

def tesseract_available():
    return os.path.exists(_TESS)

def recover_fppca(fields, recs, boxes, page):
    """GATED Tesseract recovery: only when the FPPCA amount still disagrees with its
    printed component sum after the swap-correction (i.e. the box itself is misread).
    Re-read that one box with Tesseract; adopt ONLY if Tesseract then matches the
    component sum. Never runs on the 227 already-correct pages -> no regression.
    Returns True if a value was recovered."""
    from parse import fppca_components
    if not tesseract_available():
        return False
    comp, _ = fppca_components(boxes)
    fr = fields.get("fppca")
    if comp is None or not fr or fr.get("value") is None:
        return False
    if abs(fr["value"] - comp) <= 0.02:
        return False                       # already correct
    _, tval = tess_read(page, fr["bbox"])
    if tval is None or abs(tval - comp) > 0.02:
        fr["confidence"] = "components_DISAGREE"     # Tesseract couldn't confirm -> flag only
        return False
    fr["value"] = tval
    fr["rule"] = "tesseract_recovered"
    fr["confidence"] = "tesseract_matches_components"
    rr = next((r for r in recs if r["field"] == "fppca"), None)
    if rr is not None:
        rr["value"] = tval; rr["rule"] = "tesseract_recovered"
    return True
