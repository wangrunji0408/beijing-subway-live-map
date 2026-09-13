#!/usr/bin/env python3
"""Copy the deliverables into output/.

The working files under work/out already use the compact schema (see
compact.py); the published copies additionally drop the private keys the
inference keeps around (they are prefixed with an underscore).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compact

ROOT = os.getcwd()
OUT = os.path.join(ROOT, 'work', 'out')
DEST = os.path.join(ROOT, 'output')


def public(r):
    return {k: v for k, v in r.items() if not k.startswith('_')}


def main():
    os.makedirs(DEST, exist_ok=True)
    for name, read, write in (('timetables.jsonl', compact.read_records, compact.write_records),
                              ('train_runs.jsonl', compact.read_groups, compact.write_groups)):
        src, dst = os.path.join(OUT, name), os.path.join(DEST, name)
        rows = [public(r) for r in read(src)]
        write(dst, rows)
        print(f"{name}: {len(rows)} records  {os.path.getsize(src)/1e6:.1f} MB -> "
              f"{os.path.getsize(dst)/1e6:.1f} MB")


if __name__ == '__main__':
    main()
