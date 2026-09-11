"""Interval / structural checker for parsed station timetables.

A timetable lists one departure per line (per hour).  Adjacent departures are
typically 2-15 minutes apart, minutes increase within an hour, hours increase
down the page, and every printed minute is a two-digit value 00-59.  Violations
are reported so a human can inspect the corresponding image crop.
"""
import json
from collections import Counter


def check_times(times, min_gap=2, max_gap=15, allow_same=False):
    """times: list of dicts with hour, minute (sorted or not).

    Returns (issues, stats) where issues is a list of dicts describing
    structural problems.
    """
    issues = []
    seq = sorted([(t['hour'], t['minute']) for t in times])
    # duplicate check
    dup = [k for k, c in Counter(seq).items() if c > 1]
    for h, m in dup:
        issues.append(dict(kind='duplicate', hour=h, minute=m,
                           msg=f'duplicate {h:02d}:{m:02d}'))
    # within-hour monotonicity
    by_hour = {}
    for t in times:
        by_hour.setdefault(t['hour'], []).append(t['minute'])
    for h, ms in sorted(by_hour.items()):
        ms_sorted = sorted(ms)
        if ms != ms_sorted:
            issues.append(dict(kind='unsorted', hour=h,
                               msg=f'hour {h:02d} minutes not increasing: {ms}'))
        if len(set(ms)) != len(ms):
            issues.append(dict(kind='dup_hour', hour=h, msg=f'hour {h:02d} has duplicates: {ms}'))
        for m in ms:
            if not (0 <= m <= 59):
                issues.append(dict(kind='range', hour=h, minute=m, msg=f'invalid minute {m}'))
    # gap checks over the full ordered sequence
    def to_abs(h, m):
        return h * 60 + m
    abs_seq = sorted(to_abs(h, m) for h, m in seq)
    gaps_all = [b - a for a, b in zip(abs_seq, abs_seq[1:]) if b > a]
    med = sorted(gaps_all)[len(gaps_all) // 2] if gaps_all else 5
    eff_max = max(max_gap, 2.2 * med)
    for a, b in zip(abs_seq, abs_seq[1:]):
        g = b - a
        if g <= 0:
            continue
        if g < min_gap:
            issues.append(dict(kind='gap_small', gap=g,
                               at=f'{a//60%24:02d}:{a%60:02d}->{b//60%24:02d}:{b%60:02d}',
                               msg=f'gap {g} min is below {min_gap}'))
        elif g > eff_max and g <= 120:
            issues.append(dict(kind='gap_large', gap=g,
                               at=f'{a//60%24:02d}:{a%60:02d}->{b//60%24:02d}:{b%60:02d}',
                               msg=f'gap {g} min exceeds {eff_max:.0f} (possible missed train)'))
    # hour coverage (ignore the overnight gap between the last and first service)
    hours = sorted(by_hour)
    NIGHT = {0, 1, 2, 3, 4}
    for a, b in zip(hours, hours[1:]):
        if b == a + 1 or (a == 23 and b == 0):
            continue
        missing = set(range(a + 1, b))
        if missing and missing <= NIGHT:
            continue  # e.g. 0 -> 5: no service in the small hours
        issues.append(dict(kind='hour_gap', msg=f'hours {a}->{b} not consecutive'))
    gaps = [b - a for a, b in zip(abs_seq, abs_seq[1:]) if b > a]
    stats = dict(n=len(times), n_hours=len(hours),
                 median_gap=(sorted(gaps)[len(gaps) // 2] if gaps else None),
                 max_gap=(max(gaps) if gaps else None),
                 min_gap=(min(gaps) if gaps else None))
    return issues, stats
