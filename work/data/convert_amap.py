#!/usr/bin/env python3
"""Convert the Amap-derived Beijing subway station dataset (GCJ-02) to GeoJSON.

Source : https://github.com/sphynxlee/bj-subway-typing  (public/data/metro.json)
Upstream: Amap subway draw API  https://map.amap.com/subway/index.html?uid=1100
Format : GCJ-02 ("Mars") coordinates, 27 lines, stations only (no geographic
         line geometry; the upstream `segments` field is a station-id order,
         and the raw Amap draw file stores line polylines as canvas pixels).

Outputs:
  beijing_subway_stations_amap_gcj02.geojson       Point per station
  beijing_subway_lines_stations_amap_gcj02.json    cleaned line -> stations
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw", "amap_metro_beijing_gcj02.json")
src = json.load(open(RAW, encoding="utf-8"))

features, by_line, seen_ids = [], {}, set()
for ln in src["lines"]:
    key = ln["id"]
    stations = []
    for st in ln.get("stations", []):
        lon, lat = st["lon"], st["lat"]
        props = {
            "line_key": key, "line_id": ln.get("lineId"), "line_name": ln.get("lineName"),
            "color": ln.get("color"), "seq": st.get("sequence"),
            "name": st.get("nameZh"), "name_zh": st.get("nameZh"), "name_en": st.get("nameEn"),
            "amap_station_id": st.get("stationId") or st.get("id"),
            "operator": ln.get("operatorName"),
            "coord_system": "GCJ-02",
        }
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props})
        stations.append({"seq": st.get("sequence"), "name": st.get("nameZh"), "name_en": st.get("nameEn"),
                         "lat": lat, "lon": lon, "amap_station_id": props["amap_station_id"]})
        seen_ids.add(props["amap_station_id"])
    by_line[key] = {"line_id": ln.get("lineId"), "name": ln.get("lineName"), "color": ln.get("color"),
                    "operator": ln.get("operatorName"), "coord_system": "GCJ-02",
                    "station_count": len(stations), "stations": stations}

meta = {
    "name": "Beijing Subway stations (Amap-derived)",
    "source": src.get("source"),
    "source_url": src.get("sourceUrl"),
    "repo": "https://github.com/sphynxlee/bj-subway-typing",
    "repo_data_path": "public/data/metro.json",
    "license": src.get("license"),
    "license_note": "The upstream repository ships no LICENSE file; the JSON self-describes as practice data derived from the Amap subway draw API. Treat as source-available reference data, not a redistributable open-data license.",
    "generatedAt": src.get("generatedAt"),
    "coordinateSystem": "GCJ-02",
    "line_count": len(by_line),
    "station_record_count": len(features),
    "unique_amap_station_ids": len(seen_ids),
    "geometry": "stations only; upstream provides no geographic line geometry",
}
with open(os.path.join(HERE, "beijing_subway_stations_amap_gcj02.geojson"), "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "metadata": meta, "features": features}, f, ensure_ascii=False, separators=(",", ":"))
with open(os.path.join(HERE, "beijing_subway_lines_stations_amap_gcj02.json"), "w", encoding="utf-8") as f:
    json.dump({"metadata": meta, "lines": by_line}, f, ensure_ascii=False, separators=(",", ":"))

print(f"lines={len(by_line)} station_records={len(features)} unique_station_ids={len(seen_ids)}", file=sys.stderr)
for k, v in by_line.items():
    print(f"  {k:16s} {v['name']:8s} stations={v['station_count']}", file=sys.stderr)
