#!/usr/bin/env bash
# End-to-end regeneration of the timetable dataset, train diagrams and map data.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/7 parse all timetable images -> work/parsed/<line>.jsonl"
python3 work/parse/parse_line.py build-all --jobs 8

echo "== 2/7 merge per-line output -> work/out/timetables.jsonl"
python3 work/parse/finalize.py

echo "== 3/7 infer train diagrams -> work/out/train_runs.jsonl"
python3 work/parse/infer_diagram.py

echo "== 4/7 build map data -> web/data/network.json"
python3 work/parse/build_web_data.py

echo "== 5/7 export compact deliverables -> output/"
python3 work/parse/export.py
cp work/out/parse_report.json output/

echo "== 6/7 QA summary"
python3 work/parse/validate_final.py

echo "== 7/7 diagram checks"
python3 work/parse/check_diagram.py --allow 6      # no train may overtake another
python3 work/parse/check_speed.py                  # segment speeds vs official spacing
python3 work/parse/check_reverse.py --tol 2        # diagram vs parsed timetables

echo
echo "serve the map with:  cd web && python3 -m http.server 8765 --bind 127.0.0.1"
echo "then open http://127.0.0.1:8765/"
