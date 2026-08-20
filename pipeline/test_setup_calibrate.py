#!/usr/bin/env python3
"""Tests for setup_calibrate.py. Run: python3 -m pytest test_setup_calibrate.py -q

All pure — no network, no prompts, no files written. The point of these is that
a wrong threshold is worse than no threshold, so every derivation is checked for
ordering, for degenerate input, and for the specific failure mode it exists to
prevent.
"""
import pytest
import setup_calibrate as S


# ───────────────────────────────────────────────── helpers
def test_percentile_known_values():
    v = [1, 2, 3, 4, 5]
    assert S.percentile(v, 0) == 1
    assert S.percentile(v, 50) == 3
    assert S.percentile(v, 100) == 5

def test_percentile_interpolates():
    assert S.percentile([10, 20], 50) == 15

def test_percentile_single_value():
    assert S.percentile([42], 50) == 42
    assert S.percentile([42], 99) == 42

def test_percentile_empty_raises():
    with pytest.raises(ValueError):
        S.percentile([], 50)

@pytest.mark.parametrize("junk", [None, "abc", "", [], {}, float("nan"), float("inf")])
def test_numbers_rejects_junk(junk):
    assert S.numbers([junk], 0, 100) == []

def test_numbers_accepts_numeric_strings():
    assert S.numbers(["48"], 0, 100) == [48.0]

def test_numbers_applies_range():
    assert S.numbers([5, 50, 500], 20, 120) == [50.0]

def test_numbers_handles_none_input():
    assert S.numbers(None, 0, 100) == []


# ───────────────────────────────────────────────── RHR screen
def _rhr_history(n=200, base=46):
    """A plausible resting-HR history: mostly 44-52 with a little spread."""
    return [base + (i % 9) for i in range(n)]

def test_rhr_screen_refuses_small_sample():
    d = S.derive_rhr_screen([48] * 5)
    assert not d.ok
    assert "need 30+" in d.reason
    assert d.n == 5

def test_rhr_screen_tiers_are_ordered():
    d = S.derive_rhr_screen(_rhr_history())
    lo, hi = d.value["implausible"]
    assert lo < d.value["suspect"] < hi

def test_rhr_screen_brackets_the_real_history():
    """The implausible tier must not clip values the athlete actually records."""
    hist = _rhr_history()
    lo, hi = S.derive_rhr_screen(hist).value["implausible"]
    assert lo < min(hist) and hi > max(hist)

def test_rhr_screen_keeps_illness_values_plausible():
    """THE POINT OF TWO TIERS: an illness reading is data, not noise.

    A few high-50s nights in an otherwise mid-40s history must land ABOVE the
    suspect threshold (so they get flagged) but INSIDE the implausible bounds
    (so they are never silently dropped).
    """
    hist = _rhr_history() + [58, 59, 57]
    d = S.derive_rhr_screen(hist)
    lo, hi = d.value["implausible"]
    assert 58 > d.value["suspect"], "an illness night should trip the flag"
    assert lo < 58 < hi, "an illness night must NOT be discarded as a fault"

def test_rhr_screen_survives_a_device_artifact():
    """One absurd reading must not drag the bounds far enough to blind the screen."""
    clean = S.derive_rhr_screen(_rhr_history())
    dirty = S.derive_rhr_screen(_rhr_history() + [101])
    assert dirty.value["implausible"][1] - clean.value["implausible"][1] <= 10

def test_rhr_screen_does_not_collapse_on_a_flat_history():
    """An athlete with an unusually consistent RHR still needs distinct tiers."""
    d = S.derive_rhr_screen([48] * 60)
    lo, hi = d.value["implausible"]
    assert lo < d.value["suspect"] < hi

def test_rhr_screen_records_provenance_and_n():
    d = S.derive_rhr_screen(_rhr_history(n=120))
    assert d.n == 120
    assert "p99" in d.method


# ───────────────────────────────────────────────── HRV
def test_hrv_refuses_small_sample():
    assert not S.derive_hrv_recovered([50] * 10).ok

def test_hrv_uses_median_not_mean():
    """A long low tail from bad nights must not drag the bar down.

    If this ever used a mean, the threshold would sink below the athlete's
    typical night and almost every night would read as 'recovered'.
    """
    hist = [55] * 90 + [20, 22, 25, 18, 30, 21, 19, 24, 23, 26]
    d = S.derive_hrv_recovered(hist)
    mean = sum(hist) / len(hist)
    assert d.value == 55
    assert d.value > mean

def test_hrv_ignores_impossible_readings():
    d = S.derive_hrv_recovered([55] * 40 + [0, 999, -5])
    assert d.n == 40


# ───────────────────────────────────────────────── load ratio
def _ratios(n=40, base=0.85):
    return [round(base + (i % 7) * 0.02, 2) for i in range(n)]

def test_ratio_refuses_small_sample():
    d = S.derive_ratio_bands(_ratios(n=4))
    assert not d.ok and "need 10+" in d.reason

def test_ratio_bands_are_ordered():
    d = S.derive_ratio_bands(_ratios())
    assert d.value["elevated"] > d.value["normal_max"]

def test_ratio_bands_sit_above_typical():
    """Normal rides must read as normal, or the metric cries wolf every day."""
    r = _ratios()
    d = S.derive_ratio_bands(r)
    median = sorted(r)[len(r) // 2]
    assert d.value["normal_max"] >= median

def test_ratio_bands_flag_a_heat_day():
    """The metric's whole purpose: a genuinely costly day must clear the bar."""
    d = S.derive_ratio_bands(_ratios())
    assert 1.50 > d.value["elevated"]

def test_ratio_bands_keep_a_gap_when_rider_is_very_consistent():
    """Identical ratios collapse p75 onto p90; the bands must stay distinct."""
    d = S.derive_ratio_bands([0.9] * 20)
    assert d.value["elevated"] > d.value["normal_max"]

def test_ratio_bands_are_personal():
    """Two riders with different baselines must get different bands.

    This is the argument for deriving rather than shipping a default at all.
    """
    low = S.derive_ratio_bands(_ratios(base=0.80))
    high = S.derive_ratio_bands(_ratios(base=1.15))
    assert high.value["normal_max"] > low.value["normal_max"]


# ───────────────────────────────────────────────── HR bands
def test_hr_bands_are_contiguous_and_ascending():
    b = S.derive_hr_bands(190).value
    order = ["REC", "Z2", "TEMPO", "THRESH", "VO2"]
    for a, c in zip(order, order[1:]):
        assert b[a][1] == b[c][0], "bands must not leave a gap"
        assert b[a][0] < b[a][1]

def test_hr_bands_marked_provisional():
    assert "PROVISIONAL" in S.derive_hr_bands(190).method

@pytest.mark.parametrize("bad", [None, "abc", 0, 60, 400])
def test_hr_bands_reject_impossible_max(bad):
    d = S.derive_hr_bands(bad)
    assert not d.ok and d.reason

def test_hr_bands_scale_with_max():
    assert S.derive_hr_bands(200).value["Z2"][1] > S.derive_hr_bands(180).value["Z2"][1]


# ───────────────────────────────────────────────── max HR reconciliation
def test_reconcile_prefers_a_higher_observed_reading():
    v, note = S.reconcile_hr_max(185, 192)
    assert v == 192 and "HIGHER" in note

def test_reconcile_keeps_profile_but_warns_it_is_a_floor():
    v, note = S.reconcile_hr_max(190, 178)
    assert v == 190 and "floor" in note

def test_reconcile_handles_one_sided_input():
    assert S.reconcile_hr_max(None, 188)[0] == 188
    assert S.reconcile_hr_max(186, None)[0] == 186

def test_reconcile_handles_no_input():
    v, note = S.reconcile_hr_max(None, None)
    assert v is None and note

def test_reconcile_ignores_absurd_values():
    assert S.reconcile_hr_max(999, 188)[0] == 188


# ───────────────────────────────────────────────── rendering
def _render(entries, uncal=None):
    src = S.render_local_config(entries, "2026-08-20", uncal)
    ns = {}
    exec(compile(src, "athlete_config_local.py", "exec"), ns)
    return src, ns

def test_rendered_config_is_valid_python_and_loads():
    src, ns = _render([
        S.ConfigEntry("FTP", "265", "confirmed"),
        S.ConfigEntry("RHR_SUSPECT", "54", "p90 of 200 nights"),
    ])
    assert ns["FTP"] == 265 and ns["RHR_SUSPECT"] == 54

def test_rendered_config_carries_provenance():
    src, _ = _render([S.ConfigEntry("FTP", "265", "20-min test 2026-08-01")])
    assert "# 20-min test 2026-08-01" in src

def test_rendered_multiline_provenance_is_fully_commented():
    """Every provenance line needs its own '#', or the file will not parse."""
    src, ns = _render([S.ConfigEntry("FTP", "265", "line one\nline two")])
    assert "# line one" in src and "# line two" in src
    assert ns["FTP"] == 265

def test_rendered_config_round_trips_complex_values():
    bands = {"REC": (0, 129), "Z2": (129, 152), "TEMPO": (152, 165),
             "THRESH": (165, 175), "VO2": (175, 250)}
    _, ns = _render([S.ConfigEntry("HR_BANDS", S.fmt_hr_bands(bands), "")])
    assert ns["HR_BANDS"] == bands

def test_rendered_reserve_round_trips():
    res = {"hr_rest": 45, "hr_max": 190}
    _, ns = _render([S.ConfigEntry("RESERVE", S.fmt_reserve(res), "")])
    assert ns["RESERVE"] == res

def test_uncalibrated_items_are_listed_as_comments():
    src, ns = _render([S.ConfigEntry("FTP", "265", "")],
                      uncal=[("VT2_LOAD", "no ventilation strap")])
    assert "VT2_LOAD: no ventilation strap" in src
    assert "VT2_LOAD" not in ns, "an uncalibrated value must NOT be assigned"

def test_empty_render_still_valid():
    _, ns = _render([])
    assert "FTP" not in ns


# ───────────────────────────────────────────────── regressions
def test_tight_history_still_leaves_room_for_illness():
    """REGRESSION. Found by running against real data.

    An athlete with a very consistent resting HR (44-48 all year) produced a
    p99+5 fault bound of ~56 — so a genuine illness night at 58 would have been
    silently DROPPED as a device fault, defeating the entire two-tier design.
    The fault bound must scale with the median, not hug the observed range.
    """
    d = S.derive_rhr_screen([44 + (i % 5) for i in range(300)])
    lo, hi = d.value["implausible"]
    assert lo < 58 < hi, "an illness night must survive a tight history"
    assert not lo < 101 < hi, "a device artifact must still be caught"
    assert d.value["suspect"] < 58, "and the illness night must still be flagged"

@pytest.mark.parametrize("median", [40, 45, 50, 60])
def test_illness_survives_at_any_baseline(median):
    """A 25% lift over baseline is illness, not a fault, wherever baseline sits."""
    d = S.derive_rhr_screen([median + (i % 3) - 1 for i in range(200)])
    lo, hi = d.value["implausible"]
    assert lo < median * 1.25 < hi


# ───────────────────────────────────────────────── LTHR-anchored zones
def test_lthr_bands_contiguous_and_ascending():
    b = S.derive_hr_bands_from_lthr(167).value
    order = ["REC", "Z2", "TEMPO", "THRESH", "VO2"]
    for a, c in zip(order, order[1:]):
        assert b[a][1] == b[c][0]
        assert b[a][0] < b[a][1]

def test_lthr_z2_ceiling_lands_near_measured_vt1():
    """Sanity anchor: for a rider with LTHR 167 and a lab-measured VT1 of 150,
    the derived Z2 ceiling should land within a couple of beats."""
    assert abs(S.derive_hr_bands_from_lthr(167).value["Z2"][1] - 150) <= 3

def test_lthr_threshold_band_contains_lthr():
    """LTHR must fall inside the threshold band, or the anchor is misapplied."""
    lo, hi = S.derive_hr_bands_from_lthr(167).value["THRESH"]
    assert lo <= 167 <= hi

@pytest.mark.parametrize("bad", [None, "abc", 0, 50, 300])
def test_lthr_bands_reject_impossible_values(bad):
    assert not S.derive_hr_bands_from_lthr(bad).ok

def test_lthr_marked_provisional():
    assert "PROVISIONAL" in S.derive_hr_bands_from_lthr(167).method
