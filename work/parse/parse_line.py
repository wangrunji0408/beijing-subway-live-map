#!/usr/bin/env python3
"""Per-line timetable parsing pipeline.

The digit reader is tesseract applied to a *clean re-rendering* of each table
row (every extracted glyph drawn as black-on-white at its original position).
That is far more reliable than classifying individual glyphs, while the glyph
extraction still provides accurate segmentation, row grouping and marker colour.

Usage:
  python3 work/parse/parse_line.py build <line> [--meta meta.json]
  python3 work/parse/parse_line.py build-all [--lines 1,2,...]
  python3 work/parse/parse_line.py one <image>
"""
import sys, os, glob, json, argparse, re
import numpy as np
from collections import defaultdict
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common, checker

ROOT = os.getcwd()
TT = os.path.join(ROOT, 'timetables')
OUT = os.path.join(ROOT, 'work', 'parsed')
OVERRIDES = os.path.join(ROOT, 'work', 'overrides.json')


def images_for(line):
    return sorted(glob.glob(os.path.join(TT, f'{line}-*.jpg'))) + \
           sorted(glob.glob(os.path.join(TT, f'{line}-*.png')))


def parse_station_name(path):
    base = os.path.basename(path).rsplit('.', 1)[0]
    parts = base.split('-')
    return parts[1] if len(parts) > 1 else base


# ---------------------------------------------------------------- table logic
def cluster_rows(nums, tol):
    ys = sorted(nums, key=lambda n: n['row_y'])
    rows = []
    for n in ys:
        if rows and n['row_y'] - rows[-1]['yc'] <= tol:
            rows[-1]['items'].append(n)
            rows[-1]['yc'] = float(np.mean([i['row_y'] for i in rows[-1]['items']]))
        else:
            rows.append(dict(yc=n['row_y'], items=[n]))
    return rows


def select_table_rows(rows, med_h):
    rows = [r for r in rows if len(r['items']) >= 2]
    if len(rows) < 3:
        return []
    ys = [r['yc'] for r in rows]
    gaps = [b - a for a, b in zip(ys, ys[1:]) if b - a > 0]
    if not gaps:
        return rows
    pitch = float(np.median(gaps))
    best, cur = [], [rows[0]]
    for r in rows[1:]:
        if 0.55 * pitch <= r['yc'] - cur[-1]['yc'] <= 1.7 * pitch and len(r['items']) >= 2:
            cur.append(r)
        else:
            if len(cur) > len(best):
                best = cur
            cur = [r]
    if len(cur) > len(best):
        best = cur
    return best


def split_panels(nums, img_w):
    if not nums:
        return [nums]
    bins = np.zeros(img_w // 10 + 2, int)
    for n in nums:
        bins[min(len(bins) - 1, n['x0'] // 10)] += 1
    # candidate empty bands
    cands = []
    empty_start = None
    for i, v in enumerate(bins):
        if v == 0:
            if empty_start is None:
                empty_start = i
        else:
            if empty_start is not None:
                w = i - empty_start
                if empty_start > 2 and w * 10 > max(120, 0.045 * img_w):
                    cands.append(((empty_start + w / 2) * 10, w))
                empty_start = None
    if not cands:
        return [nums]

    total = len(nums)
    y0 = min(n['y0'] for n in nums); y1 = max(n['y1'] for n in nums)
    span = max(1, y1 - y0)

    def side_y(side):
        return (min(n['y0'] for n in side), max(n['y1'] for n in side))

    def looks_like_table(side):
        if len(side) < 0.25 * total:
            return False
        sy0, sy1 = side_y(side)
        return (sy1 - sy0) >= 0.6 * span

    # prefer a wide gap near the middle whose two sides are both full tables
    valid = []
    for cut, w in cands:
        left = [n for n in nums if n['x0'] < cut]
        right = [n for n in nums if n['x0'] >= cut]
        if not (looks_like_table(left) and looks_like_table(right)):
            continue
        # a genuine two-panel poster has two tables with the SAME vertical extent
        ly0, ly1 = side_y(left); ry0, ry1 = side_y(right)
        if abs(ly0 - ry0) > 0.12 * span or abs(ly1 - ry1) > 0.12 * span:
            continue
        if not (0.30 * img_w <= cut <= 0.72 * img_w):
            continue
        valid.append((w, cut, left, right))
    if not valid:
        return [nums]
    valid.sort(reverse=True)
    return [valid[0][2], valid[0][3]]


# ---------------------------------------------------------------- row reading
def render_items(items, pad=4):
    x0 = min(n['x0'] for n in items) - pad; x1 = max(n['x1'] for n in items) + pad
    y0 = min(n['y0'] for n in items) - pad; y1 = max(n['y1'] for n in items) + pad
    canvas = np.full((y1 - y0, x1 - x0), 255, np.uint8)
    for n in items:
        for g in n['glyphs']:
            sub = g['mask']; yy = g['y0'] - y0; xx = g['x0'] - x0
            reg = canvas[yy:yy + sub.shape[0], xx:xx + sub.shape[1]]
            canvas[yy:yy + sub.shape[0], xx:xx + sub.shape[1]] = np.where(sub, 0, reg)
    return canvas


def upscale(canvas, items, cap=5):
    hs = [g['h'] for n in items for g in n['glyphs']]
    sc = max(2, int(round(60.0 / max(1, np.median(hs))))) if hs else 3
    sc = min(sc, cap)
    return Image.fromarray(canvas).resize((canvas.shape[1] * sc, canvas.shape[0] * sc),
                                          Image.LANCZOS)


def split_by_width(items, maxw=800):
    chunks = []
    cur = [items[0]]
    x0 = items[0]['x0']
    for n in items[1:]:
        if n['x1'] - x0 > maxw:
            chunks.append(cur); cur = [n]; x0 = n['x0']
        else:
            cur.append(n)
    chunks.append(cur)
    return chunks


def align_digits(digits, items, hour_first):
    """Align a digit string to the numbers of one row.

    Two alignments are tried - the fixed two-digit minute layout and the
    extracted glyph count - and the one yielding more valid minutes wins.
    """
    N = len(items)

    def valid(out):
        mins = out[1:] if hour_first else out
        return sum(1 for m in mins if m and m.isdigit() and 0 <= int(m) <= 59)

    cands = []
    if hour_first:
        for hl in (1, 2, 0):
            if len(digits) == 2 * (N - 1) + hl:
                out = [digits[:hl] if hl else None]
                rest = digits[hl:]
                out += [rest[2 * i:2 * i + 2] for i in range(N - 1)]
                cands.append(('fixed', out))
    elif len(digits) == 2 * N:
        cands.append(('fixed', [digits[2 * i:2 * i + 2] for i in range(N)]))
    E = sum(n['n_glyphs'] for n in items)
    if len(digits) == E and E > 0:
        out = []; k = 0
        for n in items:
            out.append(digits[k:k + n['n_glyphs']]); k += n['n_glyphs']
        cands.append(('glyphcount', out))
    if not cands:
        return None, 'fail'
    best = max(cands, key=lambda c: valid(c[1]))
    if valid(best[1]) < (N - 1 if hour_first else N) * 0.7:
        return None, 'fail'
    return best[1], best[0]


def read_rows_batch(rows, hour_flags):
    """OCR every row of one panel in a single tesseract call.

    All rows are rendered white-on-black onto one tall canvas; tesseract's TSV
    line boxes are matched back to the rows by vertical overlap.  This avoids
    one tesseract process per row, which dominates the runtime.
    """
    if not rows:
        return []
    tiles = [render_items(r, pad=8) for r in rows]
    hs = [g['h'] for r in rows for n in r for g in n['glyphs']]
    sc = min(3, max(2, int(round(60.0 / max(1, np.median(hs)))))) if hs else 2
    gap = 24
    W = max(c.shape[1] for c in tiles)
    H = sum(c.shape[0] + gap for c in tiles) + gap
    # keep the OCR canvas within a sane pixel budget (huge line-6 images)
    sc = max(1, min(sc, int(4200 / max(1, W)), int(7000 / max(1, H))))
    canvas = np.full((H, W), 255, np.uint8)
    pos = []
    y = gap
    for c in tiles:
        canvas[y:y + c.shape[0], :c.shape[1]] = c
        pos.append((y, y + c.shape[0])); y += c.shape[0] + gap
    img = Image.fromarray(canvas).resize((W * sc, H * sc), Image.LANCZOS)
    lines = common.ocr_tsv(img, psm=6)
    acc = [''] * len(rows)
    for ln in sorted(lines, key=lambda l: (l['top'], l['left'])):
        top = ln['top'] / sc; bot = (ln['top'] + ln['height']) / sc
        best = None
        for i, (a, b) in enumerate(pos):
            ov = min(bot, b) - max(top, a)
            if ov > 0 and (best is None or ov > best[0]):
                best = (ov, i)
        if best and best[0] > 0.35 * (pos[best[1]][1] - pos[best[1]][0]):
            acc[best[1]] += ''.join(ch for ch in ln['text'] if ch.isdigit())
    out = []
    for i, r in enumerate(rows):
        if not acc[i]:
            out.append((None, '', 'fail')); continue
        toks, how = align_digits(acc[i], r, hour_flags[i])
        out.append((toks, acc[i], how))
    return out


def read_hour_column(hour_items):
    """OCR the stacked hour labels as one narrow strip; returns list of texts."""
    if not hour_items:
        return [], ''
    x0 = min(n['x0'] for n in hour_items) - 6; x1 = max(n['x1'] for n in hour_items) + 6
    y0 = min(n['y0'] for n in hour_items) - 6; y1 = max(n['y1'] for n in hour_items) + 6
    canvas = np.full((y1 - y0, x1 - x0), 255, np.uint8)
    for n in hour_items:
        for g in n['glyphs']:
            sub = g['mask']; yy = g['y0'] - y0; xx = g['x0'] - x0
            reg = canvas[yy:yy + sub.shape[0], xx:xx + sub.shape[1]]
            canvas[yy:yy + sub.shape[0], xx:xx + sub.shape[1]] = np.where(sub, 0, reg)
    img = upscale(canvas, hour_items)
    txt = common.ocr_image(img, psm=6)
    toks = [t for t in re.split(r'\s+', txt) if t.isdigit()]
    return toks, txt


def read_hour_column_img(a, rows, med_h):
    """Read the hour column straight from the image.

    Returns (tokens, separate).  `separate` is True when the hour digits sit
    to the LEFT of each row's first number (so they are not part of the row
    items) - e.g. line 11, where the hour sits on a grey cell that merges with
    the table rules.  When False the hour label is the row's leftmost number.
    """
    if a is None or not rows:
        return [], False
    gray = common.lum(a)
    m = common.ink_mask(a)
    lx = min(r['items'][0]['x0'] for r in rows)
    y0 = max(0, int(min(r['yc'] for r in rows) - 1.3 * med_h))
    y1 = min(a.shape[0], int(max(r['yc'] for r in rows) + 1.3 * med_h))
    xa = max(0, int(lx - 4.0 * med_h)); xb = max(0, int(lx - 0.25 * med_h))
    if xb <= xa:
        return [], False
    sub = m[y0:y1, xa:xb]
    if sub.sum() < 0.02 * sub.size:
        return [], False
    cols = sub.sum(0); nz = np.where(cols > 0)[0]
    x0 = xa + int(nz[0]); x1 = xa + int(nz[-1]) + 1
    crop = gray[y0:y1, x0:x1].astype(np.uint8)
    t = common.otsu(crop)
    text = crop < t
    if text.mean() > 0.5:
        text = ~text
    img = Image.fromarray(np.where(text, 0, 255).astype(np.uint8))
    sc = min(3, max(2, int(round(60.0 / max(1, med_h)))))
    img = img.resize((img.size[0] * sc, img.size[1] * sc), Image.LANCZOS)
    txt = common.ocr_image(img, psm=6)
    toks = [t2 for t2 in re.split(r'\s+', txt) if t2.isdigit()]
    # only accept it as a separate hour column if the tokens look like hours
    if len(toks) < 0.5 * len(rows):
        return [], False
    vals = sorted(set(int(t2) % 24 for t2 in toks))
    best = cur = 1
    for p_, q_ in zip(vals, vals[1:]):
        cur = cur + 1 if q_ == (p_ + 1) % 24 else 1
        best = max(best, cur)
    if best >= max(3, 0.5 * len(vals)):
        return toks, True
    return [], False


def resolve_hours(obs, n, extra=None):
    """Recover the consecutive hour sequence from per-row observations.

    obs[i] is a guessed hour for row i (or None); `extra` is a set of hour
    values read from the hour column (possibly misaligned / missing some rows).
    Every possible start hour is tried and the consecutive sequence matching
    the evidence best wins, so a few misread labels cannot rotate the table.
    """
    extra = set(extra or [])
    best = None
    for h0 in range(24):
        hours = [(h0 + i) % 24 for i in range(n)]
        hset = set(hours)
        score = sum(1 for o, h in zip(obs, hours) if o is not None and o == h)
        score += 2 * sum(1 for v in extra if v in hset)
        anchor_ok = 0 if (obs and obs[0] is not None and obs[0] == h0) else 1
        key = (-score, anchor_ok, h0)
        if best is None or key < best[0]:
            best = (key, hours)
    return best[1] if best else list(range(n))


def build_timetable(nums, med_h, meta_for_image, overrides=None, overrides_panels=None):
    out = []
    panels = split_panels(nums, meta_for_image.get('img_w', 10000))
    overrides_panels = overrides_panels or {}
    for pi, panel in enumerate(panels):
        if len(panel) < 5:
            continue
        rows = select_table_rows(cluster_rows(panel, 0.6 * med_h), med_h)
        if len(rows) < 3:
            continue
        rows = [dict(yc=r['yc'], items=sorted(r['items'], key=lambda n: n['x0'])) for r in rows]
        lefts = [r['items'][0] for r in rows]
        mode_x = float(np.median([n['x0'] for n in lefts]))
        near = [abs(n['x0'] - mode_x) <= 1.2 * med_h for n in lefts]
        if sum(near) < 0.5 * len(rows):
            near = [False] * len(rows)
        idx = [i for i, ok in enumerate(near) if ok] or list(range(len(rows)))
        a, b = idx[0], idx[-1]
        rows = rows[a:b + 1]; lefts = lefts[a:b + 1]; near = near[a:b + 1]

        # read the hour column straight from the image (works even when the
        # hour glyphs merge with the table or were dropped from the rows)
        strip_toks, separate = read_hour_column_img(meta_for_image.get('img'), rows, med_h)
        strip_set = set(int(t) % 24 for t in strip_toks if t.isdigit()) if strip_toks else set()
        if len(strip_toks) != len(rows):
            strip_toks = None
        # if the hour digits sit left of the row's first number they are NOT in
        # the row items, so the row must be aligned as all-minutes
        hour_flags = [not separate] * len(rows)

        row_items_list = [list(r['items']) for r in rows]
        batch = read_rows_batch(row_items_list, hour_flags)
        obs = []
        for i, (ok, (toks, text, how)) in enumerate(zip(hour_flags, batch)):
            v = None
            if ok and toks and toks[0] and toks[0].isdigit() and int(toks[0]) <= 24:
                v = int(toks[0])
            if v is None and strip_toks is not None and i < len(strip_toks) \
               and strip_toks[i].isdigit():
                v = int(strip_toks[i]) % 24
            obs.append(v)
        hours = resolve_hours(obs, len(rows), extra=strip_set)

        times = []
        flags = []
        for (r, lm, ok, row_items, (toks, text, how), v) in zip(
                rows, lefts, hour_flags, row_items_list, batch, hours):
            if toks is None:
                flags.append(dict(row_y=round(r['yc']), kind='ocr_fail', text=text[:100]))
                continue
            if len(toks) != len(row_items):
                flags.append(dict(row_y=round(r['yc']), kind='count_mismatch',
                                  got=len(toks), want=len(row_items), text=text[:100]))
            for i, (tok, num) in enumerate(zip(toks, row_items)):
                if ok and i == 0:
                    continue  # hour label
                if tok is None:
                    continue
                if not tok.isdigit():
                    flags.append(dict(row_y=round(r['yc']), kind='bad_minute', text=tok))
                    continue
                mv = int(tok)
                if mv > 59:
                    # common tesseract failure: the two digits of a minute are
                    # read in reverse order ("80" for "08").  Repair when the
                    # swapped value is a legal minute.
                    sw = tok[::-1]
                    if len(sw) == 2 and sw.isdigit() and int(sw) <= 59:
                        flags.append(dict(row_y=round(r['yc']), kind='repaired_swap',
                                          text=tok, fixed=sw))
                        tok = sw; mv = int(sw)
                    else:
                        flags.append(dict(row_y=round(r['yc']), kind='bad_minute', text=tok))
                        continue
                times.append(dict(hour=int(v), minute=mv, terminal=None,
                                  color=num.get('marker')))
        ov = overrides_panels.get(pi, overrides)
        if ov:
            times = apply_overrides(times, ov)
        times.sort(key=lambda t: (t['hour'], t['minute']))
        out.append(dict(times=times, flags=flags, n_rows=len(rows), panel=pi))
    return out


def apply_overrides(times, ov):
    """Apply manual corrections.

    ov is a list of:
      {"row_set": {"hour": H, "minutes": [...]}}  replace all minutes in hour H
      {"del": [h, m]}                              delete one departure
      {"add": [h, m]}                              add one departure
      [h, old_m, new_m]                            rename one departure
    """
    for o in ov:
        if isinstance(o, dict) and 'row_set' in o:
            H = o['row_set']['hour']
            mins = [int(m) for m in o['row_set']['minutes']]
            times = [t for t in times if t['hour'] != H]
            times += [dict(hour=H, minute=m, terminal=None, color=None) for m in mins]
        elif isinstance(o, dict) and 'set_times' in o:
            times = [dict(hour=int(h) % 24, minute=int(m), terminal=None, color=None)
                     for h, m in o['set_times']]
        elif isinstance(o, dict) and 'del' in o:
            h, m = o['del']; times = [t for t in times if not (t['hour'] == h and t['minute'] == m)]
        elif isinstance(o, dict) and 'add' in o:
            h, m = o['add']; times.append(dict(hour=h, minute=m, terminal=None, color=None))
        elif isinstance(o, (list, tuple)) and len(o) == 3:
            h, m, nm = o
            for t in times:
                if t['hour'] == h and t['minute'] == m:
                    t['minute'] = nm
    return times


# ---------------------------------------------------------------- build stage
def build_one(path, meta_map, overrides_all):
    base = os.path.basename(path).rsplit('.', 1)[0]
    suffix = base.split('-')[-1]
    rel = os.path.relpath(path, ROOT)
    m = dict(meta_map.get(suffix, {}) or {})
    # per-image overrides win (meta["_images"][<image base>])
    m.update((meta_map.get('_images', {}) or {}).get(base, {}) or {})
    # per-panel metadata (two timetables in one image, e.g. line 18)
    panels_meta = (meta_map.get('_panels', {}) or {}).get(base, {}) or {}
    # overrides: a plain list applies to every panel; "path#i" or a
    # {"0": [...], "1": [...]} dict targets individual panels
    ov = overrides_all.get(rel)
    ov_panels = {}
    for i in range(6):
        if f'{rel}#{i}' in overrides_all:
            ov_panels[i] = overrides_all[f'{rel}#{i}']
    if isinstance(ov, dict) and not isinstance(ov, list):
        for k, v in ov.items():
            try:
                ov_panels[int(k)] = v
            except (TypeError, ValueError):
                pass
        ov = None
    nums, meta = common.extract_numbers(path)
    tts = build_timetable(nums, meta['med_h'], dict(m, **meta), overrides=ov,
                          overrides_panels=ov_panels)
    recs = []
    for i, tt in enumerate(tts):
        pm = panels_meta.get(str(tt.get('panel', i)), {}) or {}
        issues, stats = checker.check_times(tt['times'])
        recs.append(dict(
            id=base if len(tts) == 1 else f'{base}#{i}',
            source=rel, suffix=suffix,
            line=base.split('-')[0], station=parse_station_name(path),
            direction=pm.get('direction', m.get('direction')),
            service=pm.get('service', m.get('service')),
            legend=pm.get('legend', m.get('legend')), times=tt['times'],
            _issues=issues, _stats=stats, _flags=tt['flags']))
    return recs


def build_line(line, meta_map=None, overrides_all=None):
    meta_map = dict(meta_map or {})
    overrides_all = dict(overrides_all or {})
    # per-line hand-written metadata / overrides (safe for parallel workers)
    mp = os.path.join(OUT, line, 'meta.json')
    if os.path.exists(mp):
        meta_map.update(json.load(open(mp)))
    op = os.path.join(OUT, line, 'overrides.json')
    if os.path.exists(op):
        overrides_all.update(json.load(open(op)))
    paths = images_for(line)
    recs, report = [], []
    for p in paths:
        try:
            rs = build_one(p, meta_map, overrides_all)
        except Exception as e:
            report.append(dict(source=os.path.relpath(p, ROOT), error=repr(e)[:300]))
            continue
        for r in rs:
            report.append(dict(source=r['source'], id=r['id'], n_times=len(r['times']),
                               stats=r.pop('_stats'), issues=r.pop('_issues'),
                               flags=r.pop('_flags')))
            recs.append(r)
    os.makedirs(OUT, exist_ok=True)
    jsonl = os.path.join(OUT, f'{line}.jsonl')
    with open(jsonl, 'w') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.makedirs(os.path.join(OUT, line), exist_ok=True)
    json.dump(report, open(os.path.join(OUT, line, 'report.json'), 'w'),
              ensure_ascii=False, indent=1)
    bad = sum(1 for r in report if r.get('issues') or r.get('flags') or r.get('error'))
    print(f'[{line}] {len(recs)} timetables, {bad}/{len(report)} images need review -> {jsonl}')
    return recs, report


def write_line(line, recs, report):
    os.makedirs(OUT, exist_ok=True)
    jsonl = os.path.join(OUT, f'{line}.jsonl')
    with open(jsonl, 'w') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.makedirs(os.path.join(OUT, line), exist_ok=True)
    json.dump(report, open(os.path.join(OUT, line, 'report.json'), 'w'),
              ensure_ascii=False, indent=1)
    bad = sum(1 for r in report if r.get('issues') or r.get('flags') or r.get('error'))
    print(f'[{line}] {len(recs)} timetables, {bad}/{len(report)} images need review -> {jsonl}')


def line_meta(line, meta_map):
    mm = dict(meta_map)
    mp = os.path.join(OUT, line, 'meta.json')
    if os.path.exists(mp):
        mm.update(json.load(open(mp)))
    return mm


def line_overrides(line, overrides_all):
    oo = dict(overrides_all)
    op = os.path.join(OUT, line, 'overrides.json')
    if os.path.exists(op):
        oo.update(json.load(open(op)))
    return oo


def build_all(lines, meta_map, overrides_all, jobs=8):
    from concurrent.futures import ThreadPoolExecutor
    tasks = []
    for line in lines:
        mm = line_meta(line, meta_map)
        oo = line_overrides(line, overrides_all)
        for p in images_for(line):
            tasks.append((line, p, mm, oo))
    results = defaultdict(lambda: ([], []))
    lock = __import__('threading').Lock()

    def work(t):
        line, p, mm, oo = t
        try:
            rs = build_one(p, mm, oo)
        except Exception as e:
            return line, [], [dict(source=os.path.relpath(p, ROOT), error=repr(e)[:300])]
        rep = []
        for r in rs:
            rep.append(dict(source=r['source'], id=r['id'], n_times=len(r['times']),
                            stats=r.pop('_stats'), issues=r.pop('_issues'), flags=r.pop('_flags')))
        return line, rs, rep

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for line, rs, rep in ex.map(work, tasks):
            results[line][0].extend(rs)
            results[line][1].extend(rep)
    for line in lines:
        write_line(line, *results[line])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['build', 'build-all', 'one'])
    ap.add_argument('line', nargs='?')
    ap.add_argument('--lines', default=None)
    ap.add_argument('--meta', default=None)
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
    meta_map = {}
    if a.meta and os.path.exists(a.meta):
        meta_map = json.load(open(a.meta))
    overrides = json.load(open(OVERRIDES)) if os.path.exists(OVERRIDES) else {}
    if a.stage == 'build':
        build_line(a.line, meta_map, overrides)
    elif a.stage == 'one':
        for r in build_one(a.line, meta_map, overrides):
            print(json.dumps(r, ensure_ascii=False)[:2000])
    else:
        lines = a.lines.split(',') if a.lines else [l for l in
                 ['1','2','3','4','5','6','7','8','9','10','11','12','13','14','15','16',
                  '17','18','19','S1','亦庄','八通','大兴机场','房山','昌平','燕房','首都机场']]
        build_all(lines, meta_map, overrides, jobs=a.jobs)


if __name__ == '__main__':
    main()
