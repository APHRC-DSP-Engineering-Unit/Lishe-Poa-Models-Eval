#!/usr/bin/env python3
"""
LLM-as-judge evaluation of product-label extraction models (default: GPT-6-Sol,
Gemini 3.8 Flash, Claude Opus 5.5) against human ground truth. Judge: OpenAI GPT-4o mini.

How fields are graded
- Text fields (name, brand, manufacturer, country, package type, ingredients,
  other label info) -> judged by the LLM (blind: models shown as "A", "B", "C").
  Exact matches (ignoring case/spacing/punctuation) are marked correct in code
  without an API call, to save cost.
- Numbers and codes (barcode, category, package size, serving size, nutrition
  basis, every nutrient value) -> checked exactly in code. Code is 100% reliable
  for numbers; an LLM is not.

Marks:  ✓ correct   ✗ wrong / missing / invented   ~ partial (long text only)
        blank = field empty in ground truth AND both models (not counted)

Folder layout
  llm-judge/
    judge_eval.py
    .env                     OPENAI_API_KEY=sk-...
    data/ground_truth.json
    data/gpt-6-sol.json
    data/gemini-3.8-flash.json
    data/claude-opus-5-5.json
    output/                  (created automatically: Excel + progress cache)

Usage
  pip install openai openpyxl
  python judge_eval.py

  Models are set in DEFAULT_MODELS below, or on the command line:
  python judge_eval.py --model-file "GPT-6-Sol=data/gpt-6-sol.json" --model-file "Claude=data/claude.json"

  --limit 20      test on the first 20 products first
  --offline       no API calls; text fields graded by plain string match (layout preview)
  --yes           skip the cost confirmation prompt
Progress is saved to judge_cache.jsonl; re-running continues where it stopped.
"""
import argparse, json, os, re, sys, threading, time, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Models to compare: display name -> file inside data/
DEFAULT_MODELS = [
    ("GPT-6-Sol", "gpt-6-sol.json"),
    ("Gemini 3.8 Flash", "gemini-3.8-flash.json"),
    ("Claude Opus 5.5", "claude-opus-5-5.json"),
]

# Ground-truth IDs that the models stored under a different ID: {ground truth ID: model ID}.
# Empty by default. F406 is skipped: the ground truth splits it into F406_1 (empty) and F406_2
# (the real product). To include it, use {"F406_2": "F406"}.
ID_ALIASES = {}

# Price per 1M tokens for the judge (USD). Check OpenAI's pricing page and edit if changed.
PRICE_IN, PRICE_OUT = 0.15, 0.60

TEXT_FIELDS = {  # key -> (label, partial allowed)
    "name": ("Product name", False),
    "brand": ("Brand", False),
    "manufacturer": ("Manufacturer", False),
    "country_of_origin": ("Country of origin", False),
    "package_type": ("Package type", False),
    "ingredients": ("Ingredients", True),
    "other_info": ("Other label info", True),
}
CODE_FIELDS = {
    "category": "Category",
    "barcode": "Barcode",
    "package_size": "Package size",
    "package_count": "Package count",
    "serving_size": "Serving size",
    "nutrition_basis": "Nutrition basis",
}
FIELD_ORDER = ["name", "brand", "manufacturer", "category", "country_of_origin", "barcode",
               "package_size", "package_count", "package_type", "serving_size",
               "nutrition_basis", "ingredients", "other_info"]
LABEL = {**{k: v[0] for k, v in TEXT_FIELDS.items()}, **CODE_FIELDS}

OK, BAD, PART, NA = "✓", "✗", "~", ""

# ---------------------------------------------------------------- helpers
def empty(v):
    return v is None or (isinstance(v, str) and v.strip() in ("", "-", "n/a", "N/A", "null", "None"))

def norm_text(v):
    if empty(v):
        return ""
    s = str(v).lower()
    s = re.sub(r"[^\w%]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()

UNIT_MAP = {"g": "g", "gr": "g", "gr.": "g", "gram": "g", "grams": "g", "grm": "g", "grms": "g",
            "جم": "g", "kg": "kg", "kgs": "kg", "ml": "ml", "l": "l", "ltr": "l", "litre": "l",
            "liter": "l", "lt": "l", "mg": "mg", "pcs": "pcs", "pieces": "pcs", "piece": "pcs"}
TO_BASE = {"kg": ("g", 1000), "l": ("ml", 1000), "mg": ("g", 0.001)}

def norm_unit(u):
    if empty(u):
        return None
    u = str(u).strip().lower()
    return UNIT_MAP.get(u, u)

def to_base(amount, unit):
    u = norm_unit(unit)
    if amount is None:
        return None, u
    if u in TO_BASE:
        b, f = TO_BASE[u]
        return round(float(amount) * f, 6), b
    return round(float(amount), 6), u

def num_eq(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))

def mark_presence(gt_empty, m_empty):
    """Returns a mark if presence alone decides it, else None."""
    if gt_empty and m_empty:
        return NA
    if gt_empty != m_empty:
        return BAD
    return None

def show(v):
    return "" if v is None else str(v)

# ---------------------------------------------------------------- field extraction
def text_values(r):
    p, pk = r.get("product") or {}, r.get("package") or {}
    ptype = pk.get("type")
    if ptype and pk.get("type_raw"):
        ptype = f"{ptype} ({pk['type_raw']})"
    return {
        "name": p.get("name"), "brand": p.get("brand"), "manufacturer": p.get("manufacturer"),
        "country_of_origin": p.get("country_of_origin"), "package_type": ptype,
        "ingredients": r.get("ingredients_verbatim"), "other_info": r.get("other_label_information"),
    }

def code_display(r):
    p, pk = r.get("product") or {}, r.get("package") or {}
    ss, nb = r.get("serving_size") or {}, r.get("nutrition_basis") or {}
    size = " ".join(x for x in [show(pk.get("size")), show(pk.get("unit"))] if x)
    serv = " ".join(x for x in [show(ss.get("amount")), show(ss.get("unit"))] if x) or show(ss.get("raw"))
    return {"category": p.get("category"), "barcode": p.get("barcode"), "package_size": size or None,
            "package_count": pk.get("count"), "serving_size": serv or None,
            "nutrition_basis": nb.get("type")}

def check_code(field, g, m):
    gp, mp = g.get("product") or {}, m.get("product") or {}
    if field == "category":
        a, b = gp.get("category"), mp.get("category")
        pm = mark_presence(empty(a), empty(b))
        return pm if pm is not None else (OK if norm_text(a) == norm_text(b) else BAD)
    if field == "barcode":
        a = re.sub(r"\D", "", show(gp.get("barcode"))); b = re.sub(r"\D", "", show(mp.get("barcode")))
        pm = mark_presence(not a, not b)
        return pm if pm is not None else (OK if a == b else BAD)
    if field == "package_size":
        gk, mk = g.get("package") or {}, m.get("package") or {}
        a, b = to_base(gk.get("size"), gk.get("unit")), to_base(mk.get("size"), mk.get("unit"))
        pm = mark_presence(a == (None, None), b == (None, None))
        if pm is not None:
            return pm
        return OK if num_eq(a[0], b[0]) and a[1] == b[1] else BAD
    if field == "package_count":
        a, b = (g.get("package") or {}).get("count"), (m.get("package") or {}).get("count")
        pm = mark_presence(a is None, b is None)
        return pm if pm is not None else (OK if num_eq(a, b) else BAD)
    if field == "serving_size":
        gs, ms = g.get("serving_size") or {}, m.get("serving_size") or {}
        ga, ma = gs.get("amount"), ms.get("amount")
        ge, me = ga is None and empty(gs.get("raw")), ma is None and empty(ms.get("raw"))
        pm = mark_presence(ge, me)
        if pm is not None:
            return pm
        if ga is None or ma is None:  # only raw text available
            return OK if norm_text(gs.get("raw")) == norm_text(ms.get("raw")) else BAD
        a, b = to_base(ga, gs.get("unit")), to_base(ma, ms.get("unit"))
        return OK if num_eq(a[0], b[0]) and a[1] == b[1] else BAD
    if field == "nutrition_basis":
        a = (g.get("nutrition_basis") or {}).get("type"); b = (m.get("nutrition_basis") or {}).get("type")
        a = None if a == "unknown" else a; b = None if b == "unknown" else b
        pm = mark_presence(empty(a), empty(b))
        return pm if pm is not None else (OK if a == b else BAD)
    raise KeyError(field)

def nutrient_empty(n):
    return (not n) or (n.get("value") is None and not n.get("range")
                       and n.get("qualifier") in (None, "not_stated", "unparseable"))

def nutrient_show(n):
    if nutrient_empty(n):
        return ""
    q, v, rg, u = n.get("qualifier"), n.get("value"), n.get("range"), n.get("unit") or ""
    if rg:
        core = f"{rg[0]}–{rg[1]}"
    else:
        core = show(v)
    pre = "" if q in (None, "range") else (q + " " if q in ("<", ">") else q + " ")
    return f"{pre}{core} {u}".strip()

def check_nutrient(a, b):
    pm = mark_presence(nutrient_empty(a), nutrient_empty(b))
    if pm is not None:
        return pm
    if (a.get("qualifier") or None) != (b.get("qualifier") or None):
        return BAD
    if a.get("range") or b.get("range"):
        ra, rb = a.get("range") or [None, None], b.get("range") or [None, None]
        if not (num_eq(ra[0], rb[0]) and num_eq(ra[1], rb[1])):
            return BAD
    elif not num_eq(a.get("value"), b.get("value")):
        return BAD
    if a.get("value") is not None and norm_unit(a.get("unit")) != norm_unit(b.get("unit")):
        return BAD
    return OK

# ---------------------------------------------------------------- judge
SYSTEM_PROMPT = """You are a strict, impartial grader of data extraction from food product labels.
Humans typed the GROUND TRUTH by reading each product label. Several AI models (labelled A, B,
C, ...) read photos of the same label. For each field, decide if each model's value matches the
ground truth.

Rules:
- "correct": same text/meaning. Ignore differences in capital letters, spacing, punctuation,
  word order of a list, and harmless formatting (e.g. "Kenya" vs "KENYA", "Ltd" vs "Limited").
- Product name: correct if it clearly names the same product. Extra or fewer descriptive words
  that are on the label are fine ("Ghee" vs "Superfine Ghee" = correct). A different product,
  flavour or variant is incorrect.
- Package type: correct if it is the same kind of packaging (e.g. "bottle" vs "plastic_bottle"
  = correct; "glass_jar" vs "plastic_pouch" = incorrect).
- Spelling mistakes in names, brands or manufacturers are INCORRECT, even one letter.
- Any wrong number, percentage, or date inside a text field is INCORRECT.
- Model value empty but ground truth has a value -> "incorrect" (note: "missing").
- Ground truth empty but model gave a value -> "incorrect" (note: "not in ground truth").
- Other label info: humans typed only SOME of the label text. Mark "correct" if every piece of
  information in the ground truth appears in the model value (wording may differ, e.g. "consume
  in three days" vs "consume within 3 days"). EXTRA text from the label is fine, never penalise
  it. "partial" if some ground-truth items are missing; "incorrect" if most are missing or wrong.
- "partial" is allowed ONLY for fields marked partial_allowed=true (long text such as
  ingredients): use it when most of the content is right but some items are missing, extra
  or wrong. If almost everything is wrong, use "incorrect". Never use "partial" elsewhere.
- Notes: if not correct, give a short reason (max 15 words). If correct, note = "".
Judge each model independently. Do not prefer any model."""

def tag(i):
    return "model_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i]

def build_schema(fields, n_models):
    item = {"type": "object", "additionalProperties": False,
            "properties": {"mark": {"type": "string", "enum": ["correct", "incorrect", "partial"]},
                           "note": {"type": "string"}},
            "required": ["mark", "note"]}
    per_model = {"type": "object", "additionalProperties": False,
                 "properties": {f: item for f in fields}, "required": list(fields)}
    tags = [tag(i) for i in range(n_models)]
    return {"name": "grading", "strict": True,
            "schema": {"type": "object", "additionalProperties": False,
                       "properties": {t: per_model for t in tags}, "required": tags}}

MARK_FROM_JUDGE = {"correct": OK, "incorrect": BAD, "partial": PART}

class Judge:
    def __init__(self, model, cache_path, offline, n_models):
        self.model, self.cache_path, self.offline, self.n = model, cache_path, offline, n_models
        self.lock = threading.Lock()
        self.cache = {}
        self.usage = {"in": 0, "out": 0, "calls": 0}
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line); self.cache[d["key"]] = d["result"]
                    except Exception:
                        pass
        self.client = None
        if not offline:
            try:
                from openai import OpenAI
            except ImportError:
                sys.exit("Install the OpenAI library first:  pip install openai")
            if not os.environ.get("OPENAI_API_KEY"):
                sys.exit("OPENAI_API_KEY not found. Create a .env file next to judge_eval.py containing:\n  OPENAI_API_KEY=sk-...")
            self.client = OpenAI(max_retries=8, timeout=120)  # SDK backs off on rate limits

    @staticmethod
    def key(pid, payload):
        return pid + ":" + hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]

    def grade(self, pid, payload):
        """payload: {field: {ground_truth, model_A, model_B, ..., partial_allowed}}
        returns {model_A: {field: [mark, note]}, ...}"""
        k = self.key(pid, payload)
        if k in self.cache:
            return self.cache[k]
        tags = [tag(i) for i in range(self.n)]
        if self.offline:
            return {t: {f: [OK if norm_text(v["ground_truth"]) == norm_text(v[t]) else BAD, "offline string match"]
                        for f, v in payload.items()} for t in tags}
        user = json.dumps({"product_id": pid, "fields": payload}, ensure_ascii=False, indent=1)
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": build_schema(list(payload), self.n)})
        data = json.loads(resp.choices[0].message.content)
        result = {t: {f: [MARK_FROM_JUDGE.get(data[t][f]["mark"], BAD), data[t][f]["note"]]
                      for f in payload} for t in tags}
        for t in result:  # enforce: partial only where allowed
            for f in result[t]:
                if result[t][f][0] == PART and not payload[f]["partial_allowed"]:
                    result[t][f][0] = BAD
        with self.lock:
            self.usage["in"] += resp.usage.prompt_tokens
            self.usage["out"] += resp.usage.completion_tokens
            self.usage["calls"] += 1
            self.cache[k] = result
            with open(self.cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"key": k, "result": result}, ensure_ascii=False) + "\n")
        return result

# ---------------------------------------------------------------- per-product evaluation
def prepare(pid, g, models):
    """models: list of records (one per model). Grades code fields and easy text fields in code.
    Returns (row, judge_payload); payload is empty if no LLM judgement is needed."""
    n = len(models)
    row = {"id": pid, "fields": {}, "nutrients": []}
    gv, mv = text_values(g), [text_values(m) for m in models]
    payload = {}
    for f, (_, partial) in TEXT_FIELDS.items():
        marks = []
        for v in mv:
            pm = mark_presence(empty(gv[f]), empty(v[f]))
            if f == "other_info" and empty(gv[f]):
                pm = NA  # humans left it blank: extra label text from the model is not an error
            if pm is None and norm_text(gv[f]) == norm_text(v[f]):
                pm = OK
            if pm == BAD:
                marks.append([BAD, "missing" if empty(v[f]) else "not in ground truth"])
            elif pm is not None:
                marks.append([pm, ""])
            else:
                marks.append(None)  # needs the judge
        row["fields"][f] = {"gt": gv[f], "vals": [v[f] for v in mv], "marks": marks}
        if any(m is None for m in marks):
            payload[f] = {"ground_truth": show(gv[f]), **{tag(i): show(mv[i][f]) for i in range(n)},
                          "partial_allowed": partial}
    gd, md = code_display(g), [code_display(m) for m in models]
    for f in CODE_FIELDS:
        row["fields"][f] = {"gt": gd[f], "vals": [d[f] for d in md],
                            "marks": [[check_code(f, g, m), ""] for m in models]}
    gn, mn = g.get("nutrients") or {}, [m.get("nutrients") or {} for m in models]
    order = list(gn)
    for nut in sorted(set(gn).union(*mn), key=lambda x: order.index(x) if x in order else 999):
        x, ys = gn.get(nut), [d.get(nut) for d in mn]
        if nutrient_empty(x) and all(nutrient_empty(y) for y in ys):
            continue
        row["nutrients"].append({"nutrient": nut, "gt": nutrient_show(x), "vals": [nutrient_show(y) for y in ys],
                                 "marks": [check_nutrient(x, y) for y in ys]})
    return row, payload

def apply_judge(row, result, n):
    for f, fd in row["fields"].items():
        for i in range(n):
            if fd["marks"][i] is None:
                fd["marks"][i] = result[tag(i)][f] if result else ["?", "judge error - rerun"]

def disagree(marks):
    return OK in marks and BAD in marks

def product_verdict(row, i):
    """One mark per product for model i: ✓ only if every scored field and nutrient is ✓.
    Returns (mark, n_correct, n_scored)."""
    ms = [fd["marks"][i][0] for fd in row["fields"].values()]
    ms += [x["marks"][i] for x in row["nutrients"]]
    scored = [m for m in ms if m != NA]
    ok = scored.count(OK)
    if "?" in scored:
        return "?", ok, len(scored)
    return (OK if ok == len(scored) else BAD), ok, len(scored)

# ---------------------------------------------------------------- excel
def write_excel(path, rows, names, unmatched, info):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    GREEN, RED, AMBER = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE"), PatternFill("solid", fgColor="FFEB9C")
    HEAD = PatternFill("solid", fgColor="1F3864"); SUB = PatternFill("solid", fgColor="D9E1F2")
    WF, BF = Font(bold=True, color="FFFFFF"), Font(bold=True)
    FILL = {OK: GREEN, BAD: RED, PART: AMBER, "?": AMBER}
    n = len(names)
    W = 1 + 2 * n  # columns per field: GT, then (value, mark) per model

    def style_mark(c):
        c.alignment = Alignment(horizontal="center", vertical="top")
        if c.value in FILL:
            c.fill = FILL[c.value]

    def stats(marks):
        s = [m for m in marks if m not in (NA, "?")]
        return len(s), s.count(OK), s.count(PART), s.count(BAD)

    wb = Workbook()
    ws_sum = wb.active; ws_sum.title = "Summary"

    # ---- Basic analysis sheet (first sheet): one row per product ID, one LLM-judge ✓/✗ per model
    wbasic = wb.create_sheet("Basic analysis", 0)
    judge_name = "Judge" if info["judge"] != "offline string match" else "Judge (offline preview)"
    for j, h in enumerate([judge_name] + names, 1):
        c = wbasic.cell(1, j, h); c.font = WF; c.fill = HEAD
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    tally = [0] * n
    for r_i, row in enumerate(rows, start=2):
        wbasic.cell(r_i, 1, row["id"]).font = BF
        for i in range(n):
            m = product_verdict(row, i)[0]
            tally[i] += m == OK
            style_mark(wbasic.cell(r_i, 2 + i, m))
    r_t = len(rows) + 2
    wbasic.cell(r_t, 1, "Products ✓").font = BF
    for i in range(n):
        cc = wbasic.cell(r_t, 2 + i, f"{tally[i]}/{len(rows)}"); cc.font = BF
        cc.alignment = Alignment(horizontal="center")
    wbasic.cell(r_t + 2, 1, "✓ = the judge found every field and nutrient of the product matches the ground truth. "
                "Field-by-field details are in the Comparison and Nutrients sheets.")
    wbasic.freeze_panes = "B2"
    wbasic.auto_filter.ref = f"A1:{get_column_letter(1 + n)}{len(rows) + 1}"
    wbasic.column_dimensions["A"].width = 24
    for k in range(2, 2 + n):
        wbasic.column_dimensions[get_column_letter(k)].width = 18

    # ---- Comparison sheet
    ws = wb.create_sheet("Comparison")
    c = ws.cell(1, 1, "Product ID"); c.font = WF; c.fill = HEAD
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
    col = 2
    for f in FIELD_ORDER:
        ws.cell(1, col, LABEL[f]).font = WF
        ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + W - 1)
        heads = ["Ground truth"] + [h for nm in names for h in (nm, "✓/✗")]
        for i, h in enumerate(heads):
            cc = ws.cell(2, col + i, h); cc.font = BF; cc.fill = SUB
            ws.cell(1, col + i).fill = HEAD
        col += W
    extra = [f"{nm} nutrients ✓" for nm in names] + [f"{nm} judge notes" for nm in names]
    for i, h in enumerate(extra):
        cc = ws.cell(1, col + i, h); cc.font = WF; cc.fill = HEAD; cc.alignment = Alignment(wrap_text=True)
        ws.merge_cells(start_row=1, start_column=col + i, end_row=2, end_column=col + i)

    for r_i, row in enumerate(rows, start=3):
        ws.cell(r_i, 1, row["id"]).font = BF
        cc = 2
        for f in FIELD_ORDER:
            fd = row["fields"][f]
            ws.cell(r_i, cc, show(fd["gt"]))
            for i in range(n):
                ws.cell(r_i, cc + 1 + 2 * i, show(fd["vals"][i]))
                style_mark(ws.cell(r_i, cc + 2 + 2 * i, fd["marks"][i][0]))
            cc += W
        for i in range(n):
            scored = [x["marks"][i] for x in row["nutrients"] if x["marks"][i] != NA]
            ws.cell(r_i, cc + i, f"{scored.count(OK)}/{len(scored)}" if scored else "")
            notes = [f"{LABEL[f]}: {row['fields'][f]['marks'][i][1]}" for f in FIELD_ORDER
                     if row["fields"][f]["marks"][i][0] in (BAD, PART, "?") and row["fields"][f]["marks"][i][1]]
            ws.cell(r_i, cc + n + i, "; ".join(notes))
    last = col + 2 * n - 1
    ws.freeze_panes = "B3"
    ws.auto_filter.ref = f"A2:{get_column_letter(last)}{len(rows) + 2}"
    ws.column_dimensions["A"].width = 11
    for i in range(2, col):
        ws.column_dimensions[get_column_letter(i)].width = 6 if (i - 2) % W and (i - 2) % W % 2 == 0 else 22
    for i in range(col, last + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14 if i < col + n else 60

    # ---- Nutrients sheet
    wn = wb.create_sheet("Nutrients")
    hdr = ["Product ID", "Nutrient", "Ground truth"] + [h for nm in names for h in (nm, "✓/✗")]
    for i, h in enumerate(hdr, 1):
        cc = wn.cell(1, i, h); cc.font = WF; cc.fill = HEAD
    r_i = 2
    for row in rows:
        for x in row["nutrients"]:
            wn.cell(r_i, 1, row["id"]); wn.cell(r_i, 2, x["nutrient"]); wn.cell(r_i, 3, x["gt"])
            for i in range(n):
                wn.cell(r_i, 4 + 2 * i, x["vals"][i])
                style_mark(wn.cell(r_i, 5 + 2 * i, x["marks"][i]))
            r_i += 1
    wn.freeze_panes = "C2"; wn.auto_filter.ref = f"A1:{get_column_letter(len(hdr))}{max(r_i - 1, 1)}"
    for i, w in enumerate([11, 28, 18] + [18, 6] * n, 1):
        wn.column_dimensions[get_column_letter(i)].width = w

    # ---- Summary sheet
    ws_sum["A1"] = "Extraction accuracy vs human ground truth"; ws_sum["A1"].font = Font(bold=True, size=14)
    ws_sum["A2"] = f"Judge: {info['judge']}  |  Products compared: {len(rows)}  |  Generated: {info['when']}"

    field_marks = []  # (label, [marks per model as lists])
    totals = [[] for _ in names]
    for f in FIELD_ORDER:
        per = [[row["fields"][f]["marks"][i][0] for row in rows] for i in range(n)]
        field_marks.append((LABEL[f], per))
        for i in range(n):
            totals[i] += per[i]
    nut = [[x["marks"][i] for row in rows for x in row["nutrients"]] for i in range(n)]
    field_marks.append(("Nutrient values (all)", nut))
    field_marks.append(("ALL FIELDS + NUTRIENTS", [totals[i] + nut[i] for i in range(n)]))

    # Leaderboard
    r = 4
    ws_sum.cell(r, 1, "Leaderboard").font = Font(bold=True, size=12)
    r += 1
    for i, h in enumerate(["Rank", "Model", "Overall accuracy", "Text fields", "Nutrients", "Products 100% correct"], 1):
        cc = ws_sum.cell(r, i, h); cc.font = WF; cc.fill = HEAD; cc.alignment = Alignment(wrap_text=True, horizontal="center")
    board = []
    for i, nm in enumerate(names):
        acc = lambda ms: (lambda s: s[1] / s[0] if s[0] else 0)(stats(ms))
        perfect = sum(1 for row in rows
                      if all(row["fields"][f]["marks"][i][0] in (OK, NA) for f in FIELD_ORDER)
                      and all(x["marks"][i] in (OK, NA) for x in row["nutrients"]))
        board.append((acc(totals[i] + nut[i]), nm, acc(totals[i]), acc(nut[i]), perfect))
    for rank, (overall, nm, fa, na_, perfect) in enumerate(sorted(board, reverse=True), 1):
        r += 1
        for i, v in enumerate([rank, nm, overall, fa, na_, perfect], 1):
            cc = ws_sum.cell(r, i, v)
            if i in (3, 4, 5):
                cc.number_format = "0.0%"
        if rank == 1:
            for i in range(1, 7):
                ws_sum.cell(r, i).fill = GREEN

    # Per-field table
    r += 2
    ws_sum.cell(r, 1, "Accuracy per field").font = Font(bold=True, size=12)
    r += 1
    hdr = ["Field", "Scored"] + [h for nm in names for h in (f"{nm} ✓", f"{nm} ~", f"{nm} ✗", f"{nm} accuracy")] + ["Models disagree"]
    for i, h in enumerate(hdr, 1):
        cc = ws_sum.cell(r, i, h); cc.font = WF; cc.fill = HEAD; cc.alignment = Alignment(wrap_text=True, horizontal="center")
    ws_sum.row_dimensions[r].height = 45
    for label, per in field_marks:
        r += 1
        st = [stats(m) for m in per]
        accs = [s[1] / s[0] if s[0] else None for s in st]
        dis = sum(1 for marks in zip(*per) if disagree(marks))
        vals = [label, max(s[0] for s in st)]
        for s, a in zip(st, accs):
            vals += [s[1], s[2], s[3], a]
        vals.append(dis)
        for i, v in enumerate(vals, 1):
            cc = ws_sum.cell(r, i, v)
            if isinstance(v, float):
                cc.number_format = "0.0%"
            if label.startswith("ALL"):
                cc.font = BF
        valid = [a for a in accs if a is not None]
        if len(valid) > 1 and max(valid) != min(valid):
            best = accs.index(max(valid))
            ws_sum.cell(r, 3 + 4 * best + 3).fill = GREEN

    r += 2
    ws_sum.cell(r, 1, "Notes").font = BF
    notes = ["Accuracy = ✓ ÷ (✓ + ~ + ✗). Blank cells (empty in ground truth and all models) are not counted.",
             "~ = partial, used only for ingredients and other label info.",
             "Other label info: correct if the model includes everything the humans typed; extra text is allowed. Not scored when the ground truth is blank.",
             "Text fields graded by the LLM judge; numbers, barcode, category, sizes and nutrients checked exactly in code.",
             "'Models disagree' = for the same product, at least one model ✓ and another ✗.",
             "Model names were hidden from the judge (shown as A, B, C) to avoid bias."]
    if unmatched:
        notes.append("IDs not compared (not present in every file): " + ", ".join(sorted(unmatched)))
    if info.get("errors"):
        notes.append(f"{info['errors']} products had judge errors (marked ?). Re-run the script to retry them.")
    for t in notes:
        r += 1; ws_sum.cell(r, 1, t)
    ws_sum.column_dimensions["A"].width = 30
    ws_sum.column_dimensions["B"].width = 20
    for i in range(3, len(hdr) + 1):
        ws_sum.column_dimensions[get_column_letter(i)].width = 12
    wb.save(path)

# ---------------------------------------------------------------- terminal summary
def print_summary(rows, names, target):
    """Print the analysis summary in the terminal, with PASS/FAIL against the target accuracy."""
    n = len(names)
    tgt = f"{target:.0%}"

    def acc(marks):
        s = [m for m in marks if m not in (NA, "?")]
        return (s.count(OK) / len(s), len(s)) if s else (None, 0)

    def pct(a):
        return "   -  " if a is None else f"{a:6.1%}"

    def flag(a):
        return "" if a is None else ("PASS" if a >= target else "FAIL")

    w = max(len(x) for x in names + ["Nutrient"]) + 2
    col = max(14, max(len(x) for x in names) + 2)
    line = "=" * (34 + col * n)

    def table(title, items):
        """items: list of (label, scored count, [accuracy per model])"""
        print(f"\n{title}")
        print(f"{'':30}{'scored':>6} " + "".join(f"{nm:>{col}}" for nm in names))
        for label, cnt, accs in items:
            print(f"{label[:30]:30}{cnt:>6} " + "".join(f"{pct(a) + ' ' + flag(a):>{col}}" for a in accs))

    nut_all = [[x["marks"][i] for r in rows for x in r["nutrients"]] for i in range(n)]
    text_all = [[r["fields"][f]["marks"][i][0] for r in rows for f in TEXT_FIELDS] for i in range(n)]
    code_all = [[r["fields"][f]["marks"][i][0] for r in rows for f in CODE_FIELDS] for i in range(n)]

    print("\n" + line)
    print(f" EXTRACTION ACCURACY vs HUMAN GROUND TRUTH   |  {len(rows)} products  |  target {tgt}")
    print(line)

    # 1. Nutrients overall
    items = []
    for label, data in [("All nutrient values", nut_all)]:
        a = [acc(m) for m in data]
        items.append((label, max(c for _, c in a), [x for x, _ in a]))
    prod = []
    for i in range(n):
        ok = 0; tot = 0
        for r in rows:
            a, c = acc([x["marks"][i] for x in r["nutrients"]])
            if c:
                tot += 1; ok += a >= target
        prod.append((ok, tot))
    table(f"NUTRIENTS (value + unit + qualifier must match exactly)", items)
    print(f"{'Products >=' + tgt + ' nutrients ✓':30}{prod[0][1]:>6} "
          + "".join(f"{f'{ok}/{tot}':>{col}}" for ok, tot in prod))

    # 2. Per nutrient
    order = []
    for r in rows:
        for x in r["nutrients"]:
            if x["nutrient"] not in order:
                order.append(x["nutrient"])
    per = []
    for nut in order:
        marks = [[x["marks"][i] for r in rows for x in r["nutrients"] if x["nutrient"] == nut] for i in range(n)]
        a = [acc(m) for m in marks]
        per.append((nut, max(c for _, c in a), [x for x, _ in a]))
    per.sort(key=lambda t: -t[1])
    table("PER NUTRIENT (most common first)", per)

    # 3. Other fields
    items = []
    for f in FIELD_ORDER:
        a = [acc([r["fields"][f]["marks"][i][0] for r in rows]) for i in range(n)]
        items.append((LABEL[f], max(c for _, c in a), [x for x, _ in a]))
    table("PRODUCT FIELDS (text = LLM judge, others = exact check)", items)

    # 4. Overall
    items = []
    for label, data in [("Text fields (LLM judge)", text_all), ("Codes & sizes", code_all),
                        ("Nutrients", nut_all),
                        ("OVERALL", [text_all[i] + code_all[i] + nut_all[i] for i in range(n)])]:
        a = [acc(m) for m in data]
        items.append((label, max(c for _, c in a), [x for x, _ in a]))
    table("OVERALL", items)
    best = max(range(n), key=lambda i: acc(text_all[i] + code_all[i] + nut_all[i])[0] or 0)
    print(f"\nBest overall: {names[best]}.  PASS = accuracy >= {tgt}.  "
          "~ partial counts as not correct; fields empty everywhere are not counted.")
    print(line)

# ---------------------------------------------------------------- HTML report data
def report_data(rows, names, target, info):
    """Counts [correct, checked] per model, for the charts in report.html."""
    n = len(names)

    def cnt(marks):
        s = [m for m in marks if m not in (NA, "?")]
        return [s.count(OK), len(s)]

    text = [[r["fields"][f]["marks"][i][0] for r in rows for f in TEXT_FIELDS] for i in range(n)]
    code = [[r["fields"][f]["marks"][i][0] for r in rows for f in CODE_FIELDS] for i in range(n)]
    nut = [[x["marks"][i] for r in rows for x in r["nutrients"]] for i in range(n)]
    areas = [
        {"key": "text", "label": "Text fields (LLM judge)", "counts": [cnt(text[i]) for i in range(n)]},
        {"key": "codes", "label": "Codes & sizes", "counts": [cnt(code[i]) for i in range(n)]},
        {"key": "nutrients", "label": "Nutrient values", "counts": [cnt(nut[i]) for i in range(n)]},
        {"key": "overall", "label": "Overall", "counts": [cnt(text[i] + code[i] + nut[i]) for i in range(n)]},
    ]
    fields = [{"label": LABEL[f], "method": "LLM judge" if f in TEXT_FIELDS else "exact check",
               "counts": [cnt([r["fields"][f]["marks"][i][0] for r in rows]) for i in range(n)]}
              for f in FIELD_ORDER]
    order = []
    for r in rows:
        for x in r["nutrients"]:
            if x["nutrient"] not in order:
                order.append(x["nutrient"])
    nutrients = []
    for nt in order:
        c = [cnt([x["marks"][i] for r in rows for x in r["nutrients"] if x["nutrient"] == nt]) for i in range(n)]
        nutrients.append({"label": nt, "n": max(k[1] for k in c), "counts": c})
    pass_products = []
    for i in range(n):
        k = 0
        for r in rows:
            _, ok, sc = product_verdict(r, i)
            k += bool(sc) and ok / sc >= target
        pass_products.append(k)
    return {"models": names, "judge": info["judge"], "when": info["when"], "products": len(rows),
            "target": target, "areas": areas, "fields": fields, "nutrients": nutrients,
            "pass_products": pass_products}

# ---------------------------------------------------------------- main
def load_dotenv(path=".env"):
    """Read KEY=value lines from .env (next to this script) into the environment."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def main():
    load_dotenv()
    here = os.path.dirname(os.path.abspath(__file__))
    data = lambda name: os.path.join(here, "data", name)
    out = lambda name: os.path.join(here, "output", name)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gt", default=data("ground_truth.json"))
    ap.add_argument("--model-file", action="append", metavar="NAME=PATH",
                    help="a model to compare (repeat for each). Default: DEFAULT_MODELS in the script.")
    ap.add_argument("--out", default=out("extraction_judge_results.xlsx"))
    ap.add_argument("--cache", default=out("judge_cache.jsonl"))
    ap.add_argument("--model", default="gpt-4o-mini", help="judge model")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offline", action="store_true"); ap.add_argument("--yes", action="store_true")
    ap.add_argument("--target", type=float, default=0.85, help="accuracy needed to PASS (default 0.85 = 85%%)")
    args = ap.parse_args()

    if args.model_file:
        models = []
        for spec in args.model_file:
            if "=" not in spec:
                sys.exit(f"--model-file must look like NAME=PATH, got: {spec}")
            nm, pth = spec.split("=", 1)
            models.append((nm.strip(), pth.strip()))
    else:
        models = [(nm, data(fn)) for nm, fn in DEFAULT_MODELS]
    if len(models) > 26:
        sys.exit("At most 26 models.")
    for p in [args.gt] + [p for _, p in models]:
        if not os.path.exists(p):
            sys.exit(f"File not found: {p}\nPut the JSON files in the 'data' folder (see top of this file).")
    for p in (args.out, args.cache):
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)

    load = lambda p: {r["gt_uid"]: r for r in json.load(open(p, encoding="utf-8"))}
    G = load(args.gt)
    M = [load(p) for _, p in models]
    for gt_id, m_id in ID_ALIASES.items():  # re-key model records to the ground-truth ID
        if gt_id in G:
            for d in M:
                if m_id in d and gt_id not in d:
                    d[gt_id] = d.pop(m_id)
    names = [nm for nm, _ in models]
    ids = [i for i in G if all(i in d for d in M)]
    unmatched = (set(G).union(*map(set, M))) - set(ids)
    if args.limit:
        ids = ids[:args.limit]
    print(f"Ground truth {len(G)} | " + " | ".join(f"{nm} {len(d)}" for nm, d in zip(names, M)) + f" | comparing {len(ids)}")
    if unmatched:
        print("Not in every file (skipped):", ", ".join(sorted(unmatched)))

    judge = Judge(args.model, args.cache, args.offline, len(models))
    prepared = [(pid, *prepare(pid, G[pid], [d[pid] for d in M])) for pid in ids]
    todo = [(pid, pl) for pid, _, pl in prepared if pl and Judge.key(pid, pl) not in judge.cache]

    if todo and not args.offline:
        chars = sum(len(SYSTEM_PROMPT) + len(json.dumps(pl, ensure_ascii=False)) for _, pl in todo)
        est_in = chars / 3.5; est_out = sum(len(pl) * len(models) * 18 for _, pl in todo)
        cost = est_in / 1e6 * PRICE_IN + est_out / 1e6 * PRICE_OUT
        print(f"Judge calls needed: {len(todo)} (others solved in code or cached). "
              f"Estimated cost ≈ ${cost:.2f} with {args.model}.")
        if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
            sys.exit("Stopped.")

    results, errors = {}, 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(judge.grade, pid, pl): pid for pid, _, pl in prepared if pl}
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                results[pid] = fut.result()
            except Exception as e:
                errors += 1; results[pid] = None
                print(f"  ! {pid}: {type(e).__name__}: {str(e)[:150]}")
            if i % 100 == 0 or i == len(futs):
                print(f"  judged {i}/{len(futs)}  ({time.time() - t0:.0f}s)")

    rows = []
    for pid, row, pl in prepared:
        apply_judge(row, results.get(pid) if pl else {}, len(models))
        rows.append(row)

    info = {"judge": "offline string match" if args.offline else args.model,
            "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "errors": errors}
    write_excel(args.out, rows, names, unmatched, info)
    print_summary(rows, names, args.target)
    from report import write_report
    report_path = os.path.join(os.path.dirname(os.path.abspath(args.out)), "report.html")
    write_report(report_path, report_data(rows, names, args.target, info))
    print(f"Charts: {report_path}  (open in a browser)")
    u = judge.usage
    if u["calls"]:
        print(f"API calls {u['calls']} | tokens in {u['in']:,} out {u['out']:,} | "
              f"cost ≈ ${u['in'] / 1e6 * PRICE_IN + u['out'] / 1e6 * PRICE_OUT:.2f}")
    print(f"Saved: {args.out}" + (f"   ({errors} errors — re-run to retry)" if errors else ""))

if __name__ == "__main__":
    main()