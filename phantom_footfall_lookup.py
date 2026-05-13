#!/usr/bin/env python3
"""
Find which Phantom raw model timestamps are present in final model output.

The footfall export stores event time in UUIDv7-style entry_tracker_id values. This
module decodes those IDs, rounds to the nearest second, and compares them with
the Phantom rows from timestamp_matcher_results.tsv.
"""

import argparse
import csv
from bisect import bisect_left, bisect_right
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_ALL_TIMESTAMPS = "all_timestamps.tsv"
DEFAULT_RESULT = "timestamp_matcher_results.tsv"
DEFAULT_OUTPUT = "phantoms_in_final_output.tsv"
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_TOLERANCE = 5


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


def read_phantom_entries(path):
    rows, fieldnames = read_table(path)
    if "model" not in fieldnames and "Model" not in fieldnames:
        raise ValueError(f"{path} must contain a model column")

    entries = []
    for row in rows:
        truth = row.get("Truth", "").strip().lower()
        timestamp = (row.get("model") or row.get("Model") or row.get("timestamp") or "").strip()
        if truth != "phantom" or not timestamp:
            continue
        entries.append((parse_time_to_seconds(timestamp), timestamp, row))
    entries.sort(key=lambda item: item[0])
    return entries


def match_phantoms_to_final_outputs(phantom_entries, footfall_entries, tolerance):
    """Globally match each Phantom to the closest available final output entry."""
    footfall_seconds = [seconds for seconds, _row in footfall_entries]
    candidates = []
    for phantom_index, (phantom_seconds, _timestamp, _row) in enumerate(phantom_entries):
        left = bisect_left(footfall_seconds, phantom_seconds - tolerance)
        right = bisect_right(footfall_seconds, phantom_seconds + tolerance)
        for footfall_index in range(left, right):
            diff = abs(phantom_seconds - footfall_seconds[footfall_index])
            candidates.append((diff, phantom_index, footfall_index))

    candidates.sort()
    matched_phantoms = {}
    used_footfalls = set()
    for _diff, phantom_index, footfall_index in candidates:
        if phantom_index in matched_phantoms or footfall_index in used_footfalls:
            continue
        matched_phantoms[phantom_index] = footfall_index
        used_footfalls.add(footfall_index)
    return matched_phantoms


def build_output_rows(phantom_entries, footfall_entries, footfall_fieldnames, tolerance):
    matched_phantoms = match_phantoms_to_final_outputs(
        phantom_entries,
        footfall_entries,
        tolerance,
    )
    output_rows = []
    for phantom_index, (phantom_seconds, phantom_timestamp, phantom_row) in enumerate(phantom_entries):
        footfall_index = matched_phantoms.get(phantom_index)
        if footfall_index is None:
            output_rows.append({
                "phantom_timestamp": phantom_timestamp,
                "present_in_final_output": "FALSE",
                "final_output_timestamp": "",
                "delta_seconds": "",
                "matcher_gt": phantom_row.get("GT", ""),
                "matcher_offset": phantom_row.get("Offset", ""),
                **{field: "" for field in footfall_fieldnames},
            })
            continue

        footfall_seconds, footfall_row = footfall_entries[footfall_index]
        output_rows.append({
            "phantom_timestamp": phantom_timestamp,
            "present_in_final_output": "TRUE",
            "final_output_timestamp": fmt_time(footfall_seconds),
            "delta_seconds": str(footfall_seconds - phantom_seconds),
            "matcher_gt": phantom_row.get("GT", ""),
            "matcher_offset": phantom_row.get("Offset", ""),
            **{field: footfall_row.get(field, "") for field in footfall_fieldnames},
        })
    return output_rows


def write_output(path, rows, footfall_fieldnames):
    fieldnames = [
        "phantom_timestamp",
        "present_in_final_output",
        "final_output_timestamp",
        "delta_seconds",
        "matcher_gt",
        "matcher_offset",
        *footfall_fieldnames,
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def find_phantoms_in_final_output(
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
    phantom_entries = read_phantom_entries(result_path)
    rows = build_output_rows(
        phantom_entries,
        footfall_entries,
        footfall_fieldnames,
        tolerance,
    )
    if output_path:
        write_output(output_path, rows, footfall_fieldnames)
    return rows


find_phantom_footfall_matches = find_phantoms_in_final_output


def main():
    parser = argparse.ArgumentParser(
        description="Check which Phantom raw model timestamps are present in final output"
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
            "Seconds around each Phantom timestamp to match final output entries "
            f"(default: {DEFAULT_TOLERANCE})"
        ),
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"Timezone for decoding entry_tracker_id values (default: {DEFAULT_TIMEZONE})",
    )
    args = parser.parse_args()

    rows = find_phantoms_in_final_output(
        all_timestamps_path=Path(args.all_timestamps),
        result_path=Path(args.result),
        output_path=Path(args.output),
        tolerance=args.tolerance,
        timezone_name=args.timezone,
    )
    present = sum(1 for row in rows if row["present_in_final_output"] == "TRUE")
    missing = sum(1 for row in rows if row["present_in_final_output"] == "FALSE")
    print(f"Phantom timestamps: {len(rows)}")
    print(f"Phantoms present in final output: {present}")
    print(f"Phantoms not present in final output: {missing}")
    print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()
