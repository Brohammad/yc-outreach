#!/usr/bin/env python3
"""Build and run a scheduled outreach send queue over SMTP (stdlib only).

Reads scraped/enriched founder JSON (from yc_scraper.py / apify_enrich.py), fills a
subject/body template, staggers send times, and sends due messages when you run `run`
(cron-friendly).

Credentials: OUTREACH_SMTP_HOST, OUTREACH_SMTP_USER, OUTREACH_SMTP_PASSWORD, OUTREACH_FROM
(optional OUTREACH_SMTP_PORT, OUTREACH_REPLY_TO, OUTREACH_SMTP_SSL, and the same keys in .env).

Usage:
  python3 outreach_mailer.py plan --input yc_founders_enriched.json --template outreach_template.json
  python3 outreach_mailer.py run --queue outreach_queue.json
  python3 outreach_mailer.py status --queue outreach_queue.json
"""
from __future__ import annotations

import argparse
import email.message
import json
import os
import pathlib
import re
import smtplib
import ssl
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

HERE = pathlib.Path(__file__).parent
QUEUE_VERSION = 1
ENV_KEYS = (
    "OUTREACH_SMTP_HOST",
    "OUTREACH_SMTP_PORT",
    "OUTREACH_SMTP_USER",
    "OUTREACH_SMTP_PASSWORD",
    "OUTREACH_FROM",
    "OUTREACH_REPLY_TO",
    "OUTREACH_SMTP_SSL",
)

RANK = {"valid": 0, "unknown": 1, "site": 2, "guess": 3, "none": 4}
ML_SIGNALS = re.compile(
    r"\b(ai|artificial intelligence|machine learning|\bml\b|llm|nlp|rag|neural|"
    r"generative|computer vision|deep learning|transformer|embedding|inference|foundation model)\b",
    re.I,
)
KERALAM_RE = re.compile(
    r"kerala|keralam|kochi|cochin|ernakulam|thiruvananthapuram|trivandrum|kozhikode|calicut|"
    r"thrissur|kollam|palakkad|malappuram|alappuzha|kannur|kottayam",
    re.I,
)


def load_dotenv() -> None:
    env = HERE / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k not in os.environ:
            os.environ[k] = v


def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        sys.exit(f"Missing {name} (environment variable or .env)")
    return v


def parse_when(raw: str) -> datetime:
    """Parse ISO-8601 or 'YYYY-MM-DD HH:MM' as UTC if no offset given."""
    raw = raw.strip().replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_duration(raw: str) -> timedelta:
    raw = raw.strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)", raw)
    if not m:
        sys.exit(f"Bad duration {raw!r}; use forms like 15m, 30s, 1h")
    n = float(m.group(1))
    unit = m.group(2)[0]
    if unit == "s":
        return timedelta(seconds=n)
    if unit == "m":
        return timedelta(minutes=n)
    return timedelta(hours=n)


def slug_of(company: dict) -> str:
    if company.get("slug"):
        return company["slug"]
    m = re.search(r"/companies/([^/?#]+)", company.get("yc_url") or "")
    if m:
        return m.group(1)
    return re.sub(r"[^a-z0-9-]+", "-", (company.get("name") or "company").lower()).strip("-")


def best_email(founder: dict) -> tuple[str, str]:
    if founder.get("apify_email"):
        status = (founder.get("apify_email_status") or founder.get("apify_status") or "").lower()
        kind = "valid" if status == "valid" else "unknown"
        return founder["apify_email"].split(";")[0].strip().lower(), kind
    found = founder.get("emails_found") or []
    if found:
        return found[0].lower(), "site"
    guesses = founder.get("email_guesses") or []
    if guesses:
        return guesses[0].lower(), "guess"
    return "", "none"


def is_keralam_company(company: dict) -> bool:
    if (company.get("source") or "").lower() in ("kerala_list", "keralam", "kerala"):
        return True
    blob = " ".join(
        [company.get("location") or "", company.get("batch") or "", company.get("name") or ""]
    )
    return bool(KERALAM_RE.search(blob))


def keralam_tie(company: dict) -> str:
    if not is_keralam_company(company):
        return ""
    return (
        "I'm based in Kerala (NIT Calicut) — it's motivating to reach out to teams building from "
        "the same ecosystem."
    )


def company_text_blob(company: dict) -> str:
    tags = company.get("tags")
    tag_txt = " ".join(tags) if isinstance(tags, list) else ""
    return " ".join(
        [
            company.get("industry") or "",
            company.get("one_liner") or "",
            company.get("description") or "",
            tag_txt,
        ]
    )


def outreach_variant(company: dict) -> str:
    blob = company_text_blob(company)
    if ML_SIGNALS.search(blob):
        return "ml"
    ind = (company.get("industry") or "").strip().upper()
    if ind.startswith("AI") or "ARTIFICIAL INTELLIGENCE" in ind:
        return "ml"
    return "backend"


def variant_pick(tpl: dict, key: str, variant: str) -> str:
    return (tpl.get(f"{key}_{variant}") or tpl.get(key) or "").strip()


def industry_focus(company: dict) -> str:
    ind = (company.get("industry") or "").strip()
    if "->" in ind:
        return ind.split("->")[-1].strip()
    tags = company.get("tags")
    if isinstance(tags, list) and tags:
        t = tags[0]
        return t if isinstance(t, str) else str(t)
    return ind or "your market"


def company_hook(company: dict, variant: str = "backend") -> str:
    name = company.get("name") or "you"
    batch = company.get("batch") or "your batch"
    one = (company.get("one_liner") or "").strip().rstrip(".")
    niche = industry_focus(company)
    if variant == "ml":
        if one and niche and niche != "your market":
            return (
                f"I've been watching {name} since {batch} — {one.lower()} in {niche.lower()} is "
                f"exactly the kind of problem where model quality and production serving have to "
                f"move together, not in separate silos."
            )
        if one:
            return (
                f"What you're building around {one.lower()} at {name} is the stage where I'd want "
                f"to own evals, RAG/LLM glue, and the API surface founders can actually ship on."
            )
        return (
            f"{name} kept coming up while I short-listed teams shipping real ML in production, "
            f"not demos."
        )
    if one and niche and niche != "your market":
        return (
            f"I've been tracking {name} since {batch} — {one.lower()} is a focused bet in "
            f"{niche.lower()}, and it's the kind of product I'd want backend ownership on early."
        )
    if one:
        return (
            f"The way you're framing {one.lower()} at {name} is the stage I optimize for: "
            f"real users, tight loops, and infra that keeps up with the product."
        )
    return (
        f"{name} kept landing on my short list while I filtered for teams where engineers ship "
        f"backend and ML together, not slide decks."
    )


def pick_founder(company: dict, all_founders: bool) -> list[dict]:
    founders = list(company.get("founders") or [])
    if not founders:
        return []
    if all_founders:
        return founders
    founders.sort(
        key=lambda f: (
            RANK[best_email(f)[1]],
            0 if re.search(r"ceo", f.get("title") or "", re.I) else 1,
        )
    )
    return [founders[0]]


def subject_for(company: dict, tpl: dict, founder: dict) -> str:
    variant = outreach_variant(company)
    raw = variant_pick(tpl, "subject", variant) or "{company}"
    return fill(raw, company, founder, tpl, variant=variant)


def fill(text: str, company: dict, founder: dict, tpl: dict, *, variant: str | None = None) -> str:
    first = (founder.get("name") or "").split()
    first_name = first[0] if first else "there"
    one_liner = (company.get("one_liner") or "what you're building").rstrip(".").lower()
    variant = variant or outreach_variant(company)
    vars_ = {
        "first_name": first_name,
        "company": company.get("name") or "",
        "one_liner": one_liner,
        "batch": company.get("batch") or "",
        "industry_niche": industry_focus(company).lower(),
        "variant": variant,
        "hook": company_hook(company, variant),
        "my_name": tpl.get("my_name") or "",
        "portfolio": tpl.get("portfolio") or "",
        "github": tpl.get("github") or "",
        "resume": tpl.get("resume") or "",
        "role_aim": variant_pick(tpl, "role_aim", variant),
        "stack_pitch": variant_pick(tpl, "stack_pitch", variant),
        "proof_line": tpl.get("proof_line") or "",
        "value_prop": variant_pick(tpl, "value_prop", variant),
        "keralam_tie": keralam_tie(company),
    }

    def repl(m: re.Match) -> str:
        k = m.group(1)
        return vars_.get(k, m.group(0)) if k in vars_ else m.group(0)

    out = re.sub(r"\{(\w+)\}", repl, text or "")
    keep = []
    for line in out.splitlines():
        if re.match(r"^\s*[\w ]+:\s*$", line):
            continue
        if not line.strip():
            continue
        keep.append(line)
    return "\n".join(keep)


def load_queue(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"version": QUEUE_VERSION, "messages": []}
    data = json.loads(path.read_text())
    data.setdefault("messages", [])
    return data


def save_queue(path: pathlib.Path, data: dict) -> None:
    data["version"] = QUEUE_VERSION
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def plan_queue(
    *,
    companies: list[dict],
    tpl: dict,
    start: datetime,
    every: timedelta,
    all_founders: bool,
    only_kinds: set[str] | None,
    skip_slugs: set[str],
) -> list[dict]:
    messages: list[dict] = []
    t = start
    for company in companies:
        slug = slug_of(company)
        if slug in skip_slugs:
            continue
        for founder in pick_founder(company, all_founders):
            addr, kind = best_email(founder)
            if not addr or (only_kinds and kind not in only_kinds):
                continue
            subject = subject_for(company, tpl, founder)
            body = fill(tpl.get("body") or "", company, founder, tpl)
            variant = outreach_variant(company)
            messages.append(
                {
                    "id": str(uuid.uuid4()),
                    "slug": slug,
                    "company": company.get("name") or slug,
                    "batch": company.get("batch") or "",
                    "founder": founder.get("name") or "",
                    "to": addr,
                    "email_kind": kind,
                    "angle": variant,
                    "subject": subject,
                    "body": body,
                    "send_at": t.isoformat(),
                    "status": "pending",
                    "sent_at": None,
                    "error": None,
                }
            )
            t += every
    return messages


def cmd_plan(a: argparse.Namespace) -> None:
    tpl = json.loads(pathlib.Path(a.template).read_text())
    companies = json.loads(pathlib.Path(a.input).read_text())
    if a.limit:
        companies = companies[: a.limit]
    start = parse_when(a.start)
    every = parse_duration(a.every)
    only = set(x.strip() for x in a.only_email.split(",")) if a.only_email else None
    existing = load_queue(pathlib.Path(a.queue)) if a.merge else {"messages": []}
    pending_slugs = {m["slug"] for m in existing["messages"] if m.get("status") == "pending"}
    new = plan_queue(
        companies=companies,
        tpl=tpl,
        start=start,
        every=every,
        all_founders=a.all_founders,
        only_kinds=only,
        skip_slugs=pending_slugs if a.merge else set(),
    )
    if a.dry_run:
        print(json.dumps(new, indent=2))
        print(f"{len(new)} message(s) would be queued", file=sys.stderr)
        return
    if a.merge:
        existing["messages"].extend(new)
        data = existing
    else:
        data = {"messages": new}
    save_queue(pathlib.Path(a.queue), data)
    print(f"Queued {len(new)} message(s) in {a.queue} (first at {start.isoformat()})", file=sys.stderr)


def smtp_send(msg_rec: dict, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY-RUN to={msg_rec['to']} subject={msg_rec['subject']!r}", file=sys.stderr)
        return
    host = env("OUTREACH_SMTP_HOST")
    port = int(os.environ.get("OUTREACH_SMTP_PORT") or "587")
    user = env("OUTREACH_SMTP_USER")
    password = env("OUTREACH_SMTP_PASSWORD")
    from_addr = env("OUTREACH_FROM")
    reply_to = os.environ.get("OUTREACH_REPLY_TO") or from_addr
    use_ssl = (os.environ.get("OUTREACH_SMTP_SSL") or "").lower() in ("1", "true", "yes")

    em = email.message.EmailMessage()
    em["From"] = from_addr
    em["To"] = msg_rec["to"]
    em["Subject"] = msg_rec["subject"]
    em["Reply-To"] = reply_to
    em.set_content(msg_rec["body"])

    ctx = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as smtp:
            smtp.login(user, password)
            smtp.send_message(em)
    else:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(em)


def cmd_run(a: argparse.Namespace) -> None:
    load_dotenv()
    path = pathlib.Path(a.queue)
    data = load_queue(path)
    now = datetime.now(timezone.utc)
    sent = failed = 0
    due = [m for m in data["messages"] if m.get("status") == "pending" and parse_when(m["send_at"]) <= now]
    due.sort(key=lambda m: m["send_at"])
    if a.max:
        due = due[: a.max]
    for m in due:
        try:
            smtp_send(m, a.dry_run)
            if not a.dry_run:
                m["status"] = "sent"
                m["sent_at"] = datetime.now(timezone.utc).isoformat()
                m["error"] = None
            sent += 1
        except Exception as e:
            if not a.dry_run:
                m["status"] = "failed"
                m["error"] = str(e)
            failed += 1
            print(f"failed {m['to']}: {e}", file=sys.stderr)
        if a.sleep and sent and not a.dry_run:
            import time

            time.sleep(a.sleep)
    still = sum(1 for m in data["messages"] if m.get("status") == "pending")
    if not a.dry_run:
        save_queue(path, data)
    print(f"Due: {len(due)}; sent: {sent}; failed: {failed}; still pending: {still}", file=sys.stderr)


def cmd_status(a: argparse.Namespace) -> None:
    data = load_queue(pathlib.Path(a.queue))
    counts: dict[str, int] = {}
    for m in data["messages"]:
        counts[m.get("status", "?")] = counts.get(m.get("status", "?"), 0) + 1
    print(json.dumps({"queue": a.queue, "counts": counts, "messages": data["messages"]}, indent=2))


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Schedule and send YC outreach emails via SMTP")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="build or extend the send queue from scraped JSON")
    p_plan.add_argument("--input", default="kerala_startups_enriched.json",
                        help="founder JSON: kerala_startups_enriched.json or yc_founders_enriched.json")
    p_plan.add_argument("--template", default="outreach_template.json")
    p_plan.add_argument("--queue", default="outreach_queue.json")
    p_plan.add_argument("--start", required=True, help="First send time (ISO-8601)")
    p_plan.add_argument("--every", default="15m", help="Delay between messages, e.g. 15m")
    p_plan.add_argument("--limit", type=int, default=0, help="first N companies only")
    p_plan.add_argument("--all-founders", action="store_true", help="email every founder, not only primary")
    p_plan.add_argument("--only-email", default="", help="comma list: valid,unknown,site,guess")
    p_plan.add_argument("--merge", action="store_true", help="append to existing queue, skip duplicate pending slugs")
    p_plan.add_argument("--dry-run", action="store_true")
    p_plan.set_defaults(func=cmd_plan)

    p_run = sub.add_parser("run", help="send messages that are due (for cron)")
    p_run.add_argument("--queue", default="outreach_queue.json")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--max", type=int, default=0, help="send at most N due messages this run")
    p_run.add_argument("--sleep", type=float, default=0, help="seconds to wait after each successful send")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="print queue JSON summary")
    p_status.add_argument("--queue", default="outreach_queue.json")
    p_status.set_defaults(func=cmd_status)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
