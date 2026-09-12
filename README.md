# Beijing Subway Timetable Digitisation & Live Train Map

> 本项目全程由 **DeepSeek V4.1 Flash** 完成：图像解析、运行图反推、地图实现、数据校验与文档。

把 `timetables/` 里的北京地铁各站「列车时刻表」海报解析成结构化时刻数据（**1,977 条时刻表**），
据此反推每趟列车的运行图（**105 个线路/方向/运营日分组、16,350 趟列车**），
并做一个实时显示列车位置的动态线网地图（26 条线、521 站）。

在线地图：**https://wangrunji0408.github.io/beijing-subway-live-map/**

## 成果物

| 文件 | 说明 |
|---|---|
| `output/timetables.jsonl` | **主交付物**：每行一个时刻表（线路 × 车站 × 方向 × 运营日），共 1,977 条 |
| `output/train_runs.jsonl` | 由各站时刻表反推的**列车运行图**：105 组，含站序、站间时分与每趟车的逐站时刻 |
| `output/parse_report.json` | 解析质量报告（每条图片的 OCR 告警与间隔校验问题） |
| `web/index.html` + `web/data/network.json` | **动态地图**：真实线网几何 + 实时列车位置 |
| `work/parse/` | 解析、反推与校验的源码（另有 `work/AGENT_BRIEF.md` 校对作业说明） |

## 快速开始

```bash
# 本地看地图（纯静态页面，无需构建）
cd web && python3 -m http.server 8765 --bind 127.0.0.1
# 浏览器打开 http://127.0.0.1:8765/

# 从图片全量重建（解析 → 运行图 → 地图数据 → 自检）
./run_all.sh
```

地图操作：滚轮缩放、拖动平移；右侧可暂停/播放、拖动时刻、调节时间流速（1 秒现实 = N 秒运营时间）、
按星期选择运营日、点击线路高亮、点击列车查看逐站时刻。

## 数据来源与版权

- 时刻表图片：`timetables/`，来自各运营方官网（下载记录见 `timetables/downloaded_urls.txt`）。
- 线网几何与站点坐标：OpenStreetMap（ODbL 1.0，© OpenStreetMap contributors）；另有 Amap 派生站点数据用于交叉校验。
- 线路颜色：北京市地方标准 DB11/T 657.2-2015（经[维基百科](https://zh.wikipedia.org/wiki/Template:%E5%8C%97%E4%BA%AC%E5%9C%B0%E9%93%81%E9%A2%9C%E8%89%B2)）。
- 官方站间距：北京市轨道交通运营管理有限公司[路网车站站间距信息](https://www.bjmoa.cn/metroLineList.html)。

## 已知限制

- 少数图片下载不完整或配色特殊，OCR 可能遗漏若干行；`output/parse_report.json` 列出全部告警，
  `work/parsed/<line>/overrides.json` 可人工修正。
- 运行图的站间时分由匹配校准而非逐段实测，个别区间仍有 1–2 分钟偏差。

## 详细文档

实现细节、数据格式、校验规则与各线路特殊情况见 **[IMPLEMENTATION.md](IMPLEMENTATION.md)**。
