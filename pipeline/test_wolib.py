#!/usr/bin/env python3
"""Guards on workout-description sanitising. Each case is a real parser failure."""
import wolib


def test_bare_metres_becomes_words():
    """REGRESSION: '1800m' parsed as an 1800-MINUTE step; a 5.5h ride read as 35.5h."""
    assert "1800 metres" in wolib.sanitise("climbing is 1800m total")
    assert "1800m" not in wolib.sanitise("climbing is 1800m total")


def test_comma_does_not_rescue_metres():
    """'1,800m' still produced an 800-minute step — the comma does not help."""
    out = wolib.sanitise("gain of 1,800m")
    assert "m" not in out.split("1,800")[1][:1]


def test_percent_range_becomes_words():
    """REGRESSION: '75-80%' parsed as a power RAMP; a 4h45 ride read as 6.8h."""
    out = wolib.sanitise("ride it at 75-80% seated")
    assert "75 to 80 percent" in out
    assert "%" not in out


def test_bare_percent_becomes_words():
    assert "85 percent" in wolib.sanitise("not 85% or above")


def test_prose_bullet_is_defanged():
    """A prose bullet starting '- ' is shaped exactly like a step line."""
    out = wolib.sanitise("- Surrey climbs are short")
    assert out.startswith("• ")


def test_real_step_lines_are_untouched():
    """The steps themselves must survive verbatim, percent signs and all."""
    steps = "- 12m 80% 75rpm\n- 45m 63% 90rpm\n- 30s 120% 100rpm"
    assert wolib.sanitise(steps) == steps


def test_step_line_with_ramp_survives():
    assert wolib.sanitise("- 10m 40-60% 85rpm") == "- 10m 40-60% 85rpm"


def test_build_keeps_steps_verbatim():
    out = wolib.build("Ride at 75-80% for 1800m of climbing.", "Main\n- 12m 80% 90rpm")
    assert "- 12m 80% 90rpm" in out
    assert "75-80%" not in out and "1800m" not in out
