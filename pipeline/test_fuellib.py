#!/usr/bin/env python3
"""Tests for fuellib. Pure functions, no I/O, no network."""
import pytest
import athlete_config as C
import fuellib as F


# ── targets ────────────────────────────────────────────────────────────────
def test_targets_scale_with_duration():
    _, _, c_lo_1h, _ = F.targets(60)
    _, _, c_lo_2h, _ = F.targets(120)
    assert c_lo_2h == pytest.approx(c_lo_1h * 2)


def test_short_ride_needs_no_carbs():
    """Under an hour you ride on what you already have."""
    f_lo, _, c_lo, c_hi = F.targets(45)
    assert c_lo == 0 and c_hi == 0
    assert f_lo == 0


def test_heat_raises_the_fluid_target_only():
    f_lo_cool, _, c_lo_cool, _ = F.targets(120, temp_c=15)
    f_lo_hot, _, c_lo_hot, _ = F.targets(120, temp_c=C.TEMP_HOT + 5)
    assert f_lo_hot > f_lo_cool
    assert c_lo_hot == c_lo_cool


# ── assess ─────────────────────────────────────────────────────────────────
def test_nothing_logged_returns_none():
    """A missing number must NOT be scored as a miss — that would punish
    forgetting to log rather than under-fuelling."""
    assert F.assess(None, None, 120) is None


def test_partial_logging_is_allowed():
    a = F.assess(1000, None, 120)
    assert "fluid_hit" in a and "carb_hit" not in a


def test_hit_and_miss_are_computed_against_the_lower_bound():
    hit = F.assess(1200, 150, 120)      # 600ml/h, target floor 500
    miss = F.assess(600, 150, 120)      # 300ml/h
    assert hit["fluid_hit"] is True
    assert miss["fluid_hit"] is False
    assert miss["fluid_short_ml"] == 400


def test_zero_is_a_real_miss_not_a_missing_value():
    a = F.assess(0, 0, 120)
    assert a is not None
    assert a["fluid_hit"] is False and a["carb_hit"] is False


def test_per_hour_rates():
    a = F.assess(1180, 150, 119)
    assert a["fluid_per_h"] == pytest.approx(595, abs=2)
    assert a["carb_per_h"] == pytest.approx(76, abs=2)


# ── bottles & capacity ─────────────────────────────────────────────────────
def test_bottles_uses_the_configured_bottle_size():
    """Generic: N bottles' worth of ml must read back as N bottles."""
    bike = C.DEFAULT_BIKE
    _, _, ml = F.capacity(bike)
    assert F.bottles(ml * 2, bike) == pytest.approx(2.0)
    assert F.bottles(ml, bike) == pytest.approx(1.0)


def test_capacity_is_cages_times_bottle():
    for name, spec in C.BIKES.items():
        total, cages, ml = F.capacity(name)
        assert total == spec["cages"] * spec["bottle_ml"]
        assert (cages, ml) == (spec["cages"], spec["bottle_ml"])


def test_unknown_bike_falls_back_rather_than_crashing():
    total, cages, ml = F.capacity("penny-farthing")
    assert total > 0 and cages >= 1 and ml > 0


def test_a_ride_longer_than_capacity_demands_a_refill():
    """Carrying capacity is a HARD constraint: the tool must say a stop is
    required rather than prescribe a target the bike cannot physically hold."""
    bike = C.DEFAULT_BIKE
    _, covered = F.refill_needed(1, bike)
    need_over, _ = F.refill_needed(covered + 30, bike)
    need_under, _ = F.refill_needed(max(1, covered - 30), bike)
    assert need_over is True
    assert need_under is False


def test_covered_minutes_match_capacity_over_target():
    bike = C.DEFAULT_BIKE
    total, _, _ = F.capacity(bike)
    lo = C.FUEL["fluid_ml_per_h"][0]
    _, covered = F.refill_needed(60, bike)
    assert covered == pytest.approx(total / lo * 60, abs=2)


def test_heat_shortens_what_a_bike_covers():
    _, cool = F.refill_needed(120, "winspace", temp_c=15)
    _, hot = F.refill_needed(120, "winspace", temp_c=C.TEMP_HOT + 5)
    assert hot < cool


# ── hit rate ───────────────────────────────────────────────────────────────
def test_hit_rate_skips_unlogged_rides():
    rows = [{"fluid_hit": "1"}, {"fluid_hit": ""}, {"fluid_hit": "0"}, {"fluid_hit": "1"}]
    hits, seen = F.hit_rate(rows)
    assert (hits, seen) == (2, 3)


def test_hit_rate_windows_to_last_n():
    rows = [{"fluid_hit": "0"}] * 20 + [{"fluid_hit": "1"}] * 5
    hits, seen = F.hit_rate(rows, n=5)
    assert (hits, seen) == (5, 5)


def test_hit_rate_on_empty_log():
    assert F.hit_rate([]) == (0, 0)


# ── line ───────────────────────────────────────────────────────────────────
def test_line_is_empty_when_nothing_logged():
    assert F.line(None) == ""


def test_line_flags_a_shortfall():
    out = F.line(F.assess(600, 150, 120))
    assert "short" in out and "⚠️" in out


def test_line_reports_bottles_not_just_ml():
    out = F.line(F.assess(1180, 150, 119))
    assert "bottles" in out
