#!/usr/bin/env python3
"""
Split a stop-heavy ride at its longest stop and analyze each segment cleanly.

For social/cafe rides with a big mid-ride break, whole-ride decoupling is
contaminated (postprandial HR, cold restart). Splitting at the break gives a
clean Pw:HR + VE durability read on each leg. Uses the tested ridelib.compute.

Usage: python3 split_analyze.py <activity_id> <indoor|outdoor>
"""
import sys
import ridelib as R


def slice_streams(streams, lo, hi):
    return {k: v[lo:hi] for k, v in streams.items() if isinstance(v, list) and len(v) >= hi}


def main(activity_id, env):
    streams = R.load_stream(activity_id)
    t = streams["time"]
    gaps = R.time_gaps(t)
    gaps_sorted = sorted(gaps, key=lambda g: g[1], reverse=True)

    print(f"=== {activity_id} ({env}) — {len(t)} samples ===")
    print(f"elapsed {round((t[-1]-t[0])/60,1)}min | moving {round(R.moving_seconds(t)/60,1)}min "
          f"| paused {round((t[-1]-t[0]-R.moving_seconds(t))/60,1)}min | {len(gaps)} gaps")
    print("\nLongest stops:")
    for i, g in gaps_sorted[:6]:
        at_min = round((t[i-1]-t[0])/60, 1)
        print(f"  gap {round(g/60,1):>5}min  at ride-clock {at_min}min (sample idx {i})")

    split_i, split_gap = gaps_sorted[0]
    print(f"\nSplitting at the {round(split_gap/60,1)}min break "
          f"(ride-clock {round((t[split_i-1]-t[0])/60,1)}min, idx {split_i})\n")

    segs = [("LEG 1 (pre-break)", 0, split_i), ("LEG 2 (post-break)", split_i, len(t))]
    fields = ["moving_min", "np", "hr_avg", "hr_max", "ve_avg", "ve_rmax30",
              "normve", "ef", "ve_ef", "decoupling_pct", "decoupling_clean",
              "veZ1", "veZ2", "veZ3", "veZ4", "veZ5", "br_avg", "long_stop_min", "n_gaps"]
    for label, lo, hi in segs:
        seg = slice_streams(streams, lo, hi)
        m = R.compute(seg, env, activity_id=activity_id, name=label)
        print(f"--- {label} ---")
        for f in fields:
            print(f"  {f:16} {m[f]}")
        print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: split_analyze.py <activity_id> <indoor|outdoor>")
    main(sys.argv[1], sys.argv[2])
