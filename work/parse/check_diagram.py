#!/usr/bin/env python3
"""Train-diagram (运行图) sanity checker: trains must not overtake.

For one line + direction + service, trains run on the same track in a fixed
order: a train that leaves the origin earlier may never be behind a train that
leaves later.  This script checks every pair of runs in every group and reports
any overtaking (a later train's time earlier than an earlier train's time at a
station both serve), plus "crossings" between adjacent stations.

Line 6 is exempt: it runs 大站快车 (express services that skip stops) alongside
locals, so overtaking is legitimate there.  Pass --allow 6,7,... to exempt more.

Usage:
  python3 work/parse/check_diagram.py                 # check work/out/train_runs.jsonl
  python3 work/parse/check_diagram.py --jobs 6,7      # exempt line 6 and 7
  python3 work/parse/check_diagram.py --fix           # classify + suggest shifts
"""
import json, os, sys, argparse
from collections import defaultdict

ROOT = os.getcwd()
DEFAULT_SRC = os.path.join(ROOT, 'work', 'out', 'train_runs.jsonl')


def load(path):
    groups = []
    for line in open(path):
        line = line.strip()
        if line:
            groups.append(json.loads(line))
    return groups


def run_stops(run):
    """{station: minute} for one run."""
    return {s['station']: s['minute'] for s in run['stops']}


def check_group(g, tol=1):
    """Return a list of overtaking events within one group.

    tol is a small tolerance in minutes so that pure rounding noise (two trains
    timetabled 1 minute apart) is not reported.
    """
    order = g['station_order']
    pos = {n: i for i, n in enumerate(order)}
    runs = []
    for r in g['runs']:
        st = run_stops(r)
        runs.append((min(st.values()), st))          # (origin departure, stops)
    runs.sort(key=lambda x: x[0])
    events = []
    for i in range(len(runs)):
        t_a, A = runs[i]
        for j in range(i + 1, len(runs)):
            t_b, B = runs[j]
            if t_b - t_a <= tol:
                continue                              # same/adjacent slot: noise
            for s, ta in A.items():
                tb = B.get(s)
                if tb is None:
                    continue
                if ta > tb + tol:
                    # A left earlier but is behind B here => overtaking
                    events.append(dict(kind='overtake', station=s,
                                       earlier=t_a, later=t_b,
                                       earlier_time=ta, later_time=tb,
                                       back_by=ta - tb))
            # also detect a swap between two shared stations
            shared = [s for s in order if s in A and s in B]
            for s1, s2 in zip(shared, shared[1:]):
                d1 = A[s1] - B[s1]
                d2 = A[s2] - B[s2]
                if d1 * d2 < 0 and abs(d1) > tol and abs(d2) > tol:
                    events.append(dict(kind='cross', from_station=s1, to_station=s2,
                                       earlier=t_a, later=t_b))
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=DEFAULT_SRC)
    ap.add_argument('--allow', default='6', help='comma separated exempt line keys')
    ap.add_argument('--tol', type=int, default=1)
    ap.add_argument('--max-show', type=int, default=10)
    a = ap.parse_args()
    allow = set(x.strip() for x in a.allow.split(',') if x.strip())
    groups = load(a.src)
    bad_groups = 0
    total = 0
    per_line = defaultdict(int)
    shown = 0
    for g in groups:
        if g['line'] in allow:
            continue
        ev = check_group(g, tol=a.tol)
        if ev:
            bad_groups += 1
            total += len(ev)
            per_line[g['line']] += len(ev)
            if shown < a.max_show:
                shown += 1
                print(f"### {g['line']} · 开往{g['direction']} · {g['service']} "
                      f"({g['n_runs']} runs) -> {len(ev)} events")
                for e in ev[:3]:
                    print("   ", e)
    print(f"\nchecked {len(groups)} groups (exempt: {sorted(allow) or 'none'})")
    print(f"groups with overtaking: {bad_groups};  total events: {total}")
    if per_line:
        print("by line:", dict(sorted(per_line.items(), key=lambda kv: -kv[1])))
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
