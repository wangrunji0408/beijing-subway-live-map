#!/usr/bin/env python3
"""Infer per-train diagrams (运行图) from per-station timetables.

Within one (line, direction, service) group the station timetables are time
shifts of each other: a train leaving the origin at t passes station s at
t + tau_s.  We recover:

  * station order  - sorted by each station's robust "first service" time
    (a low percentile of its departures), which grows monotonically from origin
    to terminus; cross-checked against the OSM station order for the direction;
  * tau_s          - the total origin->terminus travel time (first-service time
    difference) distributed over the line geometry by inter-station distance;
  * train runs     - each origin departure matched to the nearest departure at
    every station, giving a stop-by-stop trajectory (short-turns simply drop out).

Output: work/out/train_runs.jsonl, one JSON object per (line, group).
"""
import json, os, glob, sys
import numpy as np
from collections import defaultdict

ROOT = os.getcwd()
PARSED = os.path.join(ROOT, 'work', 'parsed')
OUT = os.path.join(ROOT, 'work', 'out')
DATA = os.path.join(ROOT, 'work', 'data')

LINE_MAP = {'1': '1', '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7', '8': '8',
            '9': '9', '10': '10', '11': '11', '12': '12', '13': '13', '14': '14', '15': '15',
            '16': '16', '17': '17', '18': '18', '19': '19', 'S1': 'S1', '亦庄': 'Yizhuang',
            '八通': '1', '大兴机场': 'DaxingAirport', '房山': 'Fangshan',
            '昌平': 'Changping', '燕房': 'Yanfang', '首都机场': 'CapitalAirport'}

_GEO = None
_OSM = None


def to_abs(t):
    return t['hour'] * 60 + t['minute']


def load_line(line):
    p = os.path.join(PARSED, f'{line}.jsonl')
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p)]


def group_by_suffix(recs):
    """Group by (suffix, direction, service) so a station whose suffix means a
    different direction/service (rare but real) forms its own group."""
    g = defaultdict(list)
    for r in recs:
        key = (r.get('suffix') or '?', r.get('direction'), r.get('service'))
        g[key].append(r)
    return g


def dedup_times(rec):
    seen = set(); out = []
    for t in rec['times']:
        a = to_abs(t)
        if a not in seen:
            seen.add(a); out.append(a)
    return sorted(out)


def early_time(ts, q=10):
    return float(np.percentile(ts, q)) if ts else None


def osm_order(line):
    global _OSM
    if _OSM is None:
        try:
            _OSM = json.load(open(os.path.join(DATA, 'beijing_subway_lines_stations_wgs84.json')))['lines']
        except Exception:
            _OSM = {}
    key = LINE_MAP.get(line)
    if key and key in _OSM:
        return [s['name'] for s in _OSM[key]['stations']]
    return None


def load_geometry():
    global _GEO
    if _GEO is None:
        _GEO = {}
        try:
            g = json.load(open(os.path.join(DATA, 'beijing_subway_lines_wgs84.geojson')))
            for f in g['features']:
                p = f['properties']
                key = p.get('ref') or p.get('name')
                _GEO.setdefault(key, []).append(f['geometry']['coordinates'])
        except Exception:
            pass
    return _GEO


def station_fraction(key, names):
    """Fractional distance (0..1) of each station along the line geometry."""
    coords = None
    for c in load_geometry().get(key, []):
        if coords is None or len(c) > len(coords):
            coords = c
    if not coords:
        return {}
    osm = osm_order_by_key(key)
    st = {s['name']: (s['lon'], s['lat']) for s in osm}
    kx = np.cos(np.radians(np.mean([p[1] for p in coords])))
    pts = [(p[0] * kx, p[1]) for p in coords]
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + np.hypot(pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1]))
    total = cum[-1] or 1.0
    out = {}
    for n in names:
        if n not in st:
            out[n] = None
            continue
        px, py = st[n][0] * kx, st[n][1]
        best = (1e18, 0.0)
        for i in range(1, len(pts)):
            ax, ay = pts[i-1]; bx, by = pts[i]
            dx, dy = bx-ax, by-ay
            L2 = dx*dx + dy*dy or 1e-12
            t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / L2))
            qx, qy = ax + t*dx, ay + t*dy
            d2 = (px-qx)**2 + (py-qy)**2
            if d2 < best[0]:
                best = (d2, (cum[i-1] + t*(cum[i]-cum[i-1])) / total)
        out[n] = best[1]
    return out


def osm_order_by_key(key):
    global _OSM
    if _OSM is None:
        try:
            _OSM = json.load(open(os.path.join(DATA, 'beijing_subway_lines_stations_wgs84.json')))['lines']
        except Exception:
            _OSM = {}
    return _OSM.get(key, {}).get('stations', [])


def refine_tau(T0, Ts, tau0, window=8, tol=2):
    """Refine a station's running-time offset around the geometric estimate.

    Picks the shift (within +/- window minutes of the geometric guess) that has
    the most matching departures; this absorbs real dwell/running differences
    and cumulative error, so a train is only truncated when a station genuinely
    has no corresponding departure (short turn), not because of a few minutes of
    drift.
    """
    if not T0 or not Ts:
        return tau0
    best = (-1, tau0)
    for d in np.arange(tau0 - window, tau0 + window + 0.5, 1.0):
        m = sum(1 for t0 in T0 if any(abs(x - (t0 + d)) <= tol for x in Ts))
        if m > best[0]:
            best = (m, float(d))
    return best[1]


def match_runs(order, stations, tau, tol=4):
    """Build each train's trajectory from the origin's departures.

    All trains share the same calibrated inter-station running times `tau`, so
    trajectories can never overtake one another.  A train is truncated at the
    LAST station where a matching departure exists (its short-turn terminus);
    interior misses (an OCR gap at one station) are bridged with the predicted
    time, so a train does not vanish mid-line.
    """
    origin = order[0]
    base = stations[origin]
    runs = []
    for t0 in base:
        last = -1
        for i, s in enumerate(order):
            pred = t0 + tau[s]
            if any(abs(x - pred) <= tol for x in stations[s]):
                last = i
        if last < 1:
            continue
        stops = {order[i]: int(round(t0 + tau[order[i]])) for i in range(last + 1)}
        runs.append(stops)
    return runs


# stations present in the timetables but missing from the OSM line relation
# (closed / under construction) -> insert after this station
EXTRA_AFTER = {'八角游乐园': '古城', '陶然桥': '永定门外', '红庙': '大望路'}


AVG_SPEED_KMH = 36.0   # typical metro average incl. dwell


def station_km(key, names):
    """Cumulative straight-line distance (km) between consecutive stations."""
    osm = osm_order_by_key(key)
    st = {s['name']: (s['lon'], s['lat']) for s in osm}
    lat0 = np.mean([v[1] for v in st.values()]) if st else 40.0
    kx = np.cos(np.radians(lat0))
    pts = []
    for n in names:
        if n in st:
            lon, lat = st[n]
            pts.append((lon * kx * 111.32, lat * 110.57))
        else:
            pts.append(None)
    known = [(i, p) for i, p in enumerate(pts) if p is not None]
    if len(known) < 2:
        return None
    for i, p in enumerate(pts):
        if p is None:
            lows = [v for v in known if v[0] <= i]
            highs = [v for v in known if v[0] >= i]
            lo = max(lows, key=lambda v: v[0]) if lows else known[0]
            hi = min(highs, key=lambda v: v[0]) if highs else known[-1]
            if lo[0] == hi[0]:
                pts[i] = lo[1]
            else:
                f = (i - lo[0]) / (hi[0] - lo[0])
                pts[i] = (lo[1][0] + f * (hi[1][0] - lo[1][0]),
                          lo[1][1] + f * (hi[1][1] - lo[1][1]))
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + float(np.hypot(b[0]-a[0], b[1]-a[1])))
    return {n: cum[i] for i, n in enumerate(names)}


def infer_group(line, suffix, recs, meta=None, osm=None):
    stations = {}
    for r in recs:
        ts = dedup_times(r)
        if ts:
            stations[r['station']] = ts
    if len(stations) < 2:
        return None
    present = set(stations)
    key = LINE_MAP.get(line)
    m = (meta or {}).get(suffix, {}) or {}
    if not isinstance(m, dict):
        m = {}
    direction = m.get('direction')

    # build station order along the line
    if osm:
        seq = [s for s in osm if s in present]
        for e in [s for s in stations if s not in osm]:
            anchor = EXTRA_AFTER.get(e)
            if anchor and anchor in seq:
                seq.insert(seq.index(anchor) + 1, e)
            else:
                seq.append(e)
        if not seq:
            seq = list(stations)
        # orient by the known direction terminal, else by early-service time
        if direction == osm[0]:
            order = list(reversed(seq))
        elif direction == osm[-1]:
            order = seq
        else:
            et = {n: early_time(stations[n]) for n in seq}
            order = seq if et[seq[-1]] >= et[seq[0]] else list(reversed(seq))
            direction = order[-1]
    else:
        order = sorted(stations, key=lambda n: early_time(stations[n]))
        direction = direction or order[-1]

    # tau from geometry distance / average speed (robust, physically plausible)
    km = station_km(key, order) if key else None
    if km and sum(1 for n in order if km.get(n) is not None) >= 2:
        vals = [(i, km[n]) for i, n in enumerate(order) if km.get(n) is not None]
        for i, n in enumerate(order):
            if km.get(n) is None:
                lo = max((v for v in vals if v[0] <= i), default=vals[0])
                hi = min((v for v in vals if v[0] >= i), default=vals[-1])
                km[n] = lo[1] if lo[0] == hi[0] else lo[1] + (i-lo[0])/(hi[0]-lo[0])*(hi[1]-lo[1])
        d0 = km[order[0]]
        tau = {n: abs(km[n] - d0) / AVG_SPEED_KMH * 60 for n in order}
        for a, b in zip(order, order[1:]):
            if tau[b] < tau[a]:
                tau[b] = tau[a]
        total = max(tau.values())
    else:
        total = 50.0
        tau = {n: i / (len(order) - 1) * total for i, n in enumerate(order)}

    # calibrate each station's offset against the real departures, then keep it
    # monotonic along the direction
    T0 = stations[order[0]]
    for s in order[1:]:
        tau[s] = refine_tau(T0, stations[s], tau[s])
    for a, b in zip(order, order[1:]):
        if tau[b] < tau[a]:
            tau[b] = tau[a]
    total = max(tau.values())

    runs = match_runs(order, stations, tau, tol=4)
    runs = [r for r in runs if len(r) >= 2]
    return dict(line=line, group=suffix,
                direction=direction, service=m.get('service'),
                station_order=order, tau={k: round(tau[k], 1) for k in order},
                total_travel=round(total, 1),
                n_stations=len(order), n_runs=len(runs),
                runs=[dict(stops=[dict(station=s, minute=r[s]) for s in order if s in r])
                      for r in runs])


def infer_line(line, meta=None):
    recs = load_line(line)
    if not recs:
        return []
    osm = osm_order(line)
    out = []
    for key, rs in sorted(group_by_suffix(recs).items(), key=lambda kv: str(kv[0])):
        suffix = key[0]
        g = infer_group(line, suffix, rs, meta, osm)
        if g:
            out.append(g)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--lines', default=None)
    a = ap.parse_args()
    lines = a.lines.split(',') if a.lines else [os.path.basename(p)[:-6]
             for p in sorted(glob.glob(os.path.join(PARSED, '*.jsonl')))]
    os.makedirs(OUT, exist_ok=True)
    allg = []
    for line in lines:
        meta = {}
        mp = os.path.join(PARSED, line, 'meta.json')
        if os.path.exists(mp):
            meta = json.load(open(mp))
        for g in infer_line(line, meta):
            allg.append(g)
            print(f"[{line}/{g['group']}] {g['n_stations']} stations, {g['n_runs']} runs, "
                  f"total={g['total_travel']}min dir={g['direction']} svc={g['service']}")
    with open(os.path.join(OUT, 'train_runs.jsonl'), 'w') as f:
        for g in allg:
            f.write(json.dumps(g, ensure_ascii=False) + '\n')
    print('wrote', os.path.join(OUT, 'train_runs.jsonl'), len(allg), 'groups')


if __name__ == '__main__':
    main()
