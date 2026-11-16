import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.diff_kakuyomu_catalogs import main
from scripts.ingest_kakuyomu_pages import (
    _load_catalog,
    _load_catalog_snapshot,
    main as ingest_main,
)
from kakuyomu_catalog_diff import (
    append_only_catalog_status,
    exact_refresh_catalog_status,
)
from source_ingestion import CatalogPage


WORK_ID = "1234567890123456789"
EPISODE_1 = "1111111111111111111"
EPISODE_2 = "2222222222222222222"
EPISODE_3 = "3333333333333333333"


def _episode(episode_id, position, title):
    return {
        "episode_id": episode_id,
        "position": position,
        "page_url": (
            f"https://kakuyomu.jp/works/{WORK_ID}/episodes/{episode_id}"
        ),
        "title": title,
    }


def _chapter(group_id, chapter_id, title, level, start, end, episode_ids):
    return {
        "group_id": group_id,
        "chapter_id": chapter_id,
        "title": title,
        "level": level,
        "position_start": start,
        "position_end": end,
        "episode_ids": episode_ids,
    }


def _work_metadata(**overrides):
    result = {
        "source_url": f"https://kakuyomu.jp/works/{WORK_ID}",
        "title": "Synthetic work",
        "author_name": "Synthetic Author",
        "author_screen_name": "synthetic-author",
        "catchphrase": "Synthetic catchphrase",
        "introduction": "Synthetic introduction",
        "genre": "Fantasy",
        "tags": ["fixture"],
        "serial_status": "COMPLETED",
        "published_at": "2026-01-01T00:00:00Z",
        "last_episode_published_at": "2026-01-02T00:00:00Z",
        "public_episode_count": 1,
    }
    result.update(overrides)
    return result


class FixtureAdapter:
    source_fingerprint = "a" * 64

    def __init__(self, episodes):
        self.episodes = episodes

    def list_episodes(self, cursor):
        if cursor is not None:
            return CatalogPage((), None)
        return CatalogPage(tuple(item.metadata for item in self.episodes), None)

    def fetch_episode(self, episode_id):
        return b"synthetic source"


class KakuyomuCatalogDiffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_catalog(self, name, catalog):
        (self.root / name).write_text(
            json.dumps(catalog, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_reports_changes_and_exports_only_added_episodes(self):
        previous = {
            "schema_version": 2,
            "work_id": WORK_ID,
            "episodes": [
                _episode(EPISODE_1, 1, "First"),
                _episode(EPISODE_2, 2, "Second"),
            ],
            "chapters": [
                _chapter(
                    "group-1",
                    "chapter-1",
                    "Alpha",
                    0,
                    1,
                    2,
                    [EPISODE_1, EPISODE_2],
                )
            ],
        }
        current = {
            "schema_version": 2,
            "work_id": WORK_ID,
            "episodes": [
                _episode(EPISODE_2, 1, "Second renamed"),
                _episode(EPISODE_1, 2, "First"),
                _episode(EPISODE_3, 3, "Third"),
            ],
            "chapters": [
                _chapter(
                    "group-1",
                    "chapter-1",
                    "Alpha revised",
                    0,
                    1,
                    1,
                    [EPISODE_2],
                ),
                _chapter(
                    "group-2",
                    "chapter-2",
                    "Beta",
                    1,
                    2,
                    3,
                    [EPISODE_1, EPISODE_3],
                ),
            ],
        }
        self._write_catalog("previous.json", previous)
        self._write_catalog("current.json", current)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(
                [
                    "--source-root",
                    str(self.root),
                    "--previous-catalog",
                    "previous.json",
                    "--current-catalog",
                    "current.json",
                    "--export",
                    "added",
                    "--catalog-output",
                    "added.json",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["chapter_comparison"], "available")
        self.assertFalse(report["append_only_compatibility"]["append_only"])
        self.assertEqual(
            report["counts"],
            {"added": 1, "removed": 0, "updated": 2, "unchanged": 0},
        )
        changes = {
            item["episode_id"]: item for item in report["changes"]
        }
        self.assertEqual(
            changes[EPISODE_1]["changes"],
            ["position_changed", "chapter_group_changed"],
        )
        self.assertEqual(
            changes[EPISODE_2]["changes"],
            [
                "title_changed",
                "position_changed",
                "chapter_metadata_changed",
            ],
        )
        self.assertEqual(report["exported_selection"], "added")
        self.assertEqual(report["exported_episode_count"], 1)
        self.assertEqual(
            report["exported_catalog_sha256"],
            hashlib.sha256((self.root / "added.json").read_bytes()).hexdigest(),
        )
        self.assertNotIn("Second renamed", stdout.getvalue())
        self.assertNotIn("Alpha revised", stdout.getvalue())
        exported = json.loads((self.root / "added.json").read_text(encoding="utf-8"))
        self.assertEqual(exported["schema_version"], 1)
        self.assertEqual(
            [item["episode_id"] for item in exported["episodes"]],
            [EPISODE_3],
        )
        work_id, episodes, _ = _load_catalog(str(self.root), "added.json")
        self.assertEqual(work_id, WORK_ID)
        self.assertEqual([item.metadata.position for item in episodes], [3])
        output_root = self.root / "output"
        output_root.mkdir()
        ingest_stdout = io.StringIO()
        ingest_stderr = io.StringIO()
        adapter = FixtureAdapter(episodes)
        with (
            patch(
                "scripts.ingest_kakuyomu_pages.KakuyomuPageAdapter",
                return_value=adapter,
            ),
            contextlib.redirect_stdout(ingest_stdout),
            contextlib.redirect_stderr(ingest_stderr),
        ):
            ingest_result = ingest_main(
                [
                    "--source-root",
                    str(self.root),
                    "--catalog",
                    "added.json",
                    "--output-root",
                    str(output_root),
                ]
            )
        self.assertEqual(ingest_result, 0)
        self.assertEqual(ingest_stderr.getvalue(), "")
        ingestion_report = json.loads(ingest_stdout.getvalue())
        self.assertEqual(ingestion_report["status"], "complete")
        checkpoint = json.loads(
            (output_root / "source_checkpoint.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checkpoint["completed_episode_ids"], [EPISODE_3])

    def test_v1_snapshots_report_chapter_comparison_as_unavailable(self):
        self._write_catalog(
            "previous.json",
            {
                "schema_version": 1,
                "work_id": WORK_ID,
                "episodes": [_episode(EPISODE_1, 1, "First")],
            },
        )
        self._write_catalog(
            "current.json",
            {
                "schema_version": 1,
                "work_id": WORK_ID,
                "episodes": [_episode(EPISODE_1, 1, "First renamed")],
            },
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = main(
                [
                    "--source-root",
                    str(self.root),
                    "--previous-catalog",
                    "previous.json",
                    "--current-catalog",
                    "current.json",
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(
            report["chapter_comparison"],
            "unavailable_v1_snapshot",
        )
        self.assertEqual(report["counts"]["updated"], 1)
        self.assertEqual(
            report["changes"][0]["changes"],
            ["title_changed"],
        )
        self.assertEqual(
            report["work_metadata_comparison"],
            "unavailable_v3_snapshot",
        )

    def test_reports_changed_work_metadata_fields_without_echoing_values(self):
        episode = _episode(EPISODE_1, 1, "First")
        chapter = _chapter(
            "group-1",
            "chapter-1",
            "Alpha",
            0,
            1,
            1,
            [EPISODE_1],
        )
        self._write_catalog(
            "previous.json",
            {
                "schema_version": 3,
                "work_id": WORK_ID,
                "work_metadata": _work_metadata(),
                "episodes": [episode],
                "chapters": [chapter],
            },
        )
        self._write_catalog(
            "current.json",
            {
                "schema_version": 3,
                "work_id": WORK_ID,
                "work_metadata": _work_metadata(
                    introduction="Revised introduction",
                    tags=["fixture", "new-tag"],
                ),
                "episodes": [episode],
                "chapters": [chapter],
            },
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = main(
                [
                    "--source-root",
                    str(self.root),
                    "--previous-catalog",
                    "previous.json",
                    "--current-catalog",
                    "current.json",
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["work_metadata_comparison"], "available")
        self.assertEqual(
            report["work_metadata_changed_fields"],
            ["introduction", "tags"],
        )
        self.assertNotIn("Revised introduction", stdout.getvalue())
        self.assertNotIn("Synthetic Author", stdout.getvalue())

    def test_reports_empty_chapter_group_metadata_changes(self):
        base_episode = _episode(EPISODE_1, 1, "First")
        self._write_catalog(
            "previous.json",
            {
                "schema_version": 2,
                "work_id": WORK_ID,
                "episodes": [base_episode],
                "chapters": [
                    _chapter(
                        "group-1",
                        "chapter-1",
                        "Alpha",
                        0,
                        1,
                        1,
                        [EPISODE_1],
                    ),
                    _chapter(
                        "empty-group",
                        "empty-chapter",
                        "Empty",
                        1,
                        None,
                        None,
                        [],
                    ),
                ],
            },
        )
        self._write_catalog(
            "current.json",
            {
                "schema_version": 2,
                "work_id": WORK_ID,
                "episodes": [base_episode],
                "chapters": [
                    _chapter(
                        "group-1",
                        "chapter-1",
                        "Alpha",
                        0,
                        1,
                        1,
                        [EPISODE_1],
                    ),
                    _chapter(
                        "empty-group",
                        "empty-chapter",
                        "Empty renamed",
                        1,
                        None,
                        None,
                        [],
                    ),
                ],
            },
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = main(
                [
                    "--source-root",
                    str(self.root),
                    "--previous-catalog",
                    "previous.json",
                    "--current-catalog",
                    "current.json",
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(
            report["chapter_counts"],
            {"added": 0, "removed": 0, "updated": 1, "unchanged": 1},
        )
        self.assertEqual(
            report["chapter_changes"][0]["changes"],
            ["chapter_metadata_changed"],
        )

    def test_reports_removed_episode_without_exporting_deletion(self):
        self._write_catalog(
            "previous.json",
            {
                "schema_version": 1,
                "work_id": WORK_ID,
                "episodes": [
                    _episode(EPISODE_1, 1, "First"),
                    _episode(EPISODE_2, 2, "Second"),
                ],
            },
        )
        self._write_catalog(
            "current.json",
            {
                "schema_version": 1,
                "work_id": WORK_ID,
                "episodes": [_episode(EPISODE_1, 1, "First")],
            },
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = main(
                [
                    "--source-root",
                    str(self.root),
                    "--previous-catalog",
                    "previous.json",
                    "--current-catalog",
                    "current.json",
                ]
            )

        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["counts"]["removed"], 1)
        self.assertEqual(report["changes"][0]["change"], "removed")
        self.assertFalse((self.root / "source_manifest.json").exists())

    def test_existing_export_is_never_overwritten(self):
        self._write_catalog(
            "previous.json",
            {
                "schema_version": 1,
                "work_id": WORK_ID,
                "episodes": [_episode(EPISODE_1, 1, "First")],
            },
        )
        self._write_catalog(
            "current.json",
            {
                "schema_version": 1,
                "work_id": WORK_ID,
                "episodes": [
                    _episode(EPISODE_1, 1, "First"),
                    _episode(EPISODE_2, 2, "Second"),
                ],
            },
        )
        output_path = self.root / "added.json"
        output_path.write_text("preserve\n", encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(
                [
                    "--source-root",
                    str(self.root),
                    "--previous-catalog",
                    "previous.json",
                    "--current-catalog",
                    "current.json",
                    "--export",
                    "added",
                    "--catalog-output",
                    "added.json",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "ERROR: FileExistsError\n")
        self.assertEqual(output_path.read_text(encoding="utf-8"), "preserve\n")

    def test_append_only_status_allows_appending_to_an_existing_chapter(self):
        previous = {
            "schema_version": 2,
            "work_id": WORK_ID,
            "episodes": [_episode(EPISODE_1, 1, "First")],
            "chapters": [
                _chapter(
                    "group-1",
                    "chapter-1",
                    "Alpha",
                    0,
                    1,
                    1,
                    [EPISODE_1],
                )
            ],
        }
        current = {
            "schema_version": 2,
            "work_id": WORK_ID,
            "episodes": [
                _episode(EPISODE_1, 1, "First"),
                _episode(EPISODE_2, 2, "Second"),
            ],
            "chapters": [
                _chapter(
                    "group-1",
                    "chapter-1",
                    "Alpha",
                    0,
                    1,
                    2,
                    [EPISODE_1, EPISODE_2],
                )
            ],
        }
        self._write_catalog("previous.json", previous)
        self._write_catalog("current.json", current)

        status = append_only_catalog_status(
            _load_catalog_snapshot(str(self.root), "previous.json"),
            _load_catalog_snapshot(str(self.root), "current.json"),
        )

        self.assertEqual(
            status,
            {
                "append_only": True,
                "added_count": 1,
                "chapter_comparison": "available",
                "issues": [],
            },
        )

    def test_append_only_status_rejects_reordered_or_renamed_old_episode(self):
        previous = {
            "schema_version": 1,
            "work_id": WORK_ID,
            "episodes": [
                _episode(EPISODE_1, 1, "First"),
                _episode(EPISODE_2, 2, "Second"),
            ],
        }
        current = {
            "schema_version": 1,
            "work_id": WORK_ID,
            "episodes": [
                _episode(EPISODE_2, 1, "Second"),
                _episode(EPISODE_1, 2, "First renamed"),
                _episode(EPISODE_3, 3, "Third"),
            ],
        }
        self._write_catalog("previous.json", previous)
        self._write_catalog("current.json", current)

        status = append_only_catalog_status(
            _load_catalog_snapshot(str(self.root), "previous.json"),
            _load_catalog_snapshot(str(self.root), "current.json"),
        )

        self.assertFalse(status["append_only"])
        self.assertEqual(status["issues"], ["existing_episode_changed"])

    def test_exact_refresh_status_allows_work_metadata_change_only(self):
        previous = {
            "schema_version": 3,
            "work_id": WORK_ID,
            "episodes": [_episode(EPISODE_1, 1, "First")],
            "chapters": [
                _chapter(
                    "group-1",
                    "chapter-1",
                    "Alpha",
                    0,
                    1,
                    1,
                    [EPISODE_1],
                )
            ],
            "work_metadata": _work_metadata(),
        }
        current = {
            **previous,
            "work_metadata": _work_metadata(title="Updated work title"),
        }
        self._write_catalog("previous.json", previous)
        self._write_catalog("current.json", current)

        status = exact_refresh_catalog_status(
            _load_catalog_snapshot(str(self.root), "previous.json"),
            _load_catalog_snapshot(str(self.root), "current.json"),
        )

        self.assertEqual(
            status,
            {
                "same_catalog": True,
                "episode_count": 1,
                "chapter_comparison": "available",
                "issues": [],
            },
        )

    def test_exact_refresh_status_rejects_episode_and_chapter_changes(self):
        previous = {
            "schema_version": 2,
            "work_id": WORK_ID,
            "episodes": [_episode(EPISODE_1, 1, "First")],
            "chapters": [
                _chapter(
                    "group-1",
                    "chapter-1",
                    "Alpha",
                    0,
                    1,
                    1,
                    [EPISODE_1],
                )
            ],
        }
        changed = {
            **previous,
            "episodes": [_episode(EPISODE_1, 1, "Renamed")],
        }
        self._write_catalog("previous.json", previous)
        self._write_catalog("changed.json", changed)
        status = exact_refresh_catalog_status(
            _load_catalog_snapshot(str(self.root), "previous.json"),
            _load_catalog_snapshot(str(self.root), "changed.json"),
        )
        self.assertFalse(status["same_catalog"])
        self.assertEqual(status["issues"], ["episode_metadata_changed"])

        changed_chapter = {
            **previous,
            "chapters": [
                _chapter(
                    "group-1",
                    "chapter-2",
                    "Beta",
                    0,
                    1,
                    1,
                    [EPISODE_1],
                )
            ],
        }
        self._write_catalog("changed-chapter.json", changed_chapter)
        chapter_status = exact_refresh_catalog_status(
            _load_catalog_snapshot(str(self.root), "previous.json"),
            _load_catalog_snapshot(str(self.root), "changed-chapter.json"),
        )
        self.assertFalse(chapter_status["same_catalog"])
        self.assertEqual(chapter_status["issues"], ["chapter_structure_changed"])


if __name__ == "__main__":
    unittest.main()
