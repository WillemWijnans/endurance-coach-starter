#!/usr/bin/env python3
"""
🔧 ATHLETE CONFIG — EVERY NUMBER IN HERE IS PERSONAL. CALIBRATE BEFORE USE.

This file exists so that none of the analysis code contains athlete-specific
constants. Change values here; never edit the modules.

⚠️  THE DEFAULTS BELOW ARE PLACEHOLDERS, NOT RECOMMENDATIONS.
Running someone else's thresholds produces confident, wrong answers — which is
worse than no answer. Anything marked  # CALIBRATE  must be set from YOUR data
before you trust the output.

Rough order to calibrate in:
  1. FTP + HR zones        -> needed for every ride report
  2. RESERVE anchors       -> needed for reserve %s
  3. Screening bounds      -> a few weeks of wellness data
  4. Night-split thresholds-> ~2 weeks of night data
  5. Load-ratio bands      -> ~10 rides
  6. VE bands              -> only if you own a ventilation strap
"""

# ─────────────────────────────────────────────────────────────── POWER
FTP = 250                          # CALIBRATE — W. Ramp/20-min test or eFTP.

# ─────────────────────────────────────────────────────────────── HEART RATE
# CALIBRATE. Best source is a lab or ventilation test giving VT1/VT2 heart rates.
# Failing that, %HRmax estimates will do to start — but they are estimates.
HR_BANDS = {
    "REC":    (0, 120),            # below aerobic threshold
    "Z2":     (120, 150),          # endurance; top = VT1
    "TEMPO":  (150, 163),
    "THRESH": (163, 170),          # top = upper Z4
    "VO2":    (170, 250),
}

# Anchors for reserve percentages. hr_max especially: a ramp test usually
# UNDER-elicits true max, so do not assume the highest number you have seen is it.
RESERVE = {
    "hr_rest": 50,  "hr_max": 190,     # CALIBRATE
    "ve_rest": 10,  "ve_max": 160,     # only matters with a ventilation strap
    "br_rest": 13,  "br_max": 50,
}

# ─────────────────────────────────────────── VENTILATION (Tymewear etc.)
# ONLY relevant if you own a ventilation strap. Otherwise ignore entirely —
# the ride report simply omits VE.
#
# Two things worth knowing before trusting these:
#  • Absolute VE drifts 15-22 units session-to-session with strap tension and
#    sweat. Read TRENDS within a ride, never the absolute level across rides.
#  • OUTDOORS, VE is often nearly FLAT vs power while HR responds normally.
#    That makes "HR up, VE flat" expected outdoors, not a finding.
VE_BANDS = {
    "indoor":  {"Z1": (0, 55), "Z2": (55, 80),  "Z3": (80, 95),  "Z4": (95, 110), "Z5": (110, 1e9)},
    "outdoor": {"Z1": (0, 60), "Z2": (60, 72),  "Z3": (72, 84),  "Z4": (84, 96),  "Z5": (96, 1e9)},
}
VT2_LOAD = {"indoor": 95, "outdoor": 80}     # CALIBRATE — VE at threshold

# ───────────────────────────────────────────── WELLNESS OUTLIER SCREEN
# Two-tier on purpose: device errors get DROPPED, odd-but-real values get KEPT
# and flagged. Genuine illness can push resting HR into the high 50s — that is
# data, not noise, and must not be silently discarded.
RHR_IMPLAUSIBLE = (30, 90)         # CALIBRATE — outside this is a device fault
RHR_SUSPECT = 60                   # CALIBRATE — plausible but worth a look
HRV_IMPLAUSIBLE = (5, 200)

# Days with a known NON-TRAINING explanation: illness, timezone travel, device
# faults. Exclude them from trend and before/after analyses rather than letting
# them skew a mean. Format: "YYYY-MM-DD": "reason".
#
# Worth knowing: timezone-crossing travel (especially EASTBOUND) corrupts
# wellness data BY MECHANISM, not malfunction — the watch derives "resting" HR
# from a window it believes is night, and crossing enough time zones lands that
# window on hours you were awake and upright. Expect it; exclude it.
KNOWN_CONTEXT = {
    # "2026-05-08": "eastbound flight — RHR derived from an awake window",
}

# ───────────────────────────────────────────────────── NIGHT SPLITS
# Overnight AVERAGES can badly misrepresent recovery when a disturbance is
# front-loaded: HRV climbs and HR falls through the night, so the average is
# dragged down by a rough first hour while you actually end up fine.
# Splitting the night into first/last window shows what the average hides.
NIGHT_WINDOW_MIN = 90              # minutes at each end of the sleep window

HRV_LATE_RECOVERED = 50            # CALIBRATE — end-of-night HRV at/above this
                                   # = recovered. Set from your own balanced range.

# Early-night HR is judged RELATIVE TO THAT NIGHT'S OWN FLOOR (early - min),
# never as an absolute: sleep-onset HR varies with how late and active the
# evening was, so a fixed cut-off flags almost every night.
HR_EARLY_EXCESS_DISTURBED = 10     # CALIBRATE — excess over floor meaning
                                   # something disturbed the START of the night

# ─────────────────────────────────────── INTERNAL vs EXTERNAL LOAD
# TSS is power-only by design — mechanical work, comparable across conditions,
# and therefore blind to what a day COST. Most platforms also compute an
# HR-based load. The signal is the RATIO between them:
#     high ratio -> the day cost more than it produced (heat, dehydration,
#                   fatigue, illness). TSS understates that ride.
# Calibrate from ~10 normal rides, then set the bands around your own baseline.
RATIO_NORMAL_MAX = 1.10            # CALIBRATE — at/below is unremarkable
RATIO_ELEVATED = 1.20              # CALIBRATE — above, the day cost more

# Conditions worth naming when a ratio comes back high. A raised ratio says a
# day cost more than it produced; it does NOT say why. Most platforms store the
# weather alongside the ride, so the likely candidates can be surfaced instead
# of guessed at.
TEMP_HOT = 25                      # CALIBRATE — "start watching". Heat tolerance
                                   # is individual: some riders lose form at 22C,
                                   # others at 30.
TEMP_HOT_DEMONSTRATED = 32         # CALIBRATE — the temperature at which YOUR
                                   # ratio measurably breaks down. Two tiers on
                                   # purpose: one is a caution, one is evidence.
                                   # Find it by binning your own rides by temp
                                   # and reading the median ratio per band.
TEMP_COLD = 5                      # CALIBRATE
HEADWIND_NOTABLE = 45              # % of the ride into a headwind. Roughly a
                                   # third each of head/tail/cross is neutral,
                                   # so well above a third is a real tax.
WIND_STRONG_MS = 6                 # mean wind speed, m/s

# ─────────────────────────────────────────────────────────── PATHS
from pathlib import Path
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STREAM_DIR = DATA_DIR / "streams"
MASTER_LOG = DATA_DIR / "master_log.csv"
WEIGHT_LOG = DATA_DIR / "weight_log.csv"
SYNC_ENV = Path.home() / "code/garmin-intervals-sync/.env"   # or your own .env
ENV_FILE = DATA_DIR.parent / ".env"          # written by setup.py; gitignored

# ──────────────────────────────────── YOUR CALIBRATION (generated)
# setup.py writes athlete_config_local.py with values derived from YOUR OWN
# history. It is gitignored, so personal calibration never lands in git, and
# anything it defines overrides the placeholders above.
#
# This import is last on purpose — it must win. If the file is absent (a fresh
# clone, or setup not yet run) everything above stands and the tests still pass,
# but the numbers are strangers' numbers. Run:  python3 setup.py
try:
    from athlete_config_local import *        # noqa: F401,F403
    CALIBRATED = True
except ImportError:
    CALIBRATED = False
