#!/usr/bin/env python3
"""Final QA summary of the parsed dataset and inferred diagrams."""
import json, os, sys
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import compact
from collections import defaultdict, Counter

ROOT = os.getcwd()
OUT = os.path.join(ROOT, 'work', 'out')


def main():
    recs = compact.read_records(os.path.join(OUT, 'timetables.jsonl'))
    print(f"timetables.jsonl: {len(recs)} timetables")
    by_line = defaultdict(list)
    for r in recs:
        by_line[r['line']].append(r)
    print(f"{'line':8s} {'records':>7s} {'stations':>8s} {'dir?':>5s} {'weekday':>7s} "
          f"{'weekend':>7s} {'med.span':>8s}")
    for line in sorted(by_line, key=lambda x: (len(x), x)):
        rs = by_line[line]
        stations = len(set(r['station'] for r in rs))
        ndir = sum(1 for r in rs if r.get('direction'))
        nwd = sum(1 for r in rs if r.get('service') == 'weekday')
        nwe = sum(1 for r in rs if r.get('service') == 'weekend')
        spans = []
        for r in rs:
            if r['times']:
                ts = [t['hour'] * 60 + t['minute'] for t in r['times']]
                spans.append(max(ts) - min(ts))
        med = sorted(spans)[len(spans) // 2] if spans else 0
        print(f"{line:8s} {len(rs):7d} {stations:8d} {ndir:5d} {nwd:7d} {nwe:7d} "
              f"{med//60:5d}h{med%60:02d}")
    runs_p = os.path.join(OUT, 'train_runs.jsonl')
    if os.path.exists(runs_p):
        groups = compact.read_groups(runs_p)
        nruns = sum(g['n_runs'] for g in groups)
        print(f"\ntrain_runs.jsonl: {len(groups)} groups, {nruns} train runs")
        for g in groups[:0]:
            pass


if __name__ == '__main__':
    main()
