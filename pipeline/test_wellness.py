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


# ── night_split median (added Aug 30 2026) ────────────────────────────────────
# early/late alone assume the curve rises monotonically. A flat or rise-then-fall
# night reads as a collapse in the late window while the night's LEVEL was fine.
# That misread produced a wrongly-recommended rest day.

def test_night_split_reports_median():
    sp = W.night_split([(i * 60, 50) for i in range(400)])
    assert sp["median"] == 50


def test_median_survives_a_non_monotonic_night():
    """Rise then fall: late window looks bad, median shows the level was fine."""
    rising = [(i * 60, 30 + i) for i in range(120)]          # 30 -> 149
    falling = [((120 + i) * 60, 150 - 2 * i) for i in range(120)]
    sp = W.night_split(rising + falling)
    assert sp["late"] < sp["early"] + 60, "late window should look weak here"
    assert sp["median"] > sp["late"], "median must expose the level the split hides"


def test_median_absent_when_no_samples():
    assert W.night_split([]) is None


def test_sleep_detail_exposes_duration_key():
    """Duration is a PRIMARY signal; stages are a byproduct. The key must exist
    or the report silently prints a blank column."""
    import inspect
    src = inspect.getsource(W.sleep_detail)
    assert '"asleep_sec"' in src, "duration key missing — report would blank out"


# ── late-starting sleep window (added Sep 2 2026) ─────────────────────────────
# A start-lag check catches readings that begin late relative to sleep onset. It
# does NOT catch a window that is simply TRUNCATED — the device scoring nothing for
# the first couple of hours, then starting cleanly, so the lag reads fine.
# The signature is the first hour reading ABOVE the night's own median.

def test_night_split_reports_first_hour():
    sp = W.night_split([(i*60, 50) for i in range(400)])
    assert sp["first_hour"] == 50


def test_normal_night_starts_below_its_median():
    """A real night climbs: first hour is the LOW point, not the high one."""
    samples = [(i*60, 30 + i*0.1) for i in range(400)]      # 30 -> 70
    sp = W.night_split(samples)
    assert sp["first_hour"] < sp["median"]


def test_late_started_window_starts_above_median():
    """Truncated window: begins with HRV already elevated, then settles."""
    samples = [(i*60, 70 - i*0.05) for i in range(400)]     # 70 -> 50
    sp = W.night_split(samples)
    assert sp["first_hour"] > sp["median"]
    assert sp["first_hour"] - sp["median"] > W.LATE_WINDOW_MARGIN


def test_flat_night_does_not_trigger_the_flag():
    """A genuinely flat night must not be flagged — margin exists for this."""
    sp = W.night_split([(i*60, 50) for i in range(400)])
    assert sp["first_hour"] - sp["median"] <= W.LATE_WINDOW_MARGIN


# ── HRV start lag (added Sep 24 2026) ─────────────────────────────────────────
# First HRV reading minus sleep onset, on a GMT basis. See the comment block
# above HRV_START_LAG_UNRELIABLE_MIN in wellness.py. Fixtures are SYNTHETIC
# nights shaped like real Garmin records (epoch-ms sleep start, naive GMT ISO
# reading times); the lags +2.8 / +2.1 match real verified nights.
NIGHT_A_SLEEP_GMT_MS = 1_768_430_400_000          # 2026-01-14T22:40:00Z
NIGHT_A_FIRST_GMT = "2026-01-14T22:42:45.0"       # +2m45s
NIGHT_A_FIRST_LOCAL = "2026-01-15T00:42:45.0"     # same instant, +2h offset baked in
NIGHT_B_SLEEP_GMT_MS = 1_768_518_600_000          # 2026-01-15T23:10:00Z
NIGHT_B_FIRST_GMT = "2026-01-15T23:12:05.0"       # +2m05s

def test_start_lag_positive_control():
    """Known-good lags: +2.8min and +2.1min."""
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, [NIGHT_A_FIRST_GMT]) == 2.8
    assert W.hrv_start_lag_min(NIGHT_B_SLEEP_GMT_MS, [NIGHT_B_FIRST_GMT]) == 2.1

def test_start_lag_is_independent_of_machine_timezone():
    """Naive GMT strings must be read as UTC, not as this machine's local time
    (which is what _to_seconds does). Re-run under three zones."""
    import os, time
    old = os.environ.get("TZ")
    try:
        for tz in ("UTC", "Europe/Amsterdam", "America/Los_Angeles"):
            os.environ["TZ"] = tz; time.tzset()
            assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, [NIGHT_A_FIRST_GMT]) == 2.8, tz
    finally:
        if old is None: os.environ.pop("TZ", None)
        else: os.environ["TZ"] = old
        time.tzset()

def test_start_lag_mixing_local_with_gmt_goes_one_offset_wrong():
    """The classic bug, reproduced: sleepStartTimestampLocal (offset already
    added) against a GMT reading lands NEGATIVE by exactly the +2h offset."""
    sleep_local_ms = NIGHT_A_SLEEP_GMT_MS + 2 * 3600 * 1000
    lag = W.hrv_start_lag_min(sleep_local_ms, [NIGHT_A_FIRST_GMT])
    assert lag == round(2.75 - 120, 1)
    assert "timezone bug" in W.start_lag_flag(lag)

def test_start_lag_local_reading_gives_positive_offset_error():
    """The mirror mistake — Local reading vs GMT sleep — reads +2h: a false
    'unreliable night', which is why the Local fields are never used."""
    lag = W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, [NIGHT_A_FIRST_LOCAL])
    assert lag == round(2.75 + 120, 1)

def test_hrv_night_returns_gmt_times_not_local():
    """hrv_night must feed the lag from readingTimeGMT. The None-HRV reading is
    dropped so it can't define the first reading."""
    class G:
        def get_hrv_data(self, d):
            return {"hrvReadings": [
                {"hrvValue": None, "readingTimeGMT": "2026-01-14T22:30:00.0",
                 "readingTimeLocal": "2026-01-15T00:30:00.0"},
                {"hrvValue": 45, "readingTimeGMT": "2026-01-14T22:47:45.0",
                 "readingTimeLocal": "2026-01-15T00:47:45.0"},
                {"hrvValue": 39, "readingTimeGMT": NIGHT_A_FIRST_GMT,
                 "readingTimeLocal": NIGHT_A_FIRST_LOCAL}]}
    samples, summary, gmt = W.hrv_night(G(), "2026-09-22")
    assert gmt == ["2026-01-14T22:47:45.0", NIGHT_A_FIRST_GMT]
    assert summary is None                                  # no hrvSummary
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, gmt) == 2.8   # min(), not [0]

def test_start_lag_uses_earliest_reading_regardless_of_order():
    later = "2026-01-14T23:30:00.0"
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, [later, NIGHT_A_FIRST_GMT]) == 2.8

def test_start_lag_disturbed_night():
    """External movement shape: first reading +61min after onset."""
    sleep = NIGHT_A_SLEEP_GMT_MS
    first = sleep // 1000 + 61 * 60
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(first, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0")
    lag = W.hrv_start_lag_min(sleep, [iso])
    assert lag == 61.0
    assert "unreliable" in W.start_lag_flag(lag)

def test_start_lag_accepts_epoch_and_z_suffix():
    first_s = NIGHT_A_SLEEP_GMT_MS / 1000 + 165
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, [first_s]) == 2.8        # epoch s
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, [first_s * 1000]) == 2.8 # epoch ms
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, ["2026-01-14T22:42:45Z"]) == 2.8

def test_start_lag_none_when_inputs_missing():
    assert W.hrv_start_lag_min(None, [NIGHT_A_FIRST_GMT]) is None     # no sleep record
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, []) is None      # no readings
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, None) is None
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, [None, "junk"]) is None

def test_start_lag_skips_junk_readings():
    assert W.hrv_start_lag_min(NIGHT_A_SLEEP_GMT_MS, ["junk", None, NIGHT_A_FIRST_GMT]) == 2.8

def test_start_lag_flag_thresholds():
    t = W.HRV_START_LAG_UNRELIABLE_MIN
    assert W.start_lag_flag(None) is None
    assert W.start_lag_flag(0) is None                 # reading at onset: fine
    assert W.start_lag_flag(2.8) is None
    assert W.start_lag_flag(t) is None                 # "above ~20" — edge not flagged
    assert "stages/shape unreliable" in W.start_lag_flag(t + 0.1)
    assert "external movement" in W.start_lag_flag(t + 0.1)
    assert "timezone bug" in W.start_lag_flag(-0.1)


# ── night CLI args: --stages must reach night_report ─────────────────────────
def test_parse_night_args_without_flag():
    assert W.parse_night_args(["2026-09-22", "2026-09-23"]) == ("2026-09-22", "2026-09-23", False)

def test_parse_night_args_with_stages():
    assert W.parse_night_args(["2026-09-22", "2026-09-23", "--stages"])[2] is True

def test_parse_night_args_flag_position_does_not_matter():
    want = ("2026-09-22", "2026-09-23", True)
    assert W.parse_night_args(["--stages", "2026-09-22", "2026-09-23"]) == want
    assert W.parse_night_args(["2026-09-22", "--stages", "2026-09-23"]) == want

def _raises(fn, *a):
    try:
        fn(*a)
    except ValueError as e:
        return str(e)
    raise AssertionError("expected ValueError")

def test_parse_night_args_rejects_unknown_flag():
    """A typo must fail loudly, not silently drop — the original bug."""
    assert "--stage" in _raises(W.parse_night_args, ["2026-09-22", "2026-09-23", "--stage"])

def test_parse_night_args_rejects_wrong_date_count():
    _raises(W.parse_night_args, ["2026-09-22"])
    _raises(W.parse_night_args, ["2026-09-22", "2026-09-23", "2026-09-24"])
    _raises(W.parse_night_args, ["--stages"])

def test_parse_night_args_rejects_malformed_date():
    _raises(W.parse_night_args, ["2026-09-22", "tomorrow"])

def _capture_night_call(argv):
    calls = []
    orig = W.night_report
    W.night_report = lambda *a, **k: calls.append((a, k))
    try:
        W.main(argv)
    finally:
        W.night_report = orig
    return calls

def test_main_passes_show_stages_through():
    """End-to-end on the CLI: the flag given on argv must arrive as show_stages=True."""
    calls = _capture_night_call(["night", "2026-09-22", "2026-09-23", "--stages"])
    assert calls == [(("2026-09-22", "2026-09-23"), {"show_stages": True})]

def test_main_defaults_show_stages_off():
    calls = _capture_night_call(["night", "2026-09-22", "2026-09-23"])
    assert calls == [(("2026-09-22", "2026-09-23"), {"show_stages": False})]

def test_main_exits_on_bad_night_args_without_fetching():
    try:
        _capture_night_call(["night", "2026-09-22", "2026-09-23", "--stage"])
    except SystemExit as e:
        assert "--stage" in str(e.code)
    else:
        raise AssertionError("expected SystemExit")


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    p = f = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); p += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}"); f += 1
    print(f"\n{p} passed, {f} failed")
    sys.exit(1 if f else 0)
