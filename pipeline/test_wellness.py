#!/usr/bin/env python3
"""Tests for wellness.py. Run: python3 -m pytest test_wellness.py -q

Pure-logic only — no network. The screen is the part that must never regress,
because a single unscreened bad value (2026-05-08 restingHR=101) silently
corrupted a real analysis.
"""
import wellness as W


# ---- screen_value: the device-error tier ----
def test_drops_the_real_may8_artifact():
    # The exact value that corrupted the caffeine analysis.
    kept, flag = W.screen_value("restingHR", 101)
    assert kept is None, "101 is not a physiological resting HR"
    assert "implausible" in flag

def test_keeps_normal_resting_hr():
    kept, flag = W.screen_value("restingHR", 45)
    assert kept == 45.0
    assert flag is None

def test_keeps_illness_elevated_hr_but_flags_it():
    """A real fever elevates resting HR — that is data, not noise. Must be KEPT."""
    v = W.RHR_SUSPECT + 3
    kept, flag = W.screen_value("restingHR", v)
    assert kept == float(v), "genuine illness elevation must NOT be dropped"
    assert "suspect" in flag

def test_boundary_values():
    """Read bounds from config so these survive calibration."""
    lo, hi = W.RHR_IMPLAUSIBLE
    assert W.screen_value("restingHR", hi)[0] == float(hi)
    assert W.screen_value("restingHR", hi + 1)[0] is None
    assert W.screen_value("restingHR", lo)[0] == float(lo)
    assert W.screen_value("restingHR", lo - 1)[0] is None

def test_suspect_threshold_edge():
    assert W.screen_value("restingHR", W.RHR_SUSPECT)[1] is None
    assert "suspect" in W.screen_value("restingHR", W.RHR_SUSPECT + 1)[1]

def test_missing_and_garbage_values():
    for bad in (None, "", "abc", []):
        assert W.screen_value("restingHR", bad) == (None, None)

def test_hrv_screen():
    assert W.screen_value("hrv", 55)[0] == 55.0
    assert W.screen_value("hrv", 0)[0] is None
    assert W.screen_value("hrv", 999)[0] is None

def test_unknown_field_passes_through():
    assert W.screen_value("ctl", 62.5) == (62.5, None)


# ---- screen(): whole-row behaviour ----
def test_screen_does_not_mutate_input():
    rows = [{"date": "2026-05-08", "restingHR": 101, "hrv": 41}]
    W.screen(rows)
    assert rows[0]["restingHR"] == 101, "input must be left untouched"

def test_screen_reports_issues_with_dates():
    rows = [{"date": "2026-05-08", "restingHR": 101, "hrv": 41},
            {"date": "2026-05-09", "restingHR": 48, "hrv": 50}]
    out, issues = W.screen(rows)
    assert out[0]["restingHR"] is None
    assert out[1]["restingHR"] == 48.0
    assert len(issues) == 1
    assert issues[0][0] == "2026-05-08"

def test_screen_accepts_raw_api_rows_using_id():
    # the REST API returns the date under "id"
    out, _ = W.screen([{"id": "2026-05-08", "restingHR": 101}])
    assert out[0]["date"] == "2026-05-08"

def test_screen_attaches_known_context():
    W.KNOWN_CONTEXT["2099-01-01"] = "test illness"
    try:
        out, _ = W.screen([{"date": "2099-01-01"}, {"date": "2099-01-02"}])
        assert "illness" in out[0]["context"]
        assert not out[1].get("context")
    finally:
        W.KNOWN_CONTEXT.pop("2099-01-01", None)

def test_screen_empty():
    assert W.screen([]) == ([], [])


# ---- exclude_known_context ----
def test_exclude_known_context_drops_illness_and_travel():
    W.KNOWN_CONTEXT["2099-01-01"] = "test"
    try:
        kept = W.exclude_known_context([{"date": "2099-01-01"}, {"date": "2099-01-02"}])
        assert [r["date"] for r in kept] == ["2099-01-02"]
    finally:
        W.KNOWN_CONTEXT.pop("2099-01-01", None)

def test_exclude_known_context_keeps_everything_clean():
    rows = [{"date": "2026-06-01"}, {"date": "2026-06-02"}]
    assert len(W.exclude_known_context(rows)) == 2


# ---- regression guard: the analysis that got burned ----
def test_screened_mean_matches_the_corrected_analysis():
    """The May 3-9 week: with 101 in, the mean is ~55; screened, it's ~48."""
    week = [46, 47, 50, 46, 50, 101, 48]
    raw_mean = sum(week) / len(week)
    kept = [W.screen_value("restingHR", v)[0] for v in week]
    kept = [v for v in kept if v is not None]
    screened_mean = sum(kept) / len(kept)
    assert raw_mean > 55, "raw mean should be inflated by the artifact"
    assert 47 < screened_mean < 49, f"screened mean should be sane, got {screened_mean}"


# ---- night splits: timestamp normalization ----
def test_to_seconds_accepts_every_format():
    from datetime import datetime
    iso = "2026-08-05T05:46:03.0"
    want = datetime(2026, 8, 5, 5, 46, 3).timestamp()
    assert W._to_seconds(iso) == want                      # HRV: ISO string
    assert W._to_seconds(datetime(2026, 8, 5, 5, 46, 3)) == want
    assert W._to_seconds(1_785_000_000_000) == 1_785_000_000.0   # HR: epoch ms
    assert W._to_seconds(1_785_000_000) == 1_785_000_000.0       # epoch s

def test_to_seconds_rejects_junk():
    for bad in (None, "", "not-a-date", [], True):
        assert W._to_seconds(bad) is None


# ---- night_split: the real-data cases ----
def _night(vals, start=0, step_min=5):
    """(epoch-seconds, value) samples spaced step_min apart."""
    return [(start + i * step_min * 60, v) for i, v in enumerate(vals)]

def test_split_detects_recovery_through_the_night():
    # Aug 5 shape: HRV starts low, climbs by morning. Blocks are wider than the
    # 90min window so neither end straddles a transition.
    s = _night([32] * 24 + [40] * 30 + [45] * 24)   # 6.5h at 5-min spacing
    r = W.night_split(s)
    assert r["early"] == 32.0
    assert r["late"] == 45.0
    assert r["delta"] == 13.0, "should show the +13 climb"

def test_split_detects_falling_hr():
    s = _night([57] * 24 + [52] * 30 + [49] * 24)
    r = W.night_split(s)
    assert r["early"] == 57.0 and r["late"] == 49.0
    assert r["delta"] == -8.0, "HR falls through the night"
    assert r["min"] == 49.0

def test_split_reports_the_floor_not_just_the_ends():
    # the min is the key 'recovery capacity' signal — a dip mid-night must show
    s = _night([50] * 18 + [43] * 42 + [48] * 18)
    assert W.night_split(s)["min"] == 43.0

def test_split_is_order_independent():
    s = _night([32] * 18 + [45] * 18)
    assert W.night_split(s) == W.night_split(list(reversed(s)))

def test_split_average_hides_what_the_split_shows():
    """The whole point: the mean looks bad while the athlete ends up fine."""
    s = _night([32] * 18 + [40] * 42 + [45] * 18)
    r = W.night_split(s)
    mean_all = sum(v for _, v in s) / len(s)
    assert mean_all < 40, "overnight average looks poor"
    assert r["late"] > mean_all, "but the night actually ends higher"

def test_split_drops_none_values():
    s = [(0, 40), (300, None), (600, 50)]
    r = W.night_split(s)
    assert r["n"] == 2

def test_split_short_night_overlaps_windows():
    # night shorter than the window: ends overlap, delta collapses toward 0
    s = _night([40, 42, 44])          # 10 minutes total
    r = W.night_split(s, window_min=90)
    assert r["early"] == r["late"]
    assert r["delta"] == 0.0
    assert r["span_min"] == 10.0, "span_min warns the window was too wide"

def test_split_window_is_respected():
    s = _night([30] * 12 + [60] * 12)        # 115min span: 1h at 30, 1h at 60
    wide = W.night_split(s, window_min=200)  # wider than the span -> both ends
    narrow = W.night_split(s, window_min=30) #   see the whole night
    assert wide["early"] == wide["late"] == 45.0
    assert narrow["early"] == 30.0 and narrow["late"] == 60.0

def test_split_single_sample():
    r = W.night_split([(0, 45)])
    assert r["early"] == r["late"] == r["min"] == 45.0
    assert r["n"] == 1 and r["span_min"] == 0.0

def test_split_empty_and_all_junk():
    assert W.night_split([]) is None
    assert W.night_split(None) is None
    assert W.night_split([(None, 40), (0, None)]) is None

def test_split_survives_unparseable_values():
    r = W.night_split([(0, "abc"), (300, 45), (600, 47)])
    assert r["n"] == 2

# ---- early_excess: early night judged against that night's own floor ----
def test_early_excess_separates_the_good_night_from_the_bad():
    # real values: Aug 4 (good) early 46.6/min 41 -> 5.6; Aug 5 early 57.1/min 43 -> 14.1
    good = W.night_split(_night([46.6] * 24 + [41] * 30 + [45.6] * 24))
    bad = W.night_split(_night([57.1] * 24 + [43] * 30 + [49.3] * 24))
    assert W.early_excess(good) < W.HR_EARLY_EXCESS_DISTURBED
    assert W.early_excess(bad) >= W.HR_EARLY_EXCESS_DISTURBED

def test_early_excess_is_immune_to_a_shifted_baseline():
    """The whole point of using the floor: shifting the night up must not flag it."""
    base = _night([46] * 24 + [41] * 30 + [45] * 24)
    shifted = [(t, v + 8) for t, v in base]        # same shape, higher absolute
    assert W.early_excess(W.night_split(base)) == W.early_excess(W.night_split(shifted))

def test_early_excess_none_when_no_split():
    assert W.early_excess(None) is None




# ---- sleep-window guard: a watch-off night must not report a daytime average ----
class _FakeGarmin:
    """Date-aware stub. Sleep window is 1.0M-2.0M ms and straddles midnight, so
    the previous day carries the pre-midnight half — which is exactly the stitch
    the real code has to do (get_heart_rates is scoped to one calendar date)."""
    PREV, DAY = "2026-08-05", "2026-08-06"
    def __init__(self, has_sleep):
        self.has_sleep = has_sleep
    def get_sleep_data(self, d):
        if not self.has_sleep:
            return {"dailySleepDTO": {}}
        return {"dailySleepDTO": {"sleepStartTimestampGMT": 1_000_000,
                                  "sleepEndTimestampGMT": 2_000_000,
                                  "deepSleepSeconds": 1800}}
    def get_heart_rates(self, d):
        if d == self.PREV:      # evening: one pre-sleep point, one in-window
            return {"heartRateValues": [[500_000, 100], [1_200_000, 50]]}
        return {"heartRateValues": [[1_500_000, 45], [9_000_000, 120]]}
    def get_all_day_stress(self, d):
        if d == self.PREV:
            return {"stressValuesArray": [[500_000, 70], [1_200_000, 25]]}
        return {"stressValuesArray": [[1_500_000, 12], [9_000_000, 80]]}

def test_no_sleep_record_yields_no_night_samples():
    """Watch off = no night. Must NOT fall back to a two-day daytime average."""
    g = _FakeGarmin(has_sleep=False)
    assert W.hr_night_samples(g, "2026-08-06") == []
    assert W.stress_night_samples(g, "2026-08-06") == []
    assert W.night_split(W.hr_night_samples(g, "2026-08-06")) is None

def test_sleep_window_clips_and_stitches_across_midnight():
    g = _FakeGarmin(has_sleep=True)
    hr = W.hr_night_samples(g, "2026-08-06")
    # 50 comes from the PREVIOUS day (pre-midnight sleep) — the stitch must keep
    # it — while the 100 (awake, pre-sleep) and 120 (next-day) are clipped out.
    assert [v for _, v in hr] == [50, 45]
    st = W.stress_night_samples(g, "2026-08-06")
    assert [v for _, v in st] == [25, 12]

def test_sleep_window_none_when_absent():
    assert W.sleep_window(_FakeGarmin(has_sleep=False), "2026-08-06") == (None, None)
    assert W.sleep_window(_FakeGarmin(has_sleep=True), "2026-08-06")[0] == 1_000_000

def test_stress_samples_drop_unmeasurable_sentinels():
    class G(_FakeGarmin):
        def get_all_day_stress(self, d):
            if d == self.PREV:
                return {"stressValuesArray": [[1_200_000, -1]]}
            return {"stressValuesArray": [[1_300_000, 20], [1_400_000, -2]]}
    vals = W.stress_night_samples(G(has_sleep=True), "2026-08-06")
    assert [v for _, v in vals] == [20], "Garmin's -1/-2 'unmeasurable' must not be averaged"

def test_sleep_detail_reads_stages():
    sd = W.sleep_detail(_FakeGarmin(has_sleep=True), "2026-08-06")
    assert sd["deep_min"] == 30
    assert W.sleep_detail(_FakeGarmin(has_sleep=False), "2026-08-06") is None
