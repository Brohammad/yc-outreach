#!/usr/bin/env python3
"""Import Kerala CSV sets → enrich → plan send queue.

Expects any of these in the repo root:
  - kerala_startup_priority_50_emails.csv  (wave 1)
  - kerala_all_public_emails.csv
  - kerala_research_150.csv

Usage:
  python3 kerala_pipeline.py import
  python3 kerala_pipeline.py enrich
  python3 kerala_pipeline.py plan --start "2026-11-09T10:00:00+05:30" --wave priority --dry-run
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
JSON = HERE / "kerala_startups.json"
ENRICHED = HERE / "kerala_startups_enriched.json"

EXPECTED = (
    "kerala_startup_priority_50_emails.csv",
    "kerala_all_public_emails.csv",
    "kerala_research_150.csv",
)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, cwd=HERE, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import", help="merge Kerala CSVs → kerala_startups.json")
    p_en = sub.add_parser("enrich", help="fetch site emails / guesses")
    p_en.add_argument("--limit", type=int, default=0)
    p_plan = sub.add_parser("plan", help="build outreach_queue.json")
    p_plan.add_argument("--start", required=True)
    p_plan.add_argument("--every", default="20m")
    p_plan.add_argument("--queue", default="outreach_queue.json")
    p_plan.add_argument("--wave", default="", help="priority = only priority 50; empty = all merged")
    p_plan.add_argument("--dry-run", action="store_true")
    p_plan.add_argument("--merge", action="store_true")
    sub.add_parser("all", help="import + enrich")
    args = ap.parse_args()

    if args.cmd == "import":
        run([sys.executable, "startup_import.py", "--kerala-set", "--out", str(JSON)])
    elif args.cmd == "enrich":
        if not JSON.is_file():
            run([sys.executable, "kerala_pipeline.py", "import"])
        cmd = [sys.executable, "startup_enrich.py", "--input", str(JSON), "--out", str(ENRICHED)]
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        run(cmd)
    elif args.cmd == "plan":
        if not ENRICHED.is_file():
            run([sys.executable, "kerala_pipeline.py", "enrich"])
        cmd = [
            sys.executable,
            "outreach_mailer.py",
            "plan",
            "--input",
            str(ENRICHED),
            "--start",
            args.start,
            "--every",
            args.every,
            "--queue",
            args.queue,
        ]
        if args.wave:
            cmd += ["--wave", args.wave]
        if args.dry_run:
            cmd.append("--dry-run")
        if args.merge:
            cmd.append("--merge")
        run(cmd)
    elif args.cmd == "all":
        run([sys.executable, "kerala_pipeline.py", "import"])
        run([sys.executable, "kerala_pipeline.py", "enrich"])


if __name__ == "__main__":
    main()
