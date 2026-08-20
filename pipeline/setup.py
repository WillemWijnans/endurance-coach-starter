#!/usr/bin/env python3
"""
Interactive calibration wizard.

    python3 setup.py              # connect and populate everything (default)
    python3 setup.py --review     # confirm each value by hand before it lands
    python3 setup.py --dry-run    # show what it would write, change nothing
    python3 setup.py --years 2    # how far back to look (default 1)

Re-running is safe and is the point: as your history grows, thresholds that were
placeholders become derivable and derived ones sharpen. Each run reports what
MOVED since the last one.

WHAT IT DOES. Most thresholds in athlete_config.py are not preferences — they
are facts about your body that already exist in your own training history. This
walks through them, DERIVES what it can from your data, shows you the evidence,
and lets you accept or override each one. What it cannot derive it says so about
plainly and leaves as a placeholder rather than inventing a number.

WHAT IT WRITES. athlete_config_local.py, which is gitignored and overrides the
placeholders. Your calibration therefore never lands in git — which matters,
because these numbers describe one specific body and are useless on another.

The derivation maths lives in setup_calibrate.py and is fully unit-tested; this
file is only prompts, API calls and orchestration.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import athlete_config as C
import setup_calibrate as S

LOCAL_CONFIG = Path(__file__).parent / "athlete_config_local.py"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
BASE_URL = "https://intervals.icu/api/v1"

# AUTO is the DEFAULT. Connecting an account should be enough to populate the
# config — a wizard that stops for confirmation eight times is friction standing
# between the user and a working setup, and every value it proposes is derived
# from their own data anyway. `--review` restores the step-by-step walkthrough
# for anyone who wants to inspect each number before it lands.
AUTO = True

DIM, BOLD, GREEN, YELLOW, RED, RESET = (
    "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


# ───────────────────────────────────────────────────────── presentation
def head(n, title):
    print(f"\n{BOLD}── {n}. {title} {'─' * max(0, 58 - len(title))}{RESET}")

def info(msg):   print(f"   {msg}")
def dim(msg):    print(f"   {DIM}{msg}{RESET}")
def warn(msg):   print(f"   {YELLOW}!{RESET} {msg}")
def bad(msg):    print(f"   {RED}✗{RESET} {msg}")
def good(msg):   print(f"   {GREEN}✓{RESET} {msg}")


def histogram(vals, width=44, buckets=11):
    """A crude ASCII distribution, so a proposed threshold can be eyeballed.

    Showing the spread matters more than showing the number: a threshold that
    sits in a sensible place on your own distribution is obviously right, and
    one that does not is obviously wrong.
    """
    if len(vals) < 5:
        return
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        dim(f"all {len(vals)} values = {lo:g}")
        return
    step = (hi - lo) / buckets
    counts = [0] * buckets
    for v in vals:
        counts[min(int((v - lo) / step), buckets - 1)] += 1
    peak = max(counts) or 1
    for i, c in enumerate(counts):
        edge = lo + i * step
        bar = "█" * max(0, round(c / peak * width))
        dim(f"{edge:6.1f} │{bar} {c if c else ''}")


def ask(prompt, default=None, cast=str, allow_skip=True, force=False):
    """Prompt with a default. Enter accepts, 's' skips, Ctrl-C/EOF aborts.

    Re-prompts on bad input rather than crashing or silently taking the default
    — a mistyped FTP that silently becomes the placeholder is exactly the kind
    of quiet wrongness this whole tool exists to avoid.
    """
    if (AUTO and not force) or not sys.stdin.isatty():
        return default
    suffix = f" [{default}]" if default is not None else ""
    skip = "/s to skip" if allow_skip else ""
    while True:
        try:
            raw = input(f"   {BOLD}?{RESET} {prompt}{suffix}{DIM}{skip}{RESET}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n   aborted — nothing written")
            sys.exit(1)
        if not raw:
            return default
        if allow_skip and raw.lower() in ("s", "skip"):
            return None
        try:
            return cast(raw)
        except (TypeError, ValueError):
            bad(f"'{raw}' is not a valid {cast.__name__} — try again")


def confirm(prompt, default=True, force=False):
    if (AUTO and not force) or not sys.stdin.isatty():
        return default
    d = "Y/n" if default else "y/N"
    try:
        raw = input(f"   {BOLD}?{RESET} {prompt} [{d}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n   aborted — nothing written")
        sys.exit(1)
    return default if not raw else raw.startswith("y")


def accept(d: S.Derived, label, fmt=str):
    """Show a derived value with its evidence and let the user accept/override."""
    if not d.ok:
        warn(f"{label}: {d.reason}")
        dim("leaving the placeholder in place — re-run setup when you have more data")
        return None
    info(f"{label}: {BOLD}{fmt(d.value)}{RESET}")
    dim(f"derived from {d.method}")
    return d


# ───────────────────────────────────────────────────────── api
def pick(d, *keys):
    """First present, non-null value among keys. Field names vary by endpoint."""
    for k in keys:
        v = (d or {}).get(k)
        if v not in (None, "", 0):
            return v
    return None


CYCLING_TYPES = {"Ride", "VirtualRide", "GravelRide", "MountainBikeRide"}


def cycling_settings(groups):
    """Pick the CYCLING sport-settings group.

    intervals stores settings per sport group, and they genuinely differ — one
    real athlete had max_hr 185 for Ride, 186 for Run and 187 for Swim. Grabbing
    the first group would quietly calibrate cycling zones off running numbers.
    """
    best, best_n = None, 0
    for g in groups or []:
        n = len(CYCLING_TYPES & set(g.get("types") or []))
        if n > best_n:
            best, best_n = g, n
    return best or {}


def get(path, aid, key, **params):
    import requests
    r = requests.get(f"{BASE_URL}{path}", params=params or None,
                     auth=("API_KEY", key), timeout=90)
    r.raise_for_status()
    return r.json()


def verify(aid, key):
    """Confirm the credentials work before asking anything else."""
    try:
        p = get(f"/athlete/{aid}/profile", aid, key)
        return p.get("athlete") or p
    except Exception as e:
        bad(f"could not reach intervals.icu: {e}")
        return None


# ───────────────────────────────────────────────────────── stages
def stage_connect():
    head(1, "Connect to intervals.icu")
    dim("Find both at intervals.icu → Settings → Developer.")
    dim("Your API key is never printed back and never enters git.")
    try:
        aid, key = C.__dict__.get("_creds_override") or __import__("wellness").creds()
        good(f"found existing credentials for athlete {aid}")
        if confirm("use them?", True):
            return aid, key
    except SystemExit:
        dim("no saved credentials found")
    except Exception:
        dim("no saved credentials found")

    aid = ask("athlete id (e.g. i12345)", allow_skip=False, force=True)
    key = ask("api key", allow_skip=False, force=True)
    if not aid or not key:
        sys.exit("   need both to continue")
    if not str(aid).startswith("i"):
        aid = f"i{aid}"
    if confirm(f"save them to {ENV_FILE.name} (gitignored) so you only do this once?",
               True, force=True):
        ENV_FILE.write_text(
            f"INTERVALS_ATHLETE_ID={aid}\nINTERVALS_API_KEY={key}\n")
        ENV_FILE.chmod(0o600)
        good(f"written to {ENV_FILE} (permissions 600)")
    return aid, key


def stage_power(settings):
    head(2, "Threshold power")
    ftp = pick(settings, "ftp", "indoor_ftp")
    if ftp:
        info(f"intervals has your FTP as {BOLD}{ftp}W{RESET}")
    else:
        warn("no FTP found in your profile")
    dim("This anchors every power zone and every TSS number, so it matters more")
    dim("than anything else here. If it is stale, fix it now.")
    v = ask("FTP in watts", default=ftp, cast=int, allow_skip=False)
    if not v or not 80 <= v <= 600:
        warn("skipping FTP — placeholder retained")
        return None
    src = "confirmed during setup" if v == ftp else "entered during setup"
    return S.ConfigEntry("FTP", str(v), f"{src} {date.today()}")


def stage_hr(settings, activities, wellness_rows):
    head(3, "Heart rate")
    observed = max((pick(a, "max_heartrate", "icu_hr_max", "maxHR") or 0)
                   for a in activities) if activities else 0
    stored = pick(settings, "max_hr")
    hr_max, note = S.reconcile_hr_max(stored, observed or None)
    if hr_max is None:
        warn(note)
        hr_max = ask("your max HR, if you know it", cast=int)
        note = "entered during setup"
    else:
        info(f"max HR: {BOLD}{hr_max}{RESET}")
        dim(note)
        hr_max = ask("accept max HR", default=hr_max, cast=int) or hr_max
    if not hr_max:
        return [], [("HR_BANDS", "no max HR available")]

    # Resting HR anchors every reserve percentage. Take it from the athlete's own
    # nights rather than asking — a remembered figure is usually a best-ever one.
    rhr_vals = S.numbers([r.get("restingHR") for r in wellness_rows], *S.SANE_RHR)
    if len(rhr_vals) >= S.MIN_N_WELLNESS:
        rest = int(round(S.percentile(sorted(rhr_vals), 50)))
        rest_src = f"median of {len(rhr_vals)} nights"
        info(f"resting HR: {BOLD}{rest}{RESET} ({rest_src})")
    else:
        rest = ask("resting HR", default=50, cast=int) or 50
        rest_src = "entered during setup"

    # Prefer an LTHR anchor when the platform has one — threshold is a
    # physiological landmark, max HR is only a ceiling.
    lthr = pick(settings, "lthr")
    bands = S.derive_hr_bands_from_lthr(lthr) if lthr else S.derive_hr_bands(hr_max)
    if not bands.ok and lthr:
        bands = S.derive_hr_bands(hr_max)
    if lthr and bands.ok:
        info(f"anchoring zones to your lactate-threshold HR of {BOLD}{lthr}{RESET}")
    entries = [S.ConfigEntry("RESERVE",
                             S.fmt_reserve({"hr_rest": int(rest), "hr_max": int(hr_max),
                                            "ve_rest": 10, "ve_max": 160,
                                            "br_rest": 13, "br_max": 50}),
                             f"hr_max from your history, hr_rest = {rest_src}; "
                             f"set {date.today()}. VE/BR left at defaults")]
    if bands.ok:
        print()
        warn("HR ZONES ARE THE WEAKEST NUMBERS HERE.")
        if lthr:
            dim("Anchored to your LTHR, which is a real physiological landmark —")
            dim("better than %HRmax, but the zone WIDTHS are still standard ratios")
            dim("and yours may not be. Replace with a measured VT1/VT2 when you can.")
        else:
            dim("These are %HRmax estimates, the weakest anchor available. Real VT1")
            dim("ranges 65-85% of max, so your Z2 ceiling could be 15bpm off.")
            dim("Set an LTHR on intervals, or test, and re-run this.")
        b = bands.value
        for k in ("REC", "Z2", "TEMPO", "THRESH", "VO2"):
            info(f"{k:<7} {b[k][0]}-{b[k][1]}")
        if confirm("use these provisional zones?", True):
            entries.append(S.ConfigEntry("HR_BANDS", S.fmt_hr_bands(b),
                                         f"{bands.method} — set {date.today()}"))
        else:
            return entries, [("HR_BANDS", "declined provisional zones; set from a test")]
    return entries, []


def stage_wellness(rows):
    head(4, "Wellness screening thresholds")
    dim("Deriving from your own nights: what counts as a device fault, what")
    dim("counts as odd-but-real, and what end-of-night HRV means recovered.")
    if not rows:
        warn("no wellness data in this window — nothing to derive from")
        dim("connect a wearable under intervals Settings -> Connections, then")
        dim("re-run this in a month or so")
        return [], [("RHR / HRV thresholds", "no wellness data available")]

    rhr = S.derive_rhr_screen([r.get("restingHR") for r in rows])
    hrv = S.derive_hrv_recovered([r.get("hrv") for r in rows])
    entries, uncal = [], []

    if rhr.ok:
        histogram(rhr.sample)
    d = accept(rhr, "resting HR screen",
               lambda v: f"fault outside {v['implausible']}, flag above {v['suspect']}")
    if d:
        dim("Two tiers on purpose: faults get dropped, odd-but-real values get")
        dim("KEPT and flagged. Illness pushes RHR up — that is data, not noise.")
        if confirm("accept?", True):
            v = d.value
            entries += [
                S.ConfigEntry("RHR_IMPLAUSIBLE", repr(v["implausible"]),
                              f"{d.method}; set {date.today()}"),
                S.ConfigEntry("RHR_SUSPECT", str(v["suspect"]),
                              f"p90 of your own {d.n} nights"),
            ]
        else:
            uncal.append(("RHR_IMPLAUSIBLE / RHR_SUSPECT", "declined"))
    else:
        uncal.append(("RHR_IMPLAUSIBLE / RHR_SUSPECT", rhr.reason))

    print()
    d = accept(hrv, "HRV_LATE_RECOVERED", lambda v: f"{v}ms")
    if d and confirm("accept?", True):
        entries.append(S.ConfigEntry("HRV_LATE_RECOVERED", str(d.value),
                                     f"{d.method}; set {date.today()}"))
    elif not d:
        uncal.append(("HRV_LATE_RECOVERED", hrv.reason))
    return entries, uncal


def stage_load(activities):
    head(5, "Internal-vs-external load bands")
    dim("hr_load / power_load. Your normal range is personal — a rider whose")
    dim("typical ratio is 0.85 and one at 1.15 need different bands to get the")
    dim("same warning at the same physiological moment.")
    ratios = []
    for a in activities:
        r = S.numbers([a.get("hr_load")], 1, 1000), S.numbers([a.get("power_load")], 1, 1000)
        if r[0] and r[1]:
            ratios.append(r[0][0] / r[1][0])
    d = S.derive_ratio_bands(ratios)
    if d.ok:
        histogram(d.sample)
    d = accept(d, "load ratio bands",
               lambda v: f"normal <={v['normal_max']}, elevated >={v['elevated']}")
    if d and confirm("accept?", True):
        return [S.ConfigEntry("RATIO_NORMAL_MAX", str(d.value["normal_max"]),
                              f"{d.method}; set {date.today()}"),
                S.ConfigEntry("RATIO_ELEVATED", str(d.value["elevated"]),
                              "p90 of your own rides")], []
    return [], [("RATIO_NORMAL_MAX / RATIO_ELEVATED",
                 d.reason if d and not d.ok else "declined")]


def stage_ve():
    head(6, "Ventilation strap")
    dim("Only relevant with a ventilation strap (Tymewear or similar).")
    if not confirm("do you have one?", False):
        good("skipping VE entirely — ride reports will simply omit it")
        return [], []
    warn("VE bands cannot be derived from history — they need a ramp test.")
    dim("Ride a ramp with the strap, find the VE at which breathing 'breaks")
    dim("away' from linear, and set VT2_LOAD to that. Until then the shipped")
    dim("placeholders will misclassify your zones.")
    v = ask("VE at threshold (indoor), if you know it", cast=float)
    if v:
        return [S.ConfigEntry("VT2_LOAD", repr({"indoor": v, "outdoor": round(v * 0.85, 1)}),
                              f"entered during setup {date.today()}; outdoor estimated at 85%")], []
    return [], [("VE_BANDS / VT2_LOAD", "needs a ramp test with the strap")]


def short(v, n=56):
    """Compact a value for the summary line. Full detail lives in the file."""
    t = repr(v)
    return t if len(t) <= n else t[:n - 1] + "…"


def load_values(source_text):
    """Exec generated config text and return its assignments."""
    ns = {}
    try:
        exec(compile(source_text, "athlete_config_local.py", "exec"), ns)
    except Exception:
        return {}
    return {k: v for k, v in ns.items() if not k.startswith("__")}


def summarise(new_src, previous, uncal):
    """Report what landed, and what MOVED since the last run.

    The diff matters more than the values on a re-run: as history accumulates,
    a threshold that was a placeholder becomes derived, and one derived from 40
    rides shifts once there are 300. Seeing that movement is how you notice your
    own baseline changing.
    """
    new = load_values(new_src)
    head(7, "Result")
    if not new:
        warn("nothing could be derived yet — all placeholders retained")
    for k, v in new.items():
        was = previous.get(k)
        if k in previous and was != v:
            info(f"{k:<22} {BOLD}{short(v)}{RESET}  {YELLOW}(was {short(was, 24)}){RESET}")
        elif k not in previous:
            info(f"{k:<22} {BOLD}{short(v)}{RESET}  {GREEN}(new){RESET}")
        else:
            info(f"{k:<22} {short(v)}")
    for k in previous:
        if k not in new:
            warn(f"{k} is no longer derivable — it was {previous[k]}")
    if uncal:
        print()
        for n, why in uncal:
            dim(f"still placeholder — {n}: {why}")
    return new


# ───────────────────────────────────────────────────────── main
def main(argv):
    global AUTO
    dry = "--dry-run" in argv
    AUTO = "--review" not in argv
    years = 1
    if "--years" in argv:
        try:
            years = max(1, int(argv[argv.index("--years") + 1]))
        except (IndexError, ValueError):
            sys.exit("--years needs a number")

    print(f"{BOLD}Calibration setup{RESET}")
    if AUTO:
        dim("Populating your config from your own intervals history.")
        dim("Every value below is derived from YOUR data, and each carries the")
        dim("evidence behind it. Re-run any time; use --review to confirm each")
        dim("one by hand, or just edit athlete_config_local.py afterwards.")
    else:
        dim("Reviewing each value before it is written.")
    if dry:
        warn("DRY RUN — nothing will be written")
    if LOCAL_CONFIG.exists() and not dry:
        warn(f"{LOCAL_CONFIG.name} already exists and will be REPLACED.")
        dim("re-deriving from your latest data; changes are listed at the end")

    aid, key = stage_connect()
    profile = verify(aid, key)
    if profile is None:
        sys.exit("   check your athlete id and api key, then re-run")
    good(f"connected as athlete {aid}")

    try:
        settings = cycling_settings(get(f"/athlete/{aid}/sport-settings", aid, key))
        if settings:
            dim(f"loaded cycling settings ({', '.join((settings.get('types') or [])[:3])}…)")
    except Exception as e:
        bad(f"could not fetch sport settings: {e}")
        settings = {}

    newest = date.today()
    oldest = newest - timedelta(days=365 * years)
    try:
        activities = get(f"/athlete/{aid}/activities", aid, key,
                         oldest=oldest.isoformat(), newest=newest.isoformat())
        dim(f"loaded {len(activities)} activities from the last {years}y")
    except Exception as e:
        bad(f"could not fetch activities: {e}")
        activities = []
    try:
        wellness = get(f"/athlete/{aid}/wellness", aid, key,
                       oldest=oldest.isoformat(), newest=newest.isoformat())
        dim(f"loaded {len(wellness)} days of wellness")
    except Exception as e:
        bad(f"could not fetch wellness: {e}")
        wellness = []

    entries, uncal = [], []
    e = stage_power(settings)
    if e:
        entries.append(e)
    for fn, args in ((stage_hr, (settings, activities, wellness)),
                     (stage_wellness, (wellness,)),
                     (stage_load, (activities,)),
                     (stage_ve, ())):
        try:
            got, missed = fn(*args)
            entries += got
            uncal += missed
        except SystemExit:
            raise
        except Exception as exc:            # one bad stage must not lose the rest
            bad(f"{fn.__name__} failed: {exc}")
            uncal.append((fn.__name__, f"stage errored: {exc}"))

    src = S.render_local_config(entries, date.today().isoformat(), uncal)
    previous = load_values(LOCAL_CONFIG.read_text()) if LOCAL_CONFIG.exists() else {}
    summarise(src, previous, uncal)
    if dry:
        print()
        dim("dry run — nothing written. Re-run without --dry-run to apply.")
        return
    LOCAL_CONFIG.write_text(src)
    print()
    good(f"wrote {LOCAL_CONFIG.name} — {len(entries)} values calibrated"
         + (f", {len(uncal)} left as placeholders" if uncal else ""))
    dim("Next: fill in athlete_profile.template.md — the things data cannot tell")
    dim("a coach (what fails first at max, how you respond to heat, life")
    dim("constraints). Then read coaching_protocol.md.")


if __name__ == "__main__":
    main(sys.argv[1:])
