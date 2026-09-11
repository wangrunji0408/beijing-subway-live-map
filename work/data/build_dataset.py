#!/usr/bin/env python3
"""Build Beijing Subway line geometry + station point datasets from OpenStreetMap.

Source data: OpenStreetMap via Overpass API (raw/ov_routes_geom.json,
raw/ov_extra.json, raw/ov_stations_broad.json).  OSM coordinates are
WGS84 / EPSG:4326.

Line geometry comes from OSM route relations (ordered way members).
Stations come from the route relations' stop node members; a few stations
that exist as OSM station nodes but are missing from a route relation's
stop list (e.g. the five Line 18 stations opened 2025-12-27) are recovered
by snapping station nodes that lie within 60 m of the line geometry.
Every recovered station is flagged with source="osm_station_node_gapfill".

Outputs (in this directory):
  beijing_subway_lines_wgs84.geojson         LineString / MultiLineString per line
  beijing_subway_stations_wgs84.geojson      merged station complexes (Point)
  beijing_subway_stops_by_line_wgs84.geojson per-line ordered stop points
  beijing_subway_lines_stations_wgs84.json   line_key -> [station objects]
  beijing_subway_lines_gcj02.geojson         GCJ-02 derived from the WGS84 lines
  beijing_subway_stations_gcj02.geojson      GCJ-02 derived from the WGS84 stations
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")

# line_key, chinese name, overpass relation id, ref, note
LINES = [
    ("1",            "1号线",        1667139,  "1",  "OSM relation covers 1号线+八通线 (环球度假区-苹果园)"),
    ("2",            "2号线",        1667237,  "2",  "loop"),
    ("3",            "3号线",        18420549, "3",  "opened 2024-12-15"),
    ("4",            "4号线",        2083779,  "4",  "OSM relation covers 4号线+大兴线 (安河桥北-天宫院)"),
    ("5",            "5号线",        1721064,  "5",  ""),
    ("6",            "6号线",        4625141,  "6",  ""),
    ("7",            "7号线",        4623397,  "7",  ""),
    ("8",            "8号线",        1721068,  "8",  ""),
    ("9",            "9号线",        2674583,  "9",  ""),
    ("10",           "10号线",       1721076,  "10", "loop"),
    ("11",           "11号线",       13623627, "11", ""),
    ("12",           "12号线",       18441519, "12", "opened 2024-12-15"),
    ("13",           "13号线",       1667376,  "13", ""),
    ("14",           "14号线",       4611276,  "14", ""),
    ("15",           "15号线",       1350597,  "15", ""),
    ("16",           "16号线",       7800400,  "16", ""),
    ("17",           "17号线",       13625144, "17", ""),
    ("18",           "18号线",       20010820, "18", "opened 2025-12-27 (OSM relation stop list was incomplete)"),
    ("19",           "19号线",       13625326, "19", ""),
    ("S1",           "S1线",         8008812,  "S1", "monorail"),
    ("Yizhuang",     "亦庄线",       2201487,  "24", ""),
    ("Batong",       "八通线",       1667272,  "1E", "also included in line 1 relation"),
    ("DaxingAirport","大兴机场线",   10136948, None, ""),
    ("Fangshan",     "房山线",       1721084,  "25", ""),
    ("Changping",    "昌平线",       2111424,  "27", ""),
    ("Yanfang",      "燕房线",       12798054, "25S",""),
    ("CapitalAirport","首都机场线",  2062998,  "L1", "direction 北新桥->T2 (includes Terminal 3)"),
    # extras / branches
    ("Xijiao",       "西郊线",       8008876,  "西郊","light rail (extra)"),
    ("Daxing",       "大兴线",       2684710,  "4S", "branch of line 4 (extra)"),
]

R = 6371000.0
LAT0, LON0 = 39.9, 116.4

def hav(a, b, c, d):
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2 - p1, math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))

def xy(lat, lon):
    return ((lon - LON0) * 111320.0 * math.cos(math.radians(LAT0)), (lat - LAT0) * 110540.0)

def is_rail_station(t):
    rail, st = t.get("railway"), t.get("station")
    if rail in ("station", "halt", "tram_stop"):
        return True
    if st in ("subway", "light_rail", "monorail", "train", "funicular"):
        return True
    if t.get("subway") == "yes" or t.get("train") == "yes" or t.get("light_rail") == "yes" or t.get("monorail") == "yes":
        return True
    return False

def is_metro(t):
    if t.get("station") in ("subway", "light_rail", "monorail"):
        return True
    return t.get("subway") == "yes" or t.get("light_rail") == "yes" or t.get("monorail") == "yes"

# ---------------------------------------------------------------- load raw
routes = {}
for fn in ("ov_routes_geom.json", "ov_extra.json"):
    p = os.path.join(RAW, fn)
    if not os.path.exists(p):
        continue
    for e in json.load(open(p))["elements"]:
        if e["type"] == "relation":
            routes[e["id"]] = e
st_els = json.load(open(os.path.join(RAW, "ov_stations_broad.json")))["elements"]

cands = []
for e in st_els:
    t = e.get("tags", {})
    if not is_rail_station(t):
        continue
    lat = e.get("lat") if e.get("lat") is not None else (e.get("center") or {}).get("lat")
    lon = e.get("lon") if e.get("lon") is not None else (e.get("center") or {}).get("lon")
    if lat is None or lon is None or "name" not in t:
        continue
    cands.append({
        "osm": f"{e['type']}/{e['id']}", "osm_id": e["id"], "osm_type": e["type"],
        "lat": lat, "lon": lon, "name": t["name"], "name_en": t.get("name:en"),
        "station": t.get("station"), "railway": t.get("railway"), "is_metro": is_metro(t),
    })
print(f"rail-station candidates: {len(cands)}", file=sys.stderr)

def nearest(lat, lon):
    best, bd = None, 1e18
    for s in cands:
        d = hav(lat, lon, s["lat"], s["lon"])
        if d < bd:
            bd, best = d, s
    return best, bd

def assemble(way_geoms, tol=2e-5):
    """Concatenate ordered way geometries into continuous segments."""
    segs, cur = [], None
    for geom in way_geoms:
        pts = [(p["lat"], p["lon"]) for p in geom]
        if not pts:
            continue
        if cur is None:
            cur = pts
            continue
        def close(a, b):
            return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol
        if close(cur[-1], pts[0]):
            cur.extend(pts[1:])
        elif close(cur[-1], pts[-1]):
            cur.extend(list(reversed(pts))[1:])
        elif close(cur[0], pts[-1]):
            cur = pts[:-1] + cur
        elif close(cur[0], pts[0]):
            cur = list(reversed(pts))[:-1] + cur
        else:
            segs.append(cur)
            cur = pts
    if cur:
        segs.append(cur)
    return segs

def build_polyline(segs):
    """Return (flat list of (x,y) metres, cumulative chainage list)."""
    pts, cum = [], [0.0]
    for s in segs:
        for i, (lat, lon) in enumerate(s):
            p = xy(lat, lon)
            if pts and i == 0 and abs(p[0] - pts[-1][0]) < 0.5 and abs(p[1] - pts[-1][1]) < 0.5:
                continue
            if pts:
                cum.append(cum[-1] + math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]))
            pts.append(p)
    return pts, cum

def project(pts, cum, lat, lon):
    """Return (chainage_m, perpendicular_distance_m) of a point on the polyline."""
    px, py = xy(lat, lon)
    best = (0.0, 1e18)
    for i in range(len(pts) - 1):
        ax, ay = pts[i]; bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        cx, cy = ax + t * dx, ay + t * dy
        d = math.hypot(px - cx, py - cy)
        if d < best[1]:
            best = (cum[i] + t * math.sqrt(L2), d)
    return best

CLOSED_MARKERS = ("在建", "封闭", "改造", "未开通", "规划", "暂缓")
def norm_name(n):
    return n.replace("站", "").replace("（", "(").replace("）", ")").strip()

line_features, stop_features, by_line = [], [], {}

# ---- pass 1: geometry + stations from route-relation stop members
records = []
all_stop_coords = []
for key, name, rid, ref, note in LINES:
    rel = routes.get(rid)
    if rel is None:
        print(f"WARN missing relation {rid} for {key}", file=sys.stderr)
        continue
    tags = rel.get("tags", {})
    way_geoms = [m.get("geometry", []) for m in rel["members"]
                 if m["type"] == "way" and m.get("role", "") in ("", None) and m.get("geometry")]
    segs = assemble(way_geoms)
    if len(segs) == 1:
        geom = {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in segs[0]]}
    else:
        geom = {"type": "MultiLineString", "coordinates": [[[lon, lat] for lat, lon in s] for s in segs]}
    stops = [m for m in rel["members"] if m["type"] == "node"
             and str(m.get("role", "")).startswith("stop") and m.get("lat") is not None]
    pts, cum = build_polyline(segs)
    entries = []
    for m in stops:
        s, d = nearest(m["lat"], m["lon"])
        ch, _ = project(pts, cum, s["lat"], s["lon"])
        entries.append({"name": s["name"], "name_en": s.get("name_en"), "lat": s["lat"], "lon": s["lon"],
                        "osm_station": s["osm"], "match_dist_m": round(d), "chainage": ch,
                        "source": "osm_route_stop"})
    for e in entries:
        all_stop_coords.append((key, e["lat"], e["lon"], e["name"]))
    records.append(dict(key=key, name=name, ref=ref, rid=rid, note=note, tags=tags,
                        geom=geom, segs=segs, way_geoms=way_geoms, pts=pts, cum=cum, entries=entries))

# ---- pass 2: gap fill from OSM station nodes, guarded against duplicates /
#             other lines' stations / closed or under-construction stations
for rec in records:
    key, entries = rec["key"], rec["entries"]
    added = []
    for s in cands:
        if not s["is_metro"]:
            continue
        if any(mk in s["name"] for mk in CLOSED_MARKERS):
            continue
        ch, dist = project(rec["pts"], rec["cum"], s["lat"], s["lon"])
        if dist > 60:
            continue
        if any(hav(s["lat"], s["lon"], e["lat"], e["lon"]) < 150 for e in entries):
            continue                                  # duplicate of this line's own station
        if any(k != key and hav(s["lat"], s["lon"], la, lo) < 150 for k, la, lo, _ in all_stop_coords):
            continue                                  # belongs to another line (or duplicate node)
        if any(norm_name(s["name"]) == norm_name(e["name"]) for e in entries):
            continue
        added.append({"name": s["name"], "name_en": s.get("name_en"), "lat": s["lat"], "lon": s["lon"],
                      "osm_station": s["osm"], "match_dist_m": round(dist), "chainage": ch,
                      "source": "osm_station_node_gapfill"})
    entries.extend(added)
    entries.sort(key=lambda e: e["chainage"])
    # de-duplicate loop-closure / repeated stations by name
    seen, dedup = set(), []
    for e in entries:
        n = norm_name(e["name"])
        if n in seen:
            continue
        seen.add(n)
        dedup.append(e)
    rec["entries"] = dedup
    rec["added"] = len(added)

# ---- pass 3: emit features
for rec in records:
    key, name, entries = rec["key"], rec["name"], rec["entries"]
    line_features.append({
        "type": "Feature", "geometry": rec["geom"],
        "properties": {
            "line_key": key, "name": name, "name_zh": name, "name_en": rec["tags"].get("name:en"),
            "ref": rec["ref"], "osm_relation": rec["rid"], "osm_name": rec["tags"].get("name"),
            "station_count": len(entries), "way_count": len(rec["way_geoms"]),
            "note": rec["note"], "coord_system": "WGS84 (EPSG:4326)",
        },
    })
    seq = []
    for i, e in enumerate(entries, 1):
        stop_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(e["lon"], 7), round(e["lat"], 7)]},
            "properties": {
                "line_key": key, "line_name": name, "seq": i,
                "name": e["name"], "name_en": e["name_en"],
                "osm_station": e["osm_station"], "match_dist_m": e["match_dist_m"],
                "source": e["source"], "coord_system": "WGS84 (EPSG:4326)",
            },
        })
        seq.append({"seq": i, "name": e["name"], "name_en": e["name_en"],
                    "lat": round(e["lat"], 7), "lon": round(e["lon"], 7),
                    "osm_station": e["osm_station"], "source": e["source"]})
    by_line[key] = {"name": name, "name_en": rec["tags"].get("name:en"), "ref": rec["ref"],
                    "osm_relation": rec["rid"], "coord_system": "WGS84 (EPSG:4326)",
                    "station_count": len(seq), "stations": seq}
    print(f"{key:14s} {name:8s} ways={len(rec['way_geoms']):3d} segs={len(rec['segs']):2d} "
          f"stations={len(entries):3d} (gapfilled {rec['added']})", file=sys.stderr)


# ------------------------------------------------- merge station complexes
parent = list(range(len(stop_features)))
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[rb] = ra

coords = [f["geometry"]["coordinates"] for f in stop_features]
for i in range(len(coords)):
    for j in range(i + 1, len(coords)):
        if abs(coords[i][0] - coords[j][0]) > 0.006 or abs(coords[i][1] - coords[j][1]) > 0.006:
            continue
        if hav(coords[i][1], coords[i][0], coords[j][1], coords[j][0]) <= 400:
            union(i, j)

groups = {}
for i, f in enumerate(stop_features):
    groups.setdefault(find(i), []).append(f)

station_features = []
for members in groups.values():
    names, lines, line_names, osm_ids = [], set(), [], set()
    for m in members:
        for n in (m["properties"]["name"], m["properties"]["name_en"]):
            if n and n not in names:
                names.append(n)
        lines.add(m["properties"]["line_key"])
        if m["properties"]["line_name"] not in line_names:
            line_names.append(m["properties"]["line_name"])
        osm_ids.add(m["properties"]["osm_station"])
    lat = sum(m["geometry"]["coordinates"][1] for m in members) / len(members)
    lon = sum(m["geometry"]["coordinates"][0] for m in members) / len(members)
    en = next((m["properties"]["name_en"] for m in members if m["properties"]["name_en"]), None)
    station_features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
        "properties": {
            "name": members[0]["properties"]["name"], "name_zh": members[0]["properties"]["name"],
            "name_en": en, "aliases": names, "lines": sorted(lines), "line_names": line_names,
            "osm_station_ids": sorted(osm_ids), "coord_system": "WGS84 (EPSG:4326)",
        },
    })
station_features.sort(key=lambda f: f["properties"]["name"])

# ------------------------------------------------- GCJ-02 (derived)
def out_of_china(lat, lon):
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)
def _tf_lat(x, y):
    r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    r += (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
    r += (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    return r
def _tf_lon(x, y):
    r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    r += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    r += (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
    r += (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    return r
def wgs84_to_gcj02(lat, lon):
    if out_of_china(lat, lon):
        return lat, lon
    a, ee = 6378245.0, 0.00669342162296594323
    dlat, dlon = _tf_lat(lon - 105.0, lat - 35.0), _tf_lon(lon - 105.0, lat - 35.0)
    rlat = math.radians(lat)
    magic = 1 - ee * math.sin(rlat) ** 2
    sq = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sq) * math.pi)
    dlon = (dlon * 180.0) / (a / sq * math.cos(rlat) * math.pi)
    return lat + dlat, lon + dlon

def convert_geom(g):
    if g["type"] == "Point":
        la, lo = wgs84_to_gcj02(g["coordinates"][1], g["coordinates"][0])
        return {"type": "Point", "coordinates": [round(lo, 7), round(la, 7)]}
    if g["type"] == "LineString":
        out = []
        for lon, lat in g["coordinates"]:
            la, lo = wgs84_to_gcj02(lat, lon)
            out.append([round(lo, 7), round(la, 7)])
        return {"type": "LineString", "coordinates": out}
    if g["type"] == "MultiLineString":
        out = []
        for seg in g["coordinates"]:
            s = []
            for lon, lat in seg:
                la, lo = wgs84_to_gcj02(lat, lon)
                s.append([round(lo, 7), round(la, 7)])
            out.append(s)
        return {"type": "MultiLineString", "coordinates": out}
    raise ValueError(g["type"])

def dump(path, obj):
    with open(os.path.join(HERE, path), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", path, os.path.getsize(os.path.join(HERE, path)), "bytes", file=sys.stderr)

meta = {
    "name": "Beijing Subway lines and stations",
    "source": "OpenStreetMap via Overpass API",
    "source_url": "https://overpass.openstreetmap.fr/api/interpreter (Overpass API, OSM data)",
    "osm_copyright": "© OpenStreetMap contributors",
    "license": "Open Database License (ODbL) 1.0",
    "coord_system": "WGS84 (EPSG:4326)",
    "line_count": len(line_features),
    "station_complex_count": len(station_features),
    "stop_count": len(stop_features),
}
dump("beijing_subway_lines_wgs84.geojson", {"type": "FeatureCollection", "metadata": meta, "features": line_features})
dump("beijing_subway_stations_wgs84.geojson", {"type": "FeatureCollection", "metadata": meta, "features": station_features})
dump("beijing_subway_stops_by_line_wgs84.geojson", {"type": "FeatureCollection", "metadata": meta, "features": stop_features})
dump("beijing_subway_lines_stations_wgs84.json", {"metadata": meta, "lines": by_line})

gcj_meta = dict(meta, coord_system="GCJ-02 (Mars, derived from WGS84 via the standard eviltransform algorithm)",
                note="Derived by coordinate transform, not an independent source.")
dump("beijing_subway_lines_gcj02.geojson", {"type": "FeatureCollection", "metadata": gcj_meta,
     "features": [{"type": "Feature", "geometry": convert_geom(f["geometry"]),
                   "properties": dict(f["properties"], coord_system="GCJ-02")} for f in line_features]})
dump("beijing_subway_stations_gcj02.geojson", {"type": "FeatureCollection", "metadata": gcj_meta,
     "features": [{"type": "Feature", "geometry": convert_geom(f["geometry"]),
                   "properties": dict(f["properties"], coord_system="GCJ-02")} for f in station_features]})

print(f"lines={len(line_features)} station_complexes={len(station_features)} stops={len(stop_features)}", file=sys.stderr)
