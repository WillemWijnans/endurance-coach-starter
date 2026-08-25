#!/usr/bin/env python3
"""Tests for check_log — the reconciliation that would have caught three rides
sitting unlogged on disk for weeks."""
import csv
import check_log as K
import athlete_config as C


def _write_log(tmp_path, rows, monkeypatch):
    log = tmp_path / "log.csv"
    cols = ["activity_id", "date", "np"]
    with log.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    monkeypatch.setattr(C, "MASTER_LOG", log)
    return log


def _write_streams(tmp_path, ids, monkeypatch):
    d = tmp_path / "streams"
    d.mkdir(exist_ok=True)
    for i in ids:
        (d / f"{i}.json").write_text("{}")
    monkeypatch.setattr(C, "STREAM_DIR", d)
    return d


def test_clean_state_reports_ok(tmp_path, monkeypatch):
    _write_streams(tmp_path, ["i1", "i2"], monkeypatch)
    _write_log(tmp_path, [{"activity_id": "i1", "date": "2026-01-01", "np": "200"},
                          {"activity_id": "i2", "date": "2026-01-02", "np": "210"}], monkeypatch)
    assert K.orphan_streams() == []
    assert K.missing_streams() == []
    assert K.undated_rows() == []
    assert K.report() is True


def test_detects_the_real_failure_a_stream_with_no_row(tmp_path, monkeypatch):
    """The exact bug: stream on disk, no row, nothing errors, data invisible."""
    _write_streams(tmp_path, ["i1", "i2", "i3"], monkeypatch)
    _write_log(tmp_path, [{"activity_id": "i1", "date": "2026-01-01", "np": "200"}], monkeypatch)
    assert K.orphan_streams() == ["i2", "i3"]
    assert K.report() is False


def test_detects_a_row_whose_stream_vanished(tmp_path, monkeypatch):
    _write_streams(tmp_path, ["i1"], monkeypatch)
    _write_log(tmp_path, [{"activity_id": "i1", "date": "2026-01-01", "np": "200"},
                          {"activity_id": "i9", "date": "2026-01-02", "np": "210"}], monkeypatch)
    assert K.missing_streams() == ["i9"]
    assert K.report() is False


def test_detects_undated_rows(tmp_path, monkeypatch):
    _write_streams(tmp_path, ["i1"], monkeypatch)
    _write_log(tmp_path, [{"activity_id": "i1", "date": "", "np": "200"}], monkeypatch)
    assert K.undated_rows() == ["i1"]
    assert K.report() is False


def test_missing_log_file_is_not_a_crash(tmp_path, monkeypatch):
    _write_streams(tmp_path, ["i1"], monkeypatch)
    monkeypatch.setattr(C, "MASTER_LOG", tmp_path / "nope.csv")
    assert K.logged_ids() == set()
    assert K.orphan_streams() == ["i1"]


def test_empty_everything(tmp_path, monkeypatch):
    _write_streams(tmp_path, [], monkeypatch)
    _write_log(tmp_path, [], monkeypatch)
    assert K.report() is True
