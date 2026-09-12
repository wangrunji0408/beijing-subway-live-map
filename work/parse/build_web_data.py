#!/usr/bin/env python3
"""Assemble web/data/network.json from OSM geometry + inferred train runs.

* Lines get real geometry (WGS84) and a display colour.
* Stations are snapped onto their line so the front-end can interpolate.
* Each inferred (line, direction, service) group becomes a set of runs whose
  stop minutes are aligned to the group's station order.
* Direction is resolved automatically by matching the inferred station order to
  the OSM station order (forward vs reverse); service is resolved from the file
  suffix unless a hand-written meta.json says otherwise.
"""
import json, os, glob, re
import numpy as np

ROOT = os.getcwd()
DATA = os.path.join(ROOT, 'work', 'data')
OUT = os.path.join(ROOT, 'web', 'data')
PARSED = os.path.join(ROOT, 'work', 'parsed')

# timetable folder -> OSM line key
LINE_MAP = {
    '1': '1', '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7', '8': '8',
    '9': '9', '10': '10', '11': '11', '12': '12', '13': '13', '14': '14', '15': '15',
    '16': '16', '17': '17', '18': '18', '19': '19', 'S1': 'S1',
    '亦庄': 'Yizhuang', '八通': '1', '大兴机场': 'DaxingAirport', '房山': 'Fangshan',
    '昌平': 'Changping', '燕房': 'Yanfang', '首都机场': 'CapitalAirport',
}

COLORS = {
    # official Beijing Subway line colours (DB11/T 657.2-2015),
    # from zh.wikipedia.org/wiki/Template:北京地铁颜色
    '1': '#A4343A', '2': '#004B87', '3': '#D90627', '4': '#008C95', '5': '#AA0061',
    '6': '#B58500', '7': '#FFC56E', '8': '#009B77', '9': '#97D700', '10': '#0092BC',
    '11': '#FF8674', '12': '#9C4F01', '13': '#F4DA40', '14': '#CA9A8E', '15': '#653279',
    '16': '#6BA539', '17': '#00ABAB', '18': '#685BC7', '19': '#D3A3C9', 'S1': '#A45A2A',
    '亦庄': '#D0006F', '八通': '#A4343A', '大兴机场': '#0049A5', '房山': '#D86018',
    '昌平': '#D986BA', '燕房': '#D86018', '首都机场': '#A192B2',
    'Yizhuang': '#D0006F', 'Batong': '#A4343A', 'DaxingAirport': '#0049A5',
    'Fangshan': '#D86018', 'Changping': '#D986BA', 'Yanfang': '#D86018',
    'CapitalAirport': '#A192B2', 'Xijiao': '#D22630', 'Daxing': '#008C95',
}

# suffix -> (direction_parity, service).  parity 1 = "first" direction.
SUFFIX_SERVICE = {'1': 'weekday', '2': 'weekday', '3': 'weekend', '4': 'weekend',
                  '5': 'weekend', '6': 'weekend', '7': 'weekday', '8': 'weekday'}


def load_osm():
    d = json.load(open(os.path.join(DATA, 'beijing_subway_lines_stations_wgs84.json')))
    return d['lines']


def load_geojson():
    g = json.load(open(os.path.join(DATA, 'beijing_subway_lines_wgs84.geojson')))
    out = {}
    for f in g['features']:
        p = f['properties']
        key = p.get('ref') or p.get('name')
        out.setdefault(key, []).append(f['geometry']['coordinates'])
    return out


def norm(s):
    return re.sub(r'[\s号线\(\)（）]', '', str(s))


def snap_stations(line, kx):
    """Add 'd' (0..1 distance along the path) to every station of a line."""
    pts = [(p[1] * kx, p[0]) for p in line['path']]   # (lon*kx, lat)
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + np.hypot(pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1]))
    total = cum[-1] or 1.0
    for s in line['stations']:
        px, py = s['lon'] * kx, s['lat']
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
        s['d'] = round(best[1], 5)


def build():
    osm = load_osm()
    geo = load_geojson()
    groups = [json.loads(l) for l in open(os.path.join(ROOT, 'work', 'out', 'train_runs.jsonl'))]

    # OSM station order per display line
    osm_order = {}
    for key, L in osm.items():
        osm_order[key] = [s['name'] for s in L['stations']]

    lines_out = {}
    used_keys = set()
    for tline, okey in LINE_MAP.items():
        if okey not in osm:
            continue
        used_keys.add(okey)
    for okey in used_keys:
        L = osm[okey]
        coords = None
        for c in geo.get(okey, []):
            if coords is None or len(c) > len(coords):
                coords = c
        if coords is None:
            # fall back to straight line through stations
            coords = [[s['lon'], s['lat']] for s in L['stations']]
        lines_out[okey] = dict(
            name=L.get('name') or okey, color=COLORS.get(okey, '#888'),
            path=[[p[1], p[0]] for p in coords],   # [lat, lon]
            stations=[dict(name=s['name'], lat=s['lat'], lon=s['lon'], seq=s['seq'])
                      for s in L['stations']])

    # snap stations onto their line for smooth train interpolation
    all_lats = [s['lat'] for L in lines_out.values() for s in L['stations']]
    kx = np.cos(np.radians(np.mean(all_lats))) if all_lats else 1.0
    for L in lines_out.values():
        snap_stations(L, kx)

    # attach each group to a display line and resolve direction
    out_groups = []
    for g in groups:
        okey = LINE_MAP.get(g['line'])
        if okey is None or okey not in lines_out:
            continue
        oo = osm_order[okey]
        order = g['station_order']
        # safety net: a station with no geometry on this line would make the
        # train interpolation return nothing and the train would disappear
        # between its neighbours, so drop such stops from the order
        geom = {s['name'] for s in lines_out[okey]['stations']}
        kept = [n for n in order if n in geom]
        if len(kept) >= 2 and len(kept) != len(order):
            order = kept
        # score forward vs reverse by the fraction of stations present in order
        def score(seq):
            pos = {norm(n): i for i, n in enumerate(seq)}
            idx = [pos.get(norm(n)) for n in order]
            idx = [i for i in idx if i is not None]
            if len(idx) < 2:
                return -1, False
            inv = sum(1 for a, b in zip(idx, idx[1:]) if b < a)
            return len(idx) - inv, inv <= (len(idx) - 1) / 2
        fs, fwd = score(oo)
        rs, rev = score(list(reversed(oo)))
        if rev and rs >= fs:
            direction = oo[0]
        else:
            direction = oo[-1]
        # infer_diagram resolves the service from the records; the suffix
        # table is only a legacy fallback
        service = g.get('service') or SUFFIX_SERVICE.get(g['group'], 'unknown')
        # hand-written meta wins
        mp = os.path.join(PARSED, g['line'], 'meta.json')
        if os.path.exists(mp):
            m = json.load(open(mp)).get(g['group'], {})
            if not isinstance(m, dict):
                m = {}
            if m.get('direction'):
                direction = m['direction']
            if m.get('service'):
                service = m['service']
        out_groups.append(dict(line=okey, tline=g['line'], group=g['group'],
                               direction=direction, service=service,
                               stations=order,
                               runs=[run_pairs(r, order) for r in g['runs']]))

    # drop runs that are too short / non monotonic
    cleaned = []
    for g in out_groups:
        runs = []
        for r in g['runs']:
            times = r[1::2]
            if len(times) < 2 or any(b < a for a, b in zip(times, times[1:])):
                continue
            runs.append(r)
        g['runs'] = runs
        if runs:
            cleaned.append(g)

    net = dict(generated='', lines=lines_out, groups=cleaned)
    os.makedirs(OUT, exist_ok=True)
    json.dump(net, open(os.path.join(OUT, 'network.json'), 'w'), ensure_ascii=False)
    print('lines', len(lines_out), 'groups', len(cleaned),
          'runs', sum(len(g['runs']) for g in cleaned))
    sz = os.path.getsize(os.path.join(OUT, 'network.json'))
    print('network.json', round(sz / 1e6, 2), 'MB')


def run_pairs(run, order):
    """Flatten a run to [station_index, minute, station_index, minute, ...]."""
    pos = {n: i for i, n in enumerate(order)}
    out = []
    for s in run['stops']:
        i = pos.get(s['station'])
        if i is not None:
            out += [i, int(s['minute'])]
    return out


if __name__ == '__main__':
    build()
