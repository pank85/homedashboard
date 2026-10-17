"""Tests for app.formatting. Imports only the formatting module."""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.formatting import (  # noqa: E402
    elapsed_from_herdr,
    format_bytes,
    format_duration,
    format_percent,
    format_relative,
    health_label,
    image_short,
    state_label,
)

TIB = 1024**4
NOW = datetime(2024, 6, 1, 0, 0, 12, tzinfo=timezone.utc)


def test_format_bytes_zero():
    assert format_bytes(0) == "0 B"


def test_format_bytes_one_byte_through_1023_stay_in_bytes():
    assert format_bytes(1) == "1 B"
    assert format_bytes(1023) == "1023 B"


def test_format_bytes_1024_is_one_kib():
    assert format_bytes(1024) == "1.0 KiB"


def test_format_bytes_one_decimal_at_each_unit():
    assert format_bytes(1536) == "1.5 KiB"
    assert format_bytes(1024**2) == "1.0 MiB"
    assert format_bytes(1024**3) == "1.0 GiB"
    assert format_bytes(1024**4) == "1.0 TiB"


def test_format_bytes_at_or_above_1024_tib_stays_on_tib():
    assert format_bytes(1024 * TIB) == "1024.0 TiB"
    assert format_bytes(2048 * TIB) == "2048.0 TiB"


def test_format_bytes_bad_values_are_unknown():
    assert format_bytes(None) == "unknown"
    assert format_bytes(True) == "unknown"
    assert format_bytes(False) == "unknown"
    assert format_bytes(-1) == "unknown"
    assert format_bytes("1024") == "unknown"
    assert format_bytes(float("nan")) == "unknown"


def test_format_duration_seconds():
    assert format_duration(42) == "42s"
    assert format_duration(0) == "0s"


def test_format_duration_minutes_with_seconds():
    assert format_duration(90) == "1m 30s"


def test_format_duration_hours_with_minutes():
    assert format_duration(5 * 3600 + 12 * 60) == "5h 12m"


def test_format_duration_days_with_hours():
    assert format_duration(3 * 86400 + 4 * 3600) == "3d 4h"


def test_format_duration_truncates_to_int_seconds():
    assert format_duration(59.9) == "59s"


def test_format_duration_bad_values_are_unknown():
    assert format_duration(None) == "unknown"
    assert format_duration(True) == "unknown"
    assert format_duration(-1) == "unknown"
    assert format_duration("42") == "unknown"


def test_format_percent_is_one_decimal():
    assert format_percent(0) == "0.0%"
    assert format_percent(12.3) == "12.3%"
    assert format_percent(12.25) == "12.3%"


def test_format_percent_bad_values_are_unknown():
    assert format_percent(None) == "unknown"
    assert format_percent(True) == "unknown"
    assert format_percent("12") == "unknown"


def test_format_relative_seconds():
    assert format_relative("2024-06-01T00:00:00Z", now=NOW) == "12s ago"


def test_format_relative_uses_offset_form():
    assert format_relative("2024-06-01T00:00:00+00:00", now=NOW) == "12s ago"


def test_format_relative_minutes_hours_days():
    assert format_relative("2024-05-31T23:59:00Z", now=NOW) == "1m ago"
    assert format_relative("2024-05-31T22:00:00Z", now=NOW) == "2h ago"
    assert format_relative("2024-05-28T00:00:00Z", now=NOW) == "4d ago"


def test_format_relative_future_and_bad_are_unknown():
    assert format_relative("2024-06-01T00:00:13Z", now=NOW) == "unknown"
    assert format_relative(None) == "unknown"
    assert format_relative("not-a-date") == "unknown"
    assert format_relative("") == "unknown"


def test_image_short_elides_registry_and_digest():
    assert image_short("ghcr.io/org/app:1.2") == "app:1.2"
    assert image_short("redis") == "redis"
    assert image_short("localhost:5000/app:1") == "app:1"
    assert image_short("app@sha256:deadbeef") == "app"


def test_image_short_blank_is_empty():
    assert image_short(None) == ""
    assert image_short("") == ""
    assert image_short("   ") == ""


def test_health_label_none_variants():
    assert health_label(None) == "none"
    assert health_label("") == "none"
    assert health_label("none") == "none"
    assert health_label("NULL") == "none"


def test_health_label_word_passes_through():
    assert health_label("healthy") == "healthy"
    assert health_label(" starting ") == "starting"


def test_state_label_blank_is_unknown():
    assert state_label(None) == "unknown"
    assert state_label("") == "unknown"
    assert state_label("running") == "running"


def test_elapsed_from_herdr_seq_is_not_time():
    assert elapsed_from_herdr({"state_change_seq": 5}) == (None, "unknown")


def test_elapsed_from_herdr_ms_durations():
    assert elapsed_from_herdr({"elapsed_ms": 5000}) == (5, "herdr")
    assert elapsed_from_herdr({"duration_ms": 1500}) == (1, "herdr")


def test_elapsed_from_herdr_epoch_timestamp():
    epoch_now = datetime.fromtimestamp(1_700_000_012, tz=timezone.utc)
    assert elapsed_from_herdr({"state_since": 1_700_000_000}, now=epoch_now) == (12, "herdr")


def test_elapsed_from_herdr_small_epoch_is_rejected():
    assert elapsed_from_herdr({"state_since": 1000}) == (None, "unknown")


def test_elapsed_from_herdr_iso_timestamp():
    assert elapsed_from_herdr({"status_since": "2024-06-01T00:00:00Z"}, now=NOW) == (12, "herdr")


def test_elapsed_from_herdr_missing_is_unknown():
    assert elapsed_from_herdr({}) == (None, "unknown")
