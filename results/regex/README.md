# ① Regex comparison: results

This folder holds everything the **regex comparison** (`compare.py`) produces. It compares each model's output against `data/ground_truth.json`, field by field, using regular expressions to normalize text and numbers.

| Model | Output file compared |
|---|---|
| GPT-6-Sol | `data/gpt-6-sol.json` |
| Gemini 3.8 Flash | `data/gemini-3.8-flash.json` |
| Claude Opus 5.5 | `data/claude-opus-5-5.json` |

Rebuild everything in this folder, plus the dashboard `site/regex.html`, with:

```bash
python3 compare.py                    # pass threshold 80% (default)
python3 compare.py --threshold 0.85   # stricter pass mark
```

Files here are overwritten on every run, except this README.

---

## The files

| File | Format | One row / entry per | Use it for |
|---|---|---|---|
| `summary.csv` | CSV | model (3 rows) | the headline numbers: pass rate, mean score, the six category scores |
| `records.csv` | CSV | product × model (1,501 × 3 = 4,503 rows) | each product's score, YES/NO and category scores, in a spreadsheet |
| `comparison.json` | JSON | everything | the full detail: every field's ground-truth value, model value, score and status. The dashboards are built from this. |
| `regex_summary.json` | JSON | model | a small summary (no per-product data) for the Overview page |

All scores are **fractions from 0 to 1**. Multiply by 100 for a percentage (`0.876` = 87.6%).

---

## How a product is scored

Scoring happens at three levels: **field → category → product**.

### 1. Field score (0–1)

Each field is compared with its own rule:

| Field | Category | Weight in category | Rule |
|---|---|---|---|
| Product name | Identity | 6 | Word order ignored. 0.6 × share of ground-truth words found + 0.4 × word overlap (Dice). Same words in any order = 1. |
| Brand | Identity | 5 | As name, after removing legal suffixes (Ltd, Limited, PLC, Inc…) and address tails ("…, P.O BOX 558, NAKURU"). |
| Manufacturer | Identity | 2 | Same as brand. |
| Category | Identity | 3 | Exact match after normalization: 1 or 0. |
| Country of origin | Identity | 1 | Exact after aliases (USA = United States, UK = United Kingdom, Türkiye = Turkey, "Made in Kenya" = Kenya…): 1 or 0. |
| Barcode | Identity | 3 | Digits only, leading zeros ignored (UPC-A = EAN-13). Same code = 1. Off only by a check digit = 0.75. Otherwise 0. |
| Package size | Package | 4 | Number, converted to a base unit (kg → g, l → ml). See *numbers* below. |
| Package unit | Package | 2 | Exact after normalizing units (`ML` = `ml`, `ltr` = `l`): 1 or 0. |
| Package count | Package | 1 | Number. |
| Package type | Package | 2 | Short text: 0.5 × word overlap + 0.5 × character similarity. Exact = 1. |
| Nutrition basis type | Nutrition basis | 5 | "per 100 g / per 100 ml / per serving", exact: 1 or 0. |
| Nutrition basis amount | Nutrition basis | 2 | Number. |
| Serving size amount | Nutrition basis | 2 | Number. |
| Serving size unit | Nutrition basis | 1 | Unit, exact: 1 or 0. |
| Each nutrient | Nutrients | 1 each | See *nutrients* below. |
| Ingredient list | Ingredients | 1 | 0.55 × word overlap + 0.25 × order/character similarity + 0.20 × share of the ground truth's E-numbers and percentages found. With no E-numbers or percentages, the first two parts are scaled up to 100%. |
| Other label information | Other label info | 1 | Share of ground-truth words found in the model's text. Extra text from the model is **not** penalized, because people typed only part of the label. |

**Numbers** (package size, amounts, nutrients):

| Difference from ground truth | Score |
|---|---|
| within 2% (or ±0.05) | **1.0** |
| within 10% (or ±0.1) | **0.5** |
| more than 10% | **0** |

Before comparing, text is normalized with regex: case, spacing, punctuation, `&`/`and`, decimal commas (`1,5` = `1.5`), `E 330` = `E330`, `Per 100ml` = `PER 100 ML`.

**Nutrients:**

- **Number:** each nutrient's value is scored with the number rule above.
- **Ranges:** both ends must match. A range on one side only scores 0.25.
- **Percent vs grams:** if one side says `20%` and the other `0.2` or `20 g`, whichever reading matches counts.
- **Bound mismatch:** if one side has a bound (`<`, `>`, `min`, `max`) and the other doesn't, the score drops by 0.25. `nil` and `not detected` count as plain values.
- **Text-only values** (`trace`, `present`): exact text match, 1 or 0.

**Missing and extra values:**

| Ground truth | Model | Status | Score |
|---|---|---|---|
| has value | same value | `match` | ≥ 0.95 |
| has value | close | `partial` | 0.5–0.95 |
| has value | wrong | `mismatch` | < 0.5 |
| has value | empty | `missing` | **0** |
| empty | has value (normal field) | `extra` | not scored (the ground truth may simply lack it) |
| empty | has value (**nutrient**) | `extra` | **0** (invented nutrient). Run `--no-penalise-extra` to skip these instead. |
| empty | empty | — | not scored |

### 2. Category score (0–1)

The **weighted average of its fields' scores**, using the field weights in the table above. For example, Identity = (6 × name + 5 × brand + 2 × manufacturer + 3 × category + 1 × country + 3 × barcode) ÷ (sum of weights of the fields that were scored). For nutrients, each nutrient counts equally.

If no field in a category has data, the category is **blank** (not scored).

### 3. Product score (0–1) and PASS

The **weighted average of the six category scores**:

| Category | Weight |
|---|---|
| Identity | **20%** |
| Package | **10%** |
| Nutrition basis | **10%** |
| Nutrients | **40%** |
| Ingredients | **15%** |
| Other label information | **5%** |
| **Total** | **100%** |

Blank categories are left out, and the remaining weights are scaled up to 100%.

A product **PASSES (YES)** when its score is **at least the threshold (default 0.80)**, otherwise **NO**.

**Worked example 1: J033 Corn flakes, GPT-6-Sol.** Category scores: identity 1.0, package 1.0, basis 1.0, nutrients 0.7778, ingredients 0, label 1.0.
(1.0×20 + 1.0×10 + 1.0×10 + 0.7778×40 + 0×15 + 1.0×5) ÷ 100 = **0.7611** → below 0.80 → **NO**.

**Worked example 2: J003 Meat masala, GPT-6-Sol.** `label` is blank, so its 5% is left out:
(0.6429×20 + 1.0×10 + 1.0×10 + 1.0×40 + 0.9715×15) ÷ 95 = **0.9203** → **YES**.

---

## `summary.csv`: one row per model

| Column | Meaning |
|---|---|
| `model` | Model name |
| `matched` | Products compared (1,500: every ground-truth product except the empty F406_1) |
| `passed` / `failed` | Products with score ≥ threshold / below it |
| `pass_rate` | `passed ÷ matched` |
| `mean_score` | Average product score |
| `identity` … `label` | Average category score over products where that category has data |

Current results (threshold 0.80):

| Model | Pass rate | Mean score | Identity | Package | Basis | Nutrients | Ingredients | Label |
|---|---|---|---|---|---|---|---|---|
| GPT-6-Sol | 87.6% | 89.9% | 82.3% | 83.3% | 95.0% | 95.6% | 86.5% | 84.0% |
| Gemini 3.8 Flash | 92.9% | 91.8% | 83.9% | 85.6% | 96.9% | 96.6% | 90.8% | 87.4% |
| Claude Opus 5.5 | 92.7% | 91.5% | 83.8% | 84.4% | 96.3% | 96.2% | 91.0% | 89.6% |

## `records.csv`: one row per product × model

| Column | Meaning |
|---|---|
| `gt_uid` | Ground-truth UID (the match key) |
| `product`, `brand` | From the **ground truth**, so they are the same on all three rows of a product |
| `model` | Which model the row scores |
| `score` | Product score, 0–1 |
| `pass` | `YES` (≥ threshold), `NO` (below), or `MISSING` (no model output to compare) |
| `identity`, `package`, `basis`, `nutrients`, `ingredients`, `label` | Category scores, 0–1. **Blank = nothing to compare in that category, not zero.** |

Notes:

- The 3 `MISSING` rows are **F406_1**. The ground truth splits F406 into an empty F406_1 and F406_2 (Tropicana Slim). The models have one F406, which is scored against F406_2.
- When averaging a category in a spreadsheet, skip blanks rather than counting them as 0.
- Filter `model` + `pass = NO` to list each model's failures.

## `comparison.json`: full detail

```text
{
  "meta": {
    "models": [...], "threshold": 0.8,
    "group_weights": {"identity": 20, "package": 10, ...},
    "gt_records": 1501, "penalise_extra_nutrients": true, ...
  },
  "summary": {
    "<model>": {
      "matched", "passed", "failed", "pass_rate", "mean_score",
      "groups": {category: average score},
      "fields": {"product.name": {"accuracy": 0.82, "n": 1498}, "nutrients.protein_g": {...}, ...},
      "field_status": {"match": n, "partial": n, "mismatch": n, "missing": n, "extra": n},
      "match_log": {...}, "unmatched_model_ids": [...]
    }
  },
  "records": [
    {
      "uid", "record_id", "collector", "name", "brand", "category",
      "models": {"<model>": {"score", "pass", "groups": {category: score}, "matched_by", "model_id"}},
      "fields": [
        {"key": "product.name", "group": "identity", "gt": "<ground-truth value>",
         "m": {"<model>": {"v": "<model value>", "s": <score or null>, "st": "match|partial|mismatch|missing|extra"}}}
      ]
    }
  ]
}
```

- `summary.<model>.fields` holds the **field-level accuracy** shown on the dashboard. It is the average field score, with `n` products.
- `records[].fields` shows the **ground-truth value next to each model's value**, as in the dashboard's product drawer.
- `s: null` means the field was not scored (an extra non-nutrient value).

## `regex_summary.json`

The same `meta` and per-model `summary` as `comparison.json`, without the products. The Overview page (`site/index.html`) reads it.

---

## What the dashboard calculates itself

`site/regex.html` works out two sections from `comparison.json` as it opens, so they are not separate files here:

- **Score distribution:** a histogram of the product `score` values per model.
- **Head-to-head agreement:** products where all models pass, all fail, or the models disagree.

The threshold slider on the dashboard re-applies PASS/FAIL live. These files always use the threshold of the last `compare.py` run (`meta.threshold`).

## Where these files are used

| Used by | Reads |
|---|---|
| `site/regex.html` | `comparison.json` (copied into the page by `compare.py`, so it opens without a server) |
| `site/index.html` (Overview) | `regex_summary.json`, via `serve.py` at `/data/regex/regex_summary.json` |
| `site/manual-review.html` (Snapshot, Team results, verdict hints) | `comparison.json`, via `serve.py` at `/data/regex/comparison.json` |

`serve.py` also serves `summary.csv` and `records.csv` at `/data/regex/summary.csv` and `/data/regex/records.csv` for download.
