# Beijing Subway — line geometry & station coordinates

Open, machine-readable Beijing Subway data saved in this directory.

**Primary dataset (geometry + stations): OpenStreetMap via the Overpass API, WGS84.**
**Secondary dataset (stations only): Amap-derived GCJ-02 station coordinates from a GitHub repo.**
**Cross-check: [Mick235711/Beijing-Subway-Tools](https://github.com/Mick235711/Beijing-Subway-Tools) (MIT) station lists (no coordinates).**

---

## 1. Files

### Primary — OSM / WGS84 (`EPSG:4326`)

| File | Format | Contents | Coverage |
|---|---|---|---|
| `beijing_subway_lines_wgs84.geojson` | GeoJSON FeatureCollection | **29 line features** (`LineString`; line 2/10 loops are closed). Props: `line_key`, `name`/`name_zh`, `ref`, `osm_relation`, `station_count`, `note`. | Lines 1–19, S1, 亦庄线, 八通线, 大兴机场线, 房山线, 昌平线, 燕房线, 首都机场线 + extras 西郊线, 大兴线 |
| `beijing_subway_stations_wgs84.geojson` | GeoJSON FeatureCollection | **410 merged station complexes** (`Point`). Interchanges merged into one point; props `name`/`name_zh`/`name_en`/`aliases`/`lines`/`line_names`/`osm_station_ids`. | Whole network |
| `beijing_subway_stops_by_line_wgs84.geojson` | GeoJSON FeatureCollection | **553 per-line ordered stop points** (`Point`). Props `line_key`, `seq`, `name`, `name_en`, `source` (`osm_route_stop` / `osm_station_node_gapfill`). | Whole network |
| `beijing_subway_lines_stations_wgs84.json` | JSON | `line_key -> {name, ref, osm_relation, station_count, stations:[{seq,name,name_en,lat,lon,osm_station,source}]}` — the "line → [stations with lat/lon]" form. | Whole network |

### Derived — GCJ-02 (from the OSM WGS84 data, standard `eviltransform` algorithm)

| File | Format | Contents |
|---|---|---|
| `beijing_subway_lines_gcj02.geojson` | GeoJSON FeatureCollection | Same 29 line features, coordinates converted WGS84 → GCJ-02 |
| `beijing_subway_stations_gcj02.geojson` | GeoJSON FeatureCollection | Same 410 station complexes, converted to GCJ-02 |

> These two files are **derived by coordinate transform**, not an independent survey.

### Secondary — Amap / GCJ-02 (independent source)

| File | Format | Contents |
|---|---|---|
| `beijing_subway_stations_amap_gcj02.geojson` | GeoJSON FeatureCollection | **526 station records** (`Point`), **27 lines**. Props `line_key`, `line_name`, `color`, `seq`, `name_zh`, `name_en`, `amap_station_id`, `operator`. |
| `beijing_subway_lines_stations_amap_gcj02.json` | JSON | Cleaned `line -> [stations with lat/lon]` from the same source. |

> The upstream file has **no geographic line geometry** (its `segments` field is only a station-id ordering; the raw Amap draw API stores line polylines as canvas pixels). Use the OSM file for line geometry.

### Provenance / tooling

| Path | Purpose |
|---|---|
| `raw/ov_routes_geom.json`, `raw/ov_extra.json` | Raw Overpass responses: route relations with ordered way geometry + stop members (OSM, ODbL) |
| `raw/ov_stations_broad.json` | Raw Overpass response: all railway stations (nodes/ways/relations) in the Beijing bbox |
| `raw/amap_metro_beijing_gcj02.json` | Upstream `public/data/metro.json` from `sphynxlee/bj-subway-typing` |
| `raw/amap_beijing_drw_raw.json` | Raw Amap subway draw-API payload (`1100_drw_beijing.json`) |
| `build_dataset.py` | Rebuilds the OSM WGS84 + derived GCJ-02 files from `raw/` |
| `convert_amap.py` | Rebuilds the Amap GCJ-02 files from `raw/` |
| `validate.py` | Cross-checks all three sources; writes `validation_report.json` |
| `validation_report.json` | Per-line counts (OSM / Amap / Mick), geometry lengths, name diffs |
| `crosscheck_mick235711_stations.json` | Extracted station-name lists used for the cross-check |

---

## 2. Coordinate systems

* **WGS84 / EPSG:4326** — OSM files (`*_wgs84.geojson`, `*_wgs84.json`). OSM base timestamp `2026-09-09T15:01:02Z`.
* **GCJ-02 (Mars)** — Amap file `beijing_subway_stations_amap_gcj02.geojson` (upstream declares `coordinateSystem: "GCJ-02"`), and the two `*_gcj02.geojson` files derived from WGS84.
* No BD-09/Baidu file is included.

Every GeoJSON `metadata` block and every feature carries a `coord_system` field.

---

## 3. Coverage (OSM / Amap / Mick counts)

| Line | 中文 | OSM stations | Amap stations | Mick cross-check | OSM geometry km |
|---|---|--:|--:|--:|--:|
| 1 | 1号线 | 35 | 35 | 35 | 51.18 |
| 2 | 2号线 | 18 | 18 | 18 | 23.14 |
| 3 | 3号线 | 10 | 10 | 10 | 14.64 |
| 4 | 4号线 | 35 | 35 | 35 | 49.51 |
| 5 | 5号线 | 23 | 23 | 23 | 27.14 |
| 6 | 6号线 | 36 | 36 | 36 | 55.06 |
| 7 | 7号线 | 30 | 30 | 30 | 39.34 |
| 8 | 8号线 | 35 | 35 | 35 | 48.64 |
| 9 | 9号线 | 13 | 13 | 13 | 15.78 |
| 10 | 10号线 | 45 | 45 | 45 | 56.99 |
| 11 | 11号线 | 4 | 4 | 4 | 2.94 |
| 12 | 12号线 | 20 | 20 | 20 | 27.41 |
| 13 | 13号线 | 17 | 17 | 17 | 40.36 |
| 14 | 14号线 | 34 | 33 | 33 | 46.57 |
| 15 | 15号线 | 20 | 20 | 20 | 40.55 |
| 16 | 16号线 | 30 | 30 | 30 | 48.72 |
| 17 | 17号线 | 20 | 20 | 20 | 48.84 |
| 18 | 18号线 | 11 | 11 | 11 | 19.66 |
| 19 | 19号线 | 10 | 10 | 10 | 20.68 |
| S1 | S1线 (monorail) | 8 | 8 | 8 | 9.69 |
| — | 亦庄线 Yizhuang | 14 | 14 | 14 | 22.71 |
| — | 八通线 Batong | 15 | (merged into BJ-1) | — | 22.10 |
| — | 大兴机场线 Daxing Airport Express | 3 | 3 | 3 | 38.62 |
| — | 房山线 Fangshan | 16 | 16 | 16 | 32.50 |
| — | 昌平线 Changping | 20 | 20 | 20 | 44.56 |
| — | 燕房线 Yanfang | 9 | 9 | 9 | 14.42 |
| — | 首都机场线 Capital Airport Express | 5 | 5 | 5 | 29.98 |
| — | 西郊线 Xijiao (extra) | 6 | 6 | 6 | 8.85 |
| — | 大兴线 Daxing (extra) | 11 | (merged into BJ-4) | — | 19.39 |

**Recent lines requested:** 3, 12, 17, 18, 19 **and both airport lines are present with full geometry** (OSM) and full station lists (OSM + Amap).

**Line 1** in OSM is the through-operated `1号线/八通线` relation (环球度假区–苹果园); a separate `八通线` feature is also provided. **Line 4** is the `4号线/大兴线` relation; a separate `大兴线` feature is also provided.

---

## 4. Sources, licenses, attribution

| Dataset | Source URL | License |
|---|---|---|
| OSM route relations & stations | `https://overpass.openstreetmap.fr/api/interpreter` (Overpass API, data © OpenStreetMap contributors) | **ODbL 1.0** |
| Amap-derived stations | `https://github.com/sphynxlee/bj-subway-typing` → `public/data/metro.json`; upstream Amap subway draw API `https://map.amap.com/subway/index.html?uid=1100` | **No LICENSE file in the repo.** JSON self-describes as "Practice data; not an official Beijing Subway product." Treat as source-available reference data, **not** a redistributable open-data license. |
| Cross-check station names | `https://github.com/Mick235711/Beijing-Subway-Tools` | **MIT** (Yihe Li, 2025) |

Attribution requirement for the primary dataset: **© OpenStreetMap contributors, ODbL 1.0** — keep this notice and share derivatives under ODbL.

---

## 5. Gaps, caveats, and decisions

1. **Line 18 stop members were incomplete in OSM.** The route relation listed only 6 of the 11 stations, but the geometry already covered the full 19.66 km line and the five missing station nodes (上地软件园, 东北旺, 龙泽西, 回龙观西大街, 文华路; `start_date=2025-12-27`) exist in OSM. They were recovered by snapping OSM station nodes lying ≤60 m from the line geometry; those records are flagged `source="osm_station_node_gapfill"`. No coordinate was invented.
2. **昌平线 朱房北** was likewise missing from the OSM route relation's stop list and was recovered the same way (flagged).
3. **Closed / under-construction stations are excluded** from the OSM station lists: `八角游乐园（封闭改造中）` (line 1) and `陶然桥(在建)` (line 14). The OSM line geometry still passes through them.
4. **Line 14 discrepancy:** OSM has 34 stations including **红庙**; Amap and the Mick cross-check have 33. OSM appears more current.
5. **Airport-line naming:** OSM uses `首都机场2号航站楼` / `首都机场3号航站楼`; the cross-check uses `2号航站楼` / `3号航站楼`. Same stations.
6. **Amap dataset limitations:** no geographic line geometry; 八通线 merged into line 1 and 大兴线 merged into line 4; 亦庄T1 is not in the target list and is absent from the Amap snapshot.
7. **Geometry is track centreline geometry** from OSM route relations, so measured lengths run slightly longer than official route lengths (which follow the passenger route). All 29 line geometries are continuous (`LineString`; no gaps).
8. **Station points** are OSM station-node positions (or way/relation centroids), i.e. generally the station building/platform centre, accurate to a few metres. Stop-to-station matching distance is recorded per record in `match_dist_m`.
9. **No Baidu (BD-09) coordinates** are provided; only WGS84 and GCJ-02.
10. **Names are preserved verbatim from OSM**, so a few station names carry an OSM trailing `站` (e.g. `长春桥站`, `车道沟站`, `北宫门站`). They are not normalised because some names legitimately end in `站` (e.g. `北京站`).

---

## 6. Reproduce

```bash
cd work/data
python3 build_dataset.py     # OSM WGS84 + derived GCJ-02  (uses raw/ov_*.json)
python3 convert_amap.py      # Amap GCJ-02               (uses raw/amap_metro_beijing_gcj02.json)
python3 validate.py          # cross-check + validation_report.json
```

To refresh the OSM source, re-run the Overpass queries in `raw/q_all.txt` / `raw/q_st2.txt`
(any Overpass mirror works; `https://overpass.openstreetmap.fr/api/interpreter` was used here)
and re-run `build_dataset.py`.
