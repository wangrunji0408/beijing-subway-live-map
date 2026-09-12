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
import json, os, glob, sys, re, bisect
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
# published station-to-station track distances (北京市轨道交通运营管理有限公司);
# they bound how long a segment may legitimately take
SPACING_PATH = os.path.join(DATA, 'station_spacing', 'bjmoa_spacing.json')
FAST_LINES = {'大兴机场', '首都机场'}
MAX_SEG_KMH = 85.0     # metro rolling stock ceiling
MIN_SEG_KMH = 20.0     # slowest plausible RUNNING average
EXPRESS_KMH = 45.0     # the airport expresses average about this
DWELL_MAX = 1.5        # minutes of station dwell a segment may additionally take
MAX_TERMINUS_HOPS = 3  # how far past the last poster we may extrapolate
DWELL_MIN = 0.75       # a stop costs at least this long, so a segment cannot
                       # be shorter than DWELL_MIN + running time
_SPACING = None


def load_spacing():
    global _SPACING
    if _SPACING is None:
        _SPACING = {}
        try:
            raw = json.load(open(SPACING_PATH))
        except Exception:
            raw = {}
        for line, pairs in raw.items():
            d = {}
            for k, m in pairs.items():
                a, b = k.split('|')
                d[(_canon(a), _canon(b))] = m / 1000.0
            _SPACING[line] = d
    return _SPACING


MERGED_SPACING = {'4': ['大兴'], '1': ['八通']}


def seg_km(line, a, b):
    allsp = load_spacing()
    sp = allsp.get(line)
    d = dict(sp or {})
    for alt in MERGED_SPACING.get(line, []):
        d.update(allsp.get(alt) or {})
    v = d.get((_canon(a), _canon(b)))
    if v is not None:
        return v
    # the published table does not cover every hop (e.g. the airport loop's
    # return leg); fall back to the OSM straight-line distance, which still
    # gives the calibration a physical bound
    key = LINE_MAP.get(line, line)
    st = {_canon(x['name']): (x['lon'], x['lat']) for x in osm_order_by_key(key)}
    pa, pb = st.get(_canon(a)), st.get(_canon(b))
    if not pa or not pb:
        return None
    kx = np.cos(np.radians((pa[1] + pb[1]) / 2))
    km = float(np.hypot((pb[0] - pa[0]) * kx * 111.32, (pb[1] - pa[1]) * 110.57))
    return km * 1.15 if km > 0.05 else None
EXTRA_AFTER = {'陶然桥': '永定门外', '红庙': '大望路'}
# stations that trains currently run through without stopping (甩站); they have
# no OSM geometry and no published spacing, so keeping them in the diagram put a
# geometry-less stop between two real ones and trains vanished there
CLOSED_STATIONS = {'八角游乐园'}

# The airport end of the Capital Airport Express is a ONE-WAY loop:
# 三元桥 -> T3 -> T2 -> back to 三元桥.  The OSM relation lists T2 before T3,
# but inbound trains call at T3 first and then run from T2 straight back to
# 三元桥 (they do not pass T3 again).
ORDER_OVERRIDE = {('CapitalAirport', 1): ['首都机场3号航站楼', '首都机场2号航站楼',
                                          '三元桥', '东直门', '北新桥']}

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
         # the official spacing table spells the airport stops this way
         'T2航站楼': '首都机场2号航站楼',
         'T3航站楼': '首都机场3号航站楼',
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


def best_shift(T0, Ts, guess, lo=None, hi=None, window=25, tol=2, prev=None, seg_guess=None):
    """Offset with the most matching departures, searched around `guess`.

    `lo` is the physical floor (the previous station's offset): a train cannot
    reach a later station earlier, so offsets must be non-decreasing.  Searching
    inside that feasible range (instead of clamping afterwards) keeps every
    station on its own best alignment.  Ties break towards `guess`.
    """
    if not T0 or not Ts:
        return guess if lo is None else max(guess, lo)
    start = guess - window
    end = guess + window
    if lo is not None:
        start = max(start, lo)
    if hi is not None:
        end = min(end, hi)
    if start > end:            # feasible interval wins over the window
        start, end = (lo if lo is not None else guess), (hi if hi is not None else guess)
    # integer search: shifts are whole minutes, and a float step would let the
    # result drift past the feasible bound
    # Because headways are short, the match count saturates over a whole range
    # of shifts and cannot pick the right one on its own.  Ties are therefore
    # broken by the SEGMENT's own geometric estimate (not the cumulative one),
    # otherwise one station's over-estimate is inherited by the next segment.
    def cost(d):
        if prev is None or seg_guess is None:
            return abs(d - guess)
        return abs((d - prev) - seg_guess)

    best = (-1, float(min(max(guess, start), end)), 1e9)
    for d in range(int(np.floor(start - 1e-9)), int(np.ceil(end + 1e-9)) + 1):
        if lo is not None and d < lo - 1e-9:
            continue
        if hi is not None and d > hi + 1e-9:
            continue
        m = _count_matches(T0, Ts, d, tol)
        c = cost(d)
        if m > best[0] or (m == best[0] and c < best[2]):
            best = (m, float(d), c)
    return best[1]


def calibrate_tau(order, stations, tau_geo, line=None):
    """Calibrate every station offset against the real departures.

    The search is additionally bounded by the published track distance: a
    segment of L km cannot take less than L/85 h (85 km/h) nor more than L/6 h
    (6 km/h, a very long dwell).  Without that bound a regular headway lets the
    matcher lock onto a neighbouring slot and compress or stretch a segment
    (line 15 had 南法信->后沙峪, 4.6 km, timed at 1 minute).
    """
    T0 = stations[order[0]]
    fit = {order[0]: 0.0}
    prev = 0.0
    fast = line in FAST_LINES
    for i, s in enumerate(order[1:], start=1):
        km = seg_km(line, order[i - 1], s) if line else None
        seg_geo = tau_geo[s] - tau_geo[order[i - 1]]
        if not stations.get(s):
            # no poster here (the terminus): use the geometric running time
            run = max(seg_geo, (km / MAX_SEG_KMH * 60.0) if km else 0.0)
            prev = prev + DWELL_MIN + run      # dwell at the stop + running time
            fit[s] = prev
            continue
        if km and km > 0.05:
            hi_kmh = 160.0 if fast else MAX_SEG_KMH
            d_lo = prev + DWELL_MIN + km / hi_kmh * 60.0
            d_hi = prev + DWELL_MAX + km / MIN_SEG_KMH * 60.0
            d = best_shift(T0, stations[s], tau_geo[s], lo=d_lo, hi=d_hi,
                           prev=prev, seg_guess=seg_geo)
        else:
            d = best_shift(T0, stations[s], tau_geo[s], lo=prev,
                           prev=prev, seg_guess=seg_geo)
        fit[s] = d
        prev = d
    return fit


def match_runs(order, stations, tau, tol=4):
    """Every train uses the same calibrated tau, so no train can overtake
    another.  A train is truncated at the LAST station with a matching
    departure (its short-turn terminus); interior OCR gaps are bridged with the
    predicted time, so a train never vanishes mid-line.

    The terminus has no arrival poster (its board lists the opposite direction),
    so a train that reaches the LAST station that does have data continues to
    the end of the order; a train that short-turns earlier still stops early.
    """
    origin = order[0]
    base = stations[origin]
    data_idx = [i for i, s in enumerate(order) if stations.get(s)]
    last_data = max(data_idx) if data_idx else len(order) - 1
    runs = []
    for t0 in base:
        last = -1
        for i, s in enumerate(order):
            if not stations.get(s):
                continue
            pred = t0 + tau[s]
            if any(abs(x - pred) <= tol for x in stations[s]):
                last = i
        if last < 0:
            continue          # matched nothing at all
        if last >= last_data:
            last = len(order) - 1          # run through to the terminus
        runs.append({order[i]: int(round(t0 + tau[order[i]])) for i in range(last + 1)})
    return runs


def infer_group(line, sign, recs, meta=None, osm=None, segkey=None):
    merged = {}
    for r in recs:
        if r['station'] in CLOSED_STATIONS:
            continue          # 甩站：通过不停车
        ts = dedup_times(r)
        if ts:
            # the dataset was collected in several batches, so the same board
            # can appear twice; the file that was downloaded (and therefore
            # published) most recently wins when they are duplicates
            try:
                mt = os.path.getmtime(os.path.join(ROOT, r.get('source', '')))
            except OSError:
                mt = 0.0
            merged.setdefault(r['station'], []).append((ts, r['id'], mt))
    # Several posters can cover one station: one per service window (they must
    # be unioned), but also a "发车时刻表" and a "列车时刻表" pair that describe
    # the SAME trains (e.g. every Capital Airport Express stop).  A departure
    # from a different poster within a minute of one already kept is that same
    # train, so it is dropped; a minute gap inside one poster is real and kept.
    # Folding by CANONICAL name also merges "清河" with "清河站", which
    # otherwise put a second copy at the end of the station order that then
    # became the diagram's origin and corrupted the whole line.
    osm_name = {_canon(n): n for n in (osm or [])}
    by_canon = {}
    for k, v in merged.items():
        by_canon.setdefault(_canon(k), []).extend(v)
    stations = {}
    for k, versions in by_canon.items():
        # One station can carry several posters.  They are either COMPLEMENTARY
        # (different windows, e.g. 13-西直门-1 covers the morning and -2 the
        # afternoon: union them) or the SAME trains published twice - every
        # Capital Airport Express stop has a 发车时刻表 and a 列车时刻表 whose
        # times drift a few minutes apart while the train count matches.
        # Unioning the latter would double count, so a poster whose departures
        # mostly coincide with one already taken is dropped.
        kept_sets = []
        for ts, rid, _mt in sorted(versions, key=lambda x: (-x[2], -len(x[0]))):
            dup = False
            for other in kept_sets:
                a, b = len(ts), len(other)
                if abs(a - b) > 0.25 * max(a, b):
                    continue              # complementary windows, not a copy
                # rank alignment breaks as soon as one poster has an extra
                # train in an hour, so compare by nearest neighbour instead
                near = []
                for t in ts:
                    i = bisect.bisect_left(other, t)
                    cands = [other[j] for j in (i - 1, i, i + 1) if 0 <= j < len(other)]
                    if cands:
                        near.append(min(abs(c - t) for c in cands))
                if near and sorted(near)[len(near) // 2] <= 4:
                    dup = True            # same trains, republished
                    break
            if not dup:
                kept_sets.append(ts)
        base = []
        for ts in kept_sets:
            base.extend(ts)
        stations[osm_name.get(k, k)] = sorted(set(base))
    if not stations:
        return None      # a single station is fine: the terminus extension
                         # completes the order (e.g. the Sunday late-night table)
    present = set(stations)
    key = segkey or LINE_MAP.get(line)
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

    # posters stop one (sometimes two) stations short of the terminus, because
    # the terminus board only shows the departing direction; add the remaining
    # stations of this direction so trains are drawn all the way in
    if osm:
        pos_o = {_canon(n): i for i, n in enumerate(osm)}
        step = 1 if sign == 1 else -1
        term = osm[-1] if sign == 1 else osm[0]
        i = pos_o.get(_canon(order[-1]))
        extra = []
        if i is not None and _canon(order[-1]) != _canon(term):
            j = i + step
            while 0 <= j < len(osm) and len(extra) < MAX_TERMINUS_HOPS:
                extra.append(osm[j])
                j += step
            if extra and _canon(extra[-1]) != _canon(term):
                extra = []                 # gap too long: another group covers it
        for n in extra:
            if n not in stations:
                stations[n] = []
            order.append(n)

    ov = ORDER_OVERRIDE.get((key, sign))
    if ov:
        pos_ov = {_canon(n): i for i, n in enumerate(ov)}
        known = [n for n in order if _canon(n) in pos_ov]
        known.sort(key=lambda n: pos_ov[_canon(n)])
        extra = [n for n in order if _canon(n) not in pos_ov]
        order = known + extra

    km = station_km(key, order) if key else None
    if km and sum(1 for n in order if km.get(n) is not None) >= 2:
        vals = [(i, km[n]) for i, n in enumerate(order) if km.get(n) is not None]
        for i, n in enumerate(order):
            if km.get(n) is None:
                lo = max((v for v in vals if v[0] <= i), default=vals[0])
                hi = min((v for v in vals if v[0] >= i), default=vals[-1])
                km[n] = lo[1] if lo[0] == hi[0] else lo[1] + (i - lo[0]) / (hi[0] - lo[0]) * (hi[1] - lo[1])
        d0 = km[order[0]]
        # the airport expresses run far faster than the network average
        v = EXPRESS_KMH if line in FAST_LINES else AVG_SPEED_KMH
        tau = {n: abs(km[n] - d0) / v * 60 for n in order}
    else:
        tau = {n: i / max(1, len(order) - 1) * 50.0 for i, n in enumerate(order)}
    for a, b in zip(order, order[1:]):
        if tau[b] < tau[a]:
            tau[b] = tau[a]

    tau = calibrate_tau(order, stations, tau, line=line)
    total = max(tau.values())

    runs = match_runs(order, stations, tau, tol=4)
    runs = [r for r in runs if len(r) >= 2]
    _keep = {k: v for k, v in stations.items() if v}
    from collections import Counter as _C
    svc = m.get('service')
    if not svc:
        cc = _C(r.get('service') for r in recs if r.get('service'))
        svc = cc.most_common(1)[0][0] if cc else None
    if osm and sign in (1, -1):
        direction = osm[-1] if sign == 1 else osm[0]
    else:
        direction = (osm[-1] if osm else None)
    return dict(line=line, group=sign, _stations=_keep, _key=LINE_MAP.get(line, line),
                direction=m.get('direction') or direction,
                service=svc,
                station_order=order, tau={k: round(tau[k], 1) for k in order},
                total_travel=round(total, 1),
                n_stations=len(order), n_runs=len(runs),
                runs=[dict(stops=[dict(station=s, minute=r[s]) for s in order if s in r])
                      for r in runs])


def physical_lines():
    """{physical key: [timetable line names]} - 1号线 and 八通线 are one line on
    the ground, 4号线 and 大兴线 likewise, so their posters must be merged or
    each diagram stops at the boundary and the shared section gets no trains."""
    out = defaultdict(list)
    for p in sorted(glob.glob(os.path.join(PARSED, '*.jsonl'))):
        ln = os.path.basename(p)[:-6]
        k = LINE_MAP.get(ln)
        if k:
            out[k].append(ln)
    return out


def display_name(key, lines):
    """the name to show on the map: prefer the primary (non-suffix) line"""
    for ln in lines:
        if ln == key:
            return ln
    return sorted(lines, key=len)[0]


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


def infer_key(key, lines):
    """Build every diagram that lies on one physical line key."""
    recs = []
    for ln in lines:
        for r in load_line(ln):
            r = dict(r)
            r['_tline'] = ln
            recs.append(r)
    if not recs:
        return []
    osm = [s['name'] for s in osm_order_by_key(key)]
    disp = display_name(key, lines)
    out = []
    for gk, rs in sorted(group_records(key, recs, osm, key in LOOP_LINES).items(),
                         key=lambda kv: str(kv[0])):
        g = infer_group(disp, gk[0], rs, None, osm, segkey=key)
        if g:
            out.append(g)
    return out



def symmetrize(groups):
    """Give both directions of a station pair the same running time.

    The two directions are calibrated independently; when one poster carries
    noisy entries the matcher can settle two minutes away from the other
    (大望路->四惠 came out at 5 min while 四惠->大望路 is 3), and a train then
    crawls across the map.  Only pairs that disagree by SYM_TOL or more are
    pooled, and the affected groups are re-timed and rebuilt.
    """
    SYM_TOL = 2.0
    seg = defaultdict(list)
    for g in groups:
        key = g.get('_key')
        tau, o = g['tau'], g['station_order']
        for x, y in zip(o, o[1:]):
            seg[(key, x, y)].append(tau[y] - tau[x])
    ref = {}
    for (key, x, y), v in seg.items():
        w = seg.get((key, y, x))
        if not w:
            continue
        m1, m2 = _median(v), _median(w)
        if abs(m1 - m2) < SYM_TOL:
            continue
        dt = min(m1, m2)          # a too-long interval is the usual failure
        tl = line_of_key(key)
        km = seg_km(tl, x, y) if tl else None
        if km and km > 0.05:
            fast = key in FAST_LINES
            lo = DWELL_MIN + km / (160.0 if fast else MAX_SEG_KMH) * 60.0
            hi = DWELL_MAX + km / MIN_SEG_KMH * 60.0
            dt = min(max(dt, lo), hi)
        ref[(key, x, y)] = dt
        ref[(key, y, x)] = dt

    changed = 0
    for g in groups:
        key, o, tau = g.get('_key'), g['station_order'], g['tau']
        new, prev, moved = {o[0]: 0.0}, 0.0, False
        for x, y in zip(o, o[1:]):
            dt = ref.get((key, x, y))
            cur = tau.get(y, prev) - tau.get(x, 0.0)
            if dt is None or abs(dt - cur) < 0.5:
                dt = cur
            else:
                moved = True
            prev = prev + max(dt, 0.5)
            new[y] = prev
        if not moved:
            continue
        changed += 1
        runs = [r for r in match_runs(o, g['_stations'], new, tol=4) if len(r) >= 2]
        g['tau'] = {k: round(v, 1) for k, v in new.items()}
        g['total_travel'] = round(max(new.values()), 1)
        g['n_runs'] = len(runs)
        g['runs'] = [dict(stops=[dict(station=s, minute=r[s]) for s in o if s in r])
                     for r in runs]
    print(f"symmetrised {changed} groups")
    return groups


def _median(xs):
    xs = sorted(xs); n = len(xs)
    if not n: return 0.0
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def line_of_key(key):
    for ln, k in LINE_MAP.items():
        if k == key:
            return ln
    return None


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
    phys = physical_lines()
    if a.lines:
        want = set(lines)
        phys = {k: [l for l in ls] for k, ls in phys.items() if want & set(ls)}
    for key, ls in sorted(phys.items(), key=lambda kv: str(kv[0])):
        for g in infer_key(key, ls):
            allg.append(g)
            print(f"[{'+'.join(ls)}/{g['group']}] {g['n_stations']} stations, {g['n_runs']} runs, "
                  f"total={g['total_travel']}min dir={g['direction']} svc={g['service']}")
    allg = symmetrize(allg)
    with open(a.out, 'w') as f:
        for g in allg:
            f.write(json.dumps(g, ensure_ascii=False) + '\n')
    print('wrote', a.out, len(allg), 'groups')


if __name__ == '__main__':
    main()
