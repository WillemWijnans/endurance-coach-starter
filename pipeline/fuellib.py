#!/usr/bin/env python3
"""
Fuelling assessment for a ride.

WHY THIS EXISTS: repeating correct fuelling advice in prose reliably fails to
change behaviour, because nothing is measured and nothing is visibly failing.
Weight logging works precisely because it is a command, a CSV and a trend.
This applies the same mechanism to fluid and carbohydrate.

Reports in BOTTLES, not ml/h. "Finish both bottles and refill once" is
executable at a roadside tap; "500-750 ml/h" is arithmetic you do afterwards.

Pure functions, no I/O — see test_fuellib.py.
"""
import athlete_config as C


def targets(moving_min, temp_c=None):
    """(fluid_lo, fluid_hi, carb_lo, carb_hi) for a ride of this duration.

    Carb need scales with DURATION (glycogen depletion), fluid with duration
    AND heat. Short rides need neither: under ~60min you ride on what you
    already have, which is why the lower bound collapses rather than scaling
    linearly down to a silly number.
    """
    hours = moving_min / 60.0
    f_lo, f_hi = C.FUEL["fluid_ml_per_h"]
    c_lo, c_hi = C.FUEL["carb_g_per_h"]
    if temp_c is not None and temp_c >= C.TEMP_HOT:
        f_lo, f_hi = f_lo * C.FUEL["heat_fluid_mult"], f_hi * C.FUEL["heat_fluid_mult"]
    if moving_min < C.FUEL["no_fuel_below_min"]:
        return (0.0, f_hi * hours, 0.0, 0.0)
    return (f_lo * hours, f_hi * hours, c_lo * hours, c_hi * hours)


def bottles(ml, bike=None):
    """ml → bottles, to 1 decimal. The unit that survives contact with a ride."""
    if ml is None:
        return None
    _, _, bottle_ml = capacity(bike)
    return round(ml / bottle_ml, 1)


def assess(fluid_ml, carb_g, moving_min, temp_c=None):
    """Compare what was consumed against target. Returns a dict, or None if
    nothing was recorded — a missing number is NOT a zero, and must never be
    scored as a miss (that would punish forgetting to log, not under-fuelling)."""
    if fluid_ml is None and carb_g is None:
        return None
    f_lo, f_hi, c_lo, c_hi = targets(moving_min, temp_c)
    hours = moving_min / 60.0 or 1.0
    out = {"hours": round(hours, 2), "fluid_target": (round(f_lo), round(f_hi)),
           "carb_target": (round(c_lo), round(c_hi))}
    if fluid_ml is not None:
        out["fluid_ml"] = fluid_ml
        out["fluid_per_h"] = round(fluid_ml / hours)
        out["fluid_bottles"] = bottles(fluid_ml)
        out["fluid_hit"] = fluid_ml >= f_lo
        out["fluid_short_ml"] = max(0, round(f_lo - fluid_ml))
    if carb_g is not None:
        out["carb_g"] = carb_g
        out["carb_per_h"] = round(carb_g / hours)
        out["carb_hit"] = carb_g >= c_lo if c_lo > 0 else True
        out["carb_short_g"] = max(0, round(c_lo - carb_g))
    return out


def hit_rate(rows, field="fluid_hit", n=10):
    """'fluid target hit 2 of the last 10 logged rides.'

    Counts only rides that RECORDED the value — rides with no entry are
    skipped, not counted as misses. Returns (hits, considered)."""
    seen = [r for r in rows if r.get(field) not in (None, "")]
    recent = seen[-n:]
    hits = sum(1 for r in recent if str(r[field]) in ("1", "True", "true"))
    return hits, len(recent)


def line(a):
    """One-line report for the ride output. Returns '' when nothing logged."""
    if not a:
        return ""
    bits = []
    if "fluid_ml" in a:
        mark = "✅" if a["fluid_hit"] else "⚠️"
        b = a["fluid_bottles"]
        bits.append(f"{mark} fluid {a['fluid_ml']}ml ({b} bottles, {a['fluid_per_h']}ml/h)"
                    + ("" if a["fluid_hit"] else f" — {a['fluid_short_ml']}ml short"))
    if "carb_g" in a:
        mark = "✅" if a["carb_hit"] else "⚠️"
        bits.append(f"{mark} carbs {a['carb_g']}g ({a['carb_per_h']}g/h)"
                    + ("" if a["carb_hit"] else f" — {a['carb_short_g']}g short"))
    return "  " + "\n  ".join(bits)

def capacity(bike=None):
    """(total_ml, cages, bottle_ml) the bike can actually carry.

    Carrying capacity is a HARD constraint that no amount of good intention
    fixes. The gravel bike has one cage; on it, the fluid target is physically
    unreachable beyond ~90min without stopping."""
    bikes = getattr(C, "BIKES", None)
    if not bikes:
        ml = C.FUEL["bottle_ml"]
        return ml, 1, ml
    b = bikes.get(bike or getattr(C, "DEFAULT_BIKE", ""), None)
    if b is None:
        b = bikes[sorted(bikes)[0]]
    return b["cages"] * b["bottle_ml"], b["cages"], b["bottle_ml"]


def refill_needed(moving_min, bike=None, temp_c=None):
    """Minutes of riding this bike covers at the LOWER fluid target, and whether
    a refill stop is required. Returns (needed: bool, minutes_covered: int)."""
    total, _, _ = capacity(bike)
    lo = C.FUEL["fluid_ml_per_h"][0]
    if temp_c is not None and temp_c >= C.TEMP_HOT:
        lo *= C.FUEL["heat_fluid_mult"]
    covered = int(total / lo * 60)
    return moving_min > covered, covered
