import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scratch.test_filter import main


class ScratchFilterDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_report_counts_without_printing_project_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "Glossary.json").write_text(
                json.dumps({"SecretTerm": "GLOSSARY_BODY_MARKER"}),
                encoding="utf-8",
            )
            (workspace / "STORY_SUMMARY.md").write_text(
                "[第1話] SUMMARY_BODY_MARKER",
                encoding="utf-8",
            )
            chapter_dir = workspace / "生肉" / "1.神んてらの世界"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "第10話.md").write_text(
                "SecretTerm RAW_BODY_MARKER",
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                result = main(["--workspace", str(workspace)])

            report = output.getvalue()
            self.assertEqual(result, 0)
            self.assertIn("Glossary Total Terms parsed: 1", report)
            self.assertIn("Glossary Filtered Terms: 1", report)
            self.assertNotIn("GLOSSARY_BODY_MARKER", report)
            self.assertNotIn("SUMMARY_BODY_MARKER", report)
            self.assertNotIn("RAW_BODY_MARKER", report)
            self.assertNotIn(str(workspace), report)


if __name__ == "__main__":
    unittest.main()
