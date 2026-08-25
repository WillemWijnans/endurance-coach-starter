#!/usr/bin/env python3
"""
Reconcile streams on disk against rows in the master log.

WHY: three rides sat on disk for WEEKS, invisible to every trend analysis,
because their stored activity_type was None and nothing ever compared the two
lists. One of them was a max ramp test carrying the best efficiency evidence in
the dataset. Nothing failed; the data was simply absent.

Usage:
  python3 check_log.py          # report, exit 1 if anything is out of sync
"""
import csv
import sys
import athlete_config as C


def orphan_streams():
    """Streams on disk with no row in the log."""
    disk = {p.stem for p in C.STREAM_DIR.glob("i*.json")}
    return sorted(disk - logged_ids())


def missing_streams():
    """Rows in the log whose stream file has gone."""
    disk = {p.stem for p in C.STREAM_DIR.glob("i*.json")}
    return sorted(logged_ids() - disk)


def logged_ids():
    if not C.MASTER_LOG.exists():
        return set()
    with C.MASTER_LOG.open() as f:
        return {r["activity_id"] for r in csv.DictReader(f)}


def undated_rows():
    """Rows with no date — logged but invisible to every date-filtered analysis."""
    if not C.MASTER_LOG.exists():
        return []
    with C.MASTER_LOG.open() as f:
        return [r["activity_id"] for r in csv.DictReader(f) if not r.get("date")]


def report():
    orphans, missing, undated = orphan_streams(), missing_streams(), undated_rows()
    ok = True
    n_logged, n_disk = len(logged_ids()), len(list(C.STREAM_DIR.glob("i*.json")))
    print(f"  streams on disk: {n_disk}   rows in log: {n_logged}")
    if orphans:
        ok = False
        print(f"\n  ⚠️  {len(orphans)} STREAM(S) NOT IN THE LOG — invisible to every analysis:")
        for a in orphans:
            print(f"        {a}   fix: python3 analyze.py {a} <env> <YYYY-MM-DD> \"<name>\"")
    if missing:
        ok = False
        print(f"\n  ⚠️  {len(missing)} logged row(s) have no stream file:")
        for a in missing:
            print(f"        {a}")
    if undated:
        ok = False
        print(f"\n  ⚠️  {len(undated)} undated row(s) — invisible to date-filtered analysis:")
        for a in undated:
            print(f"        {a}")
    if ok:
        print("  ✓ every stream is logged, every row has a stream and a date")
    return ok


if __name__ == "__main__":
    sys.exit(0 if report() else 1)
