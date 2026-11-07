#!/usr/bin/env python3
"""Add site emails and pattern guesses to a local startup JSON (no YC required).

Usage: python3 startup_enrich.py --input kerala_startups.json --out kerala_startups_enriched.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from yc_scraper import domain_of, domain_resolves, guesses, site_emails  # noqa: E402


def enrich_company(c: dict) -> dict:
    website = c.get("website") or ""
    domain = domain_of(website)
    resolves = domain_resolves(domain) if domain else False
    site = site_emails(website, domain) if domain else []
    c = dict(c)
    c["domain"] = domain
    c["site_emails"] = site
    founders = []
    for f in c.get("founders") or [{}]:
        f = dict(f)
        if f.get("apify_email") or f.get("emails_found"):
            founders.append(f)
            continue
        name = f.get("name") or ""
        first = (name.split() or [""])[0].lower()
        matched = [e for e in site if first and e.split("@")[0].startswith(first)]
        f["emails_found"] = matched
        f["email_guesses"] = guesses(name, domain) if resolves and name else []
        founders.append(f)
    c["founders"] = founders
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="kerala_startups.json")
    ap.add_argument("--out", default="kerala_startups_enriched.json")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    data = json.loads(pathlib.Path(a.input).read_text())
    if a.limit:
        data = data[: a.limit]
    out = [enrich_company(c) for c in data]
    pathlib.Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    with_email = sum(1 for c in out if any((f.get("emails_found") or f.get("email_guesses") or f.get("apify_email")) for f in c.get("founders") or []))
    print(f"Wrote {a.out} ({with_email}/{len(out)} companies have at least one email candidate)", file=sys.stderr)


if __name__ == "__main__":
    main()
