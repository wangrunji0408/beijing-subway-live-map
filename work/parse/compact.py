#!/usr/bin/env python3
"""Compact JSONL codec for the timetable and diagram records.

Every row carries the same key names, so the on-disk files were mostly
boilerplate: 40 MB of pretty keys for 6 MB of numbers.  The files now store

    times: [[5, 11, "red"], [5, 15]]              # [hour, minute, colour?]
    tau:   [0.0, 3.2, ...]                        # aligned with station_order
    runs:  [[0, 304, 1, 307], ...]                # [station index, minute, ...]

and this module converts to and from the verbose in-memory shape the rest of
the pipeline works with, so no caller has to care which form is on disk.
"""
import json


def strip_record(r):
    """verbose record -> compact record"""
    out = dict(r)
    times = []
    for t in r['times']:
        row = [t['hour'], t['minute']]
        if t.get('color'):
            row.append(t['color'])
        times.append(row)
    out['times'] = times
    return out


def expand_record(r):
    """compact record -> verbose record"""
    if not r.get('times') or not isinstance(r['times'][0], list):
        return r                      # already verbose
    out = dict(r)
    out['times'] = [{'hour': t[0], 'minute': t[1], 'terminal': None,
                     'color': t[2] if len(t) > 2 else None} for t in r['times']]
    return out


def strip_group(g):
    """verbose group -> compact group"""
    order = g['station_order']
    pos = {n: i for i, n in enumerate(order)}
    runs = []
    for run in g['runs']:
        flat = []
        for s in run['stops']:
            i = pos.get(s['station'])
            if i is not None:
                flat += [i, s['minute']]
        runs.append(flat)
    out = dict(g)
    out['tau'] = [g['tau'].get(n, 0.0) for n in order]
    out['n_stations'] = len(order)
    out['n_runs'] = len(runs)
    out['runs'] = runs
    return out


def expand_group(g):
    """compact group -> verbose group (tau dict + runs of stops)"""
    if isinstance(g.get('tau'), dict):
        return g                      # already verbose
    order = g['station_order']
    out = dict(g)
    out['tau'] = {n: v for n, v in zip(order, g['tau'])}
    out['runs'] = [dict(stops=[dict(station=order[f[k]], minute=f[k + 1])
                               for k in range(0, len(f), 2)]) for f in g['runs']]
    return out


def read_jsonl(path, expand=None):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                out.append(expand(obj) if expand else obj)
    return out


def write_jsonl(path, rows, strip=None):
    with open(path, 'w') as f:
        for r in rows:
            f.write(json.dumps(strip(r) if strip else r, ensure_ascii=False,
                               separators=(',', ':')) + '\n')


def read_records(path):
    return read_jsonl(path, expand_record)


def write_records(path, recs):
    write_jsonl(path, recs, strip_record)


def read_groups(path):
    return read_jsonl(path, expand_group)


def write_groups(path, groups):
    write_jsonl(path, groups, strip_group)
