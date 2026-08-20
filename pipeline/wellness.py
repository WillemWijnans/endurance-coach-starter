#!/usr/bin/env python3
"""
Wellness history fetcher + outlier screen.

The intervals MCP wrapper caps wellness GETs at ~8 days, which makes any long
trend / before-after analysis painful (25+ calls for 6 months). This pulls ANY
date range in ONE REST call, and screens known-bad values before they can reach
an analysis.

WHY THE SCREEN EXISTS: 2026-05-08 came back with restingHR=101 — a device
misread on the SFO->AMS flight, not a physiological resting HR. That single
value dragged its week's mean RHR to 55.4, invented a phantom "illness week",
and corrupted the first pass of the caffeine before/after analysis. Screen
first, analyse second.

The screen is deliberately TWO-TIER so we don't throw away real physiology:
  - IMPLAUSIBLE (device error)  -> value dropped to None, reported
  - SUSPECT    (real but odd)   -> value KEPT, flagged for the analyst
A genuine illness can push resting HR into the high 50s; that's data, not noise.

Also computes NIGHT SPLITS (early vs late) from Garmin's per-reading HRV and
heart-rate series — see the night-split section for why the overnight averages
mislead when a disturbance is front-loaded in the night.

Usage:
  python3 wellness.py fetch <oldest> <newest> [out.csv]   # screened CSV
  python3 wellness.py report <oldest> <newest>            # what got screened
  python3 wellness.py night <oldest> <newest>             # early/late splits
"""
import csv
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
import athlete_config as C

BASE_URL = "https://intervals.icu/api/v1"
SYNC_ENV = C.SYNC_ENV

# Screening bounds — see athlete_config.py. Two-tier ON PURPOSE: device errors
# get dropped, odd-but-real values get kept and flagged. Genuine illness can push
# resting HR well above normal; that is data, not noise.
RHR_IMPLAUSIBLE = C.RHR_IMPLAUSIBLE
RHR_SUSPECT = C.RHR_SUSPECT

HRV_IMPLAUSIBLE = C.HRV_IMPLAUSIBLE

# Dates with a known non-training explanation. Analyses comparing periods
# should usually EXCLUDE these rather than let them skew a mean.
#
# STANDING RULE (athlete, Aug 14 2026): TIMEZONE-CROSSING TRAVEL DAYS produce
# unreliable wellness data BY MECHANISM, not by malfunction — especially flying
# EASTBOUND. Garmin derives RHR/sleep from a window it believes is night; shift
# local time far enough and that window lands on hours you were awake and upright.
# The sensor is fine; the label is wrong. Expect it, exclude it, don't diagnose it.
KNOWN_CONTEXT = C.KNOWN_CONTEXT

CSV_FIELDS = ["date", "restingHR", "hrv", "avgSleepingHR", "sleepSecs",
              "sleepScore", "ctl", "atl", "weight", "respiration", "spO2",
              # Garmin Health Snapshot — a deliberate 2-min AWAKE, SEATED reading
              # the sync writes through as custom fields. NOT comparable to the
              # overnight values above (different posture/state): compare
              # snapshot-to-snapshot only. Invaluable on nights the watch wasn't
              # worn, and as a clean cross-check when an overnight average looks
              # alarming, since it is a clean deliberate reading rather than an average.
              "HrvSnapshotRmssd", "HrvSnapshotSdrr", "RestingHRSnapshot",
              "Spo2Snapshot", "readiness", "BodyBatteryMax", "BodyBatteryMin",
              "flags", "context"]


# ----------------------------------------------------------------- screening
def _num(v):
    """Coerce to float, or None if absent/unparseable."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def screen_value(field, value):
    """Screen one value. Returns (kept_value, flag_or_None).

    flag is 'implausible' (value dropped) or 'suspect' (value kept).
    """
    v = _num(value)
    if v is None:
        return None, None
    if field == "restingHR":
        lo, hi = RHR_IMPLAUSIBLE
        if not (lo <= v <= hi):
            return None, f"restingHR={v:g} implausible (dropped)"
        if v > RHR_SUSPECT:
            return v, f"restingHR={v:g} suspect (kept)"
    elif field == "hrv":
        lo, hi = HRV_IMPLAUSIBLE
        if not (lo <= v <= hi):
            return None, f"hrv={v:g} implausible (dropped)"
    return v, None


def screen(rows):
    """Screen a list of wellness dicts. Returns (screened_rows, issues).

    Does not mutate the input. issues is a list of (date, message).
    """
    out, issues = [], []
    for r in rows:
        rec = dict(r)
        date = rec.get("date") or rec.get("id") or ""
        rec["date"] = date
        for field in ("restingHR", "hrv"):
            kept, flag = screen_value(field, rec.get(field))
            rec[field] = kept
            if flag:
                issues.append((date, flag))
                rec["flags"] = f"{rec.get('flags','')} {flag}".strip()
        ctx = KNOWN_CONTEXT.get(date)
        if ctx:
            rec["context"] = ctx
        out.append(rec)
    return out, issues


def exclude_known_context(rows):
    """Drop days with a known non-training explanation (illness/travel)."""
    return [r for r in rows if not KNOWN_CONTEXT.get(r.get("date", ""))]


# -------------------------------------------------------------------- fetch
def creds():
    """Resolve intervals credentials the same way the Garmin sync does."""
    from dotenv import load_dotenv  # lazy: keeps the module importable for tests
    load_dotenv(C.ENV_FILE)      # written by setup.py
    load_dotenv(SYNC_ENV)        # or an existing Garmin-sync .env
    key = os.getenv("INTERVALS_API_KEY")
    aid = os.getenv("INTERVALS_ATHLETE_ID")
    if not key or not aid:
        import keyring
        key = key or keyring.get_password("intervals", "api_key")
        aid = aid or keyring.get_password("intervals", "athlete_id")
    if not key or not aid:
        sys.exit("could not resolve intervals credentials (.env or keyring)")
    return aid, key


def fetch(oldest, newest):
    """GET the full wellness range in one call (no 8-day cap)."""
    import requests  # lazy
    aid, key = creds()
    r = requests.get(f"{BASE_URL}/athlete/{aid}/wellness",
                     params={"oldest": oldest, "newest": newest},
                     auth=("API_KEY", key), timeout=60)
    r.raise_for_status()
    rows = [{**x, "date": x.get("id", "")} for x in r.json()]
    return sorted(rows, key=lambda x: x["date"])


def to_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ------------------------------------------------------- night-split (Garmin)
# WHY: an overnight AVERAGE can systematically overstate stress when the
# disturbance is front-loaded — HRV climbs and HR falls through the night —
# so the average is dragged down by a rough first couple of hours while the
# end-of-night value (where the night actually lands) is far healthier.
#   Real example: HRV avg 37 but last-90min 45; HR avg 54 but last-90min 49,
#   floor 43. Reading only the averages produced two false alarms in one week.
#
# Diagnostic value: the MIN/late values show recovery CAPACITY (a floor that
# holds even on bad nights means nothing systemic is wrong); the EARLY values
# show what disturbed the night (meal timing/size, room temperature, wind-down, late hard training).
NIGHT_WINDOW_MIN = C.NIGHT_WINDOW_MIN
# End-of-night HRV at/above this = recovered. Set from your own baseline range.
HRV_LATE_RECOVERED = C.HRV_LATE_RECOVERED
# Early-night HR is judged RELATIVE TO THAT NIGHT'S OWN FLOOR (early - min),
# not as an absolute. Absolute sleep-onset HR varies with how late/active the
# evening was, so a fixed cut-off flagged 8 of 9 nights once true sleep-onset
# was included; the excess-over-floor separates cleanly:
# CALIBRATE from ~2 weeks of your own nights; the split values themselves are the signal, this is just a hint.
HR_EARLY_EXCESS_DISTURBED = C.HR_EARLY_EXCESS_DISTURBED


def _to_seconds(t):
    """Normalize a timestamp to epoch seconds. Accepts datetime, ISO string,
    epoch seconds or epoch milliseconds. Returns None if unparseable."""
    if t is None:
        return None
    if isinstance(t, datetime):
        return t.timestamp()
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(t.replace("Z", "")).timestamp()
        except ValueError:
            return None
    if isinstance(t, bool):          # bool is an int subclass — reject explicitly
        return None
    if isinstance(t, (int, float)):
        return t / 1000.0 if t > 1e11 else float(t)   # ms vs s
    return None


def night_split(samples, window_min=NIGHT_WINDOW_MIN):
    """Split a night's samples into its first and last `window_min` minutes.

    samples: iterable of (timestamp, value). Timestamps may be datetimes, ISO
    strings, epoch s or epoch ms; order does not matter. None values dropped.

    Returns {early, late, delta, min, max, n, span_min} — or None if there is
    nothing usable. If the night is shorter than the window the two ends
    overlap, so early/late both approach the whole-night mean (delta -> 0):
    that is honest rather than wrong, but check span_min before reading much
    into a small delta.
    """
    pts = []
    for t, v in samples or []:
        s = _to_seconds(t)
        if s is None or v is None:
            continue
        try:
            pts.append((s, float(v)))
        except (TypeError, ValueError):
            continue
    if not pts:
        return None
    pts.sort()
    t0, t1 = pts[0][0], pts[-1][0]
    w = window_min * 60
    early = [v for s, v in pts if s - t0 <= w]
    late = [v for s, v in pts if t1 - s <= w]
    e, l = mean(early), mean(late)
    return {
        "early": round(e, 1),
        "late": round(l, 1),
        "delta": round(l - e, 1),
        "min": round(min(v for _, v in pts), 1),
        "max": round(max(v for _, v in pts), 1),
        "n": len(pts),
        "span_min": round((t1 - t0) / 60, 1),
    }


def early_excess(split):
    """How far the early night sat above that night's own floor.

    Normalizes out how late/active the evening was — a night that STARTS near
    its floor was undisturbed; one that starts well above it had something
    keeping the system up (meal, heat, late hard training, illness).
    """
    if not split:
        return None
    return round(split["early"] - split["min"], 1)


def garmin_client():
    """Authenticated Garmin client (same creds/token cache as the sync)."""
    import garminconnect                      # lazy — not needed for pure logic
    from dotenv import load_dotenv
    load_dotenv(C.ENV_FILE)      # written by setup.py
    load_dotenv(SYNC_ENV)        # or an existing Garmin-sync .env
    g = garminconnect.Garmin(os.getenv("GARMIN_USERNAME"),
                             os.getenv("GARMIN_PASSWORD"))
    g.login(str(Path.home() / ".garminconnect"))
    return g


def hrv_night(g, date_str):
    """(samples, summary) for one night — one API call for both.

    summary carries Garmin's own overnight verdict:
      high5    - best 5-min HRV reached. The PEAK, not a sustained level. It
                 is easy to misread: one observed night showed high5 of 65 while
                 the sustained last-90min was 45. Read it as "the best it got
                 to", alongside `late`, never instead of it.
      status   - LOW / BALANCED / UNBALANCED vs the wearer's own baseline
      balanced_low/high - the device's personal balanced range for this wearer
    """
    d = g.get_hrv_data(date_str) or {}
    samples = [(r.get("readingTimeLocal"), r.get("hrvValue"))
               for r in (d.get("hrvReadings") or [])]
    s = d.get("hrvSummary") or {}
    base = s.get("baseline") or {}
    summary = {
        "avg": s.get("lastNightAvg"),
        "high5": s.get("lastNight5MinHigh"),
        "status": s.get("status"),
        "balanced_low": base.get("balancedLow"),
        "balanced_high": base.get("balancedUpper"),
    } if s else None
    return samples, summary


def hrv_night_samples(g, date_str):
    """(timestamp, hrv) for one night. Garmin already scopes these to sleep."""
    return hrv_night(g, date_str)[0]


def sleep_window(g, date_str):
    """(start_ms, end_ms) of the night's sleep, or (None, None).

    Without this the per-day series get stitched across TWO calendar days and a
    "night" split silently becomes a daytime average — which on a watch-off
    night produced an alarming-looking but meaningless read. No sleep record
    means no night to report.
    """
    dto = (g.get_sleep_data(date_str) or {}).get("dailySleepDTO") or {}
    s0, s1 = dto.get("sleepStartTimestampGMT"), dto.get("sleepEndTimestampGMT")
    return (s0, s1) if s0 and s1 else (None, None)


def hr_night_samples(g, date_str):
    """(timestamp, hr) across the sleep window.

    get_heart_rates() is scoped to one CALENDAR date, so the target date alone
    starts at 00:00 and misses pre-midnight sleep. Stitch the previous day too,
    then clip to the sleep window from the sleep record.
    """
    s0, s1 = sleep_window(g, date_str)
    if not s0:
        return []          # no sleep record -> no night to report (see below)
    prev = (date.fromisoformat(date_str) - timedelta(days=1)).isoformat()
    vals = []
    for ds in (prev, date_str):
        hr = g.get_heart_rates(ds) or {}
        vals += [(t, v) for t, v in (hr.get("heartRateValues") or []) if v]
    return [(t, v) for t, v in vals if s0 <= t <= s1]


def stress_night_samples(g, date_str):
    """(timestamp, stress) across the sleep window — 3-min Garmin samples.

    Same treatment as HR: stitch the previous calendar day so true sleep onset
    is included, then clip to the sleep window.
    """
    s0, s1 = sleep_window(g, date_str)
    if not s0:
        return []
    prev = (date.fromisoformat(date_str) - timedelta(days=1)).isoformat()
    vals = []
    for ds in (prev, date_str):
        st = g.get_all_day_stress(ds) or {}
        # Garmin uses -1/-2 for "unmeasurable" — drop, don't average them in
        vals += [(t, v) for t, v in (st.get("stressValuesArray") or [])
                 if isinstance(v, (int, float)) and v >= 0]
    return [(t, v) for t, v in vals if s0 <= t <= s1]


def sleep_detail(g, date_str):
    """Sleep architecture for one night.

    DEEP sleep is the number that matters most here: it is concentrated in the
    first hours, so a disturbed early night shows up as deep-sleep loss before
    it shows anywhere else. Typical adult is 60-110min; Aug 5 2026 was 30min.
    `insight` is Garmin's own verdict — it said STRESSFUL_EVENING that night.
    """
    sl = g.get_sleep_data(date_str) or {}
    dto = sl.get("dailySleepDTO") or {}
    if not dto:
        return None
    m = lambda k: round(dto[k] / 60) if dto.get(k) is not None else None
    return {
        "deep_min": m("deepSleepSeconds"),
        "light_min": m("lightSleepSeconds"),
        "rem_min": m("remSleepSeconds"),
        "awake_min": m("awakeSleepSeconds"),
        "awake_count": dto.get("awakeCount"),
        "restless": sl.get("restlessMomentsCount"),
        "sleep_stress": dto.get("avgSleepStress"),
        "spo2_low": dto.get("lowestSpO2Value"),
        "insight": dto.get("sleepScorePersonalizedInsight"),
        "feedback": dto.get("sleepScoreFeedback"),
    }


def night_report(oldest, newest, window_min=NIGHT_WINDOW_MIN):
    """Early/late HRV + sleeping-HR splits for a date range."""
    g = garmin_client()
    d0, d1 = date.fromisoformat(oldest), date.fromisoformat(newest)
    days = []
    while d0 <= d1:
        ds = d0.isoformat()
        try:
            samples, hsum = hrv_night(g, ds)
            days.append((ds,
                         night_split(samples, window_min),
                         night_split(hr_night_samples(g, ds), window_min),
                         night_split(stress_night_samples(g, ds), window_min),
                         sleep_detail(g, ds),
                         hsum))
        except Exception as e:                      # one bad night != abort
            print(f"{ds}  fetch failed ({type(e).__name__}: {str(e)[:60]})")
        d0 += timedelta(days=1)

    f = lambda d, k: f"{d[k]:g}" if d and d.get(k) is not None else "-"
    print(f"\nAUTONOMIC — first vs last {window_min}min ({oldest} -> {newest})")
    print(f"{'date':<12}{'HRV early':>10}{'late':>6}{'peak5':>7}{'status':>11}   "
          f"{'HR early':>9}{'late':>6}{'floor':>6}   "
          f"{'stress early':>13}{'late':>6}   flags")
    for ds, hrv, hr, stress, _, hsum in days:
        flags = []
        if hrv and hrv["late"] < HRV_LATE_RECOVERED:
            flags.append("HRV not recovered")
        excess = early_excess(hr)
        if excess is not None and excess >= HR_EARLY_EXCESS_DISTURBED:
            flags.append(f"early night disturbed (+{excess:g} over floor)")
        if ctx := KNOWN_CONTEXT.get(ds):
            flags.append(ctx.split("—")[0].strip())
        h = lambda k: str(hsum[k]) if hsum and hsum.get(k) is not None else "-"
        print(f"{ds:<12}{f(hrv,'early'):>10}{f(hrv,'late'):>6}{h('high5'):>7}"
              f"{h('status'):>11}   "
              f"{f(hr,'early'):>9}{f(hr,'late'):>6}{f(hr,'min'):>6}   "
              f"{f(stress,'early'):>13}{f(stress,'late'):>6}   {'; '.join(flags)}")
    b = next((d[5] for d in days if d[5] and d[5].get("balanced_low")), None)
    if b:
        print(f"  peak5 = best 5-min HRV reached (a PEAK, not a sustained level — "
              f"read it with 'late', not instead of it)")
        print(f"  Garmin personal balanced range: {b['balanced_low']}-{b['balanced_high']}")

    print(f"\nSLEEP ARCHITECTURE  (deep sleep is front-loaded — it is the first "
          f"thing a disturbed early night costs)")
    print(f"{'date':<12}{'deep':>6}{'rem':>5}{'light':>7}{'awake':>7}{'wakes':>7}"
          f"{'restless':>10}{'sleepStress':>12}{'spO2low':>9}   Garmin's verdict")
    for ds, _, _, _, sd, _ in days:
        if not sd:
            print(f"{ds:<12}  no sleep record")
            continue
        g_ = lambda k: sd[k] if sd.get(k) is not None else "-"
        low = " <<< LOW" if (sd.get("deep_min") or 99) < 45 else ""
        print(f"{ds:<12}{str(g_('deep_min')):>6}{str(g_('rem_min')):>5}"
              f"{str(g_('light_min')):>7}{str(g_('awake_min')):>7}"
              f"{str(g_('awake_count')):>7}{str(g_('restless')):>10}"
              f"{str(g_('sleep_stress')):>12}{str(g_('spo2_low')):>9}   "
              f"{(sd.get('insight') or '-')}{low}")


# ---------------------------------------------------------------------- CLI
def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__.strip().split("Usage:")[1])
    cmd, oldest, newest = argv[0], argv[1], argv[2]
    if cmd == "night":                      # Garmin-sourced, not intervals
        night_report(oldest, newest)
        return
    rows, issues = screen(fetch(oldest, newest))
    print(f"fetched {len(rows)} days ({oldest} -> {newest})")
    if issues:
        print(f"\nscreened {len(issues)} value(s):")
        for d, msg in issues:
            print(f"  {d}  {msg}")
    else:
        print("no values screened")
    ctx = [r for r in rows if r.get("context")]
    if ctx:
        print(f"\n{len(ctx)} day(s) carry known context (exclude for period comparisons):")
        for r in ctx:
            print(f"  {r['date']}  {r['context']}")
    if cmd == "fetch":
        out = argv[3] if len(argv) > 3 else "wellness.csv"
        to_csv(rows, out)
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
