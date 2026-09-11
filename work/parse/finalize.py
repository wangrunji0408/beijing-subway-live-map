#!/usr/bin/env python3
"""Merge per-line parsing output into the final deliverables.

Outputs
  work/out/timetables.jsonl   one line per timetable (the main deliverable)
  work/out/train_runs.jsonl   per-train diagrams (regenerated separately)
  work/out/parse_report.json  aggregate quality report
"""
import json, os, glob, sys
from collections import Counter

ROOT = os.getcwd()
PARSED = os.path.join(ROOT, 'work', 'parsed')
OUT = os.path.join(ROOT, 'work', 'out')
LINES = ['1','2','3','4','5','6','7','8','9','10','11','12','13','14','15','16','17','18',
         '19','S1','亦庄','八通','大兴机场','房山','昌平','燕房','首都机场']


def main():
    os.makedirs(OUT, exist_ok=True)
    all_recs = []
    report = {}
    for line in LINES:
        p = os.path.join(PARSED, f'{line}.jsonl')
        if not os.path.exists(p):
            continue
        meta = {}
        mp = os.path.join(PARSED, line, 'meta.json')
        if os.path.exists(mp):
            meta = json.load(open(mp))
        recs = []
        for l in open(p):
            l = l.strip()
            if not l:
                continue
            try:
                recs.append(json.loads(l))
            except Exception:
                pass  # tolerate a file being rewritten concurrently
        img_meta = meta.get('_images', {}) or {}
        for r in recs:
            m = meta.get(r.get('suffix'), {}) or {}
            if not isinstance(m, dict):
                m = {}
            m = dict(m)
            m.update(img_meta.get(str(r.get('id', '')).split('#')[0], {}) or {})
            if m.get('direction'):
                r['direction'] = m['direction']
            if m.get('service'):
                r['service'] = m['service']
            if m.get('legend'):
                r['legend'] = m['legend']
            r.pop('_issues', None); r.pop('_stats', None); r.pop('_flags', None)
            all_recs.append(r)
        rep = json.load(open(os.path.join(PARSED, line, 'report.json'))) \
            if os.path.exists(os.path.join(PARSED, line, 'report.json')) else []
        c = Counter()
        for x in rep:
            if x.get('error'):
                c['error'] += 1
            for i in x.get('issues', []):
                c[i['kind']] += 1
            for f in x.get('flags', []):
                c['flag_' + f['kind']] += 1
        report[line] = dict(images=len(rep), issues=dict(c))

    all_recs.sort(key=lambda r: (r['line'], r['station'], str(r.get('suffix'))))
    with open(os.path.join(OUT, 'timetables.jsonl'), 'w') as f:
        for r in all_recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    json.dump(report, open(os.path.join(OUT, 'parse_report.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('timetables.jsonl:', len(all_recs), 'timetables')
    tot = Counter()
    for v in report.values():
        for k, n in v['issues'].items():
            tot[k] += n
    print('remaining issues:', dict(tot.most_common()))
    n_dir = sum(1 for r in all_recs if r.get('direction'))
    n_svc = sum(1 for r in all_recs if r.get('service'))
    print(f'direction filled: {n_dir}/{len(all_recs)}   service filled: {n_svc}/{len(all_recs)}')


if __name__ == '__main__':
    main()
