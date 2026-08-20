#!/usr/bin/env python3
"""
Formalize the stream extraction that's been hand-typed with jq every ride.

The intervals.icu MCP dumps the full stream (>1MB) to a tool-result temp file
when it exceeds the token limit. This trims it to just the streams we use and
saves to streams/{activity_id}.json.

Usage: python3 extract_stream.py <raw_tool_result_file> <activity_id> [type|env] [trainer]

⚠️ PASS THE TRAINER FLAG when you take the hint from the activity list. A trainer
session recorded on a head unit rather than through Zwift is typed "Ride" by the
platform, and indoor/outdoor use SEPARATE ventilation bands — so the type alone
sends an indoor ride to the outdoor zones. `trainer` accepts 1/true/yes and
forces indoor. Passing "indoor"/"outdoor" directly also works and needs no flag.

The streams-only MCP dump carries no activity type, so pass the type/env you
already see in the activity list (VirtualRide/Ride or indoor/outdoor) as the
optional 3rd arg — it's baked in so analyze.py can auto-detect indoor/outdoor.
"""
import json
import sys
from pathlib import Path
import athlete_config as C
import ridelib as R

KEEP = ["time", "watts", "heartrate", "tidal_volume_min",
        "respiration", "distance", "altitude", "cadence", "velocity_smooth"]
STREAM_DIR = C.STREAM_DIR


def extract(raw_file, activity_id, type_hint=None):
    raw = json.loads(Path(raw_file).read_text())
    # tool-result file is {"result": "<json-string>"}; inner is the MCP payload
    data = json.loads(raw["result"])["data"]
    streams = data.get("streams", {})
    trimmed = {k: streams[k] for k in KEEP if k in streams}
    # explicit hint wins; else whatever the payload carried (activity-details dump)
    atype = R.to_activity_type(type_hint) or data.get("type")
    out = STREAM_DIR / f"{activity_id}.json"
    out.write_text(json.dumps({
        "activity_id": activity_id,
        "activity_type": atype,
        "name": data.get("name"),
        "date": (data.get("start_date_local") or data.get("start_date") or "")[:10],
        "stream_lengths": data.get("stream_lengths", {}),
        "streams": trimmed,
    }))
    ve = trimmed.get("tidal_volume_min")
    n = len(trimmed.get("time", []))
    return out, n, (len(ve) if ve else 0), atype


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4, 5):
        sys.exit("usage: extract_stream.py <raw_tool_result_file> <activity_id> "
                 "[type|env] [trainer]")
    type_hint = sys.argv[3] if len(sys.argv) > 3 else None
    trainer = len(sys.argv) > 4 and sys.argv[4].strip().lower() in ("1", "true", "yes", "trainer")
    if trainer:
        # Resolve to indoor NOW, before it is stored — analyze.py reads the
        # stored activity_type and never sees the flag.
        type_hint = "indoor"
    out, n, ve_n, atype = extract(sys.argv[1], sys.argv[2], type_hint)
    env = R.env_from_type(atype) or "?"
    note = "  (trainer flag → forced indoor)" if trainer else ""
    print(f"saved {out} — {n} samples, VE={ve_n}, type={atype} → {env}{note}")
    if env == "?":
        print("⚠️  environment UNKNOWN — re-run with 'indoor' or 'outdoor' as the "
              "3rd argument, or the ride will be scored against the wrong VE bands")
