#!/usr/bin/env python3
"""
LishePoa product-extraction validator.

Compares each model's extracted product JSON against ground_truth.json and
scores every record field-by-field. All text/number normalisation is done
with regular expressions so that cosmetic differences (case, punctuation,
"&" vs "and", "E 330" vs "E330", "1,5" vs "1.5", "Per 100ml" vs "PER 100 ML")
are not counted as errors, while real differences (wrong values, missing
nutrients, wrong brand, invented numbers) are.

Records are matched on gt_uid first, then on record_id (handles GT splits
such as F406 -> F406_1 / F406_2, where the best-scoring candidate wins).

A record PASSES when its weighted accuracy >= --threshold (default 0.80).

Usage:
    python3 compare.py                       # default files, threshold 0.80
    python3 compare.py --threshold 0.85
    python3 compare.py --gt ground_truth.json --model "Claude=claude.json" ...

Outputs:
    results/comparison.json   full per-record, per-field results
    results/summary.csv       one row per model
    results/records.csv       one row per record x model
    ui/data.js                data bundle loaded by ui/index.html
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent

DEFAULT_MODELS = [
    ("Claude Opus 5.5", "claude-opus-5-5.json"),
    ("GPT-6 Sol", "gpt-6-sol.json"),
    ("Gemini 3.8 Flash", "gemini-3.8-flash.json"),
]

# Group weights for the record-level score (renormalised over applicable groups).
GROUP_WEIGHTS = {
    "identity": 20,
    "package": 10,
    "basis": 10,
    "nutrients": 40,
    "ingredients": 15,
    "label": 5,
}

# --------------------------------------------------------------------------- #
# Regex toolkit
# --------------------------------------------------------------------------- #
RE_WS = re.compile(r"\s+")
RE_AMP = re.compile(r"\s*&\s*")
RE_PUNCT = re.compile(r"[^\w%.\s]|_")          # keep %, decimal points, word chars
RE_STRAY_DOT = re.compile(r"(?<!\d)\.|\.(?!\d)")  # dots that are not decimal points
RE_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d{1,2}\b)")  # 1,5 -> 1.5 (not 1,000)
RE_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")       # 1,000 -> 1000
RE_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
RE_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)?%?")
RE_ENUM = re.compile(r"\b(?:e|ins)\s*-?\s*(\d{3,4}[a-z]?(?:\s*\(?[ivx]+\)?)?)", re.I)
RE_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
RE_DIGITS = re.compile(r"\D+")
RE_BASIS = re.compile(r"per\s*(\d+(?:\.\d+)?)?\s*(g|ml|gm|gms|grams?|millilit(?:re|er)s?)\b", re.I)
RE_UNIT_ALIASES = [
    (re.compile(r"^(g|gm|gms|gr|grams?)$"), "g"),
    (re.compile(r"^(kg|kgs|kilo(gram)?s?)$"), "kg"),
    (re.compile(r"^(ml|mls|millilit(re|er)s?)$"), "ml"),
    (re.compile(r"^(l|ltr|ltrs|lit(re|er)s?)$"), "l"),
]
UNIT_TO_BASE = {"g": ("g", 1.0), "kg": ("g", 1000.0), "ml": ("ml", 1.0), "l": ("ml", 1000.0)}


def norm_text(s: Any) -> str:
    """Lower-case, unify '&'/'and', decimal commas, drop punctuation, collapse spaces."""
    if s is None:
        return ""
    t = str(s).lower()
    t = RE_DECIMAL_COMMA.sub(".", t)
    t = RE_THOUSANDS.sub("", t)
    t = RE_AMP.sub(" and ", t)
    t = RE_PUNCT.sub(" ", t)
    t = RE_STRAY_DOT.sub(" ", t)
    return RE_WS.sub(" ", t).strip()


def tokens(s: Any) -> list[str]:
    return RE_TOKEN.findall(norm_text(s))


def norm_unit(u: Any) -> str:
    t = norm_text(u).replace(" ", "")
    for rx, canon in RE_UNIT_ALIASES:
        if rx.match(t):
            return canon
    return t


def e_numbers(s: Any) -> set[str]:
    return {RE_WS.sub("", m).lower().replace("(", "").replace(")", "")
            for m in RE_ENUM.findall(str(s or ""))}


def percentages(s: Any) -> set[str]:
    return {f"{float(p.replace(',', '.')):g}%" for p in RE_PERCENT.findall(str(s or ""))}


def first_number(s: Any) -> float | None:
    m = RE_NUMBER.search(RE_DECIMAL_COMMA.sub(".", str(s or "")))
    return float(m.group()) if m else None


def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == [] or v == {}


# --------------------------------------------------------------------------- #
# Similarity primitives (all return 0..1)
# --------------------------------------------------------------------------- #
def dice(a: list[str], b: list[str]) -> float:
    """Multiset Dice coefficient over tokens."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    return 2 * sum((ca & cb).values()) / (len(a) + len(b))


def recall(gt: list[str], other: list[str]) -> float:
    """Share of GT tokens present in the other text."""
    if not gt:
        return 1.0
    from collections import Counter
    cg, co = Counter(gt), Counter(other)
    return sum((cg & co).values()) / len(gt)


def seq_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=len(a) > 400).ratio()


def num_close(gt: float, m: float) -> float:
    """1.0 within 2% (or 0.05 abs), 0.5 within 10%, else 0."""
    diff = abs(gt - m)
    scale = abs(gt)
    if diff <= max(0.02 * scale, 0.05):
        return 1.0
    if diff <= max(0.10 * scale, 0.1):
        return 0.5
    return 0.0


# --------------------------------------------------------------------------- #
# Field comparators: (gt_value, model_value) -> score 0..1 or None (= skip)
# --------------------------------------------------------------------------- #
def cmp_short_text(g: Any, m: Any) -> float:
    a, b = norm_text(g), norm_text(m)
    if a == b:
        return 1.0
    return round(0.5 * dice(tokens(g), tokens(m)) + 0.5 * seq_ratio(a, b), 4)


RE_LEGAL_SUFFIX = re.compile(
    r"\b(?:ltd|limited|plc|inc|llc|co|company|corp(?:oration)?|s\s?a\s?e|s\s?a|gmbh|bv|pvt|private|k)\b")
RE_ADDRESS_TAIL = re.compile(r",.*$")  # 'HAPPY COW LTD, P.O BOX 558, NAKURU' -> 'HAPPY COW LTD'
COUNTRY_ALIASES = [
    (re.compile(r"^(?:t[uü]rkiye|turkey)$"), "turkey"),
    (re.compile(r"^(?:usa|us|u s a|united states(?: of america)?|america)$"), "united states"),
    (re.compile(r"^(?:uk|u k|great britain|britain|england|united kingdom)$"), "united kingdom"),
    (re.compile(r"^(?:uae|u a e|united arab emirates)$"), "united arab emirates"),
    (re.compile(r"^(?:a r e|are|arab republic of egypt|egypt)$"), "egypt"),
    (re.compile(r"^(?:holland|the netherlands|netherlands)$"), "netherlands"),
    (re.compile(r"^(?:made in )?kenya$"), "kenya"),
]


def cmp_name(g: Any, m: Any) -> float:
    """Order-insensitive: rewards covering every GT word, lightly penalises extra descriptors."""
    tg, tm = tokens(g), tokens(m)
    if norm_text(g) == norm_text(m) or sorted(tg) == sorted(tm):
        return 1.0
    return round(0.6 * recall(tg, tm) + 0.4 * dice(tg, tm), 4)


def cmp_company(g: Any, m: Any) -> float:
    def clean(v: Any) -> str:
        return RE_LEGAL_SUFFIX.sub(" ", norm_text(RE_ADDRESS_TAIL.sub("", str(v))))
    return cmp_name(clean(g), clean(m))


def norm_country(v: Any) -> str:
    t = norm_text(v).replace(".", " ")
    t = RE_WS.sub(" ", t).strip()
    for rx, canon in COUNTRY_ALIASES:
        if rx.match(t):
            return canon
    return t


def cmp_country(g: Any, m: Any) -> float:
    return 1.0 if norm_country(g) == norm_country(m) else 0.0


def cmp_exact(g: Any, m: Any) -> float:
    return 1.0 if norm_text(g) == norm_text(m) else 0.0


def cmp_barcode(g: Any, m: Any) -> float:
    """UPC-A '0721...' == EAN-13 '0721...' after stripping leading zeros.
    If one code is the other plus/minus a check digit, give partial credit."""
    a, b = RE_DIGITS.sub("", str(g)).lstrip("0"), RE_DIGITS.sub("", str(m)).lstrip("0")
    if a == b:
        return 1.0
    if a and b and (a.startswith(b) or b.startswith(a)) and abs(len(a) - len(b)) == 1:
        return 0.75
    return 0.0


def cmp_unit(g: Any, m: Any) -> float:
    return 1.0 if norm_unit(g) == norm_unit(m) else 0.0


def cmp_number(g: Any, m: Any) -> float:
    gv, mv = first_number(g), first_number(m)
    if gv is None or mv is None:
        return cmp_exact(g, m)
    return num_close(gv, mv)


def cmp_ingredients(g: Any, m: Any) -> float:
    """Token Dice + sequence order + recall of key facts (E-numbers, percentages)."""
    tg, tm = tokens(g), tokens(m)
    score = 0.55 * dice(tg, tm) + 0.25 * seq_ratio(norm_text(g), norm_text(m))
    facts_g = e_numbers(g) | percentages(g)
    if facts_g:
        facts_m = e_numbers(m) | percentages(m)
        score += 0.20 * len(facts_g & facts_m) / len(facts_g)
    else:
        score /= 0.80
    return round(score, 4)


def cmp_label(g: Any, m: Any) -> float:
    """Free-text label info: models often add extra lines, so score GT recall."""
    return round(recall(tokens(g), tokens(m)), 4)


def package_size(pkg: dict) -> tuple[float | None, str]:
    size, unit = pkg.get("size"), norm_unit(pkg.get("unit"))
    if size is None:
        return None, unit
    base, factor = UNIT_TO_BASE.get(unit, (unit, 1.0))
    return float(size) * factor, base


def basis_signature(nb: dict) -> str:
    """Canonical nutrition-basis string, e.g. 'per_100g', 'per_serving'."""
    t = (nb.get("type") or "").lower()
    if t and t != "unknown":
        return t
    m = RE_BASIS.search(str(nb.get("raw") or ""))
    if m:
        amt = m.group(1) or "100"
        return f"per_{float(amt):g}{norm_unit(m.group(2))}"
    return t or ""


# --------------------------------------------------------------------------- #
# Nutrient comparison
# --------------------------------------------------------------------------- #
def nutrient_repr(n: dict | None) -> str | None:
    if not n:
        return None
    q = n.get("qualifier")
    if n.get("range"):
        lo, hi = n["range"]
        return f"{lo:g}–{hi:g} {n.get('unit') or ''}".strip()
    v = n.get("value")
    if v is None:
        return f"{q or n.get('raw') or '?'}"
    prefix = {"<": "<", ">": ">", "min": "min ", "max": "max ", "trace": "trace "}.get(q or "", "")
    return f"{prefix}{v:g} {n.get('unit') or ''}".strip()


def cmp_nutrient(g: dict, m: dict) -> float:
    # Range vs range
    if g.get("range") or m.get("range"):
        gr, mr = g.get("range"), m.get("range")
        if gr and mr:
            return min(num_close(gr[0], mr[0]), num_close(gr[1], mr[1]))
        return 0.25
    gv, mv = g.get("value"), m.get("value")
    if gv is None:
        gv = first_number(g.get("raw"))
    if mv is None:
        mv = first_number(m.get("raw"))
    if gv is None or mv is None:
        # Non-numeric (e.g. 'trace', 'present'): compare qualifiers / raw text
        return 1.0 if norm_text(g.get("qualifier") or g.get("raw")) == norm_text(
            m.get("qualifier") or m.get("raw")) else 0.0
    gv, mv = float(gv), float(mv)
    score = num_close(gv, mv)
    # Unit-aware: one side declared '%' (e.g. "20% min") while the other used a
    # fraction (0.2) or grams-per-100g (20). Accept whichever reading agrees.
    gu, mu = (g.get("unit") or "").strip(), (m.get("unit") or "").strip()
    if score < 1 and (gu == "%") != (mu == "%"):
        alt = mv / 100 if mu == "%" else mv * 100
        score = max(score, num_close(gv, alt))
    # A bound qualifier ('<', 'min', ...) vs a plain value is a real nuance: small penalty.
    if bound_qualifier(g) != bound_qualifier(m) and score > 0:
        score -= 0.25
    return max(score, 0.0)


BOUND_QUALIFIERS = {"<": "<", ">": ">", "min": ">=", "max": "<="}


def bound_qualifier(n: dict) -> str:
    """'nil', 'not_detected', 'not_stated' etc. carry no bound -> treated as plain values."""
    return BOUND_QUALIFIERS.get((n.get("qualifier") or "").lower(), "")


# --------------------------------------------------------------------------- #
# Record comparison
# --------------------------------------------------------------------------- #
FieldSpec = tuple[str, str, Callable[[dict], Any], Callable[[Any, Any], float], float, bool]
#                key   group  getter                comparator             weight penalise_extra

FIELDS: list[FieldSpec] = [
    ("product.name", "identity", lambda r: r["product"].get("name"), cmp_name, 6, False),
    ("product.brand", "identity", lambda r: r["product"].get("brand"), cmp_company, 5, False),
    ("product.manufacturer", "identity", lambda r: r["product"].get("manufacturer"), cmp_company, 2, False),
    ("product.category", "identity", lambda r: r["product"].get("category"), cmp_exact, 3, False),
    ("product.country_of_origin", "identity", lambda r: r["product"].get("country_of_origin"), cmp_country, 1, False),
    ("product.barcode", "identity", lambda r: r["product"].get("barcode"), cmp_barcode, 3, False),
    ("package.size", "package", lambda r: package_size(r["package"])[0], cmp_number, 4, False),
    ("package.unit", "package", lambda r: r["package"].get("unit"), cmp_unit, 2, False),
    ("package.count", "package", lambda r: r["package"].get("count"), cmp_number, 1, False),
    ("package.type", "package", lambda r: r["package"].get("type"), cmp_short_text, 2, False),
    ("nutrition_basis.type", "basis", lambda r: basis_signature(r["nutrition_basis"]) or None, cmp_exact, 5, False),
    ("nutrition_basis.amount", "basis", lambda r: r["nutrition_basis"].get("amount"), cmp_number, 2, False),
    ("serving_size.amount", "basis", lambda r: r["serving_size"].get("amount"), cmp_number, 2, False),
    ("serving_size.unit", "basis", lambda r: r["serving_size"].get("unit"), cmp_unit, 1, False),
    ("ingredients_verbatim", "ingredients", lambda r: r.get("ingredients_verbatim"), cmp_ingredients, 1, False),
    ("other_label_information", "label", lambda r: r.get("other_label_information"), cmp_label, 1, False),
]


def display(v: Any) -> Any:
    if isinstance(v, float):
        return f"{v:g}"
    return v


def compare_record(gt: dict, md: dict, penalise_extra_nutrients: bool) -> dict:
    fields: list[dict] = []
    group_acc: dict[str, list[float]] = {g: [0.0, 0.0] for g in GROUP_WEIGHTS}  # [weighted score, weight]

    for key, group, get, cmp, w, pen_extra in FIELDS:
        gv, mv = get(gt), get(md)
        if is_blank(gv) and is_blank(mv):
            continue
        if is_blank(gv):
            status, score = "extra", (0.0 if pen_extra else None)
        elif is_blank(mv):
            status, score = "missing", 0.0
        else:
            score = cmp(gv, mv)
            status = "match" if score >= 0.95 else ("partial" if score >= 0.5 else "mismatch")
        if key == "package.size":  # show original value + unit for readability
            gv = f"{gt['package'].get('size'):g} {gt['package'].get('unit') or ''}".strip() if gv is not None else None
            mv = f"{md['package'].get('size'):g} {md['package'].get('unit') or ''}".strip() if mv is not None else None
        fields.append({"key": key, "group": group, "gt": display(gv), "model": display(mv),
                       "score": score, "status": status})
        if score is not None:
            group_acc[group][0] += score * w
            group_acc[group][1] += w

    # Nutrients: union of keys present in either record
    gn, mn = gt.get("nutrients") or {}, md.get("nutrients") or {}
    for key in sorted(set(gn) | set(mn)):
        g, m = gn.get(key), mn.get(key)
        if not g and not m:
            continue
        if not g:
            status, score = "extra", (0.0 if penalise_extra_nutrients else None)
        elif not m:
            status, score = "missing", 0.0
        else:
            score = cmp_nutrient(g, m)
            status = "match" if score >= 0.95 else ("partial" if score >= 0.5 else "mismatch")
        fields.append({"key": f"nutrients.{key}", "group": "nutrients", "gt": nutrient_repr(g),
                       "model": nutrient_repr(m), "score": score, "status": status})
        if score is not None:
            group_acc["nutrients"][0] += score
            group_acc["nutrients"][1] += 1

    groups = {g: (round(s / w, 4) if w else None) for g, (s, w) in group_acc.items()}
    num = sum(groups[g] * GROUP_WEIGHTS[g] for g in groups if groups[g] is not None)
    den = sum(GROUP_WEIGHTS[g] for g in groups if groups[g] is not None)
    return {"score": round(num / den, 4) if den else 0.0, "groups": groups, "fields": fields}


RE_BASE_ID = re.compile(r"^(?P<base>[A-Za-z]+\d+)(?:_\d+)?$")


def base_id(uid: str) -> str:
    m = RE_BASE_ID.match(uid or "")
    return m.group("base") if m else (uid or "")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run(gt_path: Path, models: list[tuple[str, Path]], threshold: float,
        penalise_extra: bool, out_dir: Path, ui_dir: Path) -> dict:
    gt_records = json.loads(gt_path.read_text())
    gt_by_uid = {r["gt_uid"]: r for r in gt_records}
    gt_by_rid: dict[str, list[dict]] = {}
    for r in gt_records:
        gt_by_rid.setdefault(base_id(r.get("record_id") or r["gt_uid"]), []).append(r)

    # results[gt_uid][model_name] = comparison
    results: dict[str, dict[str, dict]] = {r["gt_uid"]: {} for r in gt_records}
    match_log: dict[str, dict[str, int]] = {}
    extras: dict[str, list[str]] = {}

    for name, path in models:
        recs = json.loads(path.read_text())
        log = {"by_gt_uid": 0, "by_record_id": 0, "unmatched": 0}
        extras[name] = []
        for md in recs:
            uid = md.get("gt_uid")
            if uid in gt_by_uid:
                cands, how = [gt_by_uid[uid]], "by_gt_uid"
            else:
                cands = gt_by_rid.get(base_id(md.get("record_id") or uid or ""), [])
                how = "by_record_id"
            if not cands:
                log["unmatched"] += 1
                extras[name].append(uid)
                continue
            scored = [(compare_record(g, md, penalise_extra), g) for g in cands]
            best, g = max(scored, key=lambda x: x[0]["score"])
            best["matched_by"] = how
            best["model_id"] = uid
            best["pass"] = best["score"] >= threshold
            prev = results[g["gt_uid"]].get(name)
            if prev is None or best["score"] > prev["score"]:
                results[g["gt_uid"]][name] = best
            log[how] += 1
        match_log[name] = log

    # ---- Aggregate ----
    model_names = [n for n, _ in models]
    summary = {}
    for name in model_names:
        rows = [results[u][name] for u in results if name in results[u]]
        n = len(rows)
        status_counts: dict[str, int] = {}
        group_tot: dict[str, list[float]] = {g: [0.0, 0] for g in GROUP_WEIGHTS}
        field_tot: dict[str, list[float]] = {}
        for r in rows:
            for g, v in r["groups"].items():
                if v is not None:
                    group_tot[g][0] += v
                    group_tot[g][1] += 1
            for f in r["fields"]:
                status_counts[f["status"]] = status_counts.get(f["status"], 0) + 1
                if f["score"] is not None:
                    acc = field_tot.setdefault(f["key"], [0.0, 0])
                    acc[0] += f["score"]
                    acc[1] += 1
        passed = sum(r["pass"] for r in rows)
        summary[name] = {
            "matched": n,
            "missing_records": len(gt_records) - n,
            "passed": passed,
            "failed": n - passed,
            "pass_rate": round(passed / n, 4) if n else 0,
            "mean_score": round(sum(r["score"] for r in rows) / n, 4) if n else 0,
            "groups": {g: round(s / c, 4) if c else None for g, (s, c) in group_tot.items()},
            "fields": {k: {"accuracy": round(s / c, 4), "n": c} for k, (s, c) in field_tot.items()},
            "field_status": status_counts,
            "match_log": match_log[name],
            "unmatched_model_ids": extras[name],
        }

    records_out = []
    for r in gt_records:
        uid = r["gt_uid"]
        per_model = results[uid]
        # Merge per-field values into one side-by-side row per field key
        field_rows: dict[str, dict] = {}
        for name in model_names:
            cmp_ = per_model.get(name)
            if not cmp_:
                continue
            for f in cmp_["fields"]:
                row = field_rows.setdefault(f["key"], {"key": f["key"], "group": f["group"], "gt": f["gt"], "m": {}})
                if row["gt"] is None and f["gt"] is not None:
                    row["gt"] = f["gt"]
                row["m"][name] = {"v": f["model"], "s": f["score"], "st": f["status"]}
        records_out.append({
            "uid": uid,
            "record_id": r.get("record_id"),
            "collector": r.get("collector"),
            "name": r["product"].get("name"),
            "brand": r["product"].get("brand"),
            "category": r["product"].get("category"),
            "models": {name: {"score": c["score"], "pass": c["pass"], "groups": c["groups"],
                              "matched_by": c["matched_by"], "model_id": c["model_id"]}
                       for name, c in per_model.items()},
            "fields": list(field_rows.values()),
        })

    bundle = {
        "meta": {"ground_truth": gt_path.name, "models": model_names,
                 "model_files": {n: p.name for n, p in models},
                 "threshold": threshold, "group_weights": GROUP_WEIGHTS,
                 "gt_records": len(gt_records), "penalise_extra_nutrients": penalise_extra},
        "summary": summary,
        "records": records_out,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    ui_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    (ui_dir / "data.js").write_text("window.COMPARISON = " + json.dumps(bundle, ensure_ascii=False,
                                                                        separators=(",", ":")) + ";\n")

    with (out_dir / "summary.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "matched", "passed", "failed", "pass_rate", "mean_score", *GROUP_WEIGHTS])
        for name, s in summary.items():
            w.writerow([name, s["matched"], s["passed"], s["failed"], s["pass_rate"], s["mean_score"],
                        *[s["groups"][g] for g in GROUP_WEIGHTS]])

    with (out_dir / "records.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["gt_uid", "product", "brand", "model", "score", "pass", *GROUP_WEIGHTS])
        for rec in records_out:
            for name in model_names:
                c = rec["models"].get(name)
                if c:
                    w.writerow([rec["uid"], rec["name"], rec["brand"], name, c["score"],
                                "YES" if c["pass"] else "NO", *[c["groups"][g] for g in GROUP_WEIGHTS]])
                else:
                    w.writerow([rec["uid"], rec["name"], rec["brand"], name, "", "MISSING"])
    return bundle


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gt", default=str(ROOT / "ground_truth.json"))
    ap.add_argument("--model", action="append", metavar="NAME=PATH",
                    help="model output to compare (repeatable). Defaults to the three bundled files.")
    ap.add_argument("--threshold", type=float, default=0.80, help="pass threshold, 0..1 (default 0.80)")
    ap.add_argument("--no-penalise-extra", action="store_true",
                    help="don't penalise nutrients reported by a model but absent from GT")
    ap.add_argument("--out", default=str(ROOT / "results"))
    ap.add_argument("--ui", default=str(ROOT / "ui"))
    a = ap.parse_args()

    if a.model:
        models = [(s.split("=", 1)[0], Path(s.split("=", 1)[1])) for s in a.model]
    else:
        models = [(n, ROOT / f) for n, f in DEFAULT_MODELS]

    b = run(Path(a.gt), models, a.threshold, not a.no_penalise_extra, Path(a.out), Path(a.ui))
    print(f"Ground truth: {b['meta']['gt_records']} records | threshold {a.threshold:.0%}\n")
    hdr = f"{'Model':<20}{'Matched':>8}{'Pass':>7}{'Fail':>7}{'Pass%':>8}{'Mean':>8}  " + " ".join(
        f"{g[:6]:>7}" for g in GROUP_WEIGHTS)
    print(hdr)
    print("-" * len(hdr))
    for n, s in b["summary"].items():
        print(f"{n:<20}{s['matched']:>8}{s['passed']:>7}{s['failed']:>7}{s['pass_rate']:>8.1%}{s['mean_score']:>8.1%}  "
              + " ".join(f"{(s['groups'][g] or 0):>7.1%}" for g in GROUP_WEIGHTS))
    print(f"\nWrote {a.out}/comparison.json, summary.csv, records.csv and {a.ui}/data.js")


if __name__ == "__main__":
    main()
