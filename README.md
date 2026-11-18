# LishePoa Product Validation

How accurately do three AI models read food product labels, compared with the human-typed **ground truth**?

| Model | File |
|---|---|
| GPT-6-Sol | `data/gpt-6-sol.json` |
| Gemini 3.8 Flash | `data/gemini-3.8-flash.json` |
| Claude Opus 5.5 | `data/claude-opus-5-5.json` |
| **Ground truth** (1,501 records) | `data/ground_truth.json` |

Products are matched on `gt_uid` (for example `J001`, `F001`). The ground truth splits `F406` into `F406_1` (empty) and `F406_2`. Both methods pair the models' `F406` with `F406_2`.

The project has three ways of checking, each with its own page:

| Page | What it does |
|---|---|
| **① Regex comparison** (`site/regex.html`) | Rule-based and fully automatic. Regex normalization, a 0–100% score per field, and PASS when the weighted score is at least 80%. |
| **② LLM judge** (`site/llm-judge.html`) | GPT-4o mini grades text fields blind; numbers and codes are checked exactly in Python. PASS at 85%. |
| **③ Manual review** (`site/manual-review.html`) | Clive, Abigail and Roda check random batches of 33 products by hand. |

All three use the same six categories: **Identity**, **Package**, **Nutrition basis**, **Nutrients**, **Ingredients**, and **Other label information**.

## Quick start

```bash
python3 serve.py          # then open http://localhost:8000
```

`serve.py` needs only Python 3.10+, with no extra packages. The regex page also works when opened directly as a file. The manual review page needs the server so it can save your work.

## ③ Manual review: how the team works

1. Run `python3 serve.py`, open **③ Manual review**, and click your name (Clive, Abigail or Roda).
2. Click **Generate 33 random products**. The 1,500 products are split evenly and at random between the three reviewers (about 500 each), so nobody gets the same product twice.
3. For each product and category, compare each model with the ground truth and tick **✓ Correct**, **✗ Wrong** or **N/A**. Tick **⚠ Ground truth looks wrong** when the reference itself is the problem.
4. A product counts as checked when all 18 boxes (6 categories × 3 models) are set. The page shows three progress bars: **your batch (x / 33)**, **your share**, and **the entire dataset**, split by reviewer.
5. Work is saved automatically to `reviews/<your-name>.json`.

**Sharing progress.** There are two options:

- **Through git:** each reviewer commits their own `reviews/<name>.json`, and the team's progress adds up after a `git pull`. One file per person means no merge conflicts.
- **One shared server:** one person runs `python3 serve.py --lan`, and the others open `http://<that-computer's-IP>:8000` on the same network.

**Team results** (on the same page) shows:

- human-judged accuracy per model and category
- how often the regex and LLM-judge verdicts agree with the humans
- every ground-truth issue that was flagged
- a CSV export

## ① Regex comparison

```bash
python3 compare.py                   # default pass threshold 80%
python3 compare.py --threshold 0.85
```

Outputs:

- `site/regex.html`: self-contained dashboard. It's built from `templates/regex.html`, so edit the template, not the output.
- `results/summary.csv`, `results/records.csv`, `results/comparison.json`, and `results/regex_summary.json`

Category weights: Identity 20%, Package 10%, Nutrition basis 10%, Nutrients 40%, Ingredients 15%, Other label info 5%. The page's Methodology section has the full rules.

## ② LLM judge

One-time setup:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env       # never commit this file (it is in .gitignore)
```

Run it:

```bash
.venv/bin/python judge_eval.py --limit 100   # test on 100 products
.venv/bin/python judge_eval.py               # all products (asks before spending; well under US$1)
```

- **Restarting costs nothing extra.** Every judge answer is cached in `output/judge_cache.jsonl`, so a rerun continues where it stopped and never pays twice.
- **Full runs publish their results:** `site/llm-judge.html` and `results/llm_judge_rows.json` (the per-product marks used by the manual review page).
- **Every run rebuilds:** the terminal summary (PASS/FAIL per model, field and nutrient), `output/dashboard.html`, and `output/extraction_judge_results.xlsx`.

**The LLM-judge dashboard** is the same page whether you open `site/llm-judge.html` (with the site's top navigation) or `output/dashboard.html` (standalone; just double-click it). It shows:

- a one-sentence summary
- one card per model with its rank and pass/fail
- a scorecard of every area and field, green ✓ or red ✗
- a "Products mostly right" count
- a nutrient chart for nutrients found on 50+ products

**The pass-mark slider** (50–100%) changes the ✓/✗ marks, badges and product counts, but not the accuracy percentages, which are fixed by the results. The browser remembers your setting.

**The Excel workbook** has these sheets:

| Sheet | Contents |
|---|---|
| Basic analysis | one row per product, one ✓/✗ per model (✓ = everything on that product correct) |
| Summary | leaderboard and accuracy per field |
| One sheet per field | ground truth vs each model, with ✓/✗ and the judge's note for text fields; filterable |
| Nutrients | one row per product and nutrient, with ✓/✗ per model |
| Comparison | per product: ground truth, then each model's value with ✓/✗ and the judge's notes |

**Online dashboard data (optional):**

```bash
.venv/bin/python export_dashboard_data.py
```

This writes `output/dashboard/scorecard.json`, `nutrients.json` and `products.json` from the saved judge answers, with no API calls. It feeds the online "Label Extraction Scorecard". Rerun it after a new judge run.

Options:

| Option | What it does |
|---|---|
| `--limit N` | only the first N products (doesn't update the site page) |
| `--target 0.9` | change the PASS target (default 85%) |
| `--yes` | skip the cost question |
| `--offline` | no API calls; text graded by plain string match |
| `--model <name>` | a different judge model (default `gpt-4o-mini`) |

How the judge grades:

- **Text fields:** name, brand, manufacturer, country, package type, ingredients, and other label info are graded by the LLM. The judge sees the models as A, B and C, not by name.
- **Numbers and codes:** nutrients, barcode, sizes, category and nutrition basis are checked exactly in Python.
- **Other label info:** people typed only part of this text, so extra text from a model is fine.
- **Changing the models:** edit `DEFAULT_MODELS` near the top of `judge_eval.py`. Keep `compare.py` in step, so each model keeps the same name and colour on every page.

## Things to know about the data

- **F406.** The ground truth splits it into F406_1 (empty) and F406_2 (Tropicana Slim), while the models have one F406. Both methods compare the models' F406 with F406_2, so 1,500 products are compared. F406_1 has nothing to compare against and is left out (`ID_ALIASES` in `judge_eval.py`).
- **Missing ground truth.** Manufacturer and country of origin sometimes come from outside the label, so the ground truth has values the models can't see.
- **Units and fractions.** Some ground-truth nutrient values are stored as fractions (for example "20%" stored as 0.2 g). The regex method accepts either reading.
- **When all three models are wrong the same way,** check the ground truth first. Use the ⚠ flag on the manual review page to record it.

## Folder layout

```
data/            ground truth + model outputs (inputs)
compare.py       ① regex comparison
judge_eval.py    ② LLM judge   (report.py draws its dashboard)
export_dashboard_data.py   optional data files for the online LLM-judge dashboard
serve.py         local server for the site + manual review storage
site/            the web pages: index, regex, llm-judge, manual-review
site_nav.py      shared top navigation for generated pages
templates/       source template for the regex page
results/         generated results (committed)
reviews/         manual review files, one per reviewer (committed)
output/          LLM-judge Excel, dashboard.html and answer cache (not committed)
```
