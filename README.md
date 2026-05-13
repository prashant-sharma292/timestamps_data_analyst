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

## Phantom final-output lookup

Use `phantom_footfall_lookup.py` to check which raw model timestamps marked `Phantom` are still present in the final model output.

Create one input file:

- `phantom_final_timestamps.tsv`: two-column TSV containing Phantom timestamps and final output timestamps

```tsv
phantom_timestamp	final_output_timestamp
12:34:48	12:34:45
12:57:22	12:57:19
13:02:21	
```

Rows do not need to be paired. The script reads all values from both columns independently, then matches each Phantom timestamp to the closest available final output timestamp within tolerance.

Run:

```bash
uv run phantom_footfall_lookup.py phantom_final_timestamps.tsv
```

By default this writes `phantoms_in_final_output.tsv` and uses a 5-second tolerance.
The output has one row per `Phantom` timestamp. `present_in_final_output = TRUE`
means that raw Phantom timestamp matched a final output timestamp.

Override `--tolerance` for wider near matches:

```bash
uv run phantom_footfall_lookup.py phantom_final_timestamps.tsv --tolerance 10 -o phantoms_in_final_output_10s.tsv
```
