#!/usr/bin/env python3
"""
Recompute every logged ride in master_log_v2.csv through the CURRENT ridelib,
in place. Use after a calibration change (e.g. new VE bands) to refresh all
derived columns across the whole history.

Sources env/date/name from the log itself (authoritative), reloads each saved
stream, recomputes via the tested ridelib, and rewrites the log.

SAFE: a ride whose stream is missing (or whose recompute raises) keeps its
existing row verbatim — a ride is NEVER dropped. (This is why it sources from
the live log, not the stale legacy CSV that rebuild_log.py used.)

Run: python3 recompute_log.py
"""
import csv
from pathlib import Path
import athlete_config as C
import ridelib as R
from analyze import COLS, LOG

SD = C.STREAM_DIR


# Columns that come from the ATHLETE, not from the stream. ridelib cannot
# recompute these, so they must be carried across from the existing row or they
# are silently destroyed. This bit us on Aug 26 2026: a recompute wiped the
# fluid/carb data on the only two rides that had it, minutes after it was logged.
SELF_REPORTED = ("fluid_ml", "carb_g", "protein_g", "fluid_hit", "carb_hit")


def recompute():
    old = list(csv.DictReader(LOG.open()))
    out, recomputed, preserved = [], 0, []
    for r in old:
        aid, env = r["activity_id"], r.get("env", "")
        stream = SD / f"{aid}.json"
        if stream.exists() and env in ("indoor", "outdoor"):
            try:
                m = R.compute(R.load_stream(aid), env, activity_id=aid,
                              date=r.get("date", ""), name=r.get("name", ""))
                row = {k: m.get(k, "") for k in COLS}
                # carry self-reported fields across — see SELF_REPORTED above
                for k in SELF_REPORTED:
                    if r.get(k) not in (None, ""):
                        row[k] = r[k]
                out.append(row)
                recomputed += 1
                continue
            except Exception as e:                       # keep the old row, don't drop
                preserved.append((aid, f"{type(e).__name__}: {e}"))
        elif not stream.exists():
            # Silently keeping a stale row is the dangerous case: the ride stays
            # in the log on OLD calibration while everything around it moves, and
            # nothing says so. Name it.
            preserved.append((aid, "no saved stream"))
        else:
            preserved.append((aid, f"env is {env!r}, expected indoor/outdoor"))
        out.append({k: r.get(k, "") for k in COLS})
    out.sort(key=lambda r: r["date"], reverse=True)
    with LOG.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader()
        for r in out:
            wr.writerow(r)
    return len(out), recomputed, preserved


if __name__ == "__main__":
    total, recomputed, preserved = recompute()
    print(f"Recomputed {recomputed}/{total} rides on the current calibration.")
    if preserved:
        print(f"  Preserved as-is (missing stream / error): {preserved}")
