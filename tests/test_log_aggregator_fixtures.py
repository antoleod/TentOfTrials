"""Independent fixture coverage for the legacy log aggregator parsers."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "log_parser"
sys.path.insert(0, str(ROOT))

from tools.log_aggregator import (  # noqa: E402
    JSONLogParser,
    LogAggregator,
    NginxLogParser,
    TextLogParser,
)


def fixture_lines(name: str) -> list[str]:
    return [
        line
        for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class LogParserFixtureTests(unittest.TestCase):
    def test_json_fixture_fields(self) -> None:
        first, second = [JSONLogParser().parse(line) for line in fixture_lines("json_lines.log")]

        self.assertEqual(first["format"], "json")
        self.assertEqual(first["timestamp"], "2024-01-15T12:34:56Z")
        self.assertEqual(first["level"], "ERROR")
        self.assertEqual(first["service"], "orders")
        self.assertEqual(first["message"], "checkout failed")
        self.assertEqual(first["fields"]["order_id"], "ord-123")

        self.assertEqual(second["timestamp"], "2024-01-15T12:35:04+00:00")
        self.assertEqual(second["level"], "warn")
        self.assertEqual(second["service"], "billing")
        self.assertEqual(second["fields"]["invoice_id"], "inv-456")

    def test_text_fixture_fields(self) -> None:
        first, second = [TextLogParser().parse(line) for line in fixture_lines("text_lines.log")]

        self.assertEqual(first["format"], "text")
        self.assertEqual(first["timestamp"], 1705322101)
        self.assertEqual(first["level"], "warn")
        self.assertEqual(first["service"], "billing")
        self.assertIn("invoice_id=inv-456", first["message"])

        self.assertEqual(second["timestamp"], 1705322130)
        self.assertEqual(second["level"], "error")
        self.assertEqual(second["service"], "orders")
        self.assertIn("order_id=ord-123", second["fields"]["raw"])

    def test_nginx_fixture_fields(self) -> None:
        first, second = [NginxLogParser().parse(line) for line in fixture_lines("nginx_lines.log")]

        self.assertEqual(first["format"], "nginx")
        self.assertEqual(first["timestamp"], 1705322162)
        self.assertEqual(first["level"], "warn")
        self.assertEqual(first["service"], "nginx")
        self.assertEqual(first["fields"]["remote_addr"], "203.0.113.10")
        self.assertEqual(first["fields"]["status"], 404)
        self.assertIn("GET /api/orders/ord-123", first["fields"]["request"])

        self.assertEqual(second["level"], "error")
        self.assertEqual(second["fields"]["status"], 502)

    def test_malformed_or_unsupported_lines_do_not_crash(self) -> None:
        parsers = [JSONLogParser(), NginxLogParser(), TextLogParser()]
        aggregator = LogAggregator()

        for line in fixture_lines("malformed_lines.log"):
            for parser in parsers:
                with self.subTest(parser=parser.__class__.__name__, line=line):
                    parser.parse(line)
            aggregator._parse_line(line)

        self.assertGreaterEqual(len(aggregator.entries), 1)

    def test_aggregator_and_cli_remain_compatible(self) -> None:
        lines = fixture_lines("text_lines.log")

        aggregator = LogAggregator()
        for line in lines:
            self.assertTrue(aggregator._parse_line(line))

        self.assertEqual([entry["format"] for entry in aggregator.entries], ["text", "text"])
        summary = aggregator.get_summary()
        self.assertEqual(summary["total_entries"], 2)
        self.assertEqual(summary["by_service"]["orders"], 1)
        self.assertEqual(summary["by_service"]["billing"], 1)
        self.assertIsNotNone(summary["time_range"])

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "mixed.log"
            output_path = tmp_path / "report.json"
            input_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "log_aggregator.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["total_entries"], 2)
            self.assertEqual([entry["format"] for entry in report["entries"]], ["text", "text"])


if __name__ == "__main__":
    unittest.main()
