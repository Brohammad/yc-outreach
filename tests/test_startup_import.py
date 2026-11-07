#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import startup_import as si  # noqa: E402


class StartupImportTests(unittest.TestCase):
    def test_csv_merges_founders(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "t.csv"
            csv.write_text(
                "company,website,location,founder,email\n"
                "Acme,https://acme.test,Kochi,A One,a@acme.test\n"
                "Acme,https://acme.test,Kochi,B Two,b@acme.test\n"
            )
            out = [si.load_csv(csv)]
            companies = out[0]
            self.assertEqual(len(companies), 1)
            self.assertEqual(companies[0]["source"], "kerala_list")
            self.assertEqual(len(companies[0]["founders"]), 2)

    def test_json_normalize(self):
        raw = [{"name": "X", "location": "Kerala", "founders": [{"name": "A", "email": "a@x.com"}]}]
        c = si.normalize_company(raw[0])
        self.assertEqual(c["slug"], "x")
        self.assertEqual(c["founders"][0]["emails_found"], ["a@x.com"])


    def test_merge_campaign_wave_priority_wins(self):
        rows = [
            {"company": "Acme", "campaign_wave": "research", "founder": "A", "email": "a@acme.test"},
            {"company": "Acme", "campaign_wave": "priority", "founder": "A", "email": "a@acme.test"},
        ]
        merged = si.merge_csv_rows(rows)
        self.assertEqual(merged[0]["campaign_wave"], "priority")


if __name__ == "__main__":
    unittest.main()
