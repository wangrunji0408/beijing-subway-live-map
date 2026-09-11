#!/usr/bin/env python3
"""Crop a single timetable row (or a whole image region) for visual review.

Usage:
  python3 work/parse/crop.py <image> --row-y 1234 [--pad 20] [--out path]
  python3 work/parse/crop.py <image> --header [--out path]
  python3 work/parse/crop.py <image> --legend [--out path]

Writes a PNG under work/scratch/crops/ by default and prints its path.
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

ROOT = os.getcwd()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--row-y', type=float)
    ap.add_argument('--pad', type=int, default=26)
    ap.add_argument('--header', action='store_true')
    ap.add_argument('--legend', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args()
    im = common.load_rgb(a.image)
    W, H = im.size
    if a.header:
        box = (0, 0, W, int(H * 0.16))
    elif a.legend:
        box = (0, int(H * 0.86), W, H)
    elif a.row_y is not None:
        y = a.row_y
        box = (0, max(0, int(y - a.pad)), W, min(H, int(y + a.pad)))
    else:
        box = (0, 0, W, H)
    crop = im.crop(box)
    # upscale narrow crops for readability
    if crop.size[1] < 240:
        f = max(1, int(240 / max(1, crop.size[1])))
        f = min(f, 4)
        crop = crop.resize((crop.size[0] * f, crop.size[1] * f))
    out = a.out or os.path.join(ROOT, 'work', 'scratch', 'crops',
                                os.path.basename(a.image).rsplit('.', 1)[0] +
                                (f'_row{int(a.row_y)}' if a.row_y is not None else '') +
                                ('.header' if a.header else '.legend' if a.legend else '') + '.png')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    crop.save(out)
    print(out)


if __name__ == '__main__':
    main()
