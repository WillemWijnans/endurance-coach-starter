#!/usr/bin/env python3
"""
Internal-vs-external load: hr_load / power_load ratio.

WHY THIS EXISTS. TSS (power_load) is deliberately power-only — it measures
MECHANICAL work relative to threshold, which is what makes it comparable across
conditions. The cost is that it is blind to what a day actually took out of you:
heat, dehydration, fatigue and illness are invisible to it.

intervals already computes an HR-based load (hr_load, type HRSS) alongside it but
does NOT use it for CTL (icu_training_load_data = 100 = power priority). That is
the right default — an HR-driven CTL would jump every time you were hot or stressed.

So the SIGNAL IS THE RATIO, not either number:
    ratio = hr_load / power_load
    high ratio  -> the day cost more than it produced (heat / fatigue / illness)
    low ratio   -> normal; mechanical work exceeded cardiovascular cost

A WORKED EXAMPLE (real data, one athlete). Read in order:

    day 0   22C      power_load 142  hr_load 181  ratio 1.27   <-- cold sore that evening
    ...four days later, same illness still active...
    day 1   30-35C   power_load 169  hr_load 253  ratio 1.50   <-- heat ON TOP of it
    day 2   27C      power_load 264  hr_load 220  ratio 0.83
    day 3            power_load 259  hr_load 228  ratio 0.88

Day 0 is the metric's best argument: decoupling on that ride was +0.38%, which
reads as excellent durability, and the cold sore appeared that evening. The ratio
saw immune activation that the power-based numbers could not.

Day 1 needs care, and is a useful lesson in not over-claiming. It is tempting to
call it a clean heat day, but the rider was still four days into that illness, so
two causes were live at once. What isolates heat is days 2 and 3: SAME illness,
temperature down to 27C, ratio back to normal. The controlled comparison is what
licenses the conclusion — not the single elevated number.

The honest summary: a high ratio tells you the day cost more than it produced. It
does NOT tell you why. Heat, dehydration, fatigue and illness all raise it, and
more than one can be true at once.

Also useful alongside it: watts per heartbeat, which falls on the same days.

Usage:
  python3 loads.py <activity_id> [<activity_id> ...]
  python3 loads.py range <oldest> <newest>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import athlete_config as C
from wellness import BASE_URL, creds          # reuse the intervals REST plumbing

# Ratio bands live in athlete_config.py. CALIBRATE from ~10 of your own normal
# rides, then set the bands around your own baseline.
RATIO_NORMAL_MAX = C.RATIO_NORMAL_MAX
RATIO_ELEVATED = C.RATIO_ELEVATED


def load_ratio(hr_load, power_load):
    """hr_load / power_load, or None if either is missing/zero.

    Deliberately returns None rather than 0 or inf: a missing HR stream and a
    genuinely zero ratio must not look the same to a caller.
    """
    try:
        hr, pw = float(hr_load), float(power_load)
    except (TypeError, ValueError):
        return None
    if pw <= 0 or hr <= 0:
        return None
    return round(hr / pw, 3)


def interpret(ratio):
    """One-line verdict for a ratio. Returns '' when there is nothing to say."""
    if ratio is None:
        return "no HR or power load — cannot compare"
    if ratio >= RATIO_ELEVATED:
        return (f"⚠️  ELEVATED ({ratio:.2f}) — the day cost MORE than it produced. "
                "Heat, dehydration, fatigue or illness. TSS understates this ride.")
    if ratio > RATIO_NORMAL_MAX:
        return f"slightly elevated ({ratio:.2f}) — worth noting, not alarming"
    return f"normal ({ratio:.2f})"


def fetch_activity(activity_id):
    import requests
    aid, key = creds()
    r = requests.get(f"{BASE_URL}/activity/{activity_id}",
                     auth=("API_KEY", key), timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_range(oldest, newest, min_km=20):
    import requests
    aid, key = creds()
    r = requests.get(f"{BASE_URL}/athlete/{aid}/activities",
                     params={"oldest": oldest, "newest": newest},
                     auth=("API_KEY", key), timeout=90)
    r.raise_for_status()
    return [a for a in r.json() if (a.get("distance") or 0) >= min_km * 1000]


def conditions(a):
    """Name the conditions that plausibly explain a costly day.

    Weather is NOT invisible to the analysis — platforms store it on the
    activity, including how much of the ride was spent into a headwind. Guessing
    at "maybe it was windy" when the number is sitting in the payload is a waste
    of a real signal.

    HEAT AND WIND ARE NOT THE SAME KIND OF FACT, and the distinction matters:

      • Heat is a CAUSE. It raises heart rate at the same power, which is exactly
        what this ratio detects. Measured on one athlete's 81 weather-tagged
        rides: median ratio 0.84-0.90 all the way from below 10C to 25C, then
        1.59 above 30C.

      • Wind is CONTEXT. Across those same rides, headwind share showed no
        relationship to the ratio at all (0.86 / 0.89 / 0.85 across 0-30%,
        30-45% and 45-60%). That is what should happen: at matched watts a
        headwind changes your SPEED, not your metabolic cost, and the power-based
        load already counts the watts you produced. It explains a slow day and a
        blown pacing plan, not a costly one.

    So wind gets reported, and explicitly labelled as context. Offering it as the
    reason a ratio is high would be a confident wrong answer.

    Returns (notes, detail). `notes` holds only what is worth remarking on, so a
    mild day returns nothing rather than noise.
    """
    if not a.get("has_weather"):
        return [], {}
    temp = a.get("average_weather_temp")
    if temp is None:
        temp = a.get("average_temp")
    head = a.get("headwind_percent")
    wind = a.get("average_wind_speed")
    gust = a.get("average_wind_gust")
    detail = {"temp": temp, "headwind_pct": head, "wind_ms": wind, "gust_ms": gust}

    notes = []
    if temp is not None:
        # Two tiers: a caution, and the temperature your own data shows actually
        # costs you. Saying "warm" about a ride that historically wrecks you is
        # as unhelpful as crying heat stress at 26C.
        if temp >= C.TEMP_HOT_DEMONSTRATED:
            notes.append(f"{temp:.0f}\u00b0C \u2014 above your demonstrated heat breakpoint")
        elif temp >= C.TEMP_HOT:
            notes.append(f"{temp:.0f}\u00b0C \u2014 warm, mild effect expected")
        elif temp <= C.TEMP_COLD:
            notes.append(f"{temp:.0f}\u00b0C (cold)")

    # Wind is reported as CONTEXT, never as a cause — see the note above.
    ctx = []
    if head is not None and head >= C.HEADWIND_NOTABLE:
        ctx.append(f"{head:.0f}% headwind")
    if wind is not None and wind >= C.WIND_STRONG_MS:
        ctx.append(f"wind {wind:.0f}m/s" + (f" gusting {gust:.0f}" if gust else ""))
    if ctx:
        notes.append("context (not a cost driver): " + ", ".join(ctx))
    return notes, detail


def row(a):
    """Extract the comparison fields from an intervals activity dict."""
    hr, pw = a.get("hr_load"), a.get("power_load")
    return {
        "date": (a.get("start_date_local") or "")[:10],
        "name": (a.get("name") or "")[:34],
        "km": round((a.get("distance") or 0) / 1000),
        "power_load": pw,
        "hr_load": hr,
        "ratio": load_ratio(hr, pw),
        "w_per_beat": a.get("icu_power_hr"),
        "trimp": a.get("trimp"),
        "conditions": conditions(a)[0],
    }


def report(rows):
    print(f"{'date':<12}{'km':>5}{'power':>7}{'hr':>6}{'ratio':>7}{'W/beat':>8}   verdict")
    for r in sorted(rows, key=lambda x: x["date"]):
        g = lambda k, f="": f"{r[k]:{f}}" if r[k] is not None else "-"
        print(f"{r['date']:<12}{r['km']:>5}{g('power_load'):>7}{g('hr_load'):>6}"
              f"{g('ratio','.2f'):>7}{g('w_per_beat','.2f'):>8}   {interpret(r['ratio'])}")
        if r.get("conditions"):
            print(f"{'':<45}   conditions: {', '.join(r['conditions'])}")
    print(f"\n  <={RATIO_NORMAL_MAX} normal · >{RATIO_NORMAL_MAX} notable · "
          f">={RATIO_ELEVATED} the day cost more than it produced")
    print("  Bands are placeholders — set your own in athlete_config.py once you "
          "have\n  10+ rides. Note your typical range; deviation from it is the signal.")


def main(argv):
    if not argv:
        sys.exit(__doc__.strip().split("Usage:")[1])
    if argv[0] == "range":
        report([row(a) for a in fetch_range(argv[1], argv[2])])
    else:
        report([row(fetch_activity(a)) for a in argv])


if __name__ == "__main__":
    main(sys.argv[1:])
