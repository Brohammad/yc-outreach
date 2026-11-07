#!/usr/bin/env python3
"""Import a Kerala / local startup list into the same JSON shape as yc_scraper output.

Supports:
  - JSON array of company objects (see kerala_startups.example.json)
  - CSV export (one row per founder; repeated company name merges founders)

Usage:
  python3 startup_import.py --csv your_list.csv --out kerala_startups.json
  python3 startup_import.py --json messy_list.json --out kerala_startups.json
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (name or "company").lower()).strip("-")
    return s or "company"


def norm_founder(row: dict) -> dict:
    name = (row.get("founder") or row.get("founder_name") or row.get("name_person") or "").strip()
    if not name or name == row.get("company"):
        return {}
    out = {"name": name, "title": (row.get("title") or row.get("founder_title") or "").strip() or None}
    email = (row.get("email") or row.get("founder_email") or "").strip().lower()
    if email:
        out["emails_found"] = [email]
        out["apify_email"] = email
        out["apify_email_status"] = "valid"
    linkedin = (row.get("linkedin") or row.get("founder_linkedin") or "").strip()
    if linkedin:
        out["linkedin"] = linkedin
    return out


def normalize_company(raw: dict) -> dict:
    name = (raw.get("company") or raw.get("name") or "").strip()
    if not name:
        raise ValueError("company missing name")
    slug = (raw.get("slug") or raw.get("id") or slugify(name)).strip()
    founders = list(raw.get("founders") or [])
    if not founders and (raw.get("founder") or raw.get("founder_name")):
        f = norm_founder(raw)
        if f:
            founders = [f]
    fixed = []
    for f in founders:
        if not isinstance(f, dict):
            fixed.append({"name": str(f)})
            continue
        row = dict(f)
        email = (row.pop("email", None) or "").strip().lower()
        if email and not row.get("emails_found"):
            row["emails_found"] = [email]
            row["apify_email"] = email
            row["apify_email_status"] = "valid"
        fixed.append(row)
    founders = fixed
    return {
        "slug": slug,
        "name": name,
        "batch": raw.get("batch") or raw.get("batch_label") or "Kerala startups",
        "location": raw.get("location") or raw.get("city") or "Kerala, India",
        "website": raw.get("website") or raw.get("url") or "",
        "one_liner": raw.get("one_liner") or raw.get("description") or raw.get("tagline") or "",
        "industry": raw.get("industry") or raw.get("sector") or "",
        "tags": raw.get("tags") or [],
        "source": raw.get("source") or "kerala_list",
        "founders": founders,
    }


def merge_csv_rows(rows: list[dict]) -> list[dict]:
    by_name: dict[str, dict] = {}
    for row in rows:
        name = (row.get("company") or row.get("name") or "").strip()
        if not name:
            continue
        base = by_name.get(name.lower())
        if not base:
            base = normalize_company({**row, "company": name, "founders": []})
            by_name[name.lower()] = base
        f = norm_founder({**row, "company": name})
        if f and not any(x.get("name") == f.get("name") for x in base["founders"]):
            base["founders"].append({k: v for k, v in f.items() if v})
    return list(by_name.values())


def load_json(path: pathlib.Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "companies" in data:
        items = data["companies"]
    elif isinstance(data, list):
        items = data
    else:
        sys.exit("JSON must be a list or {\"companies\": [...]}")
    return [normalize_company(x) for x in items]


def load_csv(path: pathlib.Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        sys.exit("CSV is empty")
    # normalize header keys
    cleaned = []
    for row in rows:
        cleaned.append({k.strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()})
    return merge_csv_rows(cleaned)


def main() -> None:
    ap = argparse.ArgumentParser(description="Import local startup list for outreach_mailer.py")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=pathlib.Path)
    src.add_argument("--json", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=HERE / "kerala_startups.json")
    a = ap.parse_args()
    companies = load_csv(a.csv) if a.csv else load_json(a.json)
    a.out.write_text(json.dumps(companies, indent=2, ensure_ascii=False) + "\n")
    n_founders = sum(len(c.get("founders") or []) for c in companies)
    print(f"Wrote {len(companies)} companies, {n_founders} founders → {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
