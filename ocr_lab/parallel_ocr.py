"""Parallel re-OCR across CPU cores. Pages are independent -> process pool.
Each worker limits its own OCR thread count so workers x threads ~= cores
(the OCR engine is already multi-threaded per page, so we don't oversubscribe).
Skips pages already carrying confidence. Deterministic: same boxes as serial.
"""
import os, sys, json, time, glob
import multiprocessing as mp

ROOT = os.path.dirname(os.path.abspath(__file__))
N_WORKERS = int(os.environ.get("OCR_WORKERS", "6"))
THREADS = max(1, 16 // N_WORKERS)

def _init():
    # cap intra-op threading BEFORE onnxruntime is imported in this worker
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "ORT_INTRA_OP_NUM_THREADS"):
        os.environ[v] = str(THREADS)

def _work(p):
    sys.path.insert(0, ROOT)
    from common import ocr
    t = time.time()
    boxes = ocr(p, variant="base", force=True)
    return p, len(boxes), round(time.time() - t, 1)

def _needs(p):
    f = os.path.join(ROOT, "cache", f"p{p}_base.json")
    if not os.path.exists(f):
        return True
    try:
        b = json.load(open(f, encoding="utf-8"))
    except Exception:
        return True
    return not (b and len(b[0]) >= 5)          # already has confidence?

if __name__ == "__main__":
    pages = [p for p in range(1, 263) if _needs(p)]
    print(f"{len(pages)} pages to OCR | {N_WORKERS} workers x {THREADS} threads", flush=True)
    t0 = time.time(); done = 0
    with mp.Pool(N_WORKERS, initializer=_init) as pool:
        for p, n, dt in pool.imap_unordered(_work, pages):
            done += 1
            if done <= 6 or done % 20 == 0:
                rate = done / (time.time() - t0) * 60
                print(f"  [{done}/{len(pages)}] p{p}: {n} boxes in {dt}s "
                      f"| throughput {rate:.1f} pages/min", flush=True)
    el = time.time() - t0
    print(f"done: {len(pages)} pages in {el:.0f}s = {len(pages)/el*60:.1f} pages/min", flush=True)
