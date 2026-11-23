"""
imgio.py - a tiny helper that saves a picture (numpy array) as a PNG file.

WHY it exists:
    The calibration and debug tools need to show you pictures (the kill-feed crop, the colour
    mask, ...). Normally this needs a big library (Pillow / OpenCV). A PNG file is simple enough
    that we can write it ourselves with Python's built-in zlib, so there is nothing to install.

HOW it works:
    A PNG is: a fixed signature, then "chunks" (IHDR = size/colour type, IDAT = compressed pixel
    rows, IEND = end). Each pixel row starts with a filter byte (we use 0 = "no filter").

HOW TO IMPROVE:
    - Use filter type 1-4 for smaller files (not important for debug images).
    - Add `draw_box` variants (labels with text) if you want nicer debug pictures.
"""

import struct
import zlib

import numpy as np


def write_png(path, array) -> None:
    """Save an HxWx3 (colour) or HxW (grey) uint8 array as a PNG file."""
    arr = np.ascontiguousarray(array, dtype=np.uint8)
    colour_type = 0 if arr.ndim == 2 else 2          # 0 = greyscale, 2 = RGB
    height, width = arr.shape[:2]
    # Every row gets a leading 0 byte (filter type "none").
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(png)


def draw_hlines(image, y0: int, y1: int, colour=(0, 255, 0), thickness: int = 2):
    """Draw a top and bottom line across the picture (used to mark detected kill rows)."""
    h = image.shape[0]
    for y in (y0, y1):
        a, b = max(0, y - thickness // 2), min(h, y + thickness)
        image[a:b, :, :] = colour
    return image


def enlarge(image, factor: int = 2):
    """Make a picture bigger by repeating pixels (so small crops are easy to look at)."""
    return np.repeat(np.repeat(image, factor, axis=0), factor, axis=1)
