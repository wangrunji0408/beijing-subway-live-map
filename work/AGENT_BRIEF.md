# 时刻表解析校对任务说明（Reviewer brief）

工作目录：`/Users/wangrunji/Codes/timetable-bench`

## 背景

`work/parse/parse_line.py` 用计算机视觉 + tesseract 把每张 `timetables/<线>-<站>-<序号>.jpg`
（北京地铁各站列车时刻表）解析成时刻数据：

- `work/parsed/<line>.jsonl` —— 每行一个时刻表（一条线路的一个车站/方向/运营日）。
- `work/parsed/<line>/report.json` —— 每张图片的解析质量报告（flags / issues）。
- `work/parsed/<line>/meta.json` —— 需要你填写的方向/运营日/图例信息。
- `work/parsed/<line>/overrides.json` —— 需要你填写的人工修正。

## 你的任务

1. 查看本线路的解析问题：
   ```
   python3 work/parse/issues.py <line>
   ```
   重点看 `flag ocr_fail`（整行没读出来）、`flag bad_minute`（读出的分钟 > 59，肯定错）、
   `flag count_mismatch`、`issue duplicate`、`issue gap_small`、`issue dup_hour`。
   `gap_large` 通常是低峰期正常的 15–20 分钟间隔，除非明显是整行缺失，否则忽略。

2. 对每个有问题的图片，用 crop 工具生成可读的局部图，然后用 `read_image` 查看：
   ```
   python3 work/parse/crop.py timetables/<图片名> --row-y <row_y>   # 某一小时行
   python3 work/parse/crop.py timetables/<图片名> --header          # 表头（方向/工作日）
   python3 work/parse/crop.py timetables/<图片名> --legend          # 底部图例（终点站颜色）
   python3 work/parse/crop.py timetables/<图片名>                   # 整张图
   ```
   读出该行正确的小时与分钟。

3. 把修正写入 `work/parsed/<line>/overrides.json`（JSON 对象，键是图片相对路径）。
   支持的修正：
   ```json
   {
     "timetables/1-万寿路-1.jpg": [
       {"row_set": {"hour": 7, "minutes": [1,5,8,9,13,17,20,23,26,29,31,34,37,43,46,49,55,57]}},
       [8, 21, 23],
       {"del": [8, 55]},
       {"add": [8, 57]}
     ]
   }
   ```
   - `row_set`：整行替换（OCR 整行失败时最可靠）。`hour` 用表上的小时数，`minutes` 用你读到的分钟。
   - `[h, 旧分钟, 新分钟]`：改一个值。
   - `{"del":[h,m]}` / `{"add":[h,m]}`：删除/新增一个时刻。
   - 若同一张图片有两个时刻表（例如 18 号线），`build` 会输出两条记录，`overrides` 会同时作用于两者；
     如果两个时刻表同一小时不同，请改用 `meta.json` 的方式或跳过，避免误改。

4. 填写 `work/parsed/<line>/meta.json`。它的键是文件名末尾的序号（`-1`、`-2`…），
   对每个序号看一张该序号的图片的表头和图例，填写：
   ```json
   {
     "1": {"direction": "环球度假区", "service": "weekday",
            "legend": {"red": "四惠东", "yellow": "土桥", "blue": "果园", "pink": "四惠东", "purple": "四惠"}},
     "2": {"direction": "苹果园", "service": "weekday", "legend": {}},
     "3": {"direction": "环球度假区", "service": "weekend", "legend": {}},
     "4": {"direction": "苹果园", "service": "weekend", "legend": {}}
   }
   ```
   - `direction`：表头「开往 XXX 站方向」里的 XXX（中文站名）。
   - `service`：表头写「工作日」用 `"weekday"`，写「双休日」用 `"weekend"`。
   - `legend`：底部图例里每种颜色对应的终点站中文名；颜色用 `red/yellow/blue/green/pink/purple/orange/...`。
     若某张图片内含两个时刻表（18 号线），按你看到的实际情况填写并备注。
   - 注意：**必须以图片表头为准**，不要假设 `-1/-2/-3/-4` 的含义。

5. 重新构建并复查：
   ```
   python3 work/parse/parse_line.py build <line>
   python3 work/parse/issues.py <line>
   ```
   重复直到没有 `bad_minute` / 明显的整行缺失。

## 原则

- **只改你从图片上确认的内容，绝不编造。** 看不清就用整张图再看一次。
- 时刻表里分钟都是两位（`00`–`59`），小时是 `4`–`24`（`00` 表示午夜）。
- 同一线路所有图片风格一致；不同线路可能由不同公司运营、风格不同。
- 一张图片可能包含两个时刻表（左右两个面板），`build` 会自动拆成两条记录。
- 完成后回报：线路、时刻表条数、仍存在的问题数量、已填写的 meta 摘要。

## 解析器更新（重要）

解析器在评审期间已改进，请在你认为修完后 **重新运行一次 build** 再复查：

1. 数字高度窗口放宽到 `0.55–1.72 × med_h`，因此 BJMTR 风格线路（16/17/12/14 等）中
   更大的小时数字不再被漏掉；小时列 x 容差收紧到 `1.2 × med_h`，表头行不会被误当成数据行。
2. 一次 tesseract 调用识别整块表格（速度更快），并把形如 `80`（实为 `08`）的倒置分钟自动纠正。
3. 小时序列用「所有可能起始小时中与观测最吻合的连续序列」恢复，个别小时标签误读不会让整表错位。
4. `meta.json` 支持 `_images`：按图片名覆盖 suffix 的方向/运营日，例如
   `{"_images": {"16-北安河-1": {"direction": "宛平城", "service": "weekday"}}}`。
   终点站等 suffix 约定不适用时请使用它。
