# Beijing Subway Timetable Digitisation & Live Train Map

把 `timetables/` 里的 1,977 张北京地铁各站「列车时刻表」图片解析成结构化时刻数据（**1,995 条时刻表**），
据此反推每趟列车的运行图（**114 个线路/方向/运营日分组、18,165 趟列车**），
并做一个实时显示列车位置的动态线网地图（26 条线、521 站）。

## 成果物

| 文件 | 说明 |
|---|---|
| `output/timetables.jsonl` | **主交付物**：每行一个时刻表（一条线路的一个车站 × 一个方向 × 一个运营日），共 1,995 条 |
| `output/train_runs.jsonl` | 由各站时刻表反推的**列车运行图**：114 组，含站序、站间时分与每趟车的逐站时刻 |
| `output/parse_report.json` | 解析质量报告（每条图片的 OCR 告警与间隔校验问题） |
| `web/index.html` + `web/data/network.json` | **动态地图**：真实线网几何 + 实时列车位置，可调时刻与时间流速 |
| `work/AGENT_BRIEF.md` | 解析校对作业说明 |
| `work/parse/` | 解析与反推的源码 |

## 快速开始

```bash
# 1. 静态服务器（地图是纯静态页面）
cd web && python3 -m http.server 8765 --bind 127.0.0.1
# 浏览器打开 http://127.0.0.1:8765/
```

地图功能：滚轮缩放、拖动平移、悬停查看列车/车站信息；右侧可暂停/播放、拖动时刻、
调节时间流速（1 秒现实 = N 秒运营时间）、切换工作日/双休日、显示/隐藏线路。

## 数据格式

### timetables.jsonl

```json
{
  "id": "1-万寿路-1",
  "source": "timetables/1-万寿路-1.jpg",
  "suffix": "1",
  "line": "1",
  "station": "万寿路",
  "direction": "环球度假区",
  "service": "weekday",
  "legend": {"red": "四惠东", "yellow": "土桥"},
  "times": [
    {"hour": 5, "minute": 11, "terminal": null, "color": "red"},
    {"hour": 5, "minute": 15, "terminal": null, "color": "red"}
  ]
}
```

- `direction`：该方向「开往 X 站方向」的 X。
- `service`：`weekday`（工作日）或 `weekend`（双休日）。
- `color`：该班次在图上圆环/实心圆点的颜色，对应 `legend` 中的终点站。
- 一张图片含两个时刻表时（如 18 号线），输出两条记录，`id` 形如 `<base>#0`、`<base>#1`。

### train_runs.jsonl

```json
{
  "line": "1", "group": "1", "direction": "环球度假区", "service": "weekday",
  "station_order": ["苹果园", "古城", "..."],
  "tau": {"苹果园": 0.0, "古城": 4.3, "...": 0.0},
  "total_travel": 50.6,
  "runs": [
    {"stops": [{"station": "苹果园", "minute": 309}, {"station": "古城", "minute": 313}]}
  ]
}
```

`minute` 为自当日 0 点起的分钟数。短交路列车在中途站自然终止（`stops` 较短）。

## 解析方法（`work/parse/`）

1. **图像预处理** (`common.py`)：CMYK/截断 JPEG 归一化；Otsu + 背景极性判定得到“墨迹”掩膜。
2. **字形提取**：连通域分析区分数字与圆环/实心圆标记；圆环内部用腐蚀 + Otsu 提取数字；
   实心圆用孔洞提取，兼容深色字/浅色字两种配色。
3. **行/列还原**：按 y 聚类成小时行，按 x 间隙聚类成分钟数字，识别左侧小时列。
4. **数字识别** (`parse_line.py`)：把整行数字重绘成干净的“白底黑字”图，横向分块后交给
   tesseract（psm 7）；利用「分钟恒为两位、小时为 1–2 位」的约束做对齐，并同时尝试
   字形计数对齐，取合法分钟最多者。
5. **质量校验** (`checker.py`)：检查分钟范围、行内单调、重复、相邻班次间隔（默认 2–15 分钟，
   低峰线路自适应放宽），输出 `report.json` 供人工复核。
6. **运行图反推** (`infer_diagram.py`)：以 OSM 站序为骨架，用各站时刻的稳健分位数确定方向，
   按线路几何里程与平均旅速分配站间时分，再将始发站每一班匹配到各站最近班次。
7. **地图数据** (`build_web_data.py`)：OSM 线网几何（WGS84）+ 站点吸附到线路，
   输出 `web/data/network.json`。

## 数据来源与版权

- 时刻表图片：`timetables/`（来源见 `timetables/downloaded_urls.txt`）。
- 线网几何与站点坐标：OpenStreetMap（ODbL 1.0，© OpenStreetMap contributors），
  由 `work/data/` 下的脚本通过 Overpass API 生成；另含 Amap 派生站点数据用于交叉校验。
- 线路颜色取自北京市地方标准 DB11/T 657.2-2015（经维基百科 [Template:北京地铁颜色](https://zh.wikipedia.org/wiki/Template:%E5%8C%97%E4%BA%AC%E5%9C%B0%E9%93%81%E9%A2%9C%E8%89%B2)）。
- 地图底图仅使用上述开放数据，未使用任何受限地图瓦片。

## 已知限制

- 少数图片存在截断/损坏（如 `timetables/8-东高地-1.jpg`）或配色特殊，OCR 可能遗漏若干行；
  `work/out/parse_report.json` 会列出所有告警，`work/parsed/<line>/overrides.json` 可人工修正。
- 运行图的站间时分按里程与平均旅速估算（约 36 km/h），非逐段实测。

## 运行图校验工具

反推出运行图后有两个自检脚本（都在 `work/parse/`）：

```bash
python3 work/parse/check_diagram.py --allow 6   # 超车检查（6 号线有大站快车，豁免）
python3 work/parse/check_reverse.py --tol 2     # 由运行图反向导出时刻表，与原时刻表对比
```

* `check_diagram.py`：同一线路同一方向的列车按发车顺序不得互相超越
  （含站间交叉检测）。当前 108 组、17,725 趟车 **0 起超车**。
  6 号线因同时开行大站快车与普通车，允许超车，故豁免。
* `check_reverse.py`：把运行图在每个站的停站时刻反向导出成时刻表，与原时刻表
  逐站比对（默认 ±2 分钟）。当前 **支持率 97.3%**，不一致处即解析或反推的疑点。
* `check_speed.py`：用**官方站间距**（北京市轨道交通运营管理有限公司
  [路网车站站间距信息](https://www.bjmoa.cn/metroLineList.html)，已抓取到
  `work/data/station_spacing/bjmoa_spacing.json`）除以运行图的站间时间得到区间
  平均速度。低于 **20 km/h** 或高于 **120 km/h**（大兴机场线/首都机场线豁免上限）
  即判定解析有误。短区间另给 1.5 分钟停站余量，避免把市中心的短站距误判。
  当前 **0 起越界**（修复前 15 号线 `南法信→后沙峪` 4.6 km 仅 1 分钟 = 275 km/h）。
  另外按**每条线自身的速度中位数**判定离群区间（`--ratio-hi/--ratio-lo/--z/--min-dev`
  可调，`--strict` 时离群也返回非零）：一条线里某区间远快或远慢于本线常态即异常，
  例如修复前昌平线 `昌平东关→昌平` 达 73 km/h（本线中位 39）。

## 动画中的停站

地图动画把时刻表的分钟视为**到站时刻**：列车在第 M 分钟整（0s）到达车站，**停站 1 分钟**后（60s）发车，
再用剩余时间运行到下一站。因此

- 地图上可看到列车进站后停住约 1 分钟再启动；
- 底部运行图呈现标准**阶梯形**（水平段=停站，斜线=区间运行）；
- 点击列车后，逐站时刻按 `到达→发车` 显示（如 `07:53→07:54`），停站中的车站会高亮。

停站时长由 `web/index.html` 顶部的 `DWELL = 1` 控制，可自行调整。

## 甩站（临时通过不停车）

`八角游乐园`（1 号线）目前**临时甩站**：官方站间距表里 古城→八宝山 是直连的 3874 m，
OSM 关系里也没有该站。解析出的该站时刻表仍保留在 `output/timetables.jsonl` 中（图片确有此表），
但**运行图会跳过它**（`infer_diagram.CLOSED_STATIONS`），列车由八宝山直达古城。

另外 `build_web_data` 有一道兜底：任何在当前线路几何里没有坐标的车站都会被移出该线路的站序，
避免列车在它两侧"消失"。
