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
DEFAULT_PRIORITY_CSV = HERE / "kerala_startup_priority_50_emails.csv"
KERALA_CSV_SET = (
    ("priority", HERE / "kerala_startup_priority_50_emails.csv"),
    ("public", HERE / "kerala_all_public_emails.csv"),
    ("research", HERE / "kerala_research_150.csv"),
)
WAVE_RANK = {"priority": 0, "public": 1, "research": 2}

HEADER_ALIASES = {
    "startup": "company",
    "startup_name": "company",
    "company_name": "company",
    "organisation": "company",
    "organization": "company",
    "contact_email": "email",
    "founder_email": "email",
    "ceo_email": "email",
    "email_address": "email",
    "e_mail": "email",
    "contact_name": "founder",
    "founder_name": "founder",
    "contact": "founder",
    "ceo": "founder",
    "description": "one_liner",
    "tagline": "one_liner",
    "sector": "industry",
    "url": "website",
    "website_url": "website",
    "city": "location",
    "public_email": "email",
}


EMAIL_IN_PUBLIC_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
OUTREACH_LOCAL_PREFIXES = (
    "careers",
    "jobs",
    "hr",
    "hiring",
    "talent",
    "recruit",
    "hello",
    "contact",
    "letstalk",
    "connect",
    "info",
    "india",
)


def parse_public_emails_field(value: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in (value or "").split(";"):
        part = part.strip()
        if not part:
            continue
        m = EMAIL_IN_PUBLIC_RE.search(part.replace("u003e", ""))
        if not m:
            continue
        e = m.group(1).lower()
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def pick_outreach_email(emails: list[str]) -> str:
    if not emails:
        return ""
    if len(emails) == 1:
        return emails[0]

    def rank(e: str) -> tuple[int, str]:
        local = e.split("@", 1)[0].lower()
        for i, pref in enumerate(OUTREACH_LOCAL_PREFIXES):
            if local.startswith(pref) or pref in local:
                return (i, e)
        return (len(OUTREACH_LOCAL_PREFIXES), e)

    return min(emails, key=rank)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (name or "company").lower()).strip("-")
    return s or "company"


def norm_founder(row: dict) -> dict:
    company = (row.get("company") or "").strip()
    name = (row.get("founder") or row.get("founder_name") or row.get("name_person") or "").strip()
    if not name and row.get("name") and row.get("name") != company:
        name = row["name"].strip()
    raw_public = row.get("public_emails") or ""
    parsed = parse_public_emails_field(raw_public) if raw_public else []
    email = (row.get("email") or row.get("founder_email") or pick_outreach_email(parsed) or "").strip().lower()
    if not name and email:
        name = "Founder"
    if not name and not email:
        return {}
    if name == company:
        name = "Founder" if email else ""
    if not name:
        return {}
    out = {"name": name, "title": (row.get("title") or row.get("founder_title") or "").strip() or None}
    if email:
        out["emails_found"] = [email]
        out["apify_email"] = email
        out["apify_email_status"] = "site"
    if parsed and len(parsed) > 1:
        out["public_emails_all"] = parsed
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
    if not founders:
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
        "scan_status": raw.get("scan_status") or "",
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
            if row.get("campaign_wave"):
                base["campaign_wave"] = row["campaign_wave"]
            by_name[name.lower()] = base
        else:
            incoming = row.get("campaign_wave")
            if incoming and WAVE_RANK.get(incoming, 9) < WAVE_RANK.get(base.get("campaign_wave", "research"), 9):
                base["campaign_wave"] = incoming
            for field in ("website", "one_liner", "location", "industry"):
                if row.get(field) and not base.get(field):
                    base[field] = row[field]
        f = norm_founder({**row, "company": name})
        if not f and parse_public_emails_field(row.get("public_emails") or ""):
            f = norm_founder({**row, "company": name})
        if f and not any(x.get("name") == f.get("name") and (x.get("emails_found") or [""])[0] == (f.get("emails_found") or [""])[0] for x in base["founders"]):
            base["founders"].append({k: v for k, v in f.items() if v and k != "public_emails_all"})
    return list(by_name.values())


def alias_headers(row: dict) -> dict:
    out: dict[str, str] = {}
    for k, v in row.items():
        key = HEADER_ALIASES.get(k, k)
        if key == "founder" and k == "name" and row.get("company") and v == row.get("company"):
            continue
        if key not in out or not out[key]:
            out[key] = v
    return out


def load_json(path: pathlib.Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "companies" in data:
        items = data["companies"]
    elif isinstance(data, list):
        items = data
    else:
        sys.exit("JSON must be a list or {\"companies\": [...]}")
    return [normalize_company(x) for x in items]


def read_csv_rows(path: pathlib.Path, *, campaign_wave: str | None = None) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return []
    cleaned = []
    for row in rows:
        base = {k.strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
        aliased = alias_headers(base)
        if campaign_wave:
            aliased["campaign_wave"] = campaign_wave
        cleaned.append(aliased)
    return cleaned


def load_csv(path: pathlib.Path) -> list[dict]:
    rows = read_csv_rows(path)
    if not rows:
        sys.exit(f"CSV is empty: {path}")
    return merge_csv_rows(rows)


def load_kerala_csv_set() -> list[dict]:
    rows: list[dict] = []
    found = False
    for wave, path in KERALA_CSV_SET:
        if not path.is_file():
            continue
        found = True
        rows.extend(read_csv_rows(path, campaign_wave=wave))
    if not found:
        names = ", ".join(p.name for _, p in KERALA_CSV_SET)
        sys.exit(f"No Kerala CSV files in repo root. Expected one of: {names}")
    return merge_csv_rows(rows)


def load_csv_paths(paths: list[pathlib.Path]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        part = read_csv_rows(p)
        if not part:
            sys.exit(f"CSV is empty: {p}")
        rows.extend(part)
    return merge_csv_rows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Import local startup list for outreach_mailer.py")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=pathlib.Path, nargs="+", help="one or more CSV files")
    src.add_argument("--kerala-set", action="store_true", help="merge priority + public + research CSVs")
    src.add_argument("--json", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=HERE / "kerala_startups.json")
    a = ap.parse_args()
    if a.json:
        companies = load_json(a.json)
    elif a.kerala_set:
        companies = load_kerala_csv_set()
    else:
        companies = load_csv_paths(a.csv)
    a.out.write_text(json.dumps(companies, indent=2, ensure_ascii=False) + "\n")
    n_founders = sum(len(c.get("founders") or []) for c in companies)
    print(f"Wrote {len(companies)} companies, {n_founders} founders → {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
