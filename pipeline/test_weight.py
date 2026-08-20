#!/usr/bin/env python3
"""Tests for weight.py. Run: python3 test_weight.py"""
import weight as W


def test_lean_fat_basic():
    lean, fat = W.lean_fat(80.0, 15.0)
    assert abs(fat - 12.0) < 1e-9
    assert abs(lean - 68.0) < 1e-9

def test_lean_fat_none():
    assert W.lean_fat(80.0, None) == (None, None)
    assert W.lean_fat(None, 15.0) == (None, None)

def test_rolling_avg_smooths_spike():
    # 5 steady at 78, then a 82 spike → rolling avg должен be < 82 (dampened)
    rows = [{"date": f"2026-01-0{i+1}", "weight_kg": 78.0, "bf_pct": None, "eftp": None}
            for i in range(5)]
    rows.append({"date": "2026-01-06", "weight_kg": 82.0, "bf_pct": None, "eftp": None})
    ra = W.rolling_avg(rows, window=7)
    last_avg = ra[-1][2]
    # avg of [78,78,78,78,78,82] = 78.67, well below the 82 spike
    assert 78 < last_avg < 79, f"avg={last_avg}"

def test_rolling_avg_window_limits():
    # window=3: only last 3 count
    rows = [{"date": f"2026-01-0{i+1}", "weight_kg": w, "bf_pct": None, "eftp": None}
            for i, w in enumerate([70, 72, 74, 76, 78])]
    ra = W.rolling_avg(rows, window=3)
    # last avg = mean(74,76,78) = 76
    assert abs(ra[-1][2] - 76.0) < 1e-9

def test_rolling_avg_ignores_missing_weight():
    rows = [
        {"date": "2026-01-01", "weight_kg": 78.0, "bf_pct": None, "eftp": None},
        {"date": "2026-01-02", "weight_kg": None, "bf_pct": None, "eftp": None},  # estimate row
        {"date": "2026-01-03", "weight_kg": 80.0, "bf_pct": None, "eftp": None},
    ]
    ra = W.rolling_avg(rows, window=7)
    assert len(ra) == 2  # only the 2 real weigh-ins
    assert abs(ra[-1][2] - 79.0) < 1e-9  # mean(78,80)


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    p = f = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); p += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}"); f += 1
    print(f"\n{p} passed, {f} failed")
    sys.exit(1 if f else 0)
