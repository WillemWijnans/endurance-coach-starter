#!/usr/bin/env python3
"""
Derivation logic for the setup wizard. PURE — no network, no prompts, no files.

WHY THIS IS SEPARATE FROM setup.py: the interesting part of calibration is the
statistics, and statistics you cannot test are statistics you should not trust.
Everything here takes plain lists and returns plain results, so the whole of it
is covered by test_setup_calibrate.py without touching an API.

THE PRINCIPLE: ask the user as little as possible. Most thresholds in
athlete_config.py are not preferences — they are facts about a body that are
already sitting in that person's own history. A number derived from 200 of your
own nights beats a number you guessed, and beats someone else's number badly.

Every derivation returns a Derived, which carries the value, the sample size and
a plain-English description of how it was reached. That provenance is written
into the generated config as a comment, so six months later it is still obvious
where a threshold came from and whether it is stale.
"""
from dataclasses import dataclass, field
from typing import Any, Sequence

# Minimum samples before a derivation is trustworthy. Below these we refuse and
# keep the placeholder rather than produce a confident number from three nights.
MIN_N_WELLNESS = 30      # ~1 month of nights
MIN_N_RIDES = 10         # enough rides to see a normal spread

# Pre-filter bounds. Deliberately WIDE — this only drops physically impossible
# junk (a 0 or a 250) so it cannot distort a percentile. Real-but-odd values
# must survive to be judged by the derivation itself.
SANE_RHR = (20, 120)
SANE_HRV = (5, 250)
SANE_RATIO = (0.2, 4.0)


@dataclass
class Derived:
    """One calibrated value plus the evidence for it."""
    name: str
    value: Any = None
    n: int = 0
    method: str = ""
    reason: str = ""              # populated only when value is None
    sample: list = field(default_factory=list)   # for showing a distribution

    @property
    def ok(self) -> bool:
        return self.value is not None


def numbers(values: Sequence, lo: float, hi: float) -> list:
    """Coerce to float and keep only finite values inside [lo, hi].

    Tolerates the real shape of wellness data: Nones, missing keys, strings,
    and the occasional NaN.
    """
    out = []
    for v in values or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f in (float("inf"), float("-inf")):   # NaN / inf
            continue
        if lo <= f <= hi:
            out.append(f)
    return out


def percentile(sorted_vals: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile. p in 0..100. Assumes sorted input."""
    if not sorted_vals:
        raise ValueError("percentile of empty sequence")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))


def _stats(vals: list) -> dict:
    s = sorted(vals)
    return {"n": len(s), "min": s[0], "max": s[-1],
            "p01": percentile(s, 1), "p10": percentile(s, 10),
            "median": percentile(s, 50), "p75": percentile(s, 75),
            "p90": percentile(s, 90), "p99": percentile(s, 99),
            "sorted": s}


# ─────────────────────────────────────────────────── wellness screening
def derive_rhr_screen(raw_values, min_n=MIN_N_WELLNESS):
    """Two thresholds for the resting-HR screen, from the athlete's own history.

    IMPLAUSIBLE is set just OUTSIDE the entire observed range (p01/p99 with a
    margin) — the job of that tier is to catch device faults, so it must not
    clip real physiology. SUSPECT is p90: a value in your own top decile is
    plausible but worth a second look, which is exactly the flag-don't-drop
    behaviour the screen wants.
    """
    vals = numbers(raw_values, *SANE_RHR)
    if len(vals) < min_n:
        return Derived("RHR screen", None, len(vals),
                       reason=f"need {min_n}+ nights of resting HR, found {len(vals)}")
    st = _stats(vals)
    # The fault bound must sit WELL CLEAR of the observed range. Illness commonly
    # lifts resting HR 10-20% above baseline, and on an athlete with a very tight
    # history p99+5 lands below that — which would silently DROP the illness data
    # this two-tier design exists to preserve. So: p99+5, or a third above the
    # median, whichever is more generous. A genuine device fault (a 0, a 101, a
    # 250) is wildly wrong and still gets caught.
    high = max(int(st["p99"]) + 5, int(round(st["median"] * 1.33)))
    low = max(SANE_RHR[0], min(int(st["p01"]) - 5, int(round(st["median"] * 0.75))))
    suspect = int(round(st["p90"]))
    # Guard against a narrow history collapsing the tiers into each other.
    if suspect >= high:
        suspect = high - 1
    if low >= suspect:
        low = max(SANE_RHR[0], suspect - 10)
    return Derived(
        "RHR screen",
        {"implausible": (low, high), "suspect": suspect},
        st["n"],
        method=(f"p01={st['p01']:.0f} p90={st['p90']:.0f} p99={st['p99']:.0f} "
                f"over {st['n']} nights; fault bounds set clear of it to preserve illness data"),
        sample=st["sorted"],
    )


def derive_hrv_recovered(raw_values, min_n=MIN_N_WELLNESS):
    """End-of-night HRV meaning 'recovered' = the athlete's own median.

    Median, not mean: HRV distributions have a long low tail from bad nights,
    and a mean would drag the bar down until almost every night passed it.
    """
    vals = numbers(raw_values, *SANE_HRV)
    if len(vals) < min_n:
        return Derived("HRV_LATE_RECOVERED", None, len(vals),
                       reason=f"need {min_n}+ nights of HRV, found {len(vals)}")
    st = _stats(vals)
    return Derived(
        "HRV_LATE_RECOVERED", int(round(st["median"])), st["n"],
        method=(f"median of {st['n']} nights "
                f"(p10={st['p10']:.0f} median={st['median']:.0f} p90={st['p90']:.0f})"),
        sample=st["sorted"],
    )


# ─────────────────────────────────────────────────── internal/external load
def derive_ratio_bands(raw_ratios, min_n=MIN_N_RIDES):
    """Bands for hr_load / power_load, from the athlete's own normal rides.

    p75 = the top of unremarkable; p90 = genuinely elevated. Set from the SAME
    rides the athlete already did, so 'normal' means normal FOR THEM. A rider
    whose typical ratio is 0.85 and one whose typical is 1.15 need different
    bands to get the same warning at the same physiological moment.
    """
    vals = numbers(raw_ratios, *SANE_RATIO)
    if len(vals) < min_n:
        return Derived("ratio bands", None, len(vals),
                       reason=f"need {min_n}+ rides with both HR and power load, found {len(vals)}")
    st = _stats(vals)
    normal_max = round(st["p75"], 2)
    elevated = round(st["p90"], 2)
    # A very consistent rider can collapse p75 and p90 together; keep a real gap
    # so the two bands still mean different things.
    if elevated <= normal_max:
        elevated = round(normal_max + 0.10, 2)
    return Derived(
        "ratio bands", {"normal_max": normal_max, "elevated": elevated}, st["n"],
        method=(f"p75/p90 of {st['n']} rides "
                f"(median={st['median']:.2f} p75={st['p75']:.2f} p90={st['p90']:.2f})"),
        sample=st["sorted"],
    )


# ─────────────────────────────────────────────────── heart rate
# Provisional %HRmax anchors. THESE ARE ESTIMATES and the generated config says
# so loudly. Individual VT1 ranges roughly 65-85% of HRmax, so a %-derived Z2
# ceiling can be wrong by 15bpm. They exist to be better than a stranger's
# absolute numbers, not to substitute for a test.
HR_PCT = {"REC": 0.68, "Z2": 0.80, "TEMPO": 0.87, "THRESH": 0.92}


# % of LACTATE THRESHOLD HR (Friel-style cycling zones). Preferred over %HRmax
# when the platform has an LTHR: threshold is a physiological landmark that moves
# with training, whereas max HR is a ceiling that says little about where YOUR
# aerobic boundaries sit. The Z2 ceiling is the number that matters most for
# endurance riding, and anchoring it to LTHR gets far closer than %HRmax does.
LTHR_PCT = {"REC": 0.81, "Z2": 0.89, "TEMPO": 0.94, "THRESH": 1.05}


def derive_hr_bands_from_lthr(lthr):
    """Provisional HR zones anchored to lactate-threshold HR."""
    try:
        lt = float(lthr)
    except (TypeError, ValueError):
        return Derived("HR_BANDS", None, 0, reason="no LTHR available")
    if not 100 <= lt <= 210:
        return Derived("HR_BANDS", None, 0,
                       reason=f"LTHR {lt:.0f} outside a believable range")
    c = {k: int(round(lt * v)) for k, v in LTHR_PCT.items()}
    bands = {
        "REC":    (0, c["REC"]),
        "Z2":     (c["REC"], c["Z2"]),
        "TEMPO":  (c["Z2"], c["TEMPO"]),
        "THRESH": (c["TEMPO"], c["THRESH"]),
        "VO2":    (c["THRESH"], 250),
    }
    return Derived("HR_BANDS", bands, 0,
                   method=(f"PROVISIONAL — %LTHR of {lt:.0f} (Friel cycling zones). "
                           "Better anchored than %HRmax, but still replace it with "
                           "a measured VT1/VT2."))


def derive_hr_bands(hr_max):
    """Provisional HR zones from %HRmax. The weaker fallback when LTHR is absent."""
    try:
        hm = float(hr_max)
    except (TypeError, ValueError):
        return Derived("HR_BANDS", None, 0, reason="no max HR available")
    if not 120 <= hm <= 230:
        return Derived("HR_BANDS", None, 0,
                       reason=f"max HR {hm:.0f} outside a believable range")
    c = {k: int(round(hm * p)) for k, p in HR_PCT.items()}
    bands = {
        "REC":    (0, c["REC"]),
        "Z2":     (c["REC"], c["Z2"]),
        "TEMPO":  (c["Z2"], c["TEMPO"]),
        "THRESH": (c["TEMPO"], c["THRESH"]),
        "VO2":    (c["THRESH"], 250),
    }
    return Derived("HR_BANDS", bands, 0,
                   method=(f"PROVISIONAL — %HRmax of {hm:.0f} "
                           f"({int(HR_PCT['REC']*100)}/{int(HR_PCT['Z2']*100)}/"
                           f"{int(HR_PCT['TEMPO']*100)}/{int(HR_PCT['THRESH']*100)}%). "
                           "Replace with measured VT1/VT2."))


def reconcile_hr_max(profile_max, observed_max):
    """Compare the platform's stored max HR with the highest actually recorded.

    Worth doing explicitly: a stored max HR is often years old or was copied
    from 220-age, while the activity history contains a genuine higher reading.
    Returns (value, note).
    """
    p = numbers([profile_max], 120, 230)
    o = numbers([observed_max], 120, 230)
    if not p and not o:
        return None, "no max HR from either source"
    if not o:
        return int(p[0]), f"profile value {p[0]:.0f}; no activity data to check it"
    if not p:
        return int(o[0]), f"highest recorded in your activities ({o[0]:.0f}); nothing stored in profile"
    if o[0] > p[0]:
        return int(o[0]), (f"using {o[0]:.0f} — your activities contain a HIGHER reading "
                           f"than the {p[0]:.0f} stored in your profile")
    return int(p[0]), (f"profile says {p[0]:.0f}; highest actually recorded is {o[0]:.0f}. "
                       "A ramp test under-elicits true max, so treat this as a floor")


# ─────────────────────────────────────────────────── config rendering
@dataclass
class ConfigEntry:
    """One line destined for the generated config."""
    name: str
    literal: str          # already-formatted Python source for the value
    provenance: str = ""  # how it was arrived at; written as a comment


def fmt_hr_bands(bands: dict) -> str:
    """Render HR_BANDS as readable, aligned Python source."""
    lines = ["{"]
    for k in ("REC", "Z2", "TEMPO", "THRESH", "VO2"):
        if k in bands:
            lo, hi = bands[k]
            lines.append(f'    "{k}":{" " * (7 - len(k))}({lo}, {hi}),')
    lines.append("}")
    return "\n".join(lines)


def fmt_reserve(reserve: dict) -> str:
    lines = ["{"]
    for k, v in reserve.items():
        lines.append(f'    "{k}": {v!r},')
    lines.append("}")
    return "\n".join(lines)


HEADER = '''#!/usr/bin/env python3
"""
🔧 YOUR calibration — generated by setup.py on {date}.

This file is gitignored and OVERRIDES the placeholders in athlete_config.py.
Do not share it: these numbers describe one specific body, and running them
against a different one produces confident, wrong answers.

Re-run `python3 setup.py` at any time to regenerate. Anything you edit by hand
will be overwritten, so record hand-tuned values in your athlete profile too.

Each entry below carries the evidence it was derived from. When a number looks
wrong later, that comment tells you whether it was measured, estimated, or
guessed — and how stale it is.
"""
'''

STILL_PLACEHOLDER = '''
# ─────────────────────────────────────────────────────────────────────
# NOT YET CALIBRATED — these fell back to the placeholders in
# athlete_config.py because there was not enough data yet:
{items}
# Re-run setup.py once you have more history.
'''


def render_local_config(entries, date, uncalibrated=None) -> str:
    """Produce athlete_config_local.py source text.

    Deliberately emits plain assignments rather than anything clever: the file
    has to be readable and hand-editable in an emergency.
    """
    out = [HEADER.format(date=date)]
    for e in entries:
        if e.provenance:
            for line in e.provenance.split("\n"):
                out.append(f"# {line}")
        out.append(f"{e.name} = {e.literal}")
        out.append("")
    if uncalibrated:
        items = "\n".join(f"#   - {n}: {why}" for n, why in uncalibrated)
        out.append(STILL_PLACEHOLDER.format(items=items))
    return "\n".join(out).rstrip() + "\n"
