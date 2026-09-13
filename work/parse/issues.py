#!/usr/bin/env python3
"""List parsing problems for a line in a compact, actionable form.

Usage:
  python3 work/parse/issues.py <line> [--max N]

Prints one block per image that has flags/issues, including the currently
parsed minutes for the affected hour so a reviewer knows what to check.
"""
import sys, os, json, argparse
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import compact
from collections import defaultdict

ROOT = os.getcwd()
PARSED = os.path.join(ROOT, 'work', 'parsed')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('line')
    ap.add_argument('--max', type=int, default=40)
    ap.add_argument('--kinds', default='ocr_fail,count_mismatch,bad_minute,duplicate,gap_small,dup_hour')
    a = ap.parse_args()
    kinds = set(a.kinds.split(','))
    rep = json.load(open(os.path.join(PARSED, a.line, 'report.json')))
    recs = {}
    jp = os.path.join(PARSED, f'{a.line}.jsonl')
    if os.path.exists(jp):
        for l in open(jp):
            r = compact.expand_record(json.loads(l)); recs[r['id']] = r
    shown = 0
    for x in rep:
        probs = [f for f in x.get('flags', []) if f['kind'] in kinds]
        probs += [i for i in x.get('issues', []) if i['kind'] in kinds]
        if not probs and not x.get('error'):
            continue
        shown += 1
        if shown > a.max:
            break
        print(f"### {x['source']}  id={x.get('id')}  n_times={x.get('n_times')}")
        if x.get('error'):
            print('   ERROR', x['error'])
        # current parsed minutes by hour
        r = recs.get(x.get('id'))
        byh = defaultdict(list)
        if r:
            for t in r['times']:
                byh[t['hour']].append(t['minute'])
        for f in probs:
            if 'row_y' in f:
                print(f"   flag {f['kind']} row_y={f['row_y']} text={f.get('text')!r}")
            else:
                print(f"   issue {f['kind']}: {f.get('msg') or f.get('at')}")
        # show hours mentioned
        hours = set()
        for f in probs:
            if f.get('hour') is not None:
                hours.add(f['hour'])
            if f.get('at'):
                try:
                    hours.add(int(str(f['at']).split(':')[0]))
                except Exception:
                    pass
        for h in sorted(hours):
            print(f"   parsed hour {h:02d}: {sorted(byh.get(h, []))}")
        print()


if __name__ == '__main__':
    main()
