"""Digit recognition for timetable glyphs.

Strategy: glyphs of a given line all share one typeface, so we cluster the
extracted glyph tensors, render a contact sheet of the cluster centres, let a
human (or vision model) label each cluster with a digit, then assign every
glyph to its nearest labelled template.
"""
import os, json
import numpy as np
from PIL import Image, ImageDraw

import common


def collect_glyphs(paths, limit_per_image=None, verbose=False):
    """Return list of dicts {tensor, src, row_y, x0, w, h, marker, num_x0, num_x1}."""
    out = []
    for p in paths:
        try:
            nums, meta = common.extract_numbers(p)
        except Exception as e:
            if verbose:
                print('  ! extract failed', p, e)
            continue
        for n in nums:
            for gl in n['glyphs']:
                out.append(dict(tensor=common.glyph_tensor(gl['mask']),
                                src=p, row_y=n['row_y'], x0=gl['x0'],
                                num_x0=n['x0'], num_x1=n['x1'],
                                w=gl['w'], h=gl['h'], marker=n['marker']))
        if limit_per_image and len(out) > limit_per_image:
            break
    return out


def kmeans(X, k, iters=40, seed=0, verbose=False):
    """Simple k-means++ over rows of X. Returns (centers, labels, dists)."""
    X = np.asarray(X, np.float32)
    X = X.reshape(len(X), -1)
    rng = np.random.RandomState(seed)
    n = len(X)
    k = min(k, n)
    # k-means++ init
    centers = [X[rng.randint(n)]]
    d2 = ((X - centers[0]) ** 2).sum(1)
    for _ in range(1, k):
        probs = d2 / max(d2.sum(), 1e-9)
        i = rng.choice(n, p=probs)
        centers.append(X[i])
        d2 = np.minimum(d2, ((X - X[i]) ** 2).sum(1))
    C = np.array(centers)
    for it in range(iters):
        dist = ((X[:, None, :] - C[None, :, :]) ** 2).sum(2) if n * k * X.shape[1] < 4e7 \
            else _chunked_dist(X, C)
        lab = dist.argmin(1)
        newC = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
        shift = np.abs(newC - C).max()
        C = newC
        if verbose:
            print(f'  kmeans iter {it} shift {shift:.4f}')
        if shift < 1e-4:
            break
    dist = _chunked_dist(X, C)
    return C, dist.argmin(1), dist.min(1)


def _chunked_dist(X, C):
    out = np.empty((len(X), len(C)), np.float32)
    step = max(1, int(4e7 / max(1, len(C) * X.shape[1])))
    for i in range(0, len(X), step):
        out[i:i + step] = ((X[i:i + step, None, :] - C[None, :, :]) ** 2).sum(2)
    return out


def contact_sheet(C, labels, counts, path, X=None, cols=12, cell=44, pad=6, samples=4):
    """Render cluster samples with their index and member count.

    If X (glyph tensors) is given, up to `samples` real members closest to the
    centre are shown next to the averaged centre.
    """
    k = len(C)
    rows = (k + cols - 1) // cols
    nshow = 1 + (samples if X is not None else 0)
    cw = cell * nshow + (nshow - 1) * 2
    W = cols * (cw + pad) + pad
    H = rows * (cell + pad + 16) + pad
    sheet = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(sheet)
    members = {}
    if X is not None:
        for i, l in enumerate(labels):
            members.setdefault(int(l), []).append(i)
    for i in range(k):
        r, c = divmod(i, cols)
        x = pad + c * (cw + pad); y = pad + r * (cell + pad + 16)
        tiles = [C[i]]
        if X is not None and members.get(i):
            idxs = members[i]
            dd = ((X[idxs] - C[i]) ** 2).sum(1)
            idxs = [idxs[j] for j in np.argsort(dd)[:samples]]
            tiles += [X[j] for j in idxs]
        for s, t in enumerate(tiles):
            img = Image.fromarray((255 - t.reshape(24, 24) * 255).astype(np.uint8)) \
                .resize((cell, cell), Image.NEAREST)
            sheet.paste(img, (x + s * (cell + 2), y))
        d.rectangle([x - 1, y - 1, x + cw, y + cell], outline=(200, 200, 200))
        d.text((x, y + cell + 2), f'{i}:{counts[i]}', fill='black')
    sheet.save(path)
    return sheet


def classify_tensors(X, templates):
    """templates: list of (tensor, digit). Returns (labels, dists)."""
    T = np.array([t for t, _ in templates], np.float32)
    D = _chunked_dist(X, T)
    idx = D.argmin(1)
    return [templates[i][1] for i in idx], D.min(1)


def build_templates(C, label_map):
    """label_map: {cluster_index: digit or None}. Returns list of (center, digit)."""
    out = []
    for i, d in label_map.items():
        d = str(d).strip()
        if d == '' or d is None or d == '-1':
            continue
        out.append((C[int(i)], d))
    return out


def save_clusters(C, labels, counts, outdir):
    os.makedirs(outdir, exist_ok=True)
    np.save(os.path.join(outdir, 'centers.npy'), C)
    np.save(os.path.join(outdir, 'labels.npy'), labels)
    json.dump({'counts': [int(c) for c in counts]},
              open(os.path.join(outdir, 'clusters.json'), 'w'))


def load_clusters(outdir):
    C = np.load(os.path.join(outdir, 'centers.npy'))
    lab = np.load(os.path.join(outdir, 'labels.npy'))
    counts = json.load(open(os.path.join(outdir, 'clusters.json')))['counts']
    return C, lab, counts
