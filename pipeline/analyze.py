#!/usr/bin/env python3
"""
One-command ride analysis. Computes every metric via the tested ridelib,
appends one row to master_log_v2.csv (safe csv writer — no more comma bugs),
and prints a clean report.

Usage: python3 analyze.py <activity_id> [indoor|outdoor|auto] [date] [name]
                          [--fluid ML] [--carb G] [--protein G]

env defaults to "auto" — derived from the intervals activity type stored at
extract time (VirtualRide→indoor, Ride→outdoor). Pass indoor/outdoor only to
override; a mismatch with the recorded type prints a warning.

Assumes streams/<activity_id>.json exists (run extract_stream.py first).
"""
import csv
import sys
from pathlib import Path
import athlete_config as C
import ridelib as R
import fuellib as F

LOG = C.MASTER_LOG

# Column order for the log (stable schema).
COLS = ["activity_id", "date", "env", "name", "moving_min", "elapsed_min", "paused_min",
        "np", "if", "tss", "normve", "vif", "vtss", "vif_if", "hr_avg", "hr_max",
        "ve_avg", "ve_rmax30", "br_avg", "ef", "ve_ef", "decoupling_pct",
        "veZ1", "veZ2", "veZ3", "veZ4", "veZ5",
        "hrREC", "hrZ2", "hrTEMPO", "hrTHRESH", "hrVO2", "div_pp",
        "hrr_avg", "ver_avg", "brr_avg", "n_gaps", "long_stop_min", "decoupling_clean",
        # fuelling (self-reported, blank when not logged — blank is NOT zero)
        "fluid_ml", "carb_g", "protein_g", "fluid_hit", "carb_hit"]


def load_rows():
    """Existing log rows, for the rolling fuel hit-rate."""
    if not LOG.exists():
        return []
    with LOG.open() as f:
        return list(csv.DictReader(f))


def append_row(metrics):
    """Append one row. csv module handles commas/quoting → no more CSV bugs."""
    new_file = not LOG.exists()
    # de-dupe: if activity already logged, rewrite without the old copy
    rows = []
    if not new_file:
        with LOG.open() as f:
            rows = [r for r in csv.DictReader(f) if r["activity_id"] != metrics["activity_id"]]
    with LOG.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader()
        for r in rows:
            wr.writerow(r)
        wr.writerow({k: metrics.get(k, "") for k in COLS})
    return len(rows) + 1


SHORT_RIDE_MIN = 60   # decoupling below this is warm-up artifact, not fade


def report(m):
    flag = "✅ aligned" if abs(m["div_pp"]) <= 10 else "⚠️ Pattern A/B divergence"
    dec = m["decoupling_pct"]
    if not m.get("decoupling_clean", 1):
        dec_note = (f"⚠️ CONTAMINATED by {m['long_stop_min']}min stop — "
                    f"trust matched-power VE drift instead, not this number")
    elif m["moving_min"] < SHORT_RIDE_MIN:
        # Decoupling compares first half to second half. On a short ride the
        # first half is mostly WARM-UP, when HR still lags power — which
        # depresses first-half HR and manufactures apparent drift. Measured
        # across the log: rides <60min average +5.1% decoupling vs -0.7% for
        # 100-160min rides. The number is an artifact of duration, not a fade.
        dec_note = (f"⚠️ IGNORE — ride is only {m['moving_min']:.0f}min. Sub-"
                    f"{SHORT_RIDE_MIN}min rides average ~+5% purely from warm-up "
                    f"lag (short rides commonly show +5% where long ones show ~0%). "
                    f"Decoupling is only meaningful on rides over ~1h.")
    else:
        dec_note = ("negative (efficiency improved)" if dec < 0
                    else "excellent" if dec < 5 else "good" if dec < 7 else "notable fade")
    return f"""
{'='*60}
  {R.env_label(m['env'])}   {m['activity_id']}  {m['date']}  {m['name']}
{'='*60}
  Moving {m['moving_min']}min  (elapsed {m['elapsed_min']}, paused {m['paused_min']}, {m['n_gaps']} gaps)
  NP {m['np']}W · IF {m['if']} · TSS {m['tss']}
  HR avg {m['hr_avg']} max {m['hr_max']} · VE avg {m['ve_avg']} rmax30 {m['ve_rmax30']} · BR {m['br_avg']}
  NormVE {m['normve']} · vIF {m['vif']} · vTSS {m['vtss']} · vIF/IF {m['vif_if']}

  EF {m['ef']}   VE-EF {m['ve_ef']}   Decoupling {m['decoupling_pct']:+}%  ({dec_note})

  Reserves: HRR {m['hrr_avg']}% · VER {m['ver_avg']}% · BRR {m['brr_avg']}%

  VE zones:  Z1 {m['veZ1']} Z2 {m['veZ2']} Z3 {m['veZ3']} Z4 {m['veZ4']} Z5 {m['veZ5']}
  HR zones:  REC {m['hrREC']} Z2 {m['hrZ2']} TEMPO {m['hrTEMPO']} THR {m['hrTHRESH']} VO2 {m['hrVO2']}
  Divergence {m['div_pp']:+}pp  {flag}
{'='*60}"""


def pop_flags(argv):
    """Strip --fluid/--carb/--protein/--bike out of argv so the positional args
    keep working exactly as before. Returns (remaining_argv, fuel_dict)."""
    out, fuel, i = [], {}, 0
    nums = {"--fluid": "fluid_ml", "--carb": "carb_g", "--protein": "protein_g",
            "--temp": "temp_c"}
    text = {"--bike": "bike"}
    while i < len(argv):
        a = argv[i]
        if a in text:
            if i + 1 >= len(argv):
                sys.exit(f"{a} needs a value")
            fuel[text[a]] = argv[i + 1]
            i += 2
            continue
        if a in nums:
            if i + 1 >= len(argv):
                sys.exit(f"{a} needs a number")
            try:
                fuel[nums[a]] = float(argv[i + 1])
            except ValueError:
                sys.exit(f"{a} needs a number, got {argv[i + 1]!r}")
            i += 2
            continue
        out.append(a)
        i += 1
    return out, fuel


def fuel_history(rows):
    """Rolling hit-rate. THIS is the intervention: a visibly failing metric.
    Prose advice reliably fails to change fuelling behaviour; a number you can
    watch tends to work, the same way a weight log changes weigh-ins."""
    lines = []
    for field, label in (("fluid_hit", "fluid"), ("carb_hit", "carb")):
        hits, seen = F.hit_rate(rows, field)
        if seen >= 3:
            lines.append(f"  {label} target hit {hits} of the last {seen} logged rides")
    return "\n".join(lines)


if __name__ == "__main__":
    argv, fuel = pop_flags(sys.argv[1:])
    if not argv:
        sys.exit("usage: analyze.py <activity_id> [indoor|outdoor|auto] [date] [name] "
                 "[--fluid ML] [--carb G] [--protein G] [--bike winspace|lauf]")
    aid = argv[0]
    env_arg = argv[1] if len(argv) > 1 else "auto"
    meta = R.load_meta(aid)
    try:
        env, warn = R.resolve_env(env_arg, meta.get("activity_type"))
    except ValueError as e:
        sys.exit(f"env: {e}")
    if warn:
        print(f"⚠️  {warn}")
    date = argv[2] if len(argv) > 2 else meta.get("date", "")
    name = argv[3] if len(argv) > 3 else meta.get("name", "")
    streams = R.load_stream(aid)
    m = R.compute(streams, env, activity_id=aid, date=date, name=name)
    print(report(m))

    # ── fuelling. A missing number is blank, never zero: scoring an unlogged
    # ride as a miss would punish forgetting to log rather than under-fuelling.
    a = F.assess(fuel.get("fluid_ml"), fuel.get("carb_g"), m["moving_min"],
                 temp_c=fuel.get("temp_c"))
    if a:
        m["fluid_ml"] = fuel.get("fluid_ml", "")
        m["carb_g"] = fuel.get("carb_g", "")
        m["protein_g"] = fuel.get("protein_g", "")
        m["fluid_hit"] = int(a["fluid_hit"]) if "fluid_hit" in a else ""
        m["carb_hit"] = int(a["carb_hit"]) if "carb_hit" in a else ""
        print("\n  FUELLING")
        print(F.line(a))
        need, covered = F.refill_needed(m["moving_min"], fuel.get("bike"))
        if need:
            print(f"  ⚠️  carrying capacity covers only {covered}min — a refill stop "
                  f"was required on this bike")
    else:
        print("\n  FUELLING  — not logged. Add --fluid ML --carb G to record it.")

    prior = load_rows()
    total = append_row(m)
    print(f"\nLogged to master_log_v2.csv ({total} rides)")
    hist = fuel_history(prior + [m])
    if hist:
        print(hist)
    # A dated row is REQUIRED: every trend/EF/period analysis filters on date, so
    # an undated row is logged but silently invisible. This bit us — 6 rides from
    # Jul 19-Aug 10 2026 were missing from every date-based analysis until spotted
    # by accident. The streams-only MCP dump carries no start_date, so when the
    # date can't be derived it MUST be passed as argv[3].
    if not date:
        print("\n" + "=" * 60)
        print("⚠️  NO DATE ON THIS ROW — it will be INVISIBLE to every trend analysis.")
        print(f"   Fix now:  python3 analyze.py {aid} {env} <YYYY-MM-DD> \"<name>\"")
        print("   (then delete the undated duplicate row from master_log_v2.csv)")
        print("=" * 60)
