# Timestamp Data Analyst

Matches ground truth (GT) timestamps against model output timestamps to compute precision and recall. Each timestamp is classified as TP (True Positive), Missing (False Negative), or Phantom (False Positive).

## How it works

1. Reads two independent lists of timestamps (`GT` and `model`) from an input file
2. Sorts both lists independently
3. Greedily matches each GT timestamp to the first available model timestamp within the tolerance window
4. Unmatched GT timestamps are marked **Missing**, unmatched model timestamps are marked **Phantom**
5. Outputs a result CSV with all classifications and offsets

## Input format

The input file needs two columns: `GT` and `model`, with timestamps in `HH:MM:SS` format. Both CSV and TSV are supported (auto-detected).

You can copy directly from Google Sheets and paste into a `.tsv` file:

```
GT	model
10:24:41	10:24:42
10:32:52	10:32:32
10:33:46	10:32:53
```

Rows can have only a GT value or only a model value — they don't need to be paired.

## Usage

```bash
uv run timestamp_matcher.py report.tsv --tolerance 5 -o result.csv
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--tolerance`, `-t` | 30 | Max seconds difference to count as a match |
| `--output`, `-o` | result.csv | Output CSV path |

## Output

The result CSV has four columns:

| Column | Description |
|--------|-------------|
| GT | Ground truth timestamp (empty for Phantoms) |
| model | Model timestamp (empty for Missing) |
| Truth | Classification: `TP`, `Missing`, or `Phantom` |
| Offset | Time difference for TP matches (model - GT) |

## Phantom footfall lookup

Use `phantom_footfall_lookup.py` to check whether `Phantom` timestamps from a matcher result are present in the footfall export.

Recommended input names:

- `all_timestamps.tsv`: footfall export with `entry_tracker_id`
- `timestamp_matcher_results.tsv`: matcher output containing `Truth = Phantom` rows

```bash
python3 phantom_footfall_lookup.py
```

By default this writes `phantom_footfall_matches.tsv` and uses a 1-second tolerance.
Override `--tolerance` for wider near matches:

```bash
python3 phantom_footfall_lookup.py --tolerance 5 -o phantom_footfall_matches_tolerance_5s.tsv
```
