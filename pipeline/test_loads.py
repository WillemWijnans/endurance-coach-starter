#!/usr/bin/env python3
"""Tests for loads.py. Run: python3 -m pytest test_loads.py -q

Pure logic only — no network. Threshold-dependent tests read the bands from
athlete_config, so they keep passing after you calibrate.
"""
import athlete_config as C
import loads as L


# ---- the real Aug 2026 trip values ----
def test_heat_day_flags_elevated():
    """Worked example: TSS said 169, HR load said 253 — the ratio must catch it."""
    r = L.load_ratio(253, 169)
    assert r == 1.497
    assert r >= L.RATIO_ELEVATED
    assert "ELEVATED" in L.interpret(r)
    assert "understates" in L.interpret(r)

def test_normal_days_read_normal():
    """Normal days — mechanical work exceeded cardiovascular cost."""
    for hr, pw in [(220, 264), (228, 259)]:
        r = L.load_ratio(hr, pw)
        assert r < L.RATIO_NORMAL_MAX
        assert L.interpret(r).startswith("normal")

def test_heat_day_separates_from_normal_days():
    """The whole value of the metric: the heat day must be distinguishable."""
    heat = L.load_ratio(253, 169)
    normal = [L.load_ratio(220, 264), L.load_ratio(228, 259)]
    assert heat > max(normal) * 1.5, "heat day should stand well clear"


# ---- band boundaries ----
def test_band_boundaries():
    """Read the bands from config so these survive calibration."""
    n, e = L.RATIO_NORMAL_MAX, L.RATIO_ELEVATED
    assert L.interpret(L.load_ratio(n * 100, 100)).startswith("normal")
    assert "ELEVATED" in L.interpret(L.load_ratio(e * 100, 100))
    assert "ELEVATED" in L.interpret(L.load_ratio(e * 200, 100))


# ---- missing / junk data ----
def test_missing_data_returns_none_not_zero():
    """A missing HR stream must NOT look like a genuine ratio."""
    for hr, pw in [(None, 169), (253, None), (None, None), (0, 169), (253, 0)]:
        assert L.load_ratio(hr, pw) is None

def test_junk_values():
    for hr, pw in [("abc", 100), (100, "abc"), ([], {}), (-5, 100)]:
        assert L.load_ratio(hr, pw) is None

def test_interpret_handles_none():
    msg = L.interpret(None)
    assert "cannot compare" in msg

def test_accepts_numeric_strings():
    assert L.load_ratio("253", "169") == 1.497


# ---- row() extraction ----
def test_row_extracts_from_intervals_shape():
    a = {"start_date_local": "2026-08-14T13:42:05", "name": "Afternoon Ride",
         "distance": 88993.72, "hr_load": 253, "power_load": 169,
         "icu_power_hr": 1.2074074, "trimp": 435.8}
    r = L.row(a)
    assert r["date"] == "2026-08-14"
    assert r["km"] == 89
    assert r["ratio"] == 1.497

def test_row_survives_a_ride_with_no_hr():
    r = L.row({"start_date_local": "2026-08-14T00:00:00", "distance": 50000,
               "power_load": 100})
    assert r["ratio"] is None
    assert r["hr_load"] is None


# ---- weather conditions ----
# Weather is stored on the activity, so a costly day's likely causes can be NAMED
# rather than guessed at. These pin what counts as worth remarking on.
def _weather(**kw):
    base = {"has_weather": True, "average_weather_temp": 18,
            "headwind_percent": 30, "average_wind_speed": 2, "average_wind_gust": 4}
    base.update(kw)
    return base

def test_mild_day_reports_nothing():
    """A pleasant ride must stay quiet, or the field becomes noise."""
    assert L.conditions(_weather())[0] == []

def test_warm_day_flagged_as_mild():
    assert "mild effect" in L.conditions(_weather(average_weather_temp=27))[0][0]

def test_hot_day_flagged_against_the_demonstrated_breakpoint():
    """Two tiers: a caution at TEMP_HOT, evidence at TEMP_HOT_DEMONSTRATED."""
    assert "demonstrated heat breakpoint" in L.conditions(
        _weather(average_weather_temp=34))[0][0]

def test_cold_is_named():
    notes = L.conditions(_weather(average_weather_temp=1))[0]
    assert any("cold" in n for n in notes)

def test_headwind_is_reported_but_never_as_a_cause():
    """At matched watts, wind changes speed rather than metabolic cost, and the
    power-based load already counts the watts. Measured across 81 rides it showed
    no relationship to the ratio, so it must not be offered as an explanation."""
    assert L.conditions(_weather(headwind_percent=30))[0] == []
    notes = L.conditions(_weather(headwind_percent=55))[0]
    assert "headwind" in notes[0] and "not a cost driver" in notes[0]

def test_heat_and_wind_are_kept_separate():
    """Heat is causal, wind is context — merging them would blur the claim."""
    notes = L.conditions(_weather(average_weather_temp=34, headwind_percent=60))[0]
    assert len(notes) == 2 and "34" in notes[0] and "not a cost driver" in notes[1]

def test_heat_tiers_come_from_config():
    """Both thresholds must be calibratable, not baked into the module."""
    assert C.TEMP_HOT < C.TEMP_HOT_DEMONSTRATED

def test_strong_wind_is_named_with_gusts():
    notes = L.conditions(_weather(average_wind_speed=8, average_wind_gust=14))[0]
    assert any("8m/s" in n and "14" in n and "not a cost driver" in n for n in notes)

def test_multiple_conditions_all_reported():
    notes = L.conditions(_weather(average_weather_temp=34, headwind_percent=60,
                                  average_wind_speed=9))[0]
    assert len(notes) == 2                    # heat, plus one combined context line
    assert "headwind" in notes[1] and "9m/s" in notes[1]

def test_no_weather_data_is_silent_not_an_error():
    for a in ({}, {"has_weather": False}, {"has_weather": True}):
        assert L.conditions(a)[0] == []

def test_falls_back_to_device_temp_when_weather_temp_missing():
    """Some rides carry only the head-unit temperature."""
    a = {"has_weather": True, "average_temp": 31}
    assert "31°C" in L.conditions(a)[0][0]

def test_detail_is_returned_for_callers_that_want_raw_values():
    _, d = L.conditions(_weather(average_weather_temp=33, headwind_percent=52))
    assert d["temp"] == 33 and d["headwind_pct"] == 52

def test_row_carries_conditions():
    a = {"start_date_local": "2026-08-14T13:42:05", "distance": 88993.7,
         "hr_load": 253, "power_load": 169, **_weather(average_weather_temp=33)}
    assert L.row(a)["conditions"]

def test_row_without_weather_has_empty_conditions():
    assert L.row({"start_date_local": "2026-08-14T00:00:00",
                  "distance": 50000, "power_load": 100})["conditions"] == []
