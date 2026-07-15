#!/usr/bin/env python3
"""
Timestamp matcher: Compares GT and model timestamps directly.
Matches within a tolerance window, classifies as TP / Missing / Phantom.

Usage:
    python timestamp_matcher.py input.tsv --tolerance 5 --output result.csv
"""

import argparse
import csv


def parse_time(s):
    """Parse HH:MM:SS or H:MM:SS string to total seconds since midnight."""
    s = s.strip()
    parts = s.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 3600 + int(parts[1]) * 60
    raise ValueError(f"Cannot parse time: {s}")


def fmt_time(secs):
    """Format total seconds back to HH:MM:SS."""
    h = int(secs) // 3600
    m = (int(secs) % 3600) // 60
    s = int(secs) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_offset(secs):
    """Format an offset (seconds) as HH:MM:SS, with sign for negatives."""
    sign = "-" if secs < 0 else ""
    a = abs(int(secs))
    return f"{sign}{a // 3600:02d}:{(a % 3600) // 60:02d}:{a % 60:02d}"


def read_input(path):
    """Read CSV or TSV (auto-detected) and return two sorted lists of timestamps (in seconds)."""
    gt_times = []
    model_times = []
    with open(path, newline="") as f:
        sample = f.read(1024)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
        reader = csv.DictReader(f, dialect=dialect)
        for row in reader:
            gt_val = row.get("GT", "").strip()
            model_val = (row.get("model") or row.get("Model") or "").strip()
            if gt_val:
                gt_times.append(parse_time(gt_val))
            if model_val:
                model_times.append(parse_time(model_val))
    gt_times.sort()
    model_times.sort()
    return gt_times, model_times


def match_timestamps(gt_times, model_times, buffer):
    """
    Order-preserving sequential match: walk both sorted lists top-to-bottom.
    Pair the current GT and model if within tolerance; otherwise advance past
    the earlier of the two (it stays unmatched), keeping the sequence aligned.
    """
    tp_pairs = []
    missing = []
    phantoms = []
    gi = mi = 0
    while gi < len(gt_times) and mi < len(model_times):
        diff = model_times[mi] - gt_times[gi]
        if abs(diff) <= buffer:
            tp_pairs.append((gi, mi))
            gi += 1
            mi += 1
        elif gt_times[gi] < model_times[mi]:
            missing.append(gi)  # GT is the earlier one, too far to match
            gi += 1
        else:
            phantoms.append(mi)  # model is the earlier one, too far to match
            mi += 1

    # Once one list is exhausted, everything left over is unmatched
    missing.extend(range(gi, len(gt_times)))
    phantoms.extend(range(mi, len(model_times)))

    return tp_pairs, phantoms, missing


def run(input_path, output_path, buffer):
    gt_times, model_times = read_input(input_path)

    print(f"Loaded {len(gt_times)} GT timestamps, {len(model_times)} model timestamps")
    print(f"Buffer: {buffer}s")

    print()
    tp_pairs, phantoms, missing = match_timestamps(gt_times, model_times, buffer)

    n_tp = len(tp_pairs)
    n_phantom = len(phantoms)
    n_missing = len(missing)
    print(f"Results:")
    print(f"  raw_entries_GT:      {len(gt_times)}")
    print(f"  raw_entries_model:   {len(model_times)}")
    print(f"  TP (True Positive):  {n_tp}")
    print(f"  Phantom (FP):        {n_phantom}")
    print(f"  Missing (FN):        {n_missing}")
    if n_tp + n_phantom > 0:
        print(f"  Precision:           {n_tp / (n_tp + n_phantom) * 100:.1f}%")
    if n_tp + n_missing > 0:
        print(f"  Recall:              {n_tp / (n_tp + n_missing) * 100:.1f}%")

    # Build output rows
    rows = []
    for gi, mi in tp_pairs:
        offset = model_times[mi] - gt_times[gi]
        row = {
            "GT": fmt_time(gt_times[gi]),
            "model": fmt_time(model_times[mi]),
            "Truth": "TP",
            "Offset": fmt_offset(offset),
        }
        rows.append(row)
    for gi in missing:
        rows.append({
            "GT": fmt_time(gt_times[gi]),
            "model": "",
            "Truth": "Missing",
            "Offset": "",
        })
    for mi in phantoms:
        rows.append({
            "GT": "",
            "model": fmt_time(model_times[mi]),
            "Truth": "Phantom",
            "Offset": "",
        })

    def sort_key(row):
        times = []
        if row["GT"]:
            times.append(parse_time(row["GT"]))
        if row["model"]:
            times.append(parse_time(row["model"]))
        return min(times)

    rows.sort(key=sort_key)

    fieldnames = ["GT", "model", "Truth", "Offset"]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nOutput written to: {output_path}")
    print(f"\nGoogle Sheets formula for Truth column (paste in C2 and drag down):")
    print(f'  =IF(AND(A2<>"",B2<>""),"TP",IF(A2<>"","Missing",IF(B2<>"","Phantom","")))')


def main():
    parser = argparse.ArgumentParser(
        description="Match GT and model timestamps by direct comparison"
    )
    parser.add_argument("input", help="Input file with GT and model columns (CSV or TSV from Google Sheets paste)")
    parser.add_argument(
        "--tolerance", "-t", type=int, default=30,
        help="Max seconds difference between GT and model to count as match (default: 30)"
    )
    parser.add_argument(
        "--output", "-o", default="result.csv",
        help="Output CSV path (default: result.csv)"
    )
    args = parser.parse_args()
    run(args.input, args.output, args.tolerance)


if __name__ == "__main__":
    main()
