"""One-time: re-OCR all pages with force to populate recognition confidence
(deterministic; geometry+text identical to the champion cache, adds conf)."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, os.path.dirname(__file__))
from common import ocr
t0 = time.time()
for p in range(1, 263):
    ocr(p, variant="base", force=True)
    if p % 20 == 0:
        print(f"  re-OCR {p}/262 ({time.time()-t0:.0f}s)", flush=True)
print(f"done in {time.time()-t0:.0f}s", flush=True)
