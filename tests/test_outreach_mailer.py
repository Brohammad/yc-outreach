#!/usr/bin/env python3
"""Run: python3 tests/test_outreach_mailer.py"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import outreach_mailer as om  # noqa: E402


class OutreachMailerTests(unittest.TestCase):
    def test_outreach_variant_ml_for_ai_industry(self):
        self.assertEqual(om.outreach_variant({"industry": "AI", "one_liner": "Docs search"}), "ml")
        self.assertEqual(om.outreach_variant({"industry": "B2B", "one_liner": "Payroll API"}), "backend")

    def test_fill_rotates_value_prop_by_variant(self):
        company_ml = {"name": "BotCo", "batch": "W24", "one_liner": "Copilot.", "industry": "AI"}
        founder = {"name": "Ann Lee"}
        tpl = {
            "my_name": "A",
            "portfolio": "",
            "github": "https://github.com/x",
            "resume": "",
            "proof_line": "p",
            "role_aim_ml": "ml role",
            "role_aim_backend": "be role",
            "stack_pitch_ml": "transformers",
            "stack_pitch_backend": "fastapi",
            "value_prop_ml": "ML path for {one_liner}",
            "value_prop_backend": "BE path for {one_liner}",
            "body": "{value_prop}",
        }
        body = om.fill(tpl["body"], company_ml, founder, tpl)
        self.assertIn("ML path", body)

    def test_company_hook_uses_one_liner_and_industry(self):
        company = {
            "name": "Acme",
            "batch": "Winter 2024",
            "one_liner": "Widget routing for factories.",
            "industry": "B2B -> Supply Chain and Logistics",
        }
        hook = om.company_hook(company)
        self.assertIn("Acme", hook)
        self.assertIn("widget routing", hook.lower())

    def test_fill_includes_hook_and_profile_fields(self):
        company = {
            "name": "Acme",
            "batch": "W24",
            "one_liner": "Widgets.",
            "industry": "B2B -> Logistics",
        }
        founder = {"name": "Ann Lee"}
        tpl = {
            "my_name": "Aabid Mohamed",
            "portfolio": "",
            "github": "https://github.com/Brohammad-coder",
            "resume": "",
            "role_aim": "early backend",
            "stack_pitch": "FastAPI",
            "proof_line": "NITC",
            "body": "{hook}\n{proof_line}",
        }
        body = om.fill(tpl["body"], company, founder, tpl)
        self.assertIn("NITC", body)
        self.assertIn("Acme", body)

    def test_fill_drops_empty_placeholder_lines(self):
        company = {"name": "Acme", "batch": "W24", "one_liner": "Widgets."}
        founder = {"name": "Ann Lee"}
        tpl = {"my_name": "Me", "portfolio": "", "github": "", "resume": "", "subject": "hi {company}", "body": "Hey {first_name}\nresume: {resume}"}
        body = om.fill(tpl["body"], company, founder, tpl)
        self.assertIn("Hey Ann", body)
        self.assertNotIn("resume:", body)

    def test_plan_stagger_times(self):
        companies = [
            {
                "slug": "a",
                "name": "A",
                "batch": "W24",
                "founders": [{"name": "Ann", "email_guesses": ["ann@a.com"]}],
            },
            {
                "slug": "b",
                "name": "B",
                "batch": "W24",
                "founders": [{"name": "Bob", "email_guesses": ["bob@b.com"]}],
            },
        ]
        start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        msgs = om.plan_queue(
            companies=companies,
            tpl={"subject": "s", "body": "b", "my_name": "x"},
            start=start,
            every=om.parse_duration("15m"),
            all_founders=False,
            only_kinds=None,
            skip_slugs=set(),
        )
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["to"], "ann@a.com")
        t0 = om.parse_when(msgs[0]["send_at"])
        t1 = om.parse_when(msgs[1]["send_at"])
        self.assertEqual((t1 - t0).total_seconds(), 900)

    def test_plan_cli_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = [{"slug": "x", "name": "X", "batch": "W24", "founders": [{"name": "A", "email_guesses": ["a@x.com"]}]}]
            tpl = {"subject": "hi", "body": "body", "my_name": "me"}
            inp = Path(tmp) / "in.json"
            tpath = Path(tmp) / "tpl.json"
            inp.write_text(json.dumps(data))
            tpath.write_text(json.dumps(tpl))
            old_argv, old_stdout = sys.argv, sys.stdout
            try:
                sys.argv = [
                    "outreach_mailer.py",
                    "plan",
                    "--input",
                    str(inp),
                    "--template",
                    str(tpath),
                    "--start",
                    "2026-06-01T10:00:00Z",
                    "--every",
                    "1m",
                    "--dry-run",
                ]
                om.main()
            finally:
                sys.argv, sys.stdout = old_argv, old_stdout


if __name__ == "__main__":
    unittest.main()
