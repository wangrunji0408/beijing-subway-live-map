#!/usr/bin/env python3
"""Infer per-train diagrams (运行图) from per-station timetables.

Within one (physical direction, service) group the station timetables are time
shifts of each other: a train leaving the origin at t passes station s at
t + tau_s.  We recover:

  * station order  - the OSM order for that line, restricted to the stations
    present, oriented by the physical direction of travel;
  * tau_s          - geometry distance / average speed, then CALIBRATED against
    the real departures (the shift near the geometric guess with the most
    matches), so a train is only truncated at a genuine short-turn terminus;
  * train runs     - each origin departure, using the SAME calibrated tau for
    every train, so trajectories can never overtake one another; a run is a
    contiguous prefix of the station order.

Output: work/out/train_runs.jsonl, one JSON object per group.
"""
import json, os, glob, sys, re
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

AVG_SPEED_KMH = 36.0
LOOP_LINES = {'2', '10'}   # loop lines: the station order is cyclic
EXTRA_AFTER = {'八角游乐园': '古城', '陶然桥': '永定门外', '红庙': '大望路'}

_GEO = None
_OSM = None


def to_abs(t):
    return t['hour'] * 60 + t['minute']


def load_line(line):
    p = os.path.join(PARSED, f'{line}.jsonl')
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p)]


def _norm(s):
    n = re.sub(r'[\s\(\)（）]', '', str(s or ''))
    n = re.sub(r'号线$', '', n)
    n = re.sub(r'线$', '', n)
    n = re.sub(r'站$', '', n)
    return n


# station names that differ between the posters and the OSM relation
ALIAS = {'清河': '清河站',
         '2号航站楼': '首都机场2号航站楼',
         '3号航站楼': '首都机场3号航站楼',
         '首都机场': '首都机场2号航站楼'}


def _canon(s):
    n = _norm(s)
    return _norm(ALIAS.get(n, n))


# ---------------------------------------------------------------- grouping
def physical_sign(rec, osm, loop=False):
    """+1 forward along the OSM order, -1 backward, 0 unknown.

    On a loop line the order is cyclic, so "the next station" is not simply a
    larger index (e.g. on line 2 both neighbours of the last station are index
    0 and n-2); there the shorter arc decides the direction.
    """
    if not osm:
        return 0
    pos = {_canon(n): i for i, n in enumerate(osm)}
    si = pos.get(_canon(rec.get('station')))
    if si is None:
        return 0
    n = len(osm)
    for part in re.split(r'[、,，/]', str(rec.get('direction') or '')):
        di = pos.get(_canon(part))
        if di is None or di == si:
            continue
        if loop:
            return 1 if (di - si) % n <= n // 2 else -1
        return 1 if di > si else -1
    return 0


def group_records(line, recs, osm, loop=False):
    """One bucket per (physical direction, service).

    A terminus poster prints the DEPARTING direction, so a printed suffix can
    mean opposite directions at different stations.  Bucketing by physical
    direction keeps every train sharing a track in one group, preventing
    cross-group overtaking.
    """
    from collections import Counter
    signs = [(r, physical_sign(r, osm, loop)) for r in recs]
    maj = {}
    for r, sg in signs:
        if sg:
            maj.setdefault((r.get('suffix'), r.get('service')), Counter())[sg] += 1
    buckets = defaultdict(list)
    for r, sg in signs:
        if not sg:
            c = maj.get((r.get('suffix'), r.get('service')))
            if c:
                sg = c.most_common(1)[0][0]
        buckets[(sg, r.get('service'))].append(r)
    out = {}
    for k in [k for k in list(buckets) if k[0] == 0]:
        svc = k[1]
        cands = [kk for kk in buckets if kk[1] == svc and kk[0] != 0]
        if cands:
            tgt = max(cands, key=lambda kk: len(buckets[kk]))
            buckets[tgt] += buckets.pop(k)
        else:
            out[k] = buckets.pop(k)
    out.update(buckets)
    return out


# ---------------------------------------------------------------- times
def dedup_times(rec):
    seen = set(); out = []
    for t in rec['times']:
        a = to_abs(t)
        if a not in seen:
            seen.add(a); out.append(a)
    return sorted(out)


def early_time(ts, q=10):
    return float(np.percentile(ts, q)) if ts else None


# ---------------------------------------------------------------- geometry
def osm_order_by_key(key):
    global _OSM
    if _OSM is None:
        try:
            _OSM = json.load(open(os.path.join(DATA, 'beijing_subway_lines_stations_wgs84.json')))['lines']
        except Exception:
            _OSM = {}
    return _OSM.get(key, {}).get('stations', [])


def osm_order(line):
    key = LINE_MAP.get(line)
    return [s['name'] for s in osm_order_by_key(key)] if key else None


def station_km(key, names):
    """Cumulative straight-line distance (km) from the origin along the order."""
    osm = osm_order_by_key(key)
    st = {_canon(x['name']): (x['lon'], x['lat']) for x in osm}
    lat0 = np.mean([v[1] for v in st.values()]) if st else 40.0
    kx = np.cos(np.radians(lat0))
    pts = []
    for n in names:
        if _canon(n) in st:
            lon, lat = st[_canon(n)]
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
    for p, q in zip(pts, pts[1:]):
        cum.append(cum[-1] + float(np.hypot(q[0] - p[0], q[1] - p[1])))
    return {n: cum[i] for i, n in enumerate(names)}


# ---------------------------------------------------------------- diagram
def _count_matches(T0, Ts, d, tol=2):
    return sum(1 for t0 in T0 if any(abs(x - (t0 + d)) <= tol for x in Ts))


def best_shift(T0, Ts, guess, lo=None, window=25, tol=2):
    """Offset with the most matching departures, searched around `guess`.

    `lo` is the physical floor (the previous station's offset): a train cannot
    reach a later station earlier, so offsets must be non-decreasing.  Searching
    inside that feasible range (instead of clamping afterwards) keeps every
    station on its own best alignment.  Ties break towards `guess`.
    """
    if not T0 or not Ts:
        return guess if lo is None else max(guess, lo)
    start = guess - window
    if lo is not None:
        start = max(start, lo)
    best = (-1, max(guess, start), 1e9)
    for d in np.arange(start, guess + window + 0.5, 1.0):
        if lo is not None and d < lo - 1e-9:
            continue
        m = _count_matches(T0, Ts, d, tol)
        if m > best[0] or (m == best[0] and abs(d - guess) < best[2]):
            best = (m, float(d), abs(d - guess))
    return best[1]


def calibrate_tau(order, stations, tau_geo):
    """Calibrate every station offset against the real departures, keeping the
    sequence non-decreasing (each station searched inside the feasible range)."""
    T0 = stations[order[0]]
    fit = {order[0]: 0.0}
    prev = 0.0
    for s in order[1:]:
        prev = best_shift(T0, stations[s], tau_geo[s], lo=prev)
        fit[s] = prev
    return fit


def match_runs(order, stations, tau, tol=4):
    """Every train uses the same calibrated tau, so no train can overtake
    another.  A train is truncated at the LAST station with a matching
    departure (its short-turn terminus); interior OCR gaps are bridged with the
    predicted time, so a train never vanishes mid-line."""
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
        runs.append({order[i]: int(round(t0 + tau[order[i]])) for i in range(last + 1)})
    return runs


def infer_group(line, sign, recs, meta=None, osm=None):
    merged = {}
    for r in recs:
        ts = dedup_times(r)
        if ts:
            merged.setdefault(r['station'], []).extend(ts)
    # several posters can cover one station (e.g. one per service window); their
    # departures must be unioned, not overwritten
    stations = {k: sorted(set(v)) for k, v in merged.items()}
    if len(stations) < 2:
        return None
    present = set(stations)
    key = LINE_MAP.get(line)
    m = (meta or {}).get(sign, {}) or {}
    if not isinstance(m, dict):
        m = {}
    if osm:
        canon = {_canon(n): n for n in present}
        seq = [canon[_canon(s)] for s in osm if _canon(s) in canon]
        seen = set(seq)
        for e in [s for s in stations if s not in seen]:
            anchor = EXTRA_AFTER.get(e)
            if anchor and anchor in seq:
                seq.insert(seq.index(anchor) + 1, e)
            else:
                seq.append(e)
        if not seq:
            seq = list(stations)
        if sign == -1:
            order = list(reversed(seq))
        elif sign == 1:
            order = seq
        else:
            et = {n: early_time(stations[n]) for n in seq}
            order = seq if et[seq[-1]] >= et[seq[0]] else list(reversed(seq))
    else:
        order = sorted(stations, key=lambda n: early_time(stations[n]))

    km = station_km(key, order) if key else None
    if km and sum(1 for n in order if km.get(n) is not None) >= 2:
        vals = [(i, km[n]) for i, n in enumerate(order) if km.get(n) is not None]
        for i, n in enumerate(order):
            if km.get(n) is None:
                lo = max((v for v in vals if v[0] <= i), default=vals[0])
                hi = min((v for v in vals if v[0] >= i), default=vals[-1])
                km[n] = lo[1] if lo[0] == hi[0] else lo[1] + (i - lo[0]) / (hi[0] - lo[0]) * (hi[1] - lo[1])
        d0 = km[order[0]]
        tau = {n: abs(km[n] - d0) / AVG_SPEED_KMH * 60 for n in order}
    else:
        tau = {n: i / max(1, len(order) - 1) * 50.0 for i, n in enumerate(order)}
    for a, b in zip(order, order[1:]):
        if tau[b] < tau[a]:
            tau[b] = tau[a]

    tau = calibrate_tau(order, stations, tau)
    total = max(tau.values())

    runs = match_runs(order, stations, tau, tol=4)
    runs = [r for r in runs if len(r) >= 2]
    from collections import Counter as _C
    svc = m.get('service')
    if not svc:
        cc = _C(r.get('service') for r in recs if r.get('service'))
        svc = cc.most_common(1)[0][0] if cc else None
    if osm and sign in (1, -1):
        direction = osm[-1] if sign == 1 else osm[0]
    else:
        direction = (osm[-1] if osm else None)
    return dict(line=line, group=sign,
                direction=m.get('direction') or direction,
                service=svc,
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
    loop = line in LOOP_LINES
    for key, rs in sorted(group_records(line, recs, osm, loop).items(), key=lambda kv: str(kv[0])):
        g = infer_group(line, key[0], rs, meta, osm)
        if g:
            out.append(g)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--lines', default=None)
    ap.add_argument('--out', default=os.path.join(OUT, 'train_runs.jsonl'))
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
    with open(a.out, 'w') as f:
        for g in allg:
            f.write(json.dumps(g, ensure_ascii=False) + '\n')
    print('wrote', a.out, len(allg), 'groups')


if __name__ == '__main__':
    main()
