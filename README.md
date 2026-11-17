# LishePoa Product Validation

Compares product-label extractions from three models against the ground truth, using regex-based normalization and per-field scoring.

| Input | Role |
|---|---|
| `ground_truth.json` | Reference data (1,501 records) |
| `claude-opus-5-5.json` | Claude Opus 5.5 extraction |
| `gpt-6-sol.json` | GPT-6 Sol extraction |
| `gemini-3.8-flash.json` | Gemini 3.8 Flash extraction |

## Run

```bash
python3 compare.py                   # pass threshold 80% (default)
python3 compare.py --threshold 0.85  # stricter
xdg-open ui/index.html               # open the dashboard (works offline, no server needed)
```

Only Python 3.10+ is required. It uses the standard library only.

## Outputs

- `results/summary.csv`: one row per model with pass rate, mean accuracy, and per-group accuracy
- `results/records.csv`: one row per product × model with score and YES/NO
- `results/comparison.json`: full per-field detail
- `ui/data.js`: data bundle for `ui/index.html`

## How scoring works

Records are matched on `gt_uid`. If there's no exact match, matching falls back to `record_id` (for example, F406 is split in the GT into F406_1 and F406_2).
Each field is normalized with regexes and scored from 0 to 1. Fields are grouped as follows:
Identity 20%, Package 10%, Nutrition basis 10%, Nutrients 40%, Ingredients 15%, Other label info 5%.
A record **passes (YES)** when its weighted score is at or above the threshold. The dashboard's Methodology section has the full rules.
