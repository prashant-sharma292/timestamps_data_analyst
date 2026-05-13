#!/usr/bin/env python3
"""
Find which phantom timestamps from a matcher result are present in footfall entries.

The footfall export stores event time in UUIDv7-style entry_tracker_id values. This
module decodes those IDs, rounds to the nearest second, and compares them with
Phantom rows from result2.tsv.
"""

import argparse
import csv
from bisect import bisect_left, bisect_right
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_ALL_TIMESTAMPS = "all_timestamps.tsv"
DEFAULT_RESULT = "timestamp_matcher_results.tsv"
DEFAULT_OUTPUT = "phantom_footfall_matches.tsv"
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_TOLERANCE = 1


def parse_time_to_seconds(value):
    """Parse H:MM:SS / HH:MM:SS into seconds since midnight."""
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Cannot parse time: {value}")
    hours, minutes, seconds = (int(part) for part in parts)
    return hours * 3600 + minutes * 60 + seconds


def fmt_time(seconds):
    seconds = int(seconds) % 86400
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def read_table(path):
    """Read CSV or TSV with delimiter auto-detection."""
    with open(path, newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        except csv.Error:
            dialect = csv.excel_tab
        reader = csv.DictReader(f, dialect=dialect)
        return list(reader), reader.fieldnames or []


def uuidv7_time_to_seconds(entry_tracker_id, timezone_name=DEFAULT_TIMEZONE):
    """Decode UUIDv7 milliseconds and return rounded local seconds since midnight."""
    raw = entry_tracker_id.replace("-", "")
    if len(raw) < 12:
        raise ValueError(f"Invalid entry_tracker_id: {entry_tracker_id}")

    timestamp_ms = int(raw[:12], 16)
    tz = ZoneInfo(timezone_name)
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=tz)
    total = dt.hour * 3600 + dt.minute * 60 + dt.second
    if dt.microsecond >= 500_000:
        total += 1
    return total % 86400


def read_footfall_entries(path, timezone_name=DEFAULT_TIMEZONE):
    rows, fieldnames = read_table(path)
    if "entry_tracker_id" not in fieldnames:
        raise ValueError(f"{path} must contain an entry_tracker_id column")

    entries = []
    for row in rows:
        entry_id = row.get("entry_tracker_id", "").strip()
        if not entry_id:
            continue
        seconds = uuidv7_time_to_seconds(entry_id, timezone_name=timezone_name)
        entries.append((seconds, row))
    entries.sort(key=lambda item: item[0])
    return entries, fieldnames


def read_phantom_timestamps(path):
    rows, _fieldnames = read_table(path)
    phantoms = []
    for row in rows:
        truth = row.get("Truth", "").strip().lower()
        timestamp = (row.get("model") or row.get("Model") or row.get("timestamp") or "").strip()
        if truth == "phantom" and timestamp:
            phantoms.append(timestamp)
    return phantoms


def find_matches_for_timestamp(target_seconds, footfall_entries, tolerance):
    seconds_only = [seconds for seconds, _row in footfall_entries]
    left = bisect_left(seconds_only, target_seconds - tolerance)
    right = bisect_right(seconds_only, target_seconds + tolerance)
    return footfall_entries[left:right]


def build_output_rows(footfall_entries, footfall_fieldnames, phantom_timestamps, tolerance):
    output_rows = []
    for timestamp in phantom_timestamps:
        target_seconds = parse_time_to_seconds(timestamp)
        matches = find_matches_for_timestamp(target_seconds, footfall_entries, tolerance)

        if not matches:
            output_rows.append({
                "phantom_timestamp": timestamp,
                "matched": "FALSE",
                "footfall_timestamp": "",
                "delta_seconds": "",
                **{field: "" for field in footfall_fieldnames},
            })
            continue

        for footfall_seconds, footfall_row in matches:
            output_rows.append({
                "phantom_timestamp": timestamp,
                "matched": "TRUE",
                "footfall_timestamp": fmt_time(footfall_seconds),
                "delta_seconds": str(footfall_seconds - target_seconds),
                **{field: footfall_row.get(field, "") for field in footfall_fieldnames},
            })
    return output_rows


def write_output(path, rows, footfall_fieldnames):
    fieldnames = [
        "phantom_timestamp",
        "matched",
        "footfall_timestamp",
        "delta_seconds",
        *footfall_fieldnames,
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def find_phantom_footfall_matches(
    all_timestamps_path=DEFAULT_ALL_TIMESTAMPS,
    result_path=DEFAULT_RESULT,
    output_path=None,
    tolerance=DEFAULT_TOLERANCE,
    timezone_name=DEFAULT_TIMEZONE,
):
    footfall_entries, footfall_fieldnames = read_footfall_entries(
        all_timestamps_path,
        timezone_name=timezone_name,
    )
    phantom_timestamps = read_phantom_timestamps(result_path)
    rows = build_output_rows(
        footfall_entries,
        footfall_fieldnames,
        phantom_timestamps,
        tolerance,
    )
    if output_path:
        write_output(output_path, rows, footfall_fieldnames)
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Check which Phantom timestamps are present in all_timestamps.tsv"
    )
    parser.add_argument(
        "--all-timestamps",
        default=DEFAULT_ALL_TIMESTAMPS,
        help=f"Footfall TSV path (default: {DEFAULT_ALL_TIMESTAMPS})",
    )
    parser.add_argument(
        "--result",
        default=DEFAULT_RESULT,
        help=f"Matcher result TSV/CSV path (default: {DEFAULT_RESULT})",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=DEFAULT_OUTPUT,
        help=f"Output TSV path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--tolerance",
        "-t",
        type=int,
        default=DEFAULT_TOLERANCE,
        help=(
            "Seconds around each Phantom timestamp to accept as present "
            f"(default: {DEFAULT_TOLERANCE})"
        ),
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"Timezone for decoding entry_tracker_id values (default: {DEFAULT_TIMEZONE})",
    )
    args = parser.parse_args()

    rows = find_phantom_footfall_matches(
        all_timestamps_path=Path(args.all_timestamps),
        result_path=Path(args.result),
        output_path=Path(args.output),
        tolerance=args.tolerance,
        timezone_name=args.timezone,
    )
    matched_rows = sum(1 for row in rows if row["matched"] == "TRUE")
    matched_timestamps = {
        row["phantom_timestamp"] for row in rows if row["matched"] == "TRUE"
    }
    unmatched = sum(1 for row in rows if row["matched"] == "FALSE")
    print(f"Matched phantom timestamps: {len(matched_timestamps)}")
    print(f"Footfall match rows: {matched_rows}")
    print(f"Unmatched phantom timestamps: {unmatched}")
    print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()
