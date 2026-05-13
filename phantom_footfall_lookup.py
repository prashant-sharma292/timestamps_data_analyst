#!/usr/bin/env python3
"""
Find which final model output timestamps came from Phantom matcher rows.

The footfall export stores event time in UUIDv7-style entry_tracker_id values. This
module decodes those IDs, rounds to the nearest second, and compares each final
output timestamp with the model column in timestamp_matcher_results.tsv.
"""

import argparse
import csv
from bisect import bisect_left, bisect_right
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_ALL_TIMESTAMPS = "all_timestamps.tsv"
DEFAULT_RESULT = "timestamp_matcher_results.tsv"
DEFAULT_OUTPUT = "final_model_phantom_lookup.tsv"
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


def read_matcher_model_entries(path):
    rows, fieldnames = read_table(path)
    if "model" not in fieldnames and "Model" not in fieldnames:
        raise ValueError(f"{path} must contain a model column")

    entries = []
    for row in rows:
        timestamp = (row.get("model") or row.get("Model") or row.get("timestamp") or "").strip()
        if not timestamp:
            continue
        entries.append((parse_time_to_seconds(timestamp), timestamp, row))
    entries.sort(key=lambda item: item[0])
    return entries


def find_matches_for_timestamp(target_seconds, matcher_entries, tolerance):
    seconds_only = [seconds for seconds, _timestamp, _row in matcher_entries]
    left = bisect_left(seconds_only, target_seconds - tolerance)
    right = bisect_right(seconds_only, target_seconds + tolerance)
    return matcher_entries[left:right]


def choose_closest_match(target_seconds, matcher_entries):
    return min(
        matcher_entries,
        key=lambda item: (abs(item[0] - target_seconds), item[1]),
    )


def build_output_rows(footfall_entries, footfall_fieldnames, matcher_entries, tolerance):
    output_rows = []
    for footfall_seconds, footfall_row in footfall_entries:
        final_timestamp = fmt_time(footfall_seconds)
        matches = find_matches_for_timestamp(footfall_seconds, matcher_entries, tolerance)

        if not matches:
            output_rows.append({
                "final_output_timestamp": final_timestamp,
                "matched_model": "FALSE",
                "matched_model_timestamp": "",
                "matcher_truth": "",
                "is_phantom": "FALSE",
                "delta_seconds": "",
                "matcher_gt": "",
                "matcher_offset": "",
                **{field: footfall_row.get(field, "") for field in footfall_fieldnames},
            })
            continue

        matched_seconds, matched_timestamp, matcher_row = choose_closest_match(
            footfall_seconds,
            matches,
        )
        truth = matcher_row.get("Truth", "").strip()
        output_rows.append({
            "final_output_timestamp": final_timestamp,
            "matched_model": "TRUE",
            "matched_model_timestamp": matched_timestamp,
            "matcher_truth": truth,
            "is_phantom": "TRUE" if truth.lower() == "phantom" else "FALSE",
            "delta_seconds": str(footfall_seconds - matched_seconds),
            "matcher_gt": matcher_row.get("GT", ""),
            "matcher_offset": matcher_row.get("Offset", ""),
            **{field: footfall_row.get(field, "") for field in footfall_fieldnames},
        })
    return output_rows


def write_output(path, rows, footfall_fieldnames):
    fieldnames = [
        "final_output_timestamp",
        "matched_model",
        "matched_model_timestamp",
        "matcher_truth",
        "is_phantom",
        "delta_seconds",
        "matcher_gt",
        "matcher_offset",
        *footfall_fieldnames,
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def find_final_output_phantoms(
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
    matcher_entries = read_matcher_model_entries(result_path)
    rows = build_output_rows(
        footfall_entries,
        footfall_fieldnames,
        matcher_entries,
        tolerance,
    )
    if output_path:
        write_output(output_path, rows, footfall_fieldnames)
    return rows


find_phantom_footfall_matches = find_final_output_phantoms


def main():
    parser = argparse.ArgumentParser(
        description="Check which final model output timestamps came from Phantom rows"
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
            "Seconds around each final output timestamp to match against model rows "
            f"(default: {DEFAULT_TOLERANCE})"
        ),
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"Timezone for decoding entry_tracker_id values (default: {DEFAULT_TIMEZONE})",
    )
    args = parser.parse_args()

    rows = find_final_output_phantoms(
        all_timestamps_path=Path(args.all_timestamps),
        result_path=Path(args.result),
        output_path=Path(args.output),
        tolerance=args.tolerance,
        timezone_name=args.timezone,
    )
    matched_model_rows = sum(1 for row in rows if row["matched_model"] == "TRUE")
    phantom_final_rows = sum(1 for row in rows if row["is_phantom"] == "TRUE")
    unmatched_model_rows = sum(1 for row in rows if row["matched_model"] == "FALSE")
    print(f"Final output entries: {len(rows)}")
    print(f"Matched to model timestamps: {matched_model_rows}")
    print(f"Final output entries marked Phantom: {phantom_final_rows}")
    print(f"Final output entries without model match: {unmatched_model_rows}")
    print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()
