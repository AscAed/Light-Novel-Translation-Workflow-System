import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from kakuyomu_html_archive import validate_kakuyomu_html_archive
from kakuyomu_page_source import _EpisodePageParser
from scripts.validate_kakuyomu_html_archive import main
from source_ingestion import (
    CatalogPage,
    EpisodeMetadata,
    FetchedEpisode,
    collect_source,
    source_artifact_id,
)
from source_manifest import append_artifact, load_manifest


class _HtmlArchiveAdapter:
    def __init__(self, *, metadata, page_html, visible_text, page_charset=None):
        self.metadata = metadata
        self.page_html = page_html
        self.visible_text = visible_text
        self.page_charset = page_charset
        fingerprint_input = (
            metadata.title.encode("utf-8")
            + b"\0"
            + visible_text
            + b"\0"
            + page_html
            + b"\0"
            + (page_charset or "utf-8").encode("ascii")
        )
        self.source_fingerprint = hashlib.sha256(fingerprint_input).hexdigest()

    def list_episodes(self, cursor):
        if cursor is not None:
            raise AssertionError("The fixture has only one catalog page.")
        return CatalogPage((self.metadata,), None)

    def fetch_episode(self, episode_id):
        if episode_id != self.metadata.episode_id:
            raise AssertionError("Unexpected episode requested.")
        return FetchedEpisode(
            self.metadata,
            self.visible_text,
            self.page_html,
            self.page_charset,
        )


class KakuyomuHtmlArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "archive"
        self.root.mkdir()
        self.page_html = (
            b"<html><div class='widget-episodeTitle'>Episode One</div>"
            b"<div class='widget-episodeBody'><p>First "
            b"<ruby><rb>Kanji</rb><rp>(</rp><rt>kanji</rt><rp>)</rp>"
            b"</ruby><br>Second</p></div></html>"
        )
        parser = _EpisodePageParser()
        parser.feed(self.page_html.decode("utf-8"))
        parser.close()
        self.visible_text = parser.extracted_body().encode("utf-8")
        self.metadata = EpisodeMetadata("ep-1", "Episode One", 1)
        self._collect()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _collect(
        self, *, visible_text=None, page_html=None, title=None, page_charset=None
    ):
        metadata = EpisodeMetadata(
            "ep-1",
            title if title is not None else "Episode One",
            1,
        )
        selected_html = page_html if page_html is not None else self.page_html
        selected_text = (
            visible_text if visible_text is not None else self.visible_text
        )
        adapter = _HtmlArchiveAdapter(
            metadata=metadata,
            page_html=selected_html,
            visible_text=selected_text,
            page_charset=page_charset,
        )
        collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path=f"checkpoint-{adapter.source_fingerprint}.json",
        )

    def test_replays_current_html_to_its_bound_raw_source(self):
        report = validate_kakuyomu_html_archive(source_root=self.root)

        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["episode_count"], 1)
        self.assertEqual(report["files_verified"], 3)
        self.assertEqual(report["body_bytes"], len(self.visible_text))

    def test_replays_html_using_its_archived_response_charset(self):
        page_text = (
            "<html><div class='widget-episodeTitle'>Episode One</div>"
            "<div class='widget-episodeBody'><p>日本語の本文。</p></div></html>"
        )
        page_html = page_text.encode("shift_jis")
        parser = _EpisodePageParser()
        parser.feed(page_text)
        parser.close()
        visible_text = parser.extracted_body().encode("utf-8")
        self._collect(
            visible_text=visible_text,
            page_html=page_html,
            page_charset="shift_jis",
        )

        manifest = load_manifest(self.root / "source_manifest.json")
        episode_artifact = next(
            item
            for item in reversed(manifest["artifacts"])
            if item["kind"] == "episode"
        )
        metadata = json.loads(
            (self.root / episode_artifact["relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        report = validate_kakuyomu_html_archive(source_root=self.root)

        self.assertEqual(metadata["page_charset"], "shift_jis")
        self.assertEqual(report["status"], "verified")
        html_artifact = next(
            item
            for item in reversed(manifest["artifacts"])
            if item["kind"] == "raw_page_html"
        )
        self.assertEqual(
            (self.root / html_artifact["relative_path"]).read_bytes(),
            page_html,
        )

    def test_replays_legacy_utf8_html_without_charset_metadata(self):
        manifest_path = self.root / "source_manifest.json"
        manifest = load_manifest(manifest_path)
        episode_artifact = next(
            item
            for item in reversed(manifest["artifacts"])
            if item["kind"] == "episode"
        )
        metadata_path = self.root / episode_artifact["relative_path"]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.pop("page_charset", None)
        metadata_bytes = json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        metadata_path.write_bytes(metadata_bytes)
        episode_artifact["content_sha256"] = hashlib.sha256(
            metadata_bytes
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report = validate_kakuyomu_html_archive(source_root=self.root)

        self.assertEqual(report["status"], "verified")

    def test_rejects_html_that_does_not_match_archived_raw_source(self):
        self._collect(visible_text=b"unrelated visible text")

        with self.assertRaisesRegex(ValueError, "does not reproduce"):
            validate_kakuyomu_html_archive(source_root=self.root)

    def test_rejects_page_title_that_does_not_match_episode_metadata(self):
        self._collect(title="Different title")

        with self.assertRaisesRegex(ValueError, "title does not match"):
            validate_kakuyomu_html_archive(source_root=self.root)

    def test_rejects_html_bound_to_a_stale_raw_source_version(self):
        manifest = load_manifest(self.root / "source_manifest.json")
        raw_artifact = next(
            item
            for item in reversed(manifest["artifacts"])
            if item["kind"] == "raw_source"
        )
        episode_artifact = next(
            item
            for item in reversed(manifest["artifacts"])
            if item["kind"] == "episode"
        )
        replacement = b"new raw source version"
        replacement_path = self.root / "raw" / "replacement.bin"
        replacement_path.parent.mkdir(exist_ok=True)
        replacement_path.write_bytes(replacement)
        append_artifact(
            self.root / "source_manifest.json",
            {
                "artifact_id": source_artifact_id(
                    "work-1", "raw_source", "ep-1"
                ),
                "version_id": "v-replacement-raw",
                "kind": "raw_source",
                "content_sha256": hashlib.sha256(replacement).hexdigest(),
                "relative_path": "raw/replacement.bin",
                "parent_version_ids": [
                    episode_artifact["version_id"],
                    raw_artifact["version_id"],
                ],
            },
        )

        with self.assertRaisesRegex(ValueError, "stale source lineage"):
            validate_kakuyomu_html_archive(source_root=self.root)

    def test_rejects_corrupted_html_artifact(self):
        manifest = load_manifest(self.root / "source_manifest.json")
        html_artifact = next(
            item
            for item in manifest["artifacts"]
            if item["kind"] == "raw_page_html"
        )
        html_path = self.root.joinpath(*html_artifact["relative_path"].split("/"))
        html_path.write_bytes(b"<html>modified</html>")

        with self.assertRaisesRegex(ValueError, "content hash does not match"):
            validate_kakuyomu_html_archive(source_root=self.root)

    def test_rejects_total_html_byte_limit_before_replay(self):
        with patch("kakuyomu_html_archive.verify_manifest_files") as verify_files:
            with self.assertRaisesRegex(ValueError, "byte limit"):
                validate_kakuyomu_html_archive(
                    source_root=self.root,
                    max_total_html_bytes=len(self.page_html) - 1,
                )
        verify_files.assert_not_called()

    def test_html_byte_limit_includes_historical_page_versions(self):
        revised_html = b"<!-- repeat capture -->" + self.page_html
        self._collect(page_html=revised_html)

        with self.assertRaisesRegex(ValueError, "byte limit"):
            validate_kakuyomu_html_archive(
                source_root=self.root,
                max_total_html_bytes=len(revised_html),
            )

    def test_cli_reports_summary_without_visible_text(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["--source-root", str(self.root)])

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "verified")
        self.assertNotIn("First", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
