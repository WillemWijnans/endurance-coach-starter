#!/usr/bin/env python3
"""
Weight + body-composition tracker.

Stores REAL weigh-ins only (Garmin temp_weight=false). Computes:
  - 7-day rolling average (the only number that means anything day-to-day)
  - lean / fat mass split (bioimpedance BF% — noisy, trend only)
  - W/kg using eFTP at each weigh-in

Daily weigh-ins (morning, fasted, post-toilet) make the rolling average useful.
Single weigh-ins are noise: ±1kg swings from glycogen/hydration/food.

Usage:
  python3 weight.py add <date> <weight_kg> [bf_pct] [eftp]   # log a weigh-in
  python3 weight.py report                                    # trend summary
  python3 weight.py chart                                     # → weight_trend.png
"""
import csv
import sys
from pathlib import Path
import athlete_config as C

LOG = C.WEIGHT_LOG
CHART = C.DATA_DIR / "weight_trend.png"
COLS = ["date", "weight_kg", "bf_pct", "eftp"]


def load():
    if not LOG.exists():
        return []
    with LOG.open() as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append({
                "date": r["date"],
                "weight_kg": float(r["weight_kg"]) if r["weight_kg"] else None,
                "bf_pct": float(r["bf_pct"]) if r["bf_pct"] else None,
                "eftp": float(r["eftp"]) if r["eftp"] else None,
            })
        return sorted(rows, key=lambda x: x["date"])


def save(rows):
    rows = sorted(rows, key=lambda x: x["date"])
    with LOG.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: ("" if r.get(k) is None else r[k]) for k in COLS})


def add_weighin(date, weight, bf=None, eftp=None):
    rows = [r for r in load() if r["date"] != date]  # de-dupe by date
    rows.append({"date": date, "weight_kg": weight, "bf_pct": bf, "eftp": eftp})
    save(rows)
    return len(rows)


def rolling_avg(rows, window=7):
    """Simple trailing mean of available weigh-ins in the window (by count,
    not calendar — works whether data is daily or sparse)."""
    out = []
    weights = [r for r in rows if r["weight_kg"] is not None]
    for i, r in enumerate(weights):
        chunk = weights[max(0, i - window + 1): i + 1]
        avg = sum(c["weight_kg"] for c in chunk) / len(chunk)
        out.append((r["date"], r["weight_kg"], avg))
    return out


def lean_fat(weight, bf):
    if weight is None or bf is None:
        return None, None
    fat = weight * bf / 100
    return weight - fat, fat


def report():
    rows = load()
    weighins = [r for r in rows if r["weight_kg"] is not None]
    if not weighins:
        print("No weigh-ins logged yet.")
        return
    ra = rolling_avg(rows)
    latest = weighins[-1]
    print(f"=== Weight tracker ({len(weighins)} weigh-ins) ===\n")
    print(f"{'Date':<12}{'Wt':>7}{'7d-avg':>8}{'BF%':>6}{'Lean':>7}{'Fat':>6}{'W/kg':>7}")
    print("-" * 53)
    for r in weighins[-14:]:
        _, _, avg = next(x for x in ra if x[0] == r["date"])
        lean, fat = lean_fat(r["weight_kg"], r["bf_pct"])
        wkg = r["eftp"] / r["weight_kg"] if r["eftp"] else None
        print(f"{r['date']:<12}{r['weight_kg']:>7.2f}{avg:>8.2f}"
              f"{(f'{r['bf_pct']:.1f}' if r['bf_pct'] else '—'):>6}"
              f"{(f'{lean:.1f}' if lean else '—'):>7}"
              f"{(f'{fat:.1f}' if fat else '—'):>6}"
              f"{(f'{wkg:.2f}' if wkg else '—'):>7}")

    # Trend: first vs last 7d-avg
    if len(ra) >= 2:
        first_avg, last_avg = ra[0][2], ra[-1][2]
        span_days = (weighins[-1]["date"], weighins[0]["date"])
        print(f"\n7-day-avg trend: {first_avg:.2f} → {last_avg:.2f} kg "
              f"({last_avg - first_avg:+.2f} kg over the logged span)")
    # Latest W/kg vs Feb PR
    if latest["eftp"]:
        wkg = latest["eftp"] / latest["weight_kg"]
        print(f"Latest W/kg: {wkg:.2f} (eFTP {latest['eftp']:.0f} / {latest['weight_kg']:.1f}kg)")
        print(f"Feb PR ref:  4.14 (319 / 77.0kg)  →  {wkg - 4.14:+.2f} vs PR")
    print("\nNote: weigh daily (morning, fasted) for the 7d-avg to be meaningful.")
    print("Single readings swing ±1kg from glycogen/hydration — ignore them.")


def chart():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from datetime import datetime

    rows = load()
    weighins = [r for r in rows if r["weight_kg"] is not None]
    if len(weighins) < 2:
        print("Need ≥2 weigh-ins to chart.")
        return
    ra = rolling_avg(rows)
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in weighins]
    wts = [r["weight_kg"] for r in weighins]
    avgs = [a[2] for a in ra]
    wkg = [(datetime.strptime(r["date"], "%Y-%m-%d"), r["eftp"] / r["weight_kg"])
           for r in weighins if r["eftp"]]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [2, 1]})
    ax1.plot(dates, wts, "o", color="#bbb", markersize=5, label="weigh-in")
    ax1.plot(dates, avgs, "-", color="#0f5132", linewidth=2.5, label="7-day avg")
    ax1.axhline(77.0, color="#842029", linestyle="--", linewidth=1, label="Feb PR weight (77.0)")
    ax1.set_ylabel("Weight (kg)")
    ax1.set_title("Weight trend (real weigh-ins + 7-day average)")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(True, alpha=0.3)

    if wkg:
        wd, wv = zip(*wkg)
        ax2.plot(wd, wv, "o-", color="#1a5fb4", markersize=4, linewidth=1.8, label="W/kg (eFTP)")
        ax2.axhline(4.14, color="#842029", linestyle="--", linewidth=1, label="Feb PR (4.14)")
        ax2.set_ylabel("W/kg")
        ax2.legend(loc="lower left", fontsize=9)
        ax2.grid(True, alpha=0.3)
    ax2.set_xlabel("Date")
    fig.autofmt_xdate()
    plt.tight_layout()
    CHART.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(CHART, dpi=110)
    print(f"Chart saved: {CHART}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "add":
        date, wt = sys.argv[2], float(sys.argv[3])
        bf = float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] not in ("", "-") else None
        eftp = float(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5] not in ("", "-") else None
        n = add_weighin(date, wt, bf, eftp)
        print(f"Logged {date}: {wt}kg (now {n} weigh-ins)")
    elif cmd == "report":
        report()
    elif cmd == "chart":
        chart()
    else:
        sys.exit(__doc__)
