#!/usr/bin/env python3
"""Export the judged results as small JSON files for the online dashboard.

Uses the saved judge answers (results/llm_judge/judge_cache.jsonl), so it makes no API calls.
Run judge_eval.py first. Writes results/llm_judge/dashboard/{scorecard,nutrients,products}.json
"""
import json, os
import judge_eval as J

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "llm_judge", "dashboard")
CACHE = os.path.join(HERE, "results", "llm_judge", "judge_cache.jsonl")


def main():
    os.makedirs(OUT, exist_ok=True)
    load = lambda p: {r["gt_uid"]: r for r in json.load(open(p, encoding="utf-8"))}
    G = load(os.path.join(HERE, "data", "ground_truth.json"))
    names = [nm for nm, _ in J.DEFAULT_MODELS]
    M = [load(os.path.join(HERE, "data", fn)) for _, fn in J.DEFAULT_MODELS]
    for gt_id, m_id in J.ID_ALIASES.items():
        for d in M:
            if m_id in d and gt_id not in d:
                d[gt_id] = d.pop(m_id)
    ids = [i for i in G if all(i in d for d in M)]
    judge = J.Judge("cache-only", CACHE, True, len(names))  # reads saved answers, no API calls
    rows, missing = [], 0
    for pid in ids:
        row, pl = J.prepare(pid, G[pid], [d[pid] for d in M])
        if pl and J.Judge.key(pid, pl) not in judge.cache:
            missing += 1
        J.apply_judge(row, judge.grade(pid, pl) if pl else {}, len(names))
        rows.append(row)
    if missing:
        raise SystemExit(f"{missing} products have no saved judge answer. Run judge_eval.py first.")

    def cnt(marks):
        s = [m for m in marks if m not in (J.NA, "?")]
        return s.count(J.OK), len(s)

    def rec(base, model, ok, n):
        return {**base, "model": model, "correct": ok, "checked": n,
                "accuracy_pct": round(100 * ok / n, 1) if n else None}

    scorecard = []
    for i, nm in enumerate(names):
        text = [r["fields"][f]["marks"][i][0] for r in rows for f in J.TEXT_FIELDS]
        code = [r["fields"][f]["marks"][i][0] for r in rows for f in J.CODE_FIELDS]
        nut = [x["marks"][i] for r in rows for x in r["nutrients"]]
        for item, marks in [("Overall", text + code + nut), ("Nutrient values", nut),
                            ("Codes and sizes", code), ("Text fields", text)]:
            scorecard.append(rec({"group": "Area", "item": item, "graded_by": "mixed"}, nm, *cnt(marks)))
        for f in J.FIELD_ORDER:
            g = "LLM judge" if f in J.TEXT_FIELDS else "exact check"
            scorecard.append(rec({"group": "Field", "item": J.LABEL[f], "graded_by": g}, nm,
                                 *cnt([r["fields"][f]["marks"][i][0] for r in rows])))

    order = []
    for r in rows:
        for x in r["nutrients"]:
            if x["nutrient"] not in order:
                order.append(x["nutrient"])
    nutrients = []
    for nt in order:
        per = [cnt([x["marks"][i] for r in rows for x in r["nutrients"] if x["nutrient"] == nt])
               for i in range(len(names))]
        products = max(n for _, n in per)
        for nm, (ok, n) in zip(names, per):
            nutrients.append(rec({"nutrient": nt, "products": products}, nm, ok, n))

    products = []
    for r in rows:
        for i, nm in enumerate(names):
            _, ok, n = J.product_verdict(r, i)
            products.append({"product_id": r["id"], "model": nm, "correct": ok, "checked": n})

    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    meta = [{"label": "export_dashboard_data.py", "value": src, "type": "code", "lang": "python"},
            {"label": "Input", "value": "ground_truth.json, gpt-6-sol.json, gemini-3.8-flash.json, "
                                       "claude-opus-5-5.json and the saved judge answers (judge_cache.jsonl)"},
            {"label": "Judge", "value": "gpt-4o-mini for text fields; exact check in code for numbers and codes"},
            {"label": "Products compared", "value": str(len(rows))}]
    for name, data in [("scorecard", scorecard), ("nutrients", nutrients), ("products", products)]:
        with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"rows": data, "meta": meta}, f, ensure_ascii=False)
        print(f"{name}.json: {len(data)} rows")


if __name__ == "__main__":
    main()
