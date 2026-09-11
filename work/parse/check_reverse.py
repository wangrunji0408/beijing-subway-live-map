#!/usr/bin/env python3
"""Reverse-export station timetables from the train diagrams and compare them
with the originally parsed timetables.

For every (line, physical direction, service) group and every station it
serves, the diagram says which trains call there and when.  That derived
timetable should agree with the parsed station timetable; disagreements mean one
of the two is wrong:

  * diagram-only  - the diagram puts a train at a time the station timetable
                    does not list (missing departure in the timetable, or bad tau)
  * timetable-only- the station lists a departure no train in the group serves
                    (spurious entry, a train that starts mid-line, or a matching
                    miss)

Usage: python3 work/parse/check_reverse.py [--tol 2] [--lines 1,2] [--max 15]
"""
import json, os, sys, argparse
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import infer_diagram as inf

ROOT = os.getcwd()
PARSED = os.path.join(ROOT, 'work', 'parsed')
RUNS = os.path.join(ROOT, 'work', 'out', 'train_runs.jsonl')


def load_runs():
    return [json.loads(l) for l in open(RUNS) if l.strip()]


_OSM_CACHE = {}


def load_timetables(lines):
    """(line, station, direction, service) -> set(abs minutes)."""
    out = defaultdict(set)
    for line in lines:
        p = os.path.join(PARSED, f'{line}.jsonl')
        if not os.path.exists(p):
            continue
        for l in open(p):
            l = l.strip()
            if not l:
                continue
            r = json.loads(l)
            osm = _OSM_CACHE.setdefault(line, inf.osm_order(line))
            sign = inf.physical_sign(r, osm, line in inf.LOOP_LINES)
            key = (line, r['station'], sign, r.get('service') or '?')
            for t in r['times']:
                out[key].add(t['hour'] * 60 + t['minute'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tol', type=int, default=2)
    ap.add_argument('--lines', default=None)
    ap.add_argument('--max', type=int, default=15)
    a = ap.parse_args()
    groups = load_runs()
    lines = a.lines.split(',') if a.lines else sorted(set(g['line'] for g in groups))
    tt = load_timetables(lines)

    # derived timetable from the diagram
    derived = defaultdict(set)
    for g in groups:
        svc = g['service'] or '?'
        for run in g['runs']:
            for s in run['stops']:
                derived[(g['line'], s['station'], g['group'], svc)].add(s['minute'])

    def cover(t, S, tol):
        return any(abs(t - x) <= tol for x in S)

    per_line = defaultdict(lambda: dict(d=0, t=0, donly=0, tonly=0, matched=0))
    worst = []
    for key, O in tt.items():
        line, st, d, svc = key
        R = derived.get(key)
        if R is None:
            continue
        donly = sum(1 for x in R if not cover(x, O, a.tol))
        tonly = sum(1 for x in O if not cover(x, R, a.tol))
        matched = len(R) - donly
        p = per_line[line]
        p['d'] += len(R); p['t'] += len(O); p['donly'] += donly
        p['tonly'] += tonly; p['matched'] += matched
        if tonly or donly:
            worst.append((tonly + donly, key, len(O), len(R), matched, donly, tonly))

    print(f"compared {len(tt)} (station,direction,service) timetables against the diagram "
          f"(tol ±{a.tol} min)\n")
    print(f"{'line':8s} {'derived':>8s} {'timetable':>10s} {'matched':>8s} "
          f"{'diag-only':>10s} {'tt-only':>8s} {'support':>8s}")
    td = ttt = tm = tdo = tto = 0
    for ln in sorted(per_line, key=lambda x: (len(x), x)):
        p = per_line[ln]
        sup = p['matched'] / max(1, p['d'])
        td += p['d']; ttt += p['t']; tm += p['matched']; tdo += p['donly']; tto += p['tonly']
        print(f"{ln:8s} {p['d']:8d} {p['t']:10d} {p['matched']:8d} "
              f"{p['donly']:10d} {p['tonly']:8d} {sup:7.1%}")
    print(f"{'TOTAL':8s} {td:8d} {ttt:10d} {tm:8d} {tdo:10d} {tto:8d} {tm/max(1,td):7.1%}")
    print(f"\nworst stations by disagreement:")
    worst.sort(reverse=True)
    for w in worst[:a.max]:
        print(f"  {w[1][0]:6s} {w[1][1]:10s} {str(w[1][2])[:12]:12s} {w[1][3]:18s} "
              f"tt={w[2]:4d} derived={w[3]:4d} matched={w[4]:4d} diag_only={w[5]:3d} tt_only={w[6]:3d}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
