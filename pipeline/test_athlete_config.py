#!/usr/bin/env python3
"""Calibration sanity checks. Run: python3 -m pytest test_athlete_config.py -q

These do NOT check that your numbers are right — nothing can do that but a test
on a bike. They check that your calibration is INTERNALLY CONSISTENT, which
catches the mistakes people actually make when editing a config by hand: a zone
that overlaps the next one, a screening bound that would throw away real illness
data, a "hot" threshold above the "dangerously hot" one.

They run against whatever athlete_config_local.py holds, so they keep working
after setup.py regenerates it.

Worth knowing: on the private repo this was extracted from, an accidental edit
once replaced that athlete's measured ventilation bands with THIS FILE'S
placeholder values. Everything still passed and every derived column in a
76-ride history silently changed. If your numbers matter to you, add a test that
pins them by value, not just by consistency.
"""
import pytest
import athlete_config as C

ZONES = ["REC", "Z2", "TEMPO", "THRESH", "VO2"]


def test_you_have_calibrated_at_all():
    """Placeholders produce confident, wrong answers — the worst failure mode."""
    if not C.CALIBRATED:
        pytest.skip("no athlete_config_local.py yet — run `python3 setup.py`")


def test_ftp_is_plausible():
    assert 80 <= C.FTP <= 600, f"FTP of {C.FTP}W is not believable"


def test_hr_bands_ascend_and_leave_no_gaps():
    """A gap means some heart rates belong to no zone and vanish from reports."""
    for a, b in zip(ZONES, ZONES[1:]):
        assert C.HR_BANDS[a][1] == C.HR_BANDS[b][0], f"gap or overlap between {a} and {b}"
    for z in ZONES:
        lo, hi = C.HR_BANDS[z]
        assert lo < hi, f"{z} band is inverted or empty"


def test_hr_bands_sit_inside_the_reserve_anchors():
    assert C.HR_BANDS["VO2"][1] >= C.RESERVE["hr_max"], "top zone below your max HR"
    assert C.RESERVE["hr_rest"] < C.RESERVE["hr_max"]


def test_reserve_anchors_are_plausible():
    assert 25 <= C.RESERVE["hr_rest"] <= 90
    assert 120 <= C.RESERVE["hr_max"] <= 230


@pytest.mark.parametrize("env", ["indoor", "outdoor"])
def test_ve_bands_ascend_without_gaps(env):
    b = C.VE_BANDS[env]
    order = ["Z1", "Z2", "Z3", "Z4", "Z5"]
    for x, y in zip(order, order[1:]):
        assert b[x][1] == b[y][0], f"{env} {x}/{y} gap or overlap"
        assert b[x][0] < b[x][1]


@pytest.mark.parametrize("env", ["indoor", "outdoor"])
def test_vt2_falls_inside_the_ve_bands(env):
    """VT2 should land in the upper zones, or your VE bands disagree with it."""
    assert C.VE_BANDS[env]["Z1"][1] < C.VT2_LOAD[env] <= C.VE_BANDS[env]["Z5"][0]


def test_screening_keeps_illness_visible():
    """THE IMPORTANT ONE. Two tiers exist so device faults get dropped and
    odd-but-real values get KEPT and flagged. Illness commonly lifts resting HR
    10-20% above baseline; if the fault bound sits below that, illness is
    silently discarded and the screen defeats its own purpose."""
    lo, hi = C.RHR_IMPLAUSIBLE
    assert lo < C.RHR_SUSPECT < hi, "the flag threshold must sit inside the fault bounds"
    assert hi >= C.RHR_SUSPECT * 1.15, (
        "fault ceiling too close to the flag threshold — an illness night would "
        "be thrown away as a device error")


def test_hrv_bounds_are_ordered():
    lo, hi = C.HRV_IMPLAUSIBLE
    assert lo < hi and lo > 0


def test_night_split_thresholds_are_sane():
    assert 30 <= C.NIGHT_WINDOW_MIN <= 240
    assert C.HRV_LATE_RECOVERED > 0
    assert C.HR_EARLY_EXCESS_DISTURBED > 0, (
        "early-night HR is judged as excess over that night's own floor, so this "
        "must be a positive margin, not an absolute heart rate")


def test_load_ratio_bands_are_ordered():
    assert C.RATIO_NORMAL_MAX < C.RATIO_ELEVATED


def test_heat_thresholds_are_ordered():
    """TEMP_HOT is a caution; TEMP_HOT_DEMONSTRATED is what your data proves."""
    assert C.TEMP_COLD < C.TEMP_HOT < C.TEMP_HOT_DEMONSTRATED


def test_known_context_dates_are_iso():
    for d in C.KNOWN_CONTEXT:
        assert len(d) == 10 and d[4] == d[7] == "-", f"{d!r} should be YYYY-MM-DD"
