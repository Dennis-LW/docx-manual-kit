#!/usr/bin/env python3
"""Crop system bars off device screenshots before they go into a manual.

Either give explicit pixel amounts (``--top`` / ``--bottom``) or let
``--auto-status-bar`` guess the status bar height.

The auto heuristic, and its limits: starting from the top row, a row counts as
part of the bar while its pixels are *near-uniform* (max channel spread below
``--tolerance``) and its average colour stays close to row 0's.  The first row
that breaks either rule ends the bar.  That works for the usual flat status bar
over a plain app background; it under-crops over a photo or gradient header,
and over-crops when the app's own top area happens to be the same flat colour
as the bar.  Always eyeball the result — it is meant to save typing, not to be
trusted blindly.  A detected bar taller than ``--max-fraction`` of the image is
treated as a false positive and ignored.

Examples::

    python trim_screenshot.py shots/*.png --auto-status-bar --out-dir shots/trimmed
    python trim_screenshot.py login.png --top 72 --bottom 48
"""

from __future__ import annotations

import argparse
import os

from PIL import Image


def detect_status_bar(im, tolerance=12, max_fraction=0.12):
    """Height in pixels of the leading band of near-uniform rows (0 if none)."""
    rgb = im.convert('RGB')
    w, h = rgb.size
    px = rgb.load()
    step = max(1, w // 64)          # sampling 64 columns is plenty and much faster
    cols = range(0, w, step)

    def row_stats(y):
        vals = [px[x, y] for x in cols]
        flat = [c for p in vals for c in p]
        n = len(vals)
        avg = tuple(sum(p[i] for p in vals) / n for i in range(3))
        return avg, max(flat) - min(flat)

    first_avg, first_spread = row_stats(0)
    if first_spread > tolerance:
        return 0
    limit = int(h * max_fraction)
    y = 1
    while y < limit:
        avg, spread = row_stats(y)
        if spread > tolerance:
            break
        if max(abs(a - b) for a, b in zip(avg, first_avg)) > tolerance:
            break
        y += 1
    return 0 if y >= limit else y


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images', nargs='+', help='PNG files to crop')
    ap.add_argument('--top', type=int, default=0, help='pixels to remove from the top')
    ap.add_argument('--bottom', type=int, default=0, help='pixels to remove from the bottom')
    ap.add_argument('--auto-status-bar', action='store_true',
                    help='detect the top bar instead of using --top')
    ap.add_argument('--tolerance', type=int, default=12,
                    help='colour spread still counted as uniform (default 12)')
    ap.add_argument('--max-fraction', type=float, default=0.12,
                    help='reject a detected bar taller than this fraction (default 0.12)')
    ap.add_argument('--out-dir', help='write here instead of overwriting in place')
    args = ap.parse_args(argv)

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)

    for path in args.images:
        with Image.open(path) as im:
            w, h = im.size
            top = detect_status_bar(im, args.tolerance, args.max_fraction) \
                if args.auto_status_bar else args.top
            bottom = args.bottom
            if top + bottom >= h:
                print('%s: crop %d+%d >= height %d, skipped' % (path, top, bottom, h))
                continue
            out = os.path.join(args.out_dir, os.path.basename(path)) if args.out_dir else path
            if top or bottom:
                im.crop((0, top, w, h - bottom)).save(out, 'PNG', optimize=True)
            elif out != path:
                im.save(out, 'PNG', optimize=True)
            print('%s: %dx%d -> %dx%d (top %d, bottom %d) %s'
                  % (os.path.basename(path), w, h, w, h - top - bottom, top, bottom, out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
