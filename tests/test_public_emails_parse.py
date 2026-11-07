#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import startup_import as si  # noqa: E402

raw = "careers@ust.com (https://x); u003euscareers@ust.com (https://y); hr@co.com (https://z)"
emails = si.parse_public_emails_field(raw)
assert "careers@ust.com" in emails
picked = si.pick_outreach_email(emails)
assert picked.startswith("careers@"), picked
print("OK")
