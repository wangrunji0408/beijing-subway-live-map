#!/usr/bin/env python3
"""Check every train's inter-station speed against the official station spacing.

For each adjacent pair of stops in a train diagram we take the published
track distance (北京市轨道交通运营管理有限公司 路网车站站间距信息,
work/data/station_spacing/bjmoa_spacing.json) and divide by the timetable
interval to get the average speed over that segment, dwell included.

A metro train runs at roughly 25-45 km/h over a station-to-station segment;
anything above --max km/h (or below --min) almost certainly means the parsed
departure times are wrong, not that the train is fast.  The Daxing Airport
Express (大兴机场线) and the Capital Airport Express are exempt from the upper
bound: they are designed for 100-160 km/h.

Usage:
  python3 work/parse/check_speed.py                 # report
  python3 work/parse/check_speed.py --max 120 --min 10 --max-show 15
  python3 work/parse/check_speed.py --fix           # list the worst segments
"""
import json, os, sys, argparse, re
from collections import defaultdict, Counter

ROOT = os.getcwd()
RUNS = os.path.join(ROOT, 'work', 'out', 'train_runs.jsonl')
SPACING = os.path.join(ROOT, 'work', 'data', 'station_spacing', 'bjmoa_spacing.json')
# lines whose rolling stock legitimately exceeds the metro speed bound
FAST_LINES = {'大兴机场', '首都机场'}
DWELL_MAX = 1.5   # minutes of dwell allowed on top of the slow-speed bound
# the 大兴线 poster is published separately but is part of line 4
MERGED_SPACING = {'4': ['大兴'], '1': ['八通']}


def norm(s):
    n = re.sub(r'[\s\(\)（）]', '', str(s or ''))
    n = re.sub(r'号线$|线$|站$', '', n)
    return n


ALIAS = {'清河': '清河站', '2号航站楼': '首都机场2号航站楼',
         '3号航站楼': '首都机场3号航站楼', '首都机场': '首都机场2号航站楼'}


def canon(s):
    n = norm(s)
    return norm(ALIAS.get(n, n))


def load_spacing():
    raw = json.load(open(SPACING))
    out = {}
    for line, pairs in raw.items():
        d = {}
        for k, m in pairs.items():
            a, b = k.split('|')
            d[(canon(a), canon(b))] = m
        out[line] = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=float, default=120.0, help='max plausible km/h')
    ap.add_argument('--min', type=float, default=20.0, help='min plausible km/h')
    ap.add_argument('--max-show', type=int, default=15)
    ap.add_argument('--min-dist', type=int, default=200, help='ignore segments shorter than this (m)')
    a = ap.parse_args()

    spacing = load_spacing()
    groups = [json.loads(l) for l in open(RUNS) if l.strip()]

    per_line = defaultdict(lambda: dict(n=0, fast=0, slow=0, km=0.0, mins=0.0, nofare=0))
    bad = []
    missing = Counter()
    for g in groups:
        line = g['line']
        sp = dict(spacing.get(line) or {})
        for alt in MERGED_SPACING.get(line, []):   # e.g. 大兴线 belongs to line 4
            sp.update(spacing.get(alt) or {})
        if not sp:
            continue
        fast_ok = line in FAST_LINES
        for run in g['runs']:
            st = run['stops']
            for x, y in zip(st, st[1:]):
                sa, ta = x['station'], x['minute']
                sb, tb = y['station'], y['minute']
                m = sp.get((canon(sa), canon(sb)))
                if m is None:
                    missing[f'{line}:{sa}->{sb}'] += 1
                    per_line[line]['nofare'] += 1
                    continue
                if m < a.min_dist:
                    continue
                dt = tb - ta
                if dt <= 0:
                    continue
                # a segment's timetable gap = dwell + running; allow DWELL_MAX
                # minutes of dwell on top of the slow bound, otherwise short
                # inner-city hops (e.g. 木樨地->玉渊潭东门, 565 m) are always
                # "too slow"
                fast_lim = (m / 1000.0) / ((dt / 60.0))
                # the timetable is printed in whole minutes, so a 1 km segment
                # quantises to +-33% speed.  Use the diagram's calibrated tau
                # (float) when available so rounding is not read as an error.
                tau = g.get('tau') or {}
                if sa in tau and sb in tau and tau[sb] > tau[sa]:
                    dtau = tau[sb] - tau[sa]
                else:
                    dtau = float(dt)
                kmh = (m / 1000.0) / (dtau / 60.0)
                p = per_line[line]
                p['n'] += 1; p['km'] += m / 1000.0; p['mins'] += dt
                slow_bound = m / 1000.0 / ((dt - DWELL_MAX) / 60.0) if dt > DWELL_MAX else 1e9
                if kmh > a.max and not fast_ok:
                    p['fast'] += 1
                    bad.append((kmh - a.max, 'FAST', line, g['direction'], g['service'],
                                sa, sb, m, dt, round(kmh, 1)))
                elif slow_bound < a.min:
                    p['slow'] += 1
                    bad.append((a.min - kmh, 'SLOW', line, g['direction'], g['service'],
                                sa, sb, m, dt, round(kmh, 1)))
    print(f"segments checked: {sum(p['n'] for p in per_line.values())}  "
          f"(no published spacing: {sum(per_line[l]['nofare'] for l in per_line)})")
    print(f"\n{'line':8s} {'segs':>7s} {'med km/h':>9s} {'too fast':>9s} {'too slow':>9s}")
    for ln in sorted(per_line, key=lambda x: (len(x), x)):
        p = per_line[ln]
        if not p['n']:
            continue
        med = (p['km'] / (p['mins'] / 60.0)) if p['mins'] else 0
        print(f"{ln:8s} {p['n']:7d} {med:9.1f} {p['fast']:9d} {p['slow']:9d}")
    print(f"\nflagged segments: {len(bad)}  (fast={sum(1 for b in bad if b[1]=='FAST')}, "
          f"slow={sum(1 for b in bad if b[1]=='SLOW')})")
    bad.sort(reverse=True)
    for b in bad[:a.max_show]:
        _, kind, ln, d, svc, sa, sb, m, dt, kmh = b
        print(f"  {kind}  {ln:6s} {sa}->{sb}  {m}m / {dt}min = {kmh} km/h   "
              f"(开往{d} {svc})")
    if missing:
        print("\nsegments with no published spacing (top 10):")
        for k, v in missing.most_common(10):
            print(f"   {k}: {v}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
