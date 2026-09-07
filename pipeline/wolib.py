#!/usr/bin/env python3
"""
Sanitise PROSE for an intervals.icu workout description.

WHY: intervals parses the description for workout steps, and it does not
distinguish prose from steps. Three separate patterns get eaten:

  "1800m"     -> an 1800-MINUTE step ('m' means minutes, not metres)
  "75-80%"    -> a power RAMP target
  "- Surrey"  -> a prose bullet is shaped like a step line

A 5.5h ride parsed as 35.5h because of one "1800m" in a sentence, and a 4h45
ride parsed as 6.8h because of one "75-80%".

Real step lines look like `- 12m 80% 75rpm`: dash, number, unit. Anything else
starting with a dash is prose and must be de-fanged.
"""
import re

STEP = re.compile(r"^\s*-\s*\d+(?:m|s|h)\b")     # a genuine step line


def sanitise(text):
    """Return prose safe to put in a workout description."""
    out = []
    for ln in text.split("\n"):
        if STEP.match(ln):
            out.append(ln)                        # a real step — leave it alone
            continue
        s = ln
        s = re.sub(r"^(\s*)-\s", r"\1• ", s)      # prose bullet -> bullet char
        s = re.sub(r"\b(\d[\d,]*)m\b", r"\1 metres", s)   # 1800m -> 1800 metres
        s = re.sub(r"\b(\d+)\s*-\s*(\d+)%", r"\1 to \2 percent", s)  # 75-80% -> prose
        s = re.sub(r"\b(\d+)%", r"\1 percent", s)  # bare 85% -> prose
        out.append(s)
    return "\n".join(out)


def build(prose, steps):
    """Sanitised prose + untouched steps block."""
    return sanitise(prose).rstrip() + "\n\n" + steps
