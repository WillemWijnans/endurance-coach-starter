# Setup

Roughly 30 minutes. Steps 1–5 are the working setup; step 6 is only for
ventilation-strap owners.

---

## 1. intervals.icu account + API key

[intervals.icu](https://intervals.icu) is free and is the data store for
everything here.

1. Create an account.
2. **Settings → Developer Settings → API Key.** Copy it.
3. Note your **athlete ID** — it is in the URL when you view your profile, in
   the form `i123456`.

---

## 2. Get your wearable data in

Two separate things, and it is worth being clear about which you need.

### a. Rides and daily wellness — the native connection

intervals.icu connects directly to Garmin, Strava, Wahoo and others under
**Settings → Connections**. Do this first. It covers activities, training load,
weight, and daily wellness aggregates — enough for the ride reports, the load
ratio and the weight trend.

### b. Night splits — needs Garmin API access

**The native connection is NOT enough for this part.** intervals stores one
resting-HR and one HRV figure per night; the night-split analysis needs the
*per-reading* series behind them, and that only comes from the Garmin API
directly. Without it, `wellness.py night` will not run.

That matters more than it sounds, because the splits are the point. An overnight
average can badly misrepresent a night when the disturbance is front-loaded —
HRV climbing and HR falling through the night drags the mean down while you
actually end up fine. Reading only the average produces false alarms.

So if you use Garmin and want that analysis, you need credentials in a `.env`:

```
GARMIN_USERNAME=...
GARMIN_PASSWORD=...
```

Point `SYNC_ENV` in `athlete_config.py` at that file, or put it in the repo root
as `.env`, which is already gitignored and checked automatically.

### c. Optional: a nightly sync for the extra fields

To get HRV detail, sleep stages, Body Battery and Health Snapshot *stored in
intervals* rather than fetched live each time, you need a small sync script:
`garminconnect` to read, `PUT /api/v1/athlete/{id}/wellness/{date}` to write.

A working one is here:

**[github.com/WillemWijnans/garmin-intervals-sync](https://github.com/WillemWijnans/garmin-intervals-sync)**

It uses the **same environment variable names** as this repo
(`INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID`, `GARMIN_USERNAME`,
`GARMIN_PASSWORD`), so a single `.env` serves both — and if you set that up
first, this repo picks your intervals credentials up automatically and
`setup.py` will not need to ask. It also supports macOS Keychain instead of a
plaintext `.env`, and includes a cron recipe for running it nightly.

> Non-Garmin users: everything except the night splits works from the native
> intervals connection alone. The night functions will simply be unavailable.

---

## 3. Install

```bash
git clone <this repo> && cd endurance-coach-starter
python3 -m pip install requests python-dotenv garminconnect pytest
```

---

## 4. Calibrate — `setup.py`

**This is the step that matters.** The thresholds shipped in
`athlete_config.py` are placeholders, and running someone else's numbers gives
you confident, wrong answers.

```bash
cd pipeline && python3 setup.py
```

Connecting your account is all it takes — it then **populates every value it
can from your own history** rather than asking you to guess:

| Value | Where it comes from |
|---|---|
| FTP, max HR, LTHR | your intervals sport settings, cross-checked against the highest HR actually recorded in your activities |
| Resting HR | median of your own nights — not a remembered best-ever figure |
| HR zones | anchored to your LTHR where available, %HRmax otherwise. Provisional either way |
| Resting-HR fault/flag bounds | percentiles of your own nights, set clear enough of your range that illness stays visible |
| `HRV_LATE_RECOVERED` | median of your own nightly HRV |
| Load-ratio bands | p75/p90 of your own rides |

Each value is written with the evidence behind it — sample size, percentiles,
and an ASCII distribution you can eyeball — so it is always clear where a
threshold came from and how stale it is.

Where there isn't enough history yet, it **says so and keeps the placeholder**
rather than inventing a number.

```bash
python3 setup.py --review      # confirm each value by hand before it lands
python3 setup.py --dry-run     # show what it would write, change nothing
python3 setup.py --years 2     # look further back
```

**Re-run it as your history grows** — that is the point, not a chore. Thresholds
that were placeholders become derivable, and derived ones sharpen. Every run
reports what moved:

```
FTP                    320   (was 250)
RHR_SUSPECT            49    (was 60)
RATIO_NORMAL_MAX       0.93  (new)
```

Anything you want to keep by hand, edit directly in
`pipeline/athlete_config_local.py` — but note a later run will overwrite it, so
record hand-tuned values in your athlete profile too.

Output goes to `pipeline/athlete_config_local.py`, which is **gitignored** and
overrides the placeholders. Your calibration therefore never lands in git —
which matters, because those numbers describe one specific body.

Verify:

```bash
cd pipeline && python3 -m pytest -q          # expect 168 passed, 2 skipped
python3 wellness.py report 2026-01-01 2026-06-30
```

Common commands:

```bash
python3 wellness.py night <oldest> <newest>   # night splits + sleep architecture
python3 loads.py range <oldest> <newest>      # internal vs external load
python3 analyze.py <activity_id> <indoor|outdoor> <YYYY-MM-DD> "<name>"
python3 weight.py report
```

> **Always pass the date to `analyze.py`.** A row logged without one is invisible
> to every trend analysis, and you will not notice for weeks.

---

## 5. The MCP server — how you actually talk to it

**Do this one.** It is listed after calibration only because it needs your API
key, not because it is a nice-to-have: the day-to-day workflow in the README —
morning check, post-ride analysis, editing your training calendar in
conversation — all runs through it. Skip it only if you intend to run the
scripts by hand from a terminal.

There is a public `intervals-icu-mcp` package:

```bash
pip install intervals-icu-mcp
```

Then in your MCP config (`claude_desktop_config.json` for the desktop app, or
`claude mcp add` for the CLI — **note these are separate registries**):

```json
"intervals-icu": {
  "command": "/bin/sh",
  "args": ["-c", "INTERVALS_ICU_API_KEY=YOUR_KEY INTERVALS_ICU_ATHLETE_ID=iYOURID exec intervals-icu-mcp"]
}
```

⚠️ **That stores your API key in plaintext.** Fine locally; do not sync or share
that file. If you rotate the key, remember it now lives in **two** places — the
MCP config and your `.env`.

---

## 6. Optional — ventilation

The VE metrics need a ventilation strap ([Tymewear](https://www.tymewear.com) is
what this was built against). Without one, VE fields are simply absent and the
rest works normally.

If you do use one, two things matter more than the numbers:

- **Absolute VE drifts 15–22 units session-to-session** with strap tension and
  sweat. Read trends *within* a ride; never compare absolute levels across rides.
- **Outdoors, VE is often nearly flat versus power** while HR responds normally.
  So "HR up, VE flat" is expected outdoors and is not a finding.

A backpack or vest compresses the sensor and invalidates that ride's VE entirely.

---

## Data hygiene

`data/` is gitignored. **Keep it that way.** It will fill with wellness history,
weight, sleep and illness records — do not commit or share it.
