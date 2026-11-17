#!/usr/bin/env python3
"""
Local web server for the LishePoa validation site.

    python3 serve.py                 # http://localhost:8000  (this computer only)
    python3 serve.py --lan           # also reachable by teammates on the same Wi-Fi/LAN
    python3 serve.py --port 9000

Pages (site/):
    /                      Overview
    /regex.html            ① Regex comparison
    /llm-judge.html        ② LLM judge
    /manual-review.html    ③ Manual review (needs this server to save work)

Data (read-only, from results/):
    /data/comparison.json        regex per-record, per-field results
    /data/llm_judge_rows.json    LLM-judge per-product marks
    /data/regex_summary.json     regex per-model summary

Manual-review API (one JSON file per reviewer in reviews/, so every reviewer's
work can be committed to git without merge conflicts):
    GET  /api/reviews            -> {"Clive": {...}, "Abigail": {...}, "Roda": {...}}
    PUT  /api/reviews/<name>     body = that reviewer's full document

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
RESULTS = ROOT / "results"
REVIEWS = ROOT / "reviews"
REVIEWERS = ("Clive", "Abigail", "Roda")
DATA_FILES = {"comparison.json", "llm_judge_rows.json", "regex_summary.json"}
MAX_BODY = 5 * 1024 * 1024
_write_lock = threading.Lock()


def empty_doc(name: str) -> dict:
    return {"reviewer": name, "version": 1, "batches": [], "reviews": {}}


def load_doc(name: str) -> dict:
    path = REVIEWS / f"{name.lower()}.json"
    if not path.exists():
        return empty_doc(name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_doc(name)


def save_doc(name: str, doc: dict) -> None:
    REVIEWS.mkdir(exist_ok=True)
    path = REVIEWS / f"{name.lower()}.json"
    with _write_lock:  # write to a temp file then rename, so a crash never leaves half a file
        fd, tmp = tempfile.mkstemp(dir=REVIEWS, prefix=f".{name.lower()}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)


def valid_doc(name: str, doc: object) -> str | None:
    if not isinstance(doc, dict):
        return "body must be a JSON object"
    if doc.get("reviewer") != name:
        return "reviewer in body does not match URL"
    if not isinstance(doc.get("batches"), list) or not isinstance(doc.get("reviews"), dict):
        return "body needs 'batches' (list) and 'reviews' (object)"
    return None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def log_message(self, fmt, *args):  # quieter log: only API calls and errors
        if "/api/" in self.path or (args and str(args[1]).startswith(("4", "5"))):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, status: int, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/reviews":
            return self._json(200, {n: load_doc(n) for n in REVIEWERS})
        if path.startswith("/data/"):
            name = path[len("/data/"):]
            if name not in DATA_FILES or not (RESULTS / name).exists():
                return self._json(404, {"error": f"{name} not found. Run compare.py / judge_eval.py first."})
            body = (RESULTS / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        return super().do_GET()

    def do_PUT(self):
        m = re.fullmatch(r"/api/reviews/([A-Za-z]+)", unquote(urlparse(self.path).path))
        if not m:
            return self._json(404, {"error": "unknown endpoint"})
        name = next((r for r in REVIEWERS if r.lower() == m.group(1).lower()), None)
        if not name:
            return self._json(400, {"error": f"unknown reviewer; expected one of {', '.join(REVIEWERS)}"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "empty or too large body"})
        try:
            doc = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON"})
        err = valid_doc(name, doc)
        if err:
            return self._json(400, {"error": err})
        save_doc(name, doc)
        return self._json(200, {"ok": True, "saved": f"reviews/{name.lower()}.json"})

    do_POST = do_PUT


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces so teammates on the LAN can connect")
    a = ap.parse_args()
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    srv = ThreadingHTTPServer((host, a.port), Handler)
    print(f"LishePoa validation site: http://localhost:{a.port}/")
    if a.lan:
        print("LAN mode: teammates open http://<this-computer's-IP>:%d/  (find the IP with: hostname -I)" % a.port)
    print("Manual reviews are saved to reviews/<name>.json. Commit them to share progress. Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
