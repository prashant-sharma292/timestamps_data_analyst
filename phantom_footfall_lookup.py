#!/usr/bin/env python3
"""Find which Phantom timestamps are present in final model output timestamps."""

import argparse
import csv
from bisect import bisect_left, bisect_right
from pathlib import Path


DEFAULT_INPUT = "phantom_final_timestamps.tsv"
DEFAULT_OUTPUT = "phantoms_in_final_output.tsv"
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


def find_column(fieldnames, candidates):
    normalized = {field.lower(): field for field in fieldnames}
    for candidate in candidates:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]
    return None


def read_timestamp_lists(path):
    rows, fieldnames = read_table(path)
    phantom_column = find_column(fieldnames, [
        "phantom_timestamp",
        "phantom",
        "phantom_time",
    ])
    final_column = find_column(fieldnames, [
        "final_output_timestamp",
        "final_timestamp",
        "final_timestamps",
        "final_time",
    ])

    if not phantom_column or not final_column:
        raise ValueError(
            f"{path} must contain phantom_timestamp and final_output_timestamp columns"
        )

    phantom_entries = []
    final_entries = []
    for row in rows:
        phantom_timestamp = row.get(phantom_column, "").strip()
        final_timestamp = row.get(final_column, "").strip()
        if phantom_timestamp:
            phantom_entries.append((
                parse_time_to_seconds(phantom_timestamp),
                phantom_timestamp,
            ))
        if final_timestamp:
            final_entries.append((
                parse_time_to_seconds(final_timestamp),
                final_timestamp,
            ))

    phantom_entries.sort(key=lambda item: item[0])
    final_entries.sort(key=lambda item: item[0])
    return phantom_entries, final_entries


def match_phantoms_to_final_outputs(phantom_entries, final_entries, tolerance):
    """Globally match each Phantom to the closest available final output entry."""
    final_seconds = [seconds for seconds, _timestamp in final_entries]
    candidates = []
    for phantom_index, (phantom_seconds, _timestamp) in enumerate(phantom_entries):
        left = bisect_left(final_seconds, phantom_seconds - tolerance)
        right = bisect_right(final_seconds, phantom_seconds + tolerance)
        for final_index in range(left, right):
            diff = abs(phantom_seconds - final_seconds[final_index])
            candidates.append((diff, phantom_index, final_index))

    candidates.sort()
    matched_phantoms = {}
    used_finals = set()
    for _diff, phantom_index, final_index in candidates:
        if phantom_index in matched_phantoms or final_index in used_finals:
            continue
        matched_phantoms[phantom_index] = final_index
        used_finals.add(final_index)
    return matched_phantoms


def build_output_rows(phantom_entries, final_entries, tolerance):
    matched_phantoms = match_phantoms_to_final_outputs(
        phantom_entries,
        final_entries,
        tolerance,
    )
    output_rows = []
    for phantom_index, (phantom_seconds, phantom_timestamp) in enumerate(phantom_entries):
        final_index = matched_phantoms.get(phantom_index)
        if final_index is None:
            output_rows.append({
                "phantom_timestamp": phantom_timestamp,
                "present_in_final_output": "FALSE",
                "final_output_timestamp": "",
                "delta_seconds": "",
            })
            continue

        final_seconds, final_timestamp = final_entries[final_index]
        output_rows.append({
            "phantom_timestamp": phantom_timestamp,
            "present_in_final_output": "TRUE",
            "final_output_timestamp": final_timestamp,
            "delta_seconds": str(final_seconds - phantom_seconds),
        })
    return output_rows


def write_output(path, rows):
    fieldnames = [
        "phantom_timestamp",
        "present_in_final_output",
        "final_output_timestamp",
        "delta_seconds",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def find_phantoms_in_final_output(
    input_path=DEFAULT_INPUT,
    output_path=None,
    tolerance=DEFAULT_TOLERANCE,
):
    phantom_entries, final_entries = read_timestamp_lists(input_path)
    rows = build_output_rows(
        phantom_entries,
        final_entries,
        tolerance,
    )
    if output_path:
        write_output(output_path, rows)
    return rows


find_phantom_footfall_matches = find_phantoms_in_final_output


def main():
    parser = argparse.ArgumentParser(
        description="Check which Phantom raw model timestamps are present in final output"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Input TSV path (default: {DEFAULT_INPUT})",
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
    args = parser.parse_args()

    rows = find_phantoms_in_final_output(
        input_path=Path(args.input),
        output_path=Path(args.output),
        tolerance=args.tolerance,
    )
    present = sum(1 for row in rows if row["present_in_final_output"] == "TRUE")
    missing = sum(1 for row in rows if row["present_in_final_output"] == "FALSE")
    print(f"Phantom timestamps: {len(rows)}")
    print(f"Phantoms present in final output: {present}")
    print(f"Phantoms not present in final output: {missing}")
    print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()
