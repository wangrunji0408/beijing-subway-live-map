#!/usr/bin/env python3
"""Cross-validate the built datasets and emit validation_report.json.

Compares three independent sources:
  1. OSM route relations      -> beijing_subway_lines_stations_wgs84.json  (WGS84, geometry)
  2. Amap-derived station data -> beijing_subway_lines_stations_amap_gcj02.json (GCJ-02, stations)
  3. Mick235711 timetable repo -> data/beijing/*.json5 station lists (MIT, no coordinates)
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
osm = json.load(open(os.path.join(HERE, "beijing_subway_lines_stations_wgs84.json")))["lines"]
amap = json.load(open(os.path.join(HERE, "beijing_subway_lines_stations_amap_gcj02.json")))["lines"]

AMAP_KEY = {
    "1": "BJ-1", "2": "BJ-2", "3": "BJ-3", "4": "BJ-4", "5": "BJ-5", "6": "BJ-6", "7": "BJ-7",
    "8": "BJ-8", "9": "BJ-9", "10": "BJ-10", "11": "BJ-11", "12": "BJ-12", "13": "BJ-13",
    "14": "BJ-14", "15": "BJ-15", "16": "BJ-16", "17": "BJ-17", "18": "BJ-18", "19": "BJ-19",
    "Changping": "BJ-CHANGPING", "Fangshan": "BJ-FANGSHAN", "Yanfang": "BJ-YANFANG",
    "Yizhuang": "BJ-YIZHUANG", "S1": "BJ-S1", "Xijiao": "BJ-XIJIAO",
    "CapitalAirport": "BJ-AIRPORT", "DaxingAirport": "BJ-DZW",
}
MICK_FILE = {
    "1": "line1", "2": "line2", "3": "line3", "4": "line4", "5": "line5", "6": "line6",
    "7": "line7", "8": "line8", "9": "line9", "10": "line10", "11": "line11", "12": "line12",
    "13": "line13", "14": "line14", "15": "line15", "16": "line16", "17": "line17",
    "18": "line18", "19": "line19", "S1": "line-s1", "Yizhuang": "yizhuang-line",
    "Changping": "changping-line", "Fangshan": "fangshan-line", "Yanfang": "yanfang-line",
    "CapitalAirport": "capital-airport-express", "DaxingAirport": "daxing-airport-express",
    "Xijiao": "xijiao-line",
}

def norm(n):
    n = n.replace("站", "").replace("（", "(").replace("）", ")").strip()
    return re.sub(r"\(.*?\)", "", n).strip()

mick_lists = {}
for key, f in MICK_FILE.items():
    p = os.path.join("/tmp", f"mick_{f}.json5")
    if not os.path.exists(p):
        continue
    txt = open(p, encoding="utf-8").read()
    seg = txt.split("stations:", 1)[1].split("train_routes:", 1)[0]
    mick_lists[key] = re.findall(r'\{\s*name:\s*"([^"]+)"', seg)

report = {"sources": {
    "osm": {"file": "beijing_subway_lines_wgs84.geojson", "coord": "WGS84", "license": "ODbL 1.0",
            "geometry": True},
    "amap": {"file": "beijing_subway_stations_amap_gcj02.geojson", "coord": "GCJ-02",
             "license": "no explicit repo license; Amap draw API practice data", "geometry": False},
    "mick235711": {"repo": "https://github.com/Mick235711/Beijing-Subway-Tools", "coord": "none",
                   "license": "MIT", "geometry": False, "role": "station-name cross-check only"},
}, "lines": {}}

for key, d in osm.items():
    row = {"name": d["name"], "osm_stations": d["station_count"]}
    ak = AMAP_KEY.get(key)
    if ak and ak in amap:
        row["amap_stations"] = amap[ak]["station_count"]
        so = {norm(s["name"]) for s in d["stations"]}
        sa = {norm(s["name"]) for s in amap[ak]["stations"]}
        row["osm_only_vs_amap"] = sorted(so - sa)
        row["amap_only_vs_osm"] = sorted(sa - so)
    else:
        row["amap_stations"] = None
        row["amap_note"] = "not present as a separate line in the Amap snapshot (merged into line 1/4)"
    if key in mick_lists:
        row["mick_stations"] = len(mick_lists[key])
        so = {norm(s["name"]) for s in d["stations"]}
        sm = {norm(n) for n in mick_lists[key]}
        row["osm_only_vs_mick"] = sorted(so - sm)
        row["mick_only_vs_osm"] = sorted(sm - so)
    else:
        row["mick_stations"] = None
    row["geometry_km"] = None
    report["lines"][key] = row

# geometry length
import math
def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2 - p1, math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))
for f in json.load(open(os.path.join(HERE, "beijing_subway_lines_wgs84.geojson")))["features"]:
    k = f["properties"]["line_key"]
    g = f["geometry"]
    segs = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
    L = sum(sum(hav(a[1], a[0], b[1], b[0]) for a, b in zip(s, s[1:])) for s in segs) / 1000
    if k in report["lines"]:
        report["lines"][k]["geometry_km"] = round(L, 2)
        report["lines"][k]["geometry_type"] = g["type"]
        report["lines"][k]["coords"] = sum(len(s) for s in segs)

report["summary"] = {
    "osm_lines": len(osm),
    "osm_station_complexes": json.load(open(os.path.join(HERE, "beijing_subway_stations_wgs84.geojson")))["metadata"]["station_complex_count"],
    "osm_stop_records": sum(v["station_count"] for v in osm.values()),
    "amap_lines": len(amap),
    "amap_station_records": sum(v["station_count"] for v in amap.values()),
    "target_lines_present_osm": sorted([k for k in ["1","2","3","4","5","6","7","8","9","10","11","12","13","14","15","16","17","18","19","S1","Yizhuang","Batong","DaxingAirport","Fangshan","Changping","Yanfang","CapitalAirport"] if k in osm]),
    "not_separate_in_amap": ["Batong (merged into BJ-1)", "Daxing (merged into BJ-4)"],
}
with open(os.path.join(HERE, "validation_report.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
with open(os.path.join(HERE, "crosscheck_mick235711_stations.json"), "w", encoding="utf-8") as f:
    json.dump({"source": "https://github.com/Mick235711/Beijing-Subway-Tools",
               "license": "MIT", "files": MICK_FILE, "station_names": mick_lists}, f, ensure_ascii=False, indent=1)

print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
print("\nper-line OSM/Amap/Mick counts:")
for k, r in report["lines"].items():
    print(f"  {k:15s} {r['name']:8s} osm={r['osm_stations']:3d} amap={str(r['amap_stations']):>4s} "
          f"mick={str(r['mick_stations']):>4s} len={r['geometry_km']}km"
          + (f"  osm_only_vs_mick={r['osm_only_vs_mick']}" if r.get('osm_only_vs_mick') else ''))
