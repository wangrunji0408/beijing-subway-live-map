#!/usr/bin/env bash
# End-to-end regeneration of the timetable dataset, train diagrams and map data.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/6 parse all timetable images -> work/parsed/<line>.jsonl"
python3 work/parse/parse_line.py build-all --jobs 8

echo "== 2/6 merge per-line output -> work/out/timetables.jsonl"
python3 work/parse/finalize.py

echo "== 3/6 infer train diagrams -> work/out/train_runs.jsonl"
python3 work/parse/infer_diagram.py

echo "== 4/6 build map data -> web/data/network.json"
python3 work/parse/build_web_data.py

echo "== 5/6 copy deliverables -> output/"
mkdir -p output
cp work/out/timetables.jsonl work/out/train_runs.jsonl work/out/parse_report.json output/

echo "== 6/6 QA summary"
python3 work/parse/validate_final.py

echo
echo "serve the map with:  cd web && python3 -m http.server 8765 --bind 127.0.0.1"
echo "then open http://127.0.0.1:8765/"
