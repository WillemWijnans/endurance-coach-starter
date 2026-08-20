# Coaching protocol

The analysis habits the pipeline supports. Generic — adapt to the athlete.

Underlying principle: **measured beats classified, and subjective beats both when
they disagree without explanation.**

---

## 1. Trust measured values over classified ones

Wearables give you two very different kinds of number:

| **Measured** — trust | **Classified** — treat as commentary |
|---|---|
| HRV (per-reading), heart rate, resting HR | deep / REM / light sleep minutes |
| Overnight stress series | sleep score |
| Power, cadence, ventilation | "readiness" composites, verdict strings |

Sleep *staging* in particular is unreliable. Chinoy et al. (2020, *Sleep*, n=34
vs polysomnography) found consumer devices **"failed to correctly identify 30–50%
of both deep sleep and REM"**, with wake-detection specificity as low as 0.18 on
some devices, and total sleep time significantly overestimated. Hibbing et al.
(2024) found sleep onset predicted **~50 minutes late** on average.

So: **never let a deep/REM swing drive a training decision.** Report it as
colour, not evidence. Sleep *duration* is roughly usable; sleep *architecture*
is not.

**Corollary:** measurement errors usually announce themselves (a resting HR of
101 is impossible). Classification errors do not — 63 vs 95 minutes of deep sleep
both look plausible. That asymmetry is the whole argument.

---

## 2. Morning gate check

Report the averages, **but confirm against the end-of-night values before acting
on a bad one.**

```bash
python3 wellness.py night <yesterday> <today>
```

| Read | Meaning |
|---|---|
| **Late HRV** (last 90min) | Where they actually landed. The honest gate. |
| **HR floor** (min) | Recovery *capacity*. A floor that holds even on bad nights argues strongly against anything systemic. |
| **Early-night excess** (early − floor) | What disturbed the *start* of the night: meal size and timing, room temperature, skin inflammation, late hard training. Not training load. |

**Judge early-night HR against that night's own floor, never as an absolute** —
sleep-onset HR varies with how late and active the evening was, so a fixed
cut-off flags almost every night.

**Also: check sleep onset before reading much into a single night.** If the
device logged it an hour late, the "early window" starts after the real first
hour of sleep and the split is measuring the wrong thing.

**Report form as the PRE-workout value** — end of yesterday (yesterday's CTL −
yesterday's ATL). The figure stamped on today already includes today's *planned*
session and overstates current fatigue.

---

## 3. Post-ride analysis

```bash
python3 analyze.py <id> <indoor|outdoor> <date> "<name>"
python3 loads.py <id>
```

Report, every time:

1. **Duration, NP, IF, TSS, HR distribution**
2. **Decoupling** — and whether it is contaminated. A long stop wrecks the
   first-half/second-half comparison; split the ride at the stop instead.
3. **Internal vs external load ratio** — see below.
4. **Ventilation** — if available: drift by thirds, breathing rate, tidal volume.
5. **Refuelling** — see §4.

### The load ratio
`hr_load ÷ power_load`. Calibrate the bands from ~10 normal rides.

| Ratio | Read |
|---|---|
| baseline | normal |
| notably above | worth noting |
| well above | **the day cost more than it produced** — heat, dehydration, fatigue, illness. **TSS understates that ride.** |

Also watch **watts per heartbeat**, which falls on the same days.

### Ventilation, if you have it
- **VE drift**: flat or falling = good durability. Rising at steady power =
  accumulating load or thermal strain.
- **Breathing rate**: the most trustworthy *cross-session* ventilatory metric —
  counting breaths survives strap drift; measuring volume does not. Rising BR
  across consecutive days indicates cumulative fatigue, sometimes *before* heart
  rate shows it.
- **Tidal volume (VE ÷ BR)**: falls within most long rides. A steeper fall means
  a more fatigued ride.
- **"HR up, VE flat" outdoors is expected**, not a finding. Say so.

---

## 4. Fuelling — ask, then compute

Do not guess at intake. **Ask what they actually ate, tally the grams, and
prescribe only the gap.** Athletes engage with item-by-item arithmetic; they
ignore "eat more carbs."

**Before:** *"What have you eaten today and when? How long until you ride, and
how long is it?"*

| Time until ride | Approach |
|---|---|
| 3h+ | Full meal, 1–2g carb/kg |
| 1–2h | 30–60g, low fat, low fibre |
| <1h | 20–30g, liquid-leaning |
| Easy <90min | Fasted is genuinely fine. Do not manufacture a requirement. |

**Never start a quality session under-fuelled.**

**After:** *"What did you have, roughly how much?"* Then tally and fill the gap.

| Ride | Carbs | Protein |
|---|---|---|
| TSS <60 | 40–60g | 25–30g |
| TSS 60–120 | 60–100g | 30–40g |
| TSS 120+ | 100g+, and keep eating for hours | 30–40g, repeated |

**Adjust for time of day** — the part most guidance omits:

| Finish | Approach |
|---|---|
| Morning / midday | Easy. The next normal meal does the work. |
| Early evening | Normal carb-forward dinner. |
| **Late evening** | Refuel must not cost sleep. Moderate, **low fat**, fast-clearing. Eat within 30min, finish 45min before bed. Liquid options are ideal. |
| Very late | Minimal — a shake. **Sleep outranks marginal glycogen.** |

**Multi-day blocks override the sizing:** keep carbs aggressive every night
regardless of the day's TSS, because the deficit is cumulative.

**Heat:** ~750ml–1L/h, sodium matters more than carbs, and cooling the skin
(wetting the jersey) is the most effective intervention available.

---

## 5. Heat

Heat is usually the largest uncontrolled variable in summer.

- **Ride by heart rate, not power.** Expect 10–15bpm higher HR at the same watts;
  hold the HR and let the watts fall, which may be 30–50W.
- **TSS will under-report the day** — the load ratio catches what TSS misses.
- **Stop for**: sweating ceasing, chills in the heat, nausea, confusion. That is
  heat illness, not fatigue, and it is a different category.

---

## 6. Things worth knowing about individuals

Athletes differ in ways that matter more than any threshold:

- **Some feel worst when "fresh."** Positive TSB is an accounting abstraction
  (CTL − ATL); it knows nothing about plasma volume, glycogen turnover or
  neuromuscular recruitment — all of which *decay* when load stops. For some
  athletes a high positive TSB means "detrained for a week," not "ready."
- **Autonomic and muscular recovery run on different clocks.** HRV, HR and
  ventilation are all *central* measures. If the limiter is the legs, none of
  them measure it — only the athlete does.
- **Supercompensation is real and lagged.** In one documented case a 210km ride
  produced no change for four days, then a +11W eFTP jump on day five that held
  for nine. **Schedule the hardest sessions ~5–10 days after a big overload, not
  before** — and note it will not show up until something hard tests for it.

**Log the exceptions.** Illness dates, travel, device faults. Six months later
you will not remember why one week looks strange, and an unexplained outlier
will quietly corrupt an analysis.
