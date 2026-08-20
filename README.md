# Endurance Coach — starter kit

A data pipeline and coaching protocol for endurance athletes who train with
power, heart rate and (optionally) ventilation, using **intervals.icu** as the
data store and a wearable (Garmin etc.) as the source.

It exists because the standard dashboards answer *"what did I do?"* well and
*"what did it cost me?"* badly. This fills that gap.

---

## What it actually gives you

**1. Night splits — early vs late.**
Overnight *averages* mislead when a disturbance is front-loaded: HRV climbs and
HR falls through the night, so the average gets dragged down by a rough first
hour while you actually end up fine. Splitting first-90min vs last-90min shows
what the average hides — and separates *"something disturbed my evening"* from
*"I am not recovering."*

**2. Internal vs external load.**
TSS is power-only by design — mechanical work, comparable across conditions, and
therefore blind to what a day cost. Most platforms also compute an HR-based
load. **The ratio between them is the signal.** In testing it read 1.27 on a ride
whose decoupling looked excellent — the rider came down with a minor illness
that evening, so the ratio caught immune activation the power metrics missed
entirely. Four days later, still unwell, a 30-35°C ride read 1.50 while the two
following days at 27°C read 0.83 and 0.88 — normal. Same rider, still unwell,
so the difference was heat — the controlled comparison is what licenses that
conclusion, not the single high number. A raised ratio tells you a day cost more
than it produced; it does not tell you why.

**3. Ride reports that interpret, not just report.**
Decoupling with contamination detection (a long café stop wrecks the number and
the tool says so), efficiency factor, time-in-zone, and ventilation trends.

**4. An outlier screen that knows the difference between a device fault and a
sick day.** Two-tier on purpose: implausible values are dropped, odd-but-real
values are kept and flagged. A fever pushing resting HR up is data, not noise.

**5. A written coaching protocol** — see `coaching_protocol.md`. Morning gates,
post-ride analysis, fuelling before and after. Generic; adapt freely.

---

## ⚠️ Read this before you trust any output

**Every threshold here is personal.** The shipped values are placeholders, not
recommendations. Running someone else's numbers produces confident, wrong
answers — worse than no answer.

So the first thing you run is the calibration wizard. Connect your intervals
account and it populates the rest:

```bash
cd pipeline && python3 setup.py
```

Most of these thresholds are not preferences. They are facts about your body
already sitting in your own training history — so it derives them rather than
asking you to guess:

| What | Derived from |
|---|---|
| FTP, max HR, LTHR | your intervals settings, cross-checked against your actual activity history |
| Resting HR | the median of your own nights |
| HR zones | your LTHR where available (%HRmax otherwise) — provisional either way |
| Screening bounds | percentiles of your own nights |
| `HRV_LATE_RECOVERED` | the median of your own nightly HRV |
| Load-ratio bands | p75/p90 of your own rides |

Each one is written with its evidence — sample size, percentiles, a
distribution you can eyeball — so you can always see where a number came from.
Where there isn't enough history, it says so and keeps the placeholder instead
of inventing one. Add `--review` to confirm each value by hand instead.

**Re-run it as your history grows.** Placeholders become derivable, derived
values sharpen, and each run reports what moved since the last.

Two things it can't do for you: **HR zones still want a real test** (it will
tell you so), and **VE bands need a ramp with a ventilation strap**.

**Nothing here is medical advice.** It is a training tool. Persistent unexplained
changes in resting HR or HRV are a conversation with a doctor, not a script.

---

## Setup

See **[SETUP.md](SETUP.md)**.

Companion repo: **[garmin-intervals-sync](https://github.com/WillemWijnans/garmin-intervals-sync)**
pushes the extra Garmin fields (HRV detail, sleep stages, Body Battery, Health
Snapshot) into intervals nightly. It shares this repo's environment variable
names, so one `.env` serves both. Optional for ride analysis; **required for the
night splits**, which need per-reading data the native intervals connection does
not carry.

## How to use it day to day

The Python is not the interface. **The conversation is the interface** — you talk
to Claude, and it runs these scripts so the numbers are computed rather than
recalled. That split is the whole design: a language model guessing at your
decoupling is worthless, one reading it off a tested function is not.

### The setup

Open this repo as a project in **Claude Code** (the desktop app or the CLI) and
connect the **intervals MCP server** (SETUP.md step 5). Then Claude can read your
data, run the pipeline, and write to your training calendar in one place.

Two files do the remembering:

- **`athlete_profile.md`** — copy `athlete_profile.template.md` to it and fill it
  in. Who you are, what fails first at max, what your data does when you travel.
  Claude reads this before it says anything.
- **`coaching_protocol.md`** — the method. What to check, in what order, and what
  each number is worth.

Both are living documents. When Claude gets something wrong and you correct it,
**have it write the correction into the file.** That is how the thing improves —
otherwise you re-explain the same fact every month.

### A normal day

**Morning, before deciding anything:**

> *"Run my metrics"* · *"Analyse my night"*

You get the overnight splits, resting HR and HRV screened for device faults,
current form, and a call on whether today's session should stand. Ask for what
you actually want to know — *"is my HRV down because of training or because I
slept badly?"* is a better question than *"what's my HRV."*

**Before a ride, if it is long or hard:**

> *"I'm doing 3h endurance at 10am, I've had porridge and a banana — what else?"*

It should ask what you have already eaten rather than assume, then work in grams
and bottles against what you can actually carry.

**After the ride:**

> *"Analyse my ride"* · *"That was gravel and I wore a backpack"*

Tell it what the data genuinely cannot show: a backpack (it compresses a
ventilation strap and invalidates that ride's VE), a long café stop or a work
call (it wrecks decoupling unless the ride is split), riding to hold someone
else's wheel, a bad night before, forgetting to eat. You get the ride report,
ventilation trend, internal-vs-external load, decoupling, and refuelling scaled
to the ride and the time of day.

> **Weather is not in that list.** intervals stores temperature, wind speed and
> gusts, and `headwind_percent` — the share of the ride spent riding into it —
> so `loads.py` names those itself when a day comes back costly. Do not waste a
> sentence telling it that it was hot or windy; it already knows, and it will
> say so:
>
> ```
> 2026-08-14  1.50  ⚠️ ELEVATED — the day cost MORE than it produced.
>                   conditions: 34°C
> ```

**Planning:**

> *"Build me next week around a 4h Saturday"* · *"Drop Thursday, I'm travelling"*
> *"I felt terrible on Tuesday's intervals — adjust the block"*

Claude writes to your intervals calendar directly through MCP: creating,
updating and deleting sessions. Treat the calendar as the source of truth and let
it edit there rather than keeping a plan in chat.

> ⚠️ **Writing structured workouts:** on intervals, express targets as **% of
> FTP**, not watts and not prose. Watt-denominated steps can inflate the parsed
> duration two- or three-fold, and plain prose ignores your requested duration
> entirely and defaults to 3h. The same session written in % parses exactly.

### Standing instructions

The biggest gains come from things you say **once** and expect every time. Add
them to `coaching_protocol.md` so they survive a new conversation. Real examples:

- *"Always run the early/late night splits when I ask about a night."*
- *"Always interpret the ventilation data on the first pass — don't report it
  and then dismiss it."*
- *"Give me refuelling advice after every ride, scaled to the time of day."*
- *"Ask what I've eaten before telling me what to eat."*

### Getting good answers

**Give it the context the sensors cannot see.** Illness, a bad night with a
child, a stressful week, a flight east. Most confusing data has a boring
explanation that is not in the file.

**Push back when it sounds too confident.** The useful reply to *"your HRV is
down, take a rest day"* is *"based on what? show me the split."* On one occasion
here the athlete's own read beat the device five times running.

**Say when it is wrong, and have it write that down.** Corrections that are not
recorded get re-litigated. Corrections that are recorded compound.

**Do not let it estimate what it can compute.** If a number matters, it should
come from the pipeline. Ask *"did you calculate that or estimate it?"* — it is a
fair question and the answer should always be the former.

---

## Layout

```
pipeline/
  setup.py            ← calibration wizard. Run this first.
  setup_calibrate.py  ← the derivation maths, unit-tested
  athlete_config.py   ← ALL constants, with placeholder defaults
  athlete_config_local.py  ← YOUR calibration (generated, gitignored)
  ridelib.py          ← core metrics (NP, IF, TSS, decoupling, EF, zones)
  analyze.py          ← per-ride report
  wellness.py         ← wellness fetch, outlier screen, night splits
  loads.py            ← internal-vs-external load ratio
  weight.py           ← weight/body-comp trend
  extract_stream.py   ← trim a raw stream dump to what we use
  split_analyze.py    ← split a stop-heavy ride and analyse each leg cleanly
  recompute_log.py    ← re-run the whole log through current calibration
  test_*.py           ← 168 tests, run them
data/                 ← YOUR data. Gitignored. Never commit it.
```

## Tests

```bash
cd pipeline && python3 -m pytest -q
```

Expect **168 passed, 2 skipped**. The two skips are regression tests waiting on
a ride fixture of your own — that is expected, and adding one is worth doing.

The derivation maths in `setup_calibrate.py` is the part most worth trusting:
it is pure, has no network or prompts, and is covered by 88 tests including the
degenerate cases (a rider whose resting HR barely varies, a rider so consistent
that two percentile bands collapse together).

## Credit

Extracted from a working personal setup. The method is shared freely; the
athlete data and calibration are not included, and should not be copied.
