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
- `ui/index.html`: self-contained dashboard with the data embedded, built from `ui/template.html` (edit the template, not index.html)

## How scoring works

Records are matched on `gt_uid`. If there's no exact match, matching falls back to `record_id` (for example, F406 is split in the GT into F406_1 and F406_2).
Each field is normalized with regexes and scored from 0 to 1. Fields are grouped as follows:
Identity 20%, Package 10%, Nutrition basis 10%, Nutrients 40%, Ingredients 15%, Other label info 5%.
A record **passes (YES)** when its weighted score is at or above the threshold. The dashboard's Methodology section has the full rules.

---

# LLM judge (judge_eval.py)

This compares how well three AI models read food product labels:

- GPT-6-Sol
- Gemini 3.8 Flash
- Claude Opus 5.5

Each model read photos of 1,500 product labels and saved what it found (name, brand, nutrients, ingredients and so on) as JSON. People also typed the same labels by hand. That is the **ground truth**.

This project checks each model's answers against the ground truth, product by product, using the unique product ID (`gt_uid`, for example `J001` or `F001`).

## How the checking works

| What is checked | Who checks it | Examples |
|---|---|---|
| Text | **GPT-4o mini** acting as a judge | product name, brand, manufacturer, country, package type, ingredients, other label info |
| Numbers and codes | Python, with an exact match | nutrient values, barcode, package size, serving size, category |

- **Numbers are checked by Python, not the judge.** An AI judge can mistake 0.07 for 0.7, and Python can't.
- **The judge doesn't know which model wrote which answer.** It sees them as A, B and C, so it can't favour one.
- **Marks:** ✓ correct, ✗ wrong, missing or made up, ~ partly correct (ingredients and other label info only).
- **Capital letters, spacing and punctuation don't matter.** Spelling mistakes in names count as ✗.
- **Fields that are empty everywhere aren't counted:** empty in the ground truth and in every model.
- **Other label info:** people typed only part of this text. A model gets ✓ if it includes everything they typed, and extra text is fine. If the people left it empty, it isn't scored.
- **Nutrients:** the value, unit and qualifier (for example `<` or `Max`) must all match.
- **Target:** 85% accuracy. Anything at or above that is PASS.

## Folder layout

```
Lishe-Poa-Models-Eval/
├── judge_eval.py            main script
├── report.py                makes the chart page
├── requirements.txt         libraries to install
├── .env                     your OpenAI key (never share this file)
├── data/
│   ├── ground_truth.json
│   ├── gpt-6-sol.json
│   ├── gemini-3.8-flash.json
│   └── claude-opus-5-5.json
└── output/                  created automatically
    ├── extraction_judge_results.xlsx   final Excel file
    ├── report.html                     charts, open in a browser
    └── judge_cache.jsonl               saved judge answers (keep this)
```

## Setup (once)

1. Open the folder in VS Code and open a terminal (**Terminal → New Terminal**).
2. Create a virtual environment and install the libraries:
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
   On Windows, use `.venv\Scripts\pip` instead.
3. Put your OpenAI key in the `.env` file, as one line:
   ```
   OPENAI_API_KEY=sk-your-key-here
   ```

## Running it

Test on the first 100 products:

```
.venv/bin/python judge_eval.py --limit 100
```

Then run all products:

```
.venv/bin/python judge_eval.py
```

- **Cost:** before calling OpenAI, the script prints an estimate and asks you to type `y`. A full run of about 1,480 judge calls costs well under US$1 with GPT-4o mini.
- **Restarting:** every judge answer is saved in `output/judge_cache.jsonl`. If the run stops, run the same command again and it continues where it stopped. Products already judged are never sent or paid for again.
- **Rebuilding the results:** once everything is judged, running the command again makes no API calls. It just rebuilds the Excel file, the chart page and the terminal summary.

Useful options:

| Option | What it does |
|---|---|
| `--limit 100` | only the first 100 products |
| `--target 0.9` | change the PASS target (default `0.85` = 85%) |
| `--yes` | skip the cost question |
| `--offline` | no API calls; text graded by plain text match (layout test only) |

To add or remove a model, edit the `DEFAULT_MODELS` list near the top of `judge_eval.py`.

## What you get

**1. Summary in the terminal:** accuracy per model, per nutrient and per field, each marked PASS or FAIL against the 85% target.

**2. `output/report.html`:** a page with simple charts:
- one card per model with its overall accuracy
- accuracy by area: text, codes and sizes, nutrients, overall
- accuracy per field
- accuracy per nutrient (nutrients found on at least 20 products)

Each chart has a "Show table" link with the exact numbers.

**3. `output/extraction_judge_results.xlsx`:** the final Excel file.

| Sheet | Contents |
|---|---|
| Basic analysis | one row per product ID, one ✓/✗ per model (✓ = everything on that product correct) |
| Summary | leaderboard and accuracy per field |
| Comparison | per product: ground truth, then each model's value with ✓/✗ and the judge's notes |
| Nutrients | one row per product and nutrient, with ✓/✗ per model |

## Things to know about the data

- **F406 is not compared.** The ground truth splits it into F406_1 (empty) and F406_2 (Tropicana Slim), while the models have one F406. To include it, set `ID_ALIASES = {"F406_2": "F406"}` in `judge_eval.py`. That leaves 1,499 products compared.
- **Check the ground truth when all models are wrong.** If all three models are wrong in the same way (for example vitamin A, vitamin C or iron values), the ground truth or the units (mg vs µg) may be the problem, not the models.
- **Manufacturer and country sometimes come from outside the label.** The ground truth often has them when the label doesn't, so the models can be marked ✗ unfairly.
- **The judge model.** The script uses `gpt-4o-mini`. If OpenAI renames or retires it, add `--model <new-name>`.
