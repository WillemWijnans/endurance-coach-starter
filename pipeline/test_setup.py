#!/usr/bin/env python3
"""Integration tests for the setup wizard. Run: python3 -m pytest test_setup.py -q

No network: every stage is driven with data structures instead of API responses.
Non-interactive, so ask()/confirm() take their defaults — which is also how the
wizard behaves when piped, and worth pinning.

THE CASE THAT MATTERS MOST is a brand-new user with almost no history. They get
the wizard's worst-case output, so it has to degrade into honest placeholders
rather than confident invented numbers.
"""
import contextlib, io
from datetime import date
import pytest
import setup as U
import setup_calibrate as S


def run_all(settings, activities, wellness):
    """Drive every stage and render, capturing the console output."""
    buf = io.StringIO()
    entries, uncal = [], []
    with contextlib.redirect_stdout(buf):
        e = U.stage_power(settings)
        if e:
            entries.append(e)
        for fn, args in ((U.stage_hr, (settings, activities, wellness)),
                         (U.stage_wellness, (wellness,)),
                         (U.stage_load, (activities,)),
                         (U.stage_ve, ())):
            got, missed = fn(*args)
            entries += got
            uncal += missed
    src = S.render_local_config(entries, date.today().isoformat(), uncal)
    ns = {}
    exec(compile(src, "athlete_config_local.py", "exec"), ns)
    return src, {k: v for k, v in ns.items() if not k.startswith("__")}, uncal, buf.getvalue()


# ───────────────────────────────────────────── the brand-new user
def test_empty_account_produces_valid_config_with_nothing_invented():
    src, ns, uncal, out = run_all({}, [], [])
    assert ns == {}, "with no history, NOTHING may be written"
    assert uncal, "and the gaps must be reported"

def test_empty_account_explains_every_gap():
    _, _, uncal, _ = run_all({}, [], [])
    for name, why in uncal:
        assert why and why.strip(), f"{name} left placeholder with no reason given"

def test_empty_account_does_not_crash_on_missing_keys():
    for junk in ({}, {"ftp": None}, {"types": []}, {"max_hr": "abc"}):
        run_all(junk, [], [])


# ───────────────────────────────────────────── the well-equipped user
def _settings():
    return {"types": ["Ride", "VirtualRide"], "ftp": 265, "max_hr": 190, "lthr": 168}

def _wellness(n=200):
    return [{"date": f"day{i}", "restingHR": 46 + (i % 6), "hrv": 50 + (i % 20)}
            for i in range(n)]

def _activities(n=60):
    return [{"hr_load": 100 + (i % 10) * 3, "power_load": 120,
             "max_heartrate": 180 + (i % 5)} for i in range(n)]

def test_full_history_calibrates_everything_derivable():
    _, ns, uncal, _ = run_all(_settings(), _activities(), _wellness())
    for key in ("FTP", "RESERVE", "HR_BANDS", "RHR_IMPLAUSIBLE", "RHR_SUSPECT",
                "HRV_LATE_RECOVERED", "RATIO_NORMAL_MAX", "RATIO_ELEVATED"):
        assert key in ns, f"{key} should have been derived"
    assert ns["FTP"] == 265

def test_resting_hr_comes_from_history_not_the_default():
    """A remembered resting HR is usually a best-ever figure; use the data."""
    _, ns, _, _ = run_all(_settings(), _activities(), _wellness())
    assert ns["RESERVE"]["hr_rest"] != 50, "must not fall back to the placeholder"
    assert 44 <= ns["RESERVE"]["hr_rest"] <= 52

def test_max_hr_prefers_a_higher_recorded_reading():
    acts = _activities()
    acts.append({"hr_load": 100, "power_load": 120, "max_heartrate": 197})
    _, ns, _, out = run_all(_settings(), acts, _wellness())
    assert ns["RESERVE"]["hr_max"] == 197
    assert "HIGHER" in out

def test_zones_anchor_to_lthr_when_available():
    _, ns, _, out = run_all(_settings(), _activities(), _wellness())
    assert "lactate-threshold" in out
    lo, hi = ns["HR_BANDS"]["THRESH"]
    assert lo <= 168 <= hi

def test_zones_fall_back_to_hrmax_without_lthr():
    st = _settings()
    del st["lthr"]
    _, ns, _, out = run_all(st, _activities(), _wellness())
    assert "HR_BANDS" in ns
    assert "%HRmax estimates" in out

def test_cycling_settings_group_is_selected():
    """Sport groups carry DIFFERENT max HRs; the wrong one silently miscalibrates."""
    groups = [{"types": ["Swim"], "max_hr": 187, "ftp": None},
              {"types": ["Run", "TrailRun"], "max_hr": 186, "ftp": 369},
              {"types": ["Ride", "GravelRide"], "max_hr": 185, "ftp": 320}]
    assert U.cycling_settings(groups)["ftp"] == 320

def test_cycling_settings_survives_junk():
    for junk in ([], None, [{}], [{"types": None}], [{"types": ["Swim"]}]):
        assert isinstance(U.cycling_settings(junk), dict)


# ───────────────────────────────────────────── partial history
def test_partial_history_calibrates_only_what_it_can():
    """Enough nights to screen wellness, too few rides for load bands."""
    _, ns, uncal, _ = run_all(_settings(), _activities(n=3), _wellness())
    assert "RHR_SUSPECT" in ns
    assert "RATIO_NORMAL_MAX" not in ns
    assert any("RATIO" in n for n, _ in uncal)

def test_wellness_gap_is_explained_not_silent():
    _, ns, _, out = run_all(_settings(), _activities(), [])
    assert "HRV_LATE_RECOVERED" not in ns
    assert "no wellness data" in out


# ───────────────────────────────────────────── output safety
def test_generated_config_never_contains_the_api_key():
    """The key passes through the wizard; it must never reach the config file."""
    src, _, _, out = run_all(_settings(), _activities(), _wellness())
    assert "API_KEY" not in src and "api_key" not in src

def test_every_written_value_carries_provenance():
    src, ns, _, _ = run_all(_settings(), _activities(), _wellness())
    for line in src.splitlines():
        if line and not line.startswith(("#", " ", '"', "}", ")")) and "=" in line:
            name = line.split("=")[0].strip()
            assert f"{name} =" in src
    assert src.count("#") > len(ns), "each value should be commented with its source"


# ───────────────────────────────────────────── auto mode
def test_auto_mode_is_the_default():
    """Connecting an account should be enough; confirmation is opt-in."""
    assert U.AUTO is True

def test_auto_mode_takes_defaults_without_prompting(monkeypatch):
    """If AUTO ever stopped short-circuiting, a piped run would hang on input."""
    monkeypatch.setattr(U, "AUTO", True)
    monkeypatch.setattr(U.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("must not prompt"))
    assert U.ask("anything", default=7, cast=int) == 7
    assert U.confirm("anything", default=True) is True

def test_credentials_still_prompt_in_auto_mode(monkeypatch):
    """The ONE thing that cannot be derived must still be askable."""
    monkeypatch.setattr(U, "AUTO", True)
    monkeypatch.setattr(U.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "i4242")
    assert U.ask("athlete id", allow_skip=False, force=True) == "i4242"


# ───────────────────────────────────────────── re-run diffing
def test_load_values_reads_generated_config():
    assert U.load_values("FTP = 265\nRHR_SUSPECT = 54\n") == {"FTP": 265, "RHR_SUSPECT": 54}

def test_load_values_survives_a_corrupt_file():
    """A half-written or hand-broken config must not abort the whole run."""
    assert U.load_values("FTP = = 265") == {}
    assert U.load_values("") == {}

def test_rerun_reports_changed_values():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        U.summarise("FTP = 320\n", {"FTP": 250}, [])
    assert "was 250" in buf.getvalue()

def test_rerun_marks_newly_derivable_values():
    """The point of re-running: a placeholder becomes derived as data accrues."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        U.summarise("RATIO_NORMAL_MAX = 0.93\n", {}, [])
    assert "(new)" in buf.getvalue()

def test_rerun_flags_values_that_stopped_being_derivable():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        U.summarise("", {"FTP": 250}, [])
    assert "no longer derivable" in buf.getvalue()

def test_rerun_is_quiet_about_unchanged_values():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        U.summarise("FTP = 320\n", {"FTP": 320}, [])
    out = buf.getvalue()
    assert "was" not in out and "(new)" not in out

def test_summary_truncates_wide_values():
    assert U.short({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}, 20).endswith("…")
    assert U.short(320) == "320"
