"""Shared OCR + caching utilities. Local, CPU, no APIs."""
import io, json, os, re
from PIL import Image
import pypdf

ROOT = os.path.dirname(__file__)
PDF = os.path.join(ROOT, "..", "Issue-4.pdf")
CACHE = os.path.join(ROOT, "cache")
os.makedirs(CACHE, exist_ok=True)

_engine = None
def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine

def page_image(p):
    """1-indexed page -> PIL image of the embedded scan (each bill page = 1 image)."""
    r = pypdf.PdfReader(PDF)
    imgs = list(r.pages[p - 1].images)
    if not imgs:
        return None
    return Image.open(io.BytesIO(imgs[0].data)).convert("RGB")

def ocr(p, variant="base", force=False, preprocess=None):
    """Return list of boxes [ycenter, xmin, xmax, text, conf]. Cached per (page,variant).

    The 5th element (recognition confidence 0..1) is appended for backward compat:
    all downstream code indexes b[0:4]. Legacy 4-element caches read fine (conf absent)."""
    cf = os.path.join(CACHE, f"p{p}_{variant}.json")
    if os.path.exists(cf) and not force:
        return json.load(open(cf, encoding="utf-8"))
    # back-compat: base cache written as p{p}.json by the sweep
    legacy = os.path.join(CACHE, f"p{p}.json")
    if variant == "base" and os.path.exists(legacy) and not force:
        return json.load(open(legacy, encoding="utf-8"))
    img = page_image(p)
    if img is None:
        boxes = []
    else:
        if preprocess:
            img = preprocess(img)
        res, _ = _get_engine()(img)
        boxes = [[round(sum(pt[1] for pt in b) / 4, 1),
                  round(min(pt[0] for pt in b), 1),
                  round(max(pt[0] for pt in b), 1), t.strip(),
                  round(float(c), 3)]
                 for b, t, c in (res or [])]
    json.dump(boxes, open(cf, "w", encoding="utf-8"), ensure_ascii=False)
    return boxes

def conf_of(box):
    """Recognition confidence of an OCR box, or None for legacy 4-element boxes."""
    return box[4] if len(box) >= 5 else None

def classify(boxes):
    blob = " ".join(b[3] for b in boxes).lower().replace(" ", "")
    if "htbillforthemonth" in blob or ("easternpower" in blob and "netpayable" in blob):
        return "HT_BILL"
    if "netpayable" in blob or "subtotal" in blob:
        return "BILL?"
    if len(boxes) < 8:
        return "SPARSE"
    return "OTHER"

# dev set: cached HT bill pages spanning 01/2024..05/2026 (tune on these)
DEV_BILLS = [8, 16, 32, 48, 64, 80, 96, 112, 128, 160, 176, 192, 208, 224, 240, 256]
# held-out test set: NEVER tune against these; OCR once for final validation
TEST_BILLS = [24, 40, 56, 72, 104, 136, 168, 200, 232, 248]

def norm(s):
    return re.sub(r"[^a-z0-9%]", "", s.lower())
