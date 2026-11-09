#!/usr/bin/env python3
"""Append exactly N new outreach messages after wave 1 (dedupe slug + to)."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from outreach_mailer import (  # noqa: E402
    load_queue,
    parse_duration,
    parse_when,
    plan_queue,
    save_queue,
    slug_of,
)
from yc_scraper import domain_of, domain_resolves, guesses  # noqa: E402

CONTACT_LOCALS = ("hello", "contact", "info", "careers", "jobs", "team", "hr")


def fast_founder(company: dict) -> dict | None:
    website = company.get("website") or ""
    domain = domain_of(website)
    if not domain or not domain_resolves(domain):
        return None
    cand = [f"{local}@{domain}" for local in CONTACT_LOCALS]
    cand += guesses("Founder", domain)
    seen: set[str] = set()
    uniq: list[str] = []
    for e in cand:
        el = e.lower()
        if el not in seen:
            seen.add(el)
            uniq.append(el)
    if not uniq:
        return None
    return {"name": "Founder", "email_guesses": uniq}


def enrich_remaining(companies: list[dict], skip_slugs: set[str]) -> list[dict]:
    out: list[dict] = []
    for c in companies:
        sl = slug_of(c)
        if sl in skip_slugs:
            out.append(c)
            continue
        if c.get("founders"):
            out.append(c)
            continue
        f = fast_founder(c)
        if not f:
            out.append(c)
            continue
        nc = dict(c)
        nc["domain"] = domain_of(c.get("website") or "")
        nc["founders"] = [f]
        out.append(nc)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="kerala_startups.json")
    ap.add_argument("--template", default="outreach_template.json")
    ap.add_argument("--queue", default="outreach_queue.json")
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--start", required=True)
    ap.add_argument("--every", default="18m")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    tpl = json.loads(pathlib.Path(a.template).read_text())
    companies = json.loads(pathlib.Path(a.input).read_text())
    existing = load_queue(pathlib.Path(a.queue))
    pending = [m for m in existing["messages"] if m.get("status") == "pending"]
    skip_slugs = {m["slug"] for m in pending}
    skip_tos = {m["to"].lower() for m in existing["messages"] if m.get("to")}

    enriched = enrich_remaining(companies, skip_slugs)
    enriched.sort(key=lambda c: (c.get("name") or "").lower())

    start = parse_when(a.start)
    every = parse_duration(a.every)
    batch = plan_queue(
        companies=enriched,
        tpl=tpl,
        start=start,
        every=every,
        all_founders=False,
        only_kinds={"valid", "unknown", "site", "guess"},
        skip_slugs=skip_slugs,
    )
    new: list[dict] = []
    for m in batch:
        to = m["to"].lower()
        if to in skip_tos:
            continue
        skip_tos.add(to)
        new.append(m)
        if len(new) >= a.count:
            break

    if len(new) < a.count:
        sys.exit(f"Only built {len(new)} messages (wanted {a.count}). Enrich more companies or add CSVs.")

    if a.dry_run:
        print(json.dumps(new, indent=2))
        print(f"{len(new)} message(s) ready", file=sys.stderr)
        return

    existing["messages"].extend(new)
    save_queue(pathlib.Path(a.queue), existing)
    print(
        f"Appended {len(new)} → {a.queue} "
        f"({new[0]['send_at']} … {new[-1]['send_at']})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
