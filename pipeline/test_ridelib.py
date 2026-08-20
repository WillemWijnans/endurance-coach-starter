#!/usr/bin/env python3
"""
Tests for ridelib. Run: python3 -m pytest test_ridelib.py -v
(or: python3 test_ridelib.py  for a no-pytest fallback)

Validates the math against KNOWN values — including the two bugs that
motivated the refactor:
  1. NP must match intervals.icu's weighted_average_power (i147447349 = 239W)
  2. TSS must use MOVING time, not elapsed (the Jun 8 paused-time inflation)
"""
import math
import pytest

import athlete_config as C
import ridelib as R

# ── Regression fixtures ──────────────────────────────────────────────────────
# These pin real computed values against a saved stream file. They are the most
# valuable tests in the suite once you have your own data: extract a ride you
# trust, record what the pipeline produces today, and assert it never silently
# changes. They skip until you add a fixture of your own.
def _fixture(activity_id):
    p = C.STREAM_DIR / f"{activity_id}.json"
    if not p.exists():
        pytest.skip(f"no fixture at {p} — add your own ride to enable this test")
    return R.load_stream(activity_id)



# ---- normalized power ----
def test_np_constant_power():
    # Constant 200W → NP == 200 (4th-power-root-mean of constant = constant)
    w = [200] * 600
    assert abs(R.normalized(w) - 200) < 0.01

def test_np_short_stream_below_window():
    # Fewer samples than the rolling window: falls back to mean, no crash
    w = [100, 200, 300]
    assert R.normalized(w) > 0

def test_np_known_ride_i147447349():
    # methodology_corrections.md: NP of this ride == 239W (matches
    # intervals.icu weighted_average_power bit-for-bit). The canonical anchor.
    streams = _fixture("i147447349")
    np = R.normalized(streams["watts"])
    assert abs(np - 239) <= 1, f"NP={np:.1f}, expected 239±1"


# ---- moving time (the Jun 8 bug) ----
def test_moving_excludes_pause():
    # Block1: t=0..99 (99s of motion). Then a clean 100s pause.
    # Block2: t=199..298 (99s of motion).
    # elapsed = 298, paused = 100, moving = 198.
    time = list(range(100)) + [199 + i for i in range(100)]
    assert time[-1] - time[0] == 298           # elapsed
    assert R.moving_seconds(time) == 198        # moving excludes the 100s pause

def test_moving_no_gaps_equals_elapsed():
    time = list(range(600))
    assert R.moving_seconds(time) == 599

def test_tss_uses_moving_not_elapsed():
    # Build a ride: 1h of 314W (IF=1.0), then a 1h PAUSE (no samples), done.
    # Moving = 3600s = 1h → TSS ≈ 100. If elapsed were used (2h) → TSS ≈ 200.
    watts = [314] * 3600
    time = list(range(3600))
    streams = {"time": time + [3600 + 3600], "watts": watts + [0]}
    # add the post-pause sample so elapsed=7200 but moving=3601
    streams["watts"] = watts + [0]
    streams["time"] = list(range(3600)) + [7200]
    m = R.compute(streams, env="indoor", ftp=314)
    # moving ~1h, IF ~1.0 → TSS ~100, decisively NOT ~200
    assert 95 <= m["tss"] <= 110, f"TSS={m['tss']} (elapsed-bug would give ~200)"


# ---- decoupling ----
def test_decoupling_steady_near_zero():
    # Perfectly steady power & HR → ~0% drift
    w = [220] * 1000
    hr = [135] * 1000
    assert abs(R.pwhr_decoupling(w, hr)) < 0.5

def test_decoupling_positive_when_hr_drifts_up():
    # Same power, HR climbs in 2nd half → positive decoupling (a fade)
    w = [220] * 1000
    hr = [130] * 500 + [140] * 500
    assert R.pwhr_decoupling(w, hr) > 3

def test_decoupling_no_hr_returns_zero():
    assert R.pwhr_decoupling([200] * 100, []) == 0.0


# ---- long-stop detection (the dad-stop contamination flag) ----
def test_longest_stop_detects_big_gap():
    # t=0..99, then jump to 1899 (a clean 1800s = 30min gap), then continue
    time = list(range(100)) + [1899 + i for i in range(100)]
    assert R.longest_stop_seconds(time) == 1800

def test_longest_stop_none_when_continuous():
    assert R.longest_stop_seconds(list(range(600))) == 0.0

def test_compute_flags_long_stop():
    # ride with a 25-min mid-ride stop → decoupling_clean = 0
    w = [220] * 1000
    hr = [135] * 1000
    t = list(range(500)) + [500 + 1500 + i for i in range(500)]  # 25-min gap
    m = R.compute({"time": t, "watts": w, "heartrate": hr}, env="outdoor")
    assert m["decoupling_clean"] == 0, "should flag the 25-min stop"
    assert m["long_stop_min"] == 25.0

def test_compute_clean_when_short_stops():
    w = [220] * 1000
    hr = [135] * 1000
    t = list(range(500)) + [500 + 120 + i for i in range(500)]  # only 2-min gap
    m = R.compute({"time": t, "watts": w, "heartrate": hr}, env="outdoor")
    assert m["decoupling_clean"] == 1


# ---- zones ----
def test_zone_pct_sums_to_100():
    ve = [70, 80, 95, 110, 120, 60, 85]
    z = R.zone_pct(ve, R.VE_BANDS["outdoor"])
    assert abs(sum(z.values()) - 100) < 1e-6

def test_zone_pct_empty():
    z = R.zone_pct([], R.VE_BANDS["indoor"])
    assert sum(z.values()) == 0


# ---- reserves ----
def test_reserve_pct_basic():
    # value at rest → 0%, value at max → 100%
    assert R.reserve_pct(44, 44, 185) == 0
    assert abs(R.reserve_pct(185, 44, 185) - 100) < 1e-6
    # midpoint
    mid = (44 + 185) / 2
    assert abs(R.reserve_pct(mid, 44, 185) - 50) < 1e-6


# ---- env resolution (indoor/outdoor auto-detect + override guard) ----
def test_env_from_type_maps_known():
    assert R.env_from_type("VirtualRide") == "indoor"
    assert R.env_from_type("Ride") == "outdoor"

def test_env_from_type_unknown_and_none():
    assert R.env_from_type("Run") is None
    assert R.env_from_type(None) is None
    assert R.env_from_type("") is None

def test_resolve_env_auto_from_type():
    assert R.resolve_env("auto", "VirtualRide") == ("indoor", None)
    assert R.resolve_env("", "Ride") == ("outdoor", None)

def test_resolve_env_explicit_agrees_no_warn():
    env, warn = R.resolve_env("indoor", "VirtualRide")
    assert env == "indoor" and warn is None

def test_resolve_env_explicit_overrides_with_warning():
    # e.g. an outdoor ride recorded on the trainer head unit as VirtualRide,
    # or vice-versa — honor the explicit tag but flag the mismatch loudly.
    env, warn = R.resolve_env("outdoor", "VirtualRide")
    assert env == "outdoor"
    assert warn and "VirtualRide" in warn and "outdoor" in warn

def test_resolve_env_explicit_when_type_unknown_no_warn():
    # old stream file (no type) but caller passed env → use it, no false warning
    env, warn = R.resolve_env("indoor", None)
    assert env == "indoor" and warn is None

def test_resolve_env_auto_unknown_type_raises():
    try:
        R.resolve_env("auto", None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when env undeterminable")

def test_resolve_env_bad_arg_raises():
    try:
        R.resolve_env("inside", "Ride")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on invalid env arg")

def test_resolve_env_case_insensitive():
    assert R.resolve_env("INDOOR", "VirtualRide") == ("indoor", None)
    assert R.resolve_env("Auto", "Ride") == ("outdoor", None)

def test_env_label_prominent():
    assert "INDOOR" in R.env_label("indoor")
    assert "OUTDOOR" in R.env_label("outdoor")

def test_to_activity_type_from_env():
    # env hint (what a human/activity-list passes) -> stored activity type
    assert R.to_activity_type("indoor") == "VirtualRide"
    assert R.to_activity_type("outdoor") == "Ride"
    assert R.to_activity_type("INDOOR") == "VirtualRide"   # case-insensitive

def test_to_activity_type_passthrough_and_unknown():
    assert R.to_activity_type("VirtualRide") == "VirtualRide"  # already a type
    assert R.to_activity_type("Ride") == "Ride"
    assert R.to_activity_type(None) is None
    assert R.to_activity_type("") is None
    assert R.to_activity_type("nonsense") is None

def test_extract_hint_round_trips_to_auto_env():
    # the real pipeline flow: hint -> stored type -> auto-detected env
    assert R.env_from_type(R.to_activity_type("indoor")) == "indoor"
    assert R.env_from_type(R.to_activity_type("outdoor")) == "outdoor"


# ---- full compute on a real ride (regression vs known master_log values) ----
def test_compute_known_ride_regression():
    # i154943537 (Sun Jun 7) — from master_log: NP 229, IF 0.729, EF 1.750,
    # decoupling -1.13, ve_ef 2.729. Recompute and confirm within tolerance.
    streams = _fixture("i154943537")
    m = R.compute(streams, env="outdoor", activity_id="i154943537")
    assert abs(m["np"] - 229) <= 1, f"NP={m['np']}"
    assert abs(m["ef"] - 1.750) <= 0.01, f"EF={m['ef']}"
    assert abs(m["decoupling_pct"] - (-1.13)) <= 0.3, f"dec={m['decoupling_pct']}"
    assert abs(m["ve_ef"] - 2.729) <= 0.02, f"ve_ef={m['ve_ef']}"


# ---------------------------------------------------------------- runner
if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for tfn in tests:
        try:
            tfn()
            print(f"  PASS  {tfn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {tfn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {tfn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
