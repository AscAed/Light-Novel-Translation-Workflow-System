import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source_ingestion import (
    CatalogPage,
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    SourceAccessDenied,
    SourceRateLimited,
    collect_source,
    new_checkpoint,
    validate_checkpoint,
)
from source_manifest import append_artifact, load_manifest, verify_manifest_files


class SyntheticSourceAdapter:
    def __init__(self, pages, content, *, denied_cursors=(), limited_episodes=()):
        self.pages = pages
        self.content = content
        self.denied_cursors = set(denied_cursors)
        self.limited_episodes = set(limited_episodes)
        self.catalog_calls = []
        self.episode_calls = []
        snapshot = {
            "pages": [
                {
                    "cursor": cursor,
                    "next_cursor": page.next_cursor,
                    "episodes": [
                        {
                            "episode_id": episode.episode_id,
                            "title": episode.title,
                            "position": episode.position,
                            "source_ref": episode.source_ref,
                        }
                        for episode in page.episodes
                    ],
                }
                for cursor, page in sorted(
                    self.pages.items(),
                    key=lambda item: "" if item[0] is None else item[0],
                )
            ],
            "content": {
                episode_id: hashlib.sha256(content).hexdigest()
                for episode_id, content in sorted(self.content.items())
            },
        }
        snapshot_bytes = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.source_fingerprint = hashlib.sha256(snapshot_bytes).hexdigest()

    def list_episodes(self, cursor):
        self.catalog_calls.append(cursor)
        if cursor in self.denied_cursors:
            raise SourceAccessDenied
        return self.pages[cursor]

    def fetch_episode(self, episode_id):
        self.episode_calls.append(episode_id)
        if episode_id in self.limited_episodes:
            raise SourceRateLimited
        return self.content[episode_id]


class SourceIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_collects_pages_and_writes_metadata_and_raw_versions(self):
        adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (
                        EpisodeMetadata("ep-1", "第 1 话", 1),
                        EpisodeMetadata("ep-2", "第 2 话", 2),
                    ),
                    "page-2",
                ),
                "page-2": CatalogPage(
                    (EpisodeMetadata("ep-3", "第 3 话", 3),),
                    None,
                ),
            },
            {
                "ep-1": b"synthetic raw one",
                "ep-2": b"synthetic raw two",
                "ep-3": b"synthetic raw three",
            },
        )

        report = collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(
            report,
            {
                "status": "complete",
                "reason": None,
                "discovered_count": 3,
                "completed_count": 3,
                "pending_count": 0,
            },
        )
        self.assertEqual(adapter.catalog_calls, [None, "page-2"])
        manifest = load_manifest(self.root / "source_manifest.json")
        self.assertEqual(len(manifest["artifacts"]), 6)
        self.assertEqual(
            verify_manifest_files(self.root, manifest),
            6,
        )

    def test_resume_after_rate_limit_does_not_relist_completed_page(self):
        adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (
                        EpisodeMetadata("ep-1", "第 1 话", 1),
                        EpisodeMetadata("ep-2", "第 2 话", 2),
                    ),
                    "page-2",
                ),
                "page-2": CatalogPage(
                    (EpisodeMetadata("ep-3", "第 3 话", 3),),
                    None,
                ),
            },
            {
                "ep-1": b"synthetic raw one",
                "ep-2": b"synthetic raw two",
                "ep-3": b"synthetic raw three",
            },
            limited_episodes={"ep-2"},
        )

        paused = collect_source(adapter, root=self.root, work_id="work-1")
        checkpoint = json.loads(
            (self.root / "source_checkpoint.json").read_text(encoding="utf-8")
        )
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["reason"], "rate_limited")
        self.assertEqual(paused["completed_count"], 1)
        self.assertEqual(checkpoint["pending_episodes"][0]["episode_id"], "ep-2")

        adapter.limited_episodes.clear()
        resumed = collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(resumed["completed_count"], 3)
        self.assertEqual(adapter.catalog_calls, [None, "page-2"])
        self.assertEqual(adapter.episode_calls.count("ep-1"), 1)
        self.assertEqual(adapter.episode_calls.count("ep-2"), 2)

    def test_resume_rejects_a_changed_source_snapshot(self):
        first_adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (
                        EpisodeMetadata("ep-1", "第 1 话", 1),
                        EpisodeMetadata("ep-2", "第 2 话", 2),
                    ),
                    None,
                )
            },
            {"ep-1": b"synthetic source one", "ep-2": b"synthetic source old"},
            limited_episodes={"ep-2"},
        )
        paused = collect_source(first_adapter, root=self.root, work_id="work-1")
        checkpoint_before = (self.root / "source_checkpoint.json").read_bytes()
        self.assertEqual(paused["status"], "paused")

        changed_adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (
                        EpisodeMetadata("ep-1", "第 1 话", 1),
                        EpisodeMetadata("ep-2", "修订后的标题", 2, "source-v2"),
                    ),
                    None,
                )
            },
            {"ep-1": b"synthetic source one", "ep-2": b"synthetic source new"},
        )

        with self.assertRaisesRegex(ValueError, "current source snapshot"):
            collect_source(changed_adapter, root=self.root, work_id="work-1")

        self.assertEqual(changed_adapter.catalog_calls, [])
        self.assertEqual(changed_adapter.episode_calls, [])
        self.assertEqual(
            (self.root / "source_checkpoint.json").read_bytes(),
            checkpoint_before,
        )

    def test_access_denial_pauses_without_trying_another_cursor(self):
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((), None)},
            {},
            denied_cursors={None},
        )

        report = collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(report["status"], "paused")
        self.assertEqual(report["reason"], "access_denied")
        self.assertEqual(adapter.catalog_calls, [None])
        self.assertFalse((self.root / "source_manifest.json").exists())

    def test_local_file_adapter_collects_explicit_paths_without_modifying_sources(self):
        source_root = self.root / "input"
        (source_root / "volume-b").mkdir(parents=True)
        first_source = source_root / "volume-b" / "episode-7.md"
        second_source = source_root / "episode-2.md"
        first_source.write_bytes(b"synthetic local source 7")
        second_source.write_bytes(b"synthetic local source 2")
        first_before = first_source.read_bytes()
        second_before = second_source.read_bytes()
        adapter = LocalFileAdapter(
            source_root,
            (
                LocalEpisodeFile(
                    EpisodeMetadata("local-7", "Chapter Seven", 7),
                    "volume-b/episode-7.md",
                ),
                LocalEpisodeFile(
                    EpisodeMetadata("local-2", "Chapter Two", 2),
                    "episode-2.md",
                ),
            ),
            page_size=1,
        )

        report = collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["completed_count"], 2)
        self.assertEqual(first_source.read_bytes(), first_before)
        self.assertEqual(second_source.read_bytes(), second_before)
        manifest = load_manifest(self.root / "source_manifest.json")
        self.assertEqual(
            verify_manifest_files(self.root, manifest),
            4,
        )
        metadata_artifact = next(
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "episode"
        )
        metadata = json.loads(
            (self.root / metadata_artifact["relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(metadata["source_ref"], "local:volume-b/episode-7.md")

    def test_local_file_adapter_fingerprint_binds_paths_and_source_bytes(self):
        source_root = self.root / "input"
        source_root.mkdir()
        source_file = source_root / "episode.md"
        source_file.write_bytes(b"synthetic source before snapshot")
        adapter = LocalFileAdapter(
            source_root,
            (
                LocalEpisodeFile(
                    EpisodeMetadata("local-1", "Chapter", 1),
                    "episode.md",
                ),
            ),
        )

        source_file.write_bytes(b"synthetic source changed")

        with self.assertRaisesRegex(ValueError, "changed after snapshot"):
            adapter.fetch_episode("local-1")

        changed_adapter = LocalFileAdapter(
            source_root,
            (
                LocalEpisodeFile(
                    EpisodeMetadata("local-1", "Chapter", 1),
                    "episode.md",
                ),
            ),
        )
        self.assertNotEqual(adapter.source_fingerprint, changed_adapter.source_fingerprint)

    def test_local_file_adapter_rejects_paths_outside_explicit_root(self):
        source_root = self.root / "input"
        source_root.mkdir()

        with self.assertRaisesRegex(ValueError, "traversal components"):
            LocalFileAdapter(
                source_root,
                (LocalEpisodeFile(EpisodeMetadata("local-1", "Chapter", 1), "../outside.md"),),
            )

    def test_local_file_adapter_rejects_duplicate_episode_ids(self):
        source_root = self.root / "input"
        source_root.mkdir()
        (source_root / "one.md").write_bytes(b"one")
        (source_root / "two.md").write_bytes(b"two")

        with self.assertRaisesRegex(ValueError, "repeats an episode_id"):
            LocalFileAdapter(
                source_root,
                (
                    LocalEpisodeFile(EpisodeMetadata("local-1", "First", 1), "one.md"),
                    LocalEpisodeFile(EpisodeMetadata("local-1", "Second", 2), "two.md"),
                ),
            )

    def test_new_content_appends_a_version_with_parent_lineage(self):
        first_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), None)},
            {"ep-1": b"synthetic raw v1"},
        )
        collect_source(
            first_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="run-1.json",
        )
        first_manifest = load_manifest(self.root / "source_manifest.json")
        previous_raw = next(
            artifact
            for artifact in first_manifest["artifacts"]
            if artifact["kind"] == "raw_source"
        )

        second_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), None)},
            {"ep-1": b"synthetic raw v2"},
        )
        collect_source(
            second_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="run-2.json",
        )
        manifest = load_manifest(self.root / "source_manifest.json")
        raw_versions = [
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "raw_source"
        ]

        self.assertEqual(len(raw_versions), 2)
        self.assertIn(previous_raw["version_id"], raw_versions[1]["parent_version_ids"])
        self.assertEqual(verify_manifest_files(self.root, manifest), 3)

    def test_metadata_change_creates_linked_metadata_and_raw_versions(self):
        first_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Old title", 1),), None)},
            {"ep-1": b"synthetic raw"},
        )
        collect_source(
            first_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="run-1.json",
        )
        first_manifest = load_manifest(self.root / "source_manifest.json")
        previous_metadata = next(
            artifact
            for artifact in first_manifest["artifacts"]
            if artifact["kind"] == "episode"
        )
        previous_raw = next(
            artifact
            for artifact in first_manifest["artifacts"]
            if artifact["kind"] == "raw_source"
        )

        second_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "New title", 1),), None)},
            {"ep-1": b"synthetic raw"},
        )
        collect_source(
            second_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="run-2.json",
        )
        manifest = load_manifest(self.root / "source_manifest.json")
        metadata_versions = [
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "episode"
        ]
        raw_versions = [
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "raw_source"
        ]

        self.assertEqual(len(metadata_versions), 2)
        self.assertEqual(len(raw_versions), 2)
        self.assertIn(
            previous_metadata["version_id"],
            metadata_versions[1]["parent_version_ids"],
        )
        self.assertIn(previous_raw["version_id"], raw_versions[1]["parent_version_ids"])
        self.assertIn(
            metadata_versions[1]["version_id"],
            raw_versions[1]["parent_version_ids"],
        )
        self.assertEqual(verify_manifest_files(self.root, manifest), 4)

    def test_repeated_episode_in_catalog_is_rejected(self):
        adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (
                        EpisodeMetadata("ep-1", "First", 1),
                        EpisodeMetadata("ep-1", "Duplicate", 2),
                    ),
                    None,
                )
            },
            {"ep-1": b"synthetic"},
        )

        with self.assertRaisesRegex(ValueError, "repeats an episode_id"):
            collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(adapter.episode_calls, [])
        self.assertFalse((self.root / "source_manifest.json").exists())

    def test_repeating_a_completed_collection_is_idempotent(self):
        pages = {None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), None)}
        content = {"ep-1": b"synthetic raw"}
        first = SyntheticSourceAdapter(pages, content)
        collect_source(first, root=self.root, work_id="work-1")
        manifest_before = (self.root / "source_manifest.json").read_bytes()
        second = SyntheticSourceAdapter(pages, content)

        report = collect_source(second, root=self.root, work_id="work-1")

        self.assertEqual(report["status"], "complete")
        self.assertEqual(second.catalog_calls, [])
        self.assertEqual(second.episode_calls, [])
        self.assertEqual((self.root / "source_manifest.json").read_bytes(), manifest_before)

        new_run = SyntheticSourceAdapter(pages, content)
        collect_source(
            new_run,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="second_run.json",
        )

        self.assertEqual(new_run.catalog_calls, [None])
        self.assertEqual(new_run.episode_calls, ["ep-1"])
        self.assertEqual((self.root / "source_manifest.json").read_bytes(), manifest_before)

    def test_manifest_failure_reuses_durable_artifact_on_resume(self):
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), None)},
            {"ep-1": b"synthetic raw"},
        )
        fail_raw_manifest_once = [True]

        def append_with_raw_failure(path, artifact):
            if artifact["kind"] == "raw_source" and fail_raw_manifest_once[0]:
                fail_raw_manifest_once[0] = False
                raise OSError("synthetic manifest write failure")
            return append_artifact(path, artifact)

        with patch(
            "source_ingestion.append_artifact",
            side_effect=append_with_raw_failure,
        ):
            with self.assertRaisesRegex(OSError, "synthetic manifest write failure"):
                collect_source(adapter, root=self.root, work_id="work-1")

            checkpoint = json.loads(
                (self.root / "source_checkpoint.json").read_text(encoding="utf-8")
            )
            manifest_after_failure = load_manifest(self.root / "source_manifest.json")
            orphaned_raw = list((self.root / "raw").rglob("*.bin"))

            self.assertEqual(checkpoint["status"], "in_progress")
            self.assertEqual(checkpoint["pending_episodes"][0]["episode_id"], "ep-1")
            self.assertEqual(
                [artifact["kind"] for artifact in manifest_after_failure["artifacts"]],
                ["episode"],
            )
            self.assertEqual(len(orphaned_raw), 1)

            report = collect_source(adapter, root=self.root, work_id="work-1")

        manifest_after_resume = load_manifest(self.root / "source_manifest.json")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(adapter.catalog_calls, [None])
        self.assertEqual(
            [artifact["kind"] for artifact in manifest_after_resume["artifacts"]],
            ["episode", "raw_source"],
        )
        self.assertEqual(verify_manifest_files(self.root, manifest_after_resume), 2)

    def test_incomplete_legacy_checkpoint_refuses_unbound_resume(self):
        checkpoint = new_checkpoint("work-1", "legacy-source")
        checkpoint.update(
            {
                "schema_version": 1,
                "source_fingerprint": None,
                "page_loaded": True,
                "pending_episodes": [
                    {
                        "episode_id": "ep-1",
                        "title": "Episode",
                        "position": 1,
                    }
                ],
                "discovered_episode_ids": ["ep-1"],
            }
        )
        checkpoint.pop("source_fingerprint")
        (self.root / "source_checkpoint.json").write_text(
            json.dumps(checkpoint),
            encoding="utf-8",
        )
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((), None)},
            {"ep-1": b"synthetic raw"},
        )
        checkpoint_before = (self.root / "source_checkpoint.json").read_bytes()

        with self.assertRaisesRegex(ValueError, "no source_fingerprint"):
            collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(
            (self.root / "source_checkpoint.json").read_bytes(),
            checkpoint_before,
        )
        self.assertEqual(adapter.catalog_calls, [])
        self.assertEqual(adapter.episode_calls, [])

    def test_completed_legacy_checkpoint_migrates_without_fetching(self):
        checkpoint = new_checkpoint("work-1", "legacy-source")
        checkpoint["schema_version"] = 2
        checkpoint["status"] = "complete"
        checkpoint.pop("source_fingerprint")
        (self.root / "source_checkpoint.json").write_text(
            json.dumps(checkpoint),
            encoding="utf-8",
        )
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((), None)},
            {},
        )

        report = collect_source(adapter, root=self.root, work_id="work-1")

        migrated = json.loads(
            (self.root / "source_checkpoint.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["status"], "complete")
        self.assertEqual(migrated["schema_version"], 3)
        self.assertEqual(migrated["source_fingerprint"], adapter.source_fingerprint)
        self.assertEqual(adapter.catalog_calls, [])
        self.assertEqual(adapter.episode_calls, [])

    def test_checkpoint_rejects_non_string_status_and_pause_reason(self):
        checkpoint = new_checkpoint("work-1", "snapshot-1")
        checkpoint["status"] = []
        with self.assertRaisesRegex(ValueError, "unsupported status"):
            validate_checkpoint(checkpoint)

        checkpoint = new_checkpoint("work-1", "snapshot-1")
        checkpoint["status"] = "paused"
        checkpoint["pause_reason"] = {}
        with self.assertRaisesRegex(ValueError, "known pause_reason"):
            validate_checkpoint(checkpoint)

    def test_pagination_cycle_pauses_after_processing_the_page(self):
        adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), "page-2"),
                "page-2": CatalogPage((), "page-2"),
            },
            {"ep-1": b"synthetic raw"},
        )

        report = collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(report["status"], "paused")
        self.assertEqual(report["reason"], "pagination_cycle")
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(adapter.catalog_calls, [None, "page-2"])

        repeated = collect_source(adapter, root=self.root, work_id="work-1")
        self.assertEqual(repeated["reason"], "pagination_cycle")
        self.assertEqual(adapter.catalog_calls, [None, "page-2"])


if __name__ == "__main__":
    unittest.main()
