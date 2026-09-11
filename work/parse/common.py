"""Shared utilities for parsing Beijing subway station timetable images.

Image conventions (observed):
  * Each image = one station's "列车时刻表". Layout is a grid: one row per hour,
    one printed number per departure/arrival minute.
  * Numbers may be plain, enclosed in a coloured ring, or drawn white-on-colour
    inside a filled disc.  The colour encodes the train's terminal station; the
    legend at the bottom maps colour -> terminal.
  * Some images (e.g. Line 18) contain TWO timetables side by side.
"""
import numpy as np, subprocess, os, re, itertools
from PIL import Image, ImageFile, ImageOps
from scipy import ndimage

ImageFile.LOAD_TRUNCATED_IMAGES = True
_OCR_SEQ = itertools.count()


def load_rgb(path):
    im = Image.open(path)
    if im.mode == 'CMYK':
        # Adobe CMYK JPEGs are stored inverted; PIL's plain convert() yields a
        # negative image, so invert each channel first when that is the case.
        chans = im.split()
        inv = Image.merge('CMYK', [ImageOps.invert(c) for c in chans])
        rgb = inv.convert('RGB')
        # If the "inverted" reading is darker than the direct one, keep direct.
        direct = im.convert('RGB')
        if np.asarray(rgb).mean() < np.asarray(direct).mean():
            rgb = direct
        im = rgb
    elif im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        bg = Image.new('RGB', im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert('RGB')
    return im


def lum(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def ink_mask(a, thr=None):
    """Foreground (text/rings/lines) as boolean.

    Uses Otsu on luminance, then decides polarity by which side forms the
    largest connected region (the page background).  This copes with light
    backgrounds, dark backgrounds and light-grey cell shading alike.
    """
    gray = lum(a)
    t = otsu(gray.astype(np.uint8))
    dark = gray <= t
    light = gray > t
    def biggest(mask):
        lab, n = ndimage.label(mask)
        if n == 0:
            return 0
        return int(np.bincount(lab.ravel(), minlength=n + 1)[1:].max())
    if biggest(dark) >= biggest(light):
        return light          # background is dark -> text is light
    return dark               # background is light -> text is dark


def components(mask, min_size=12):
    lab, n = ndimage.label(mask)
    objs = ndimage.find_objects(lab)
    sizes = ndimage.sum(np.ones(lab.shape), lab, range(1, n + 1))
    out = []
    for i, sl in enumerate(objs):
        if sizes[i] < min_size:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        out.append(dict(lab=i + 1, x0=x0, y0=y0, x1=x1, y1=y1,
                        w=x1 - x0, h=y1 - y0, size=int(sizes[i])))
    return lab, out


def ocr_image(img, psm=7, whitelist='0123456789'):
    """Run tesseract on a PIL image, return stripped text.

    The temp file must live inside the workspace: the sandbox forbids tesseract
    from reading /tmp.  A unique name per process/call keeps concurrent workers
    from clobbering each other.
    """
    d = os.environ.get('OCR_TMP_DIR', os.path.join('work', 'scratch', 'ocr'))
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f'_ocr_{os.getpid()}_{next(_OCR_SEQ)}.png')
    img.save(tmp)
    cmd = ['tesseract', tmp, 'stdout', '--psm', str(psm)]
    if whitelist:
        cmd += ['-c', 'tessedit_char_whitelist=' + whitelist]
    env = dict(os.environ, OMP_THREAD_LIMIT='1')
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=env)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return r.stdout.strip()




def clean_render(mask, comps, scale=1):
    """Render selected components as black-on-white image."""
    h = mask.shape[0]; w = mask.shape[1]
    out = np.full((h, w), 255, np.uint8)
    for c in comps:
        sub = mask[c['y0']:c['y1'], c['x0']:c['x1']]
        region = out[c['y0']:c['y1'], c['x0']:c['x1']]
        region[sub] = 0
    img = Image.fromarray(out)
    if scale != 1:
        img = img.resize((w * scale, h * scale), Image.LANCZOS)
    return img


def dominant_color(a, mask):
    """Return the most common colour among mask pixels (as RGB tuple)."""
    px = a[mask]
    if len(px) == 0:
        return (0, 0, 0)
    q = (px // 24) * 24
    uniq, cnt = np.unique(q.reshape(-1, 3), axis=0, return_counts=True)
    return tuple(int(v) for v in uniq[cnt.argmax()])


def color_name(rgb):
    r, g, b = [int(v) for v in rgb]
    mx, mn = max(rgb), min(rgb)
    if mx - mn < 40:
        return 'gray' if mx < 200 else 'white'
    if r > g and r > b:
        if g > b + 40:
            return 'orange' if g > 120 else 'brown'
        if b > g + 40:
            return 'magenta' if b > 120 else 'red'
        return 'red'
    if g > r and g > b:
        return 'green'
    if b > r and b > g:
        if r > g + 30:
            return 'purple'
        return 'blue'
    return 'other'


def otsu(gray):
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    tot = gray.size
    sumall = np.dot(np.arange(256), hist)
    wB = 0; sumB = 0; best = (-1.0, 128)
    for t in range(256):
        wB += hist[t]
        if wB == 0:
            continue
        wF = tot - wB
        if wF == 0:
            break
        sumB += t * hist[t]
        var = wB * wF * ((sumB / wB) - ((sumall - sumB) / wF)) ** 2
        if var > best[0]:
            best = (var, t)
    return best[1]


def marker_digit_mask(gray, c, pad=4, min_size=6):
    """Extract the digit glyphs drawn inside a ring/disc marker.

    Works for dark-on-light (ring) and light-on-dark (filled disc) alike by
    running Otsu inside the marker box and keeping the minority class.
    """
    y0 = max(0, c['y0'] + pad); y1 = min(gray.shape[0], c['y1'] - pad)
    x0 = max(0, c['x0'] + pad); x1 = min(gray.shape[1], c['x1'] - pad)
    if y1 - y0 < 6 or x1 - x0 < 6:
        return None, (x0, y0)
    g = gray[y0:y1, x0:x1].astype(np.uint8)
    t = otsu(g)
    fg = g < t
    if fg.mean() > 0.5:
        fg = ~fg
    # drop thin border remnants touching the box edge
    l, n = ndimage.label(fg)
    if n == 0:
        return None, (x0, y0)
    sizes = ndimage.sum(np.ones(l.shape), l, range(1, n + 1))
    keep = np.zeros_like(fg)
    for i in range(n):
        if sizes[i] >= min_size:
            keep |= (l == i + 1)
    return keep, (x0, y0)


def estimate_digit_height(comps):
    """Scale-invariant estimate of the printed digit height.

    Digits are the most numerous text-like components in a timetable, so the
    mode of their height distribution is a robust estimate regardless of the
    image resolution.  Chinese labels / banners are wider, lines are flat.
    """
    hs = []
    for c in comps:
        if c['size'] < 20:
            continue
        if c['w'] > 1.9 * c['h']:
            continue          # horizontal rule / banner
        if c['h'] > 8 * max(1, c['w']):
            continue
        hs.append(c['h'])
    if not hs:
        return None
    hs = np.array(hs)
    # mode over a smoothed histogram
    lo, hi = int(hs.min()), int(hs.max())
    if hi <= lo:
        return float(lo)
    bins = np.arange(lo, hi + 2)
    hist, edges = np.histogram(hs, bins=bins)
    k = np.array([1, 2, 3, 2, 1], float); k /= k.sum()
    sm = np.convolve(hist.astype(float), k, mode='same')
    peak = int(np.argmax(sm))
    # refine: median of values near the peak
    near = hs[(hs >= edges[max(0, peak - 1)]) & (hs <= edges[min(len(edges) - 1, peak + 2)])]
    return float(np.median(near)) if len(near) else float(edges[peak])


def find_markers(comps, med_h):
    """Ring / filled-disc markers: roughly square, clearly larger than digits."""
    out = []
    for c in comps:
        if 1.74 * med_h <= c['h'] <= 3.8 * med_h and 1.74 * med_h <= c['w'] <= 3.8 * med_h \
           and abs(c['w'] - c['h']) <= 0.45 * max(c['w'], c['h']) and c['size'] >= 60:
            out.append(c)
    return out


def glyph_tensor(mask, box=24):
    """Normalise a boolean glyph mask to a box x box float array in [0,1].

    Aspect ratio is preserved (the tight glyph is centred on a square canvas
    before resizing) so that '1' and '0' keep their distinct shapes.
    """
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return np.zeros((box, box), np.float32)
    b = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = b.shape
    side = max(h, w)
    pad = np.zeros((side, side), bool)
    oy = (side - h) // 2; ox = (side - w) // 2
    pad[oy:oy + h, ox:ox + w] = b
    img = Image.fromarray((pad * 255).astype(np.uint8)).resize((box, box), Image.LANCZOS)
    return (np.asarray(img).astype(np.float32) / 255.0)


def extract_numbers(path, ink_thr=70, min_size=20):
    """Return (numbers, meta) for one timetable image.

    numbers: list of dicts
        {row_y, x0, x1, y0, y1, glyphs:[{mask(h,w bool), x0,y0,w,h}],
         marker: colour name or None, width, n_glyphs}
    meta: {img_w, img_h, med_h, rows:[(y, nglyphs)...]}
    """
    im = load_rgb(path)
    a = np.asarray(im)
    gray = lum(a)
    m = ink_mask(a, ink_thr)
    lab, comps = components(m, min_size)
    med_h = estimate_digit_height(comps)
    if med_h is None:
        return [], dict(img_w=a.shape[1], img_h=a.shape[0], med_h=18, rows=[])
    dig = [c for c in comps if 0.55 * med_h <= c['h'] <= 1.72 * med_h
           and c['w'] <= 1.9 * c['h'] and c['size'] >= 0.10 * med_h * med_h]
    if not dig:
        return [], dict(img_w=a.shape[1], img_h=a.shape[0], med_h=med_h, rows=[])
    med_h = float(np.median([c['h'] for c in dig]))
    markers = find_markers(comps, med_h)

    glyphs = []
    marker_boxes = []   # (x0,y0,x1,y1, colour)
    for mk in markers:
        mk_mask = (lab[mk['y0']:mk['y1'], mk['x0']:mk['x1']] == mk['lab'])
        gi = gray[mk['y0']:mk['y1'], mk['x0']:mk['x1']]
        col = color_name(dominant_color(a[mk['y0']:mk['y1'], mk['x0']:mk['x1']], mk_mask))
        marker_boxes.append((mk['x0'], mk['y0'], mk['x1'], mk['y1'], col))
        # full disc area (ring stroke + fill + digits)
        filled = ndimage.binary_fill_holes(mk_mask)
        r = max(2, int(0.16 * min(mk['w'], mk['h'])))
        inner = ndimage.binary_erosion(filled, iterations=r)
        if inner.sum() < 20:
            continue
        vals = gi[inner]
        t = otsu(vals.astype(np.uint8))
        cand_dark = inner & (gi < t)
        cand_light = inner & ~(gi < t)
        # the digit strokes are the minority colour inside the marker
        cand = cand_dark if cand_dark.sum() <= cand_light.sum() else cand_light
        tlab, tn = ndimage.label(cand)
        if tn == 0:
            continue
        tsizes = ndimage.sum(np.ones(tlab.shape), tlab, range(1, tn + 1))
        for i in range(1, tn + 1):
            if tsizes[i - 1] < max(10, 0.06 * med_h * med_h):
                continue
            ys, xs = np.where(tlab == i)
            gy0, gy1 = ys.min(), ys.max() + 1
            gx0, gx1 = xs.min(), xs.max() + 1
            if gy1 - gy0 < 0.45 * med_h or gx1 - gx0 < 0.12 * med_h:
                continue
            gm = (tlab[gy0:gy1, gx0:gx1] == i)
            glyphs.append(dict(mask=gm, x0=gx0 + mk['x0'], y0=gy0 + mk['y0'],
                               w=gx1 - gx0, h=gy1 - gy0, marker_color=col))
    # plain digits (not inside any marker); skip marker interiors
    def center_in(c):
        cx = (c['x0'] + c['x1']) / 2; cy = (c['y0'] + c['y1']) / 2
        for b in marker_boxes:
            if b[0] - 2 <= cx <= b[2] + 2 and b[1] - 2 <= cy <= b[3] + 2:
                return True
        return False

    for c in dig:
        if center_in(c):
            continue
        gm = (lab[c['y0']:c['y1'], c['x0']:c['x1']] == c['lab'])
        glyphs.append(dict(mask=gm, x0=c['x0'], y0=c['y0'], w=c['w'], h=c['h'],
                           marker_color=None))
    # group glyphs into rows
    glyphs.sort(key=lambda g: (g['y0'] + g['h'] / 2, g['x0']))
    rows = []
    for g in glyphs:
        yc = g['y0'] + g['h'] / 2
        for r in rows:
            if abs(r['yc'] - yc) <= 0.55 * med_h:
                r['items'].append(g); r['yc'] = np.mean([i['y0'] + i['h'] / 2 for i in r['items']]); break
        else:
            rows.append(dict(yc=yc, items=[g]))
    rows.sort(key=lambda r: r['yc'])
    # group glyphs into numbers within each row
    numbers = []
    for r in rows:
        items = sorted(r['items'], key=lambda g: g['x0'])
        cur = [items[0]]
        for g in items[1:]:
            if g['x0'] - (cur[-1]['x0'] + cur[-1]['w']) <= 0.62 * med_h:
                cur.append(g)
            else:
                numbers.append(_mknum(cur, r['yc'])); cur = [g]
        numbers.append(_mknum(cur, r['yc']))
    return numbers, dict(img_w=a.shape[1], img_h=a.shape[0], med_h=med_h,
                         img=a,
                         rows=[(round(r['yc']), len(r['items'])) for r in rows])


def _mknum(group, yc):
    x0 = min(g['x0'] for g in group); x1 = max(g['x0'] + g['w'] for g in group)
    y0 = min(g['y0'] for g in group); y1 = max(g['y0'] + g['h'] for g in group)
    return dict(row_y=yc, x0=x0, x1=x1, y0=y0, y1=y1, glyphs=group,
                marker=group[0]['marker_color'], width=x1 - x0,
                n_glyphs=len(group))



def ocr_tsv(img, psm=6, whitelist='0123456789'):
    """Run tesseract with TSV output; return list of dicts for text lines."""
    d = os.environ.get('OCR_TMP_DIR', os.path.join('work', 'scratch', 'ocr'))
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f'_ocr_{os.getpid()}_{next(_OCR_SEQ)}.png')
    img.save(tmp)
    cmd = ['tesseract', tmp, 'stdout', '--psm', str(psm)]
    if whitelist:
        cmd += ['-c', 'tessedit_char_whitelist=' + whitelist]
    cmd += ['tsv']
    env = dict(os.environ, OMP_THREAD_LIMIT='1')
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=env)
    try:
        os.remove(tmp)
    except OSError:
        pass
    out = []
    for ln in r.stdout.splitlines()[1:]:
        p = ln.split('\t')
        if len(p) != 12:
            continue
        try:
            level = int(p[0]); top = int(p[7]); height = int(p[9])
        except ValueError:
            continue
        if level != 5 or not p[11].strip():
            continue
        out.append(dict(text=p[11], left=int(p[6]), top=top, width=int(p[8]),
                        height=height, conf=float(p[10]) if p[10] not in ('', '-1') else -1))
    return out
