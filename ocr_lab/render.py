"""Render a bill page's scan to PNG for visual (codex) grading.
Usage: python render.py 8   -> samples/page8.png
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from common import page_image

def render(p, scale=1.0):
    img = page_image(p)
    if img is None:
        print(f"page {p}: no image"); return None
    if scale != 1.0:
        img = img.resize((int(img.width*scale), int(img.height*scale)))
    out = os.path.join(os.path.dirname(__file__), "samples", f"page{p}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    print(out)
    return out

if __name__ == "__main__":
    render(int(sys.argv[1]) if len(sys.argv) > 1 else 8)
