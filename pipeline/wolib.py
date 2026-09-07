#!/usr/bin/env python3
"""
Sanitise PROSE for an intervals.icu workout description.

WHY: intervals parses the description for workout steps and cannot tell prose
from steps. Every duration/target token in ordinary writing gets eaten:

  "1800m"    -> an 1800-MINUTE step   ('m' means minutes, not metres)
  "a 3h ride"-> a 180-minute step
  "30s"      -> a 30-second step
  "75-80%"   -> a power RAMP target
  "0.5km"    -> a distance step
  "- Surrey" -> a prose bullet is shaped exactly like a step line

A 5.5h ride parsed as 35.5h from one "1800m"; then as 6.8h from one "75-80%";
then as 9.3h from one "3h". Adding a comma does not help — "1,800m" yields an
800-minute step.

A REAL step line is: dash, number, unit. Anything else starting with a dash is
prose and must be de-fanged.
"""
import re

STEP = re.compile(r"^\s*-\s*\d+(?:\.\d+)?(?:m|s|h|km)\b")


def sanitise(text):
    """Return prose that intervals cannot mistake for workout steps."""
    out = []
    for ln in text.split("\n"):
        if STEP.match(ln):
            out.append(ln)                                    # genuine step
            continue
        s = ln
        s = re.sub(r"^(\s*)-\s", r"\1• ", s)                  # bullet -> •
        s = re.sub(r"\b(\d+)h(\d+)\b", r"\1 hours \2", s)     # 4h45 -> 4 hours 45
        s = re.sub(r"\b(\d+)h\b", r"\1 hours", s)             # 3h   -> 3 hours
        s = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)km\b", r"\1 kilometres", s)
        s = re.sub(r"\b(\d[\d,]*)m\b", r"\1 metres", s)
        s = re.sub(r"\b(\d+)s\b", r"\1 seconds", s)
        s = re.sub(r"\b(\d+)\s*-\s*(\d+)%", r"\1 to \2 percent", s)
        s = re.sub(r"\b(\d+)%", r"\1 percent", s)
        out.append(s)
    return "\n".join(out)


def build(prose, steps):
    """Sanitised prose + untouched steps block."""
    return sanitise(prose).rstrip() + "\n\n" + steps
