"""Lever B: image preprocessing candidates for re-OCR of low-recognition pages.

Each fn takes a PIL RGB image and returns a PIL RGB image, usable as
common.ocr(p, variant=..., force=True, preprocess=fn). Compared strictly against
the champion (base) cache — adopt only on a verified win. Local, deterministic.
"""

import cv2
import numpy as np
from PIL import Image


def upscale(img, scale=2.0):
    return img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)


def gray_otsu(img):
    a = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    _, th = cv2.threshold(a, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(cv2.cvtColor(th, cv2.COLOR_GRAY2RGB))


def upscale_otsu(img, scale=2.0):
    return gray_otsu(upscale(img, scale))


def clahe(img):
    a = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    c = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(a)
    return Image.fromarray(cv2.cvtColor(c, cv2.COLOR_GRAY2RGB))


def deskew(img):
    a = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    inv = cv2.bitwise_not(a)
    coords = np.column_stack(np.where(inv > 128))
    if len(coords) < 50:
        return img
    ang = cv2.minAreaRect(coords)[-1]
    ang = -(90 + ang) if ang < -45 else -ang
    if abs(ang) < 0.3:
        return img
    h, w = a.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    rot = cv2.warpAffine(
        np.array(img), M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return Image.fromarray(rot)


CANDIDATES = {
    "upscale2": lambda im: upscale(im, 2.0),
    "otsu": gray_otsu,
    "upscale2_otsu": lambda im: upscale_otsu(im, 2.0),
    "clahe": clahe,
    "deskew_upscale": lambda im: upscale(deskew(im), 2.0),
}
