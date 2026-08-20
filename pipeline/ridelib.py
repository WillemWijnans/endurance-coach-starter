#!/usr/bin/env python3
"""
ridelib — single source of truth for ride-stream analysis.

Replaces the scattered inline math in batch_analyze.py, dual_zone_analysis.py,
deep_analyze_*.py, reserve_analysis.py, add_ef_decoupling.py.

All metrics computed here. Tested in test_ridelib.py against known values:
  - NP of a constant-power stream equals that power
  - NP of i147447349 == 239W (methodology pipeline-validation ride)
  - Decoupling of a steady ride ≈ 0%
  - TSS uses MOVING time, not elapsed (the Jun 8 paused-time bug)

Design notes:
  - Zone bands + reserve anchors are CONFIG (one place), not magic numbers.
  - NP uses index-based 30-sample rolling (matches intervals.icu's
    weighted_average_power; validated to 239W on i147447349).
  - TSS/vTSS use MOVING-time hours (elapsed minus >GAP_THRESHOLD pauses).
"""
from __future__ import annotations
import json
import statistics
from pathlib import Path
import athlete_config as C

# ---------------------------------------------------------------- config
FTP_DEFAULT = C.FTP
GAP_THRESHOLD_S = 5        # a time delta above this is a "pause", not sampling
ROLL_WINDOW = 30           # seconds/samples for normalized power & VE

STREAM_DIR = C.STREAM_DIR

# VE (ventilation) zone bands, and the VT2 constant used for ventilatory load.
# Both live in athlete_config.py — they are highly individual and drift between
# sessions with strap tension and sweat. Only meaningful with a ventilation strap.
# NOTE outdoors VE is often nearly FLAT vs power while HR responds normally, so
# "HR up, VE flat" is expected outdoors and is not a finding.
VE_BANDS = C.VE_BANDS
VT2_LOAD = C.VT2_LOAD

# intervals.icu activity type → training environment. "VirtualRide" = trainer/
# Zwift (indoor); "Ride" = real road/gravel (outdoor). Single source of truth so
# env can be auto-derived instead of hand-typed (and mis-typed).
TYPE_ENV = {"VirtualRide": "indoor", "Ride": "outdoor"}
ENV_TYPE = {v: k for k, v in TYPE_ENV.items()}   # indoor->VirtualRide, outdoor->Ride
ENV_LABEL = {"indoor": "🏠 INDOOR", "outdoor": "🏞️ OUTDOOR"}


def env_from_type(activity_type):
    """Map an intervals.icu activity type to indoor/outdoor; None if unknown."""
    return TYPE_ENV.get(activity_type) if activity_type else None


def to_activity_type(value):
    """Normalize a type/env hint to a canonical activity_type for storage.

    The streams-only MCP dump carries no activity type, so it's supplied at
    extract time from the activity list. Accepts either an intervals type
    ('VirtualRide'/'Ride') or an env ('indoor'/'outdoor'). Blank/unknown -> None.
    """
    if not value:
        return None
    v = value.strip()
    if v in TYPE_ENV:                    # already a valid activity type
        return v
    return ENV_TYPE.get(v.lower())       # env -> type; None if unrecognized


def resolve_env(arg, activity_type):
    """Decide indoor/outdoor for a ride. Returns (env, warning|None).

    - explicit 'indoor'/'outdoor' wins, but WARNS if it contradicts the activity
      type intervals reported (guards against a fat-fingered tag).
    - '' or 'auto' → derive from the activity type.
    - undeterminable (no arg, unknown/old type) → ValueError; caller passes it.
    """
    detected = env_from_type(activity_type)
    arg = (arg or "").strip().lower()
    if arg in ("", "auto"):
        if detected is None:
            raise ValueError(
                f"env not given and activity type {activity_type!r} is unknown "
                "— pass indoor|outdoor explicitly")
        return detected, None
    if arg not in ("indoor", "outdoor"):
        raise ValueError(f"env must be indoor|outdoor|auto, got {arg!r}")
    warn = None
    if detected and detected != arg:
        warn = (f"you passed {arg!r} but intervals type {activity_type!r} maps to "
                f"{detected!r} — logging {arg!r} as an override")
    return arg, warn


def env_label(env):
    """Prominent display label for a training environment (indoor/outdoor)."""
    return ENV_LABEL.get(env, (env or "?").upper())

# HR zone boundaries — see athlete_config.py. Anchor these to MEASURED
# ventilatory landmarks (VT1/VT2) where you have them; %HRmax estimates are a
# starting point, not a substitute.
HR_BANDS = C.HR_BANDS

# Reserve anchors — see athlete_config.py. Note ramp tests typically UNDER-elicit
# true max HR, especially where the limiter is muscular rather than cardiac.
RESERVE = C.RESERVE

# ---------------------------------------------------------------- helpers
def _clean(arr):
    return [x for x in arr if x is not None]

def mean(arr):
    c = _clean(arr)
    return statistics.mean(c) if c else 0.0

def maximum(arr):
    c = _clean(arr)
    return max(c) if c else 0.0

def minimum(arr):
    c = _clean(arr)
    return min(c) if c else 0.0

def std(arr):
    c = _clean(arr)
    return statistics.stdev(c) if len(c) > 1 else 0.0

def percentile(arr, p):
    """p in [0,1]. Nearest-rank on sorted clean values."""
    c = sorted(_clean(arr))
    if not c:
        return 0.0
    return c[min(len(c) - 1, int(p * (len(c) - 1)))]

def rolling_mean(arr, window=ROLL_WINDOW):
    """Index-based rolling mean (Nones treated as 0). Matches intervals.icu."""
    c = [a if a is not None else 0 for a in arr]
    if len(c) < window:
        return [mean(c)] if c else [0.0]
    cs = [0.0]
    for v in c:
        cs.append(cs[-1] + v)
    return [(cs[i + window] - cs[i]) / window for i in range(len(c) - window + 1)]

def normalized(stream, window=ROLL_WINDOW):
    """4th-power-root-mean of the rolling mean (NP / NormVE)."""
    rm = rolling_mean(stream, window)
    if not rm:
        return 0.0
    return (sum(r ** 4 for r in rm) / len(rm)) ** 0.25

# ---------------------------------------------------------------- time
def time_gaps(time, threshold=GAP_THRESHOLD_S):
    """Return list of (index, gap_seconds) where delta > threshold."""
    return [(i, time[i] - time[i - 1])
            for i in range(1, len(time)) if time[i] - time[i - 1] > threshold]

def moving_seconds(time, threshold=GAP_THRESHOLD_S):
    """Elapsed minus paused. THE fix for the Jun 8 inflated-TSS bug."""
    if len(time) < 2:
        return 0.0
    elapsed = time[-1] - time[0]
    paused = sum(g for _, g in time_gaps(time, threshold))
    return elapsed - paused

# A gap longer than this contaminates decoupling / half-split metrics
# (postprandial HR, heat, cold-restart). See methodology_corrections.md.
LONG_STOP_S = 20 * 60

def longest_stop_seconds(time):
    gaps = time_gaps(time)
    return max((g for _, g in gaps), default=0.0)

# ---------------------------------------------------------------- zones
def zone_pct(stream, bands):
    """Percent of clean samples in each band. bands: {name: (lo, hi)}."""
    c = _clean(stream)
    n = len(c)
    if not n:
        return {k: 0.0 for k in bands}
    return {k: sum(1 for x in c if lo <= x < hi) / n * 100 for k, (lo, hi) in bands.items()}

def high_pct(zpct, high_keys):
    return sum(zpct[k] for k in high_keys)

# ---------------------------------------------------------------- reserves
def reserve_pct(value, rest, mx):
    return (value - rest) / (mx - rest) * 100 if mx > rest else 0.0

# ---------------------------------------------------------------- main
def load_stream(activity_id):
    path = STREAM_DIR / f"{activity_id}.json"
    return json.loads(path.read_text())["streams"]

def load_meta(activity_id):
    """Top-level ride metadata saved beside the streams (activity_type/name/date).
    Returns {} for older stream files captured before metadata was stored."""
    path = STREAM_DIR / f"{activity_id}.json"
    d = json.loads(path.read_text())
    return {k: d[k] for k in ("activity_type", "name", "date") if d.get(k)}

def compute(streams, env, ftp=FTP_DEFAULT, activity_id="", date="", name=""):
    """Compute the full metric set for one ride. Returns a flat dict."""
    t  = streams["time"]
    w  = streams["watts"]
    hr = streams.get("heartrate") or []
    ve = streams.get("tidal_volume_min") or []
    br = streams.get("respiration") or []

    n = len(t)
    mv_s = moving_seconds(t)
    mv_h = mv_s / 3600.0

    # --- power / load (TSS on MOVING time) ---
    NP = normalized(w)
    IF = NP / ftp if ftp else 0.0
    TSS = mv_h * IF ** 2 * 100

    # --- ventilation load ---
    vt2 = VT2_LOAD[env]
    NormVE = normalized(ve) if ve else 0.0
    vIF = NormVE / vt2 if vt2 else 0.0
    vTSS = mv_h * vIF ** 2 * 100

    hr_avg = mean(hr)
    ve_avg = mean(ve)

    # --- EF / decoupling ---
    EF = NP / hr_avg if hr_avg else 0.0
    VE_EF = NP / ve_avg if ve_avg else 0.0
    decoupling = pwhr_decoupling(w, hr)
    long_stop_s = longest_stop_seconds(t)
    decoupling_clean = long_stop_s < LONG_STOP_S  # False = decoupling is contaminated

    # --- zones ---
    ve_z = zone_pct(ve, VE_BANDS[env]) if ve else {k: 0.0 for k in VE_BANDS[env]}
    hr_z = zone_pct(hr, HR_BANDS) if hr else {k: 0.0 for k in HR_BANDS}
    ve_high = high_pct(ve_z, ["Z3", "Z4", "Z5"])
    hr_high = high_pct(hr_z, ["TEMPO", "THRESH", "VO2"])
    divergence = ve_high - hr_high

    # --- reserves ---
    res = {
        "hrr_avg": reserve_pct(hr_avg, RESERVE["hr_rest"], RESERVE["hr_max"]) if hr else 0.0,
        "ver_avg": reserve_pct(ve_avg, RESERVE["ve_rest"], RESERVE["ve_max"]) if ve else 0.0,
        "brr_avg": reserve_pct(mean(br), RESERVE["br_rest"], RESERVE["br_max"]) if br else 0.0,
    }

    return {
        "activity_id": activity_id, "date": date, "env": env, "name": name,
        "moving_min": round(mv_s / 60, 1),
        "elapsed_min": round((t[-1] - t[0]) / 60, 1) if n > 1 else 0.0,
        "paused_min": round((t[-1] - t[0] - mv_s) / 60, 1) if n > 1 else 0.0,
        "np": round(NP), "if": round(IF, 3), "tss": round(TSS),
        "normve": round(NormVE, 1), "vif": round(vIF, 3), "vtss": round(vTSS),
        "vif_if": round(vIF / IF, 3) if IF else 0.0,
        "hr_avg": round(hr_avg), "hr_max": round(maximum(hr)),
        "ve_avg": round(ve_avg, 1), "ve_rmax30": round(maximum(rolling_mean(ve)), 1) if ve else 0.0,
        "br_avg": round(mean(br)),
        "ef": round(EF, 3), "ve_ef": round(VE_EF, 3), "decoupling_pct": round(decoupling, 2),
        "veZ1": round(ve_z["Z1"], 1), "veZ2": round(ve_z["Z2"], 1), "veZ3": round(ve_z["Z3"], 1),
        "veZ4": round(ve_z["Z4"], 1), "veZ5": round(ve_z["Z5"], 1),
        "hrREC": round(hr_z["REC"], 1), "hrZ2": round(hr_z["Z2"], 1),
        "hrTEMPO": round(hr_z["TEMPO"], 1), "hrTHRESH": round(hr_z["THRESH"], 1), "hrVO2": round(hr_z["VO2"], 1),
        "div_pp": round(divergence, 1),
        "hrr_avg": round(res["hrr_avg"], 1), "ver_avg": round(res["ver_avg"], 1), "brr_avg": round(res["brr_avg"], 1),
        "n_gaps": len(time_gaps(t)),
        "long_stop_min": round(long_stop_s / 60, 1),
        "decoupling_clean": int(decoupling_clean),
    }

def pwhr_decoupling(w, hr):
    """Pw:HR drift, first half vs second half. Lower = better durability."""
    if not hr:
        return 0.0
    half = len(w) // 2
    np1, np2 = normalized(w[:half]), normalized(w[half:])
    hr1, hr2 = mean(hr[:half]), mean(hr[half:])
    if not (hr1 and hr2 and np1):
        return 0.0
    pwhr1, pwhr2 = np1 / hr1, np2 / hr2
    return (pwhr1 - pwhr2) / pwhr1 * 100
