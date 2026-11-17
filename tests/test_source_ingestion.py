import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source_ingestion import (
    CatalogPage,
    EpisodeMetadata,
    FetchedEpisode,
    LocalEpisodeFile,
    LocalFileAdapter,
    SourceAccessDenied,
    SourceRateLimited,
    _persist_work_metadata,
    collect_source,
    compare_full_refresh_versions,
    new_checkpoint,
    prepare_append_only_checkpoint,
    prepare_full_refresh_checkpoint,
    source_artifact_id,
    validate_checkpoint,
)
from source_manifest import (
    append_artifact,
    load_manifest,
    verified_manifest_content_bytes,
    verify_manifest_files,
)


class SyntheticSourceAdapter:
    def __init__(
        self,
        pages,
        content,
        *,
        page_html=None,
        denied_cursors=(),
        limited_episodes=(),
    ):
        self.pages = pages
        self.content = content
        self.page_html = page_html or {}
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
            "page_html": {
                episode_id: hashlib.sha256(page_html).hexdigest()
                for episode_id, page_html in sorted(self.page_html.items())
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
        if episode_id in self.page_html:
            metadata = next(
                episode
                for page in self.pages.values()
                for episode in page.episodes
                if episode.episode_id == episode_id
            )
            return FetchedEpisode(
                metadata,
                self.content[episode_id],
                self.page_html[episode_id],
            )
        return self.content[episode_id]


class SourceIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_append_only_checkpoint_reuses_verified_prefix_and_fetches_suffix(self):
        first = EpisodeMetadata(
            "ep-1", "First", 1, "https://source.test/ep-1"
        )
        second = EpisodeMetadata(
            "ep-2", "Second", 2, "https://source.test/ep-2"
        )
        baseline_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((first,), None)},
            {"ep-1": b"first body"},
        )
        collect_source(
            baseline_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="baseline.json",
        )
        baseline_checkpoint_bytes = (self.root / "baseline.json").read_bytes()

        update_adapter = SyntheticSourceAdapter(
            {"1": CatalogPage((second,), None)},
            {"ep-1": b"first body", "ep-2": b"second body"},
        )
        checkpoint = prepare_append_only_checkpoint(
            update_adapter,
            root=self.root,
            work_id="work-1",
            current_episodes=(first, second),
            baseline_episode_ids=["ep-1"],
            baseline_checkpoint_relative_path="baseline.json",
            checkpoint_relative_path="update.json",
        )

        self.assertEqual(checkpoint["status"], "in_progress")
        self.assertEqual(checkpoint["cursor"], "1")
        self.assertEqual(checkpoint["discovered_episode_ids"], ["ep-1"])
        self.assertEqual(checkpoint["completed_episode_ids"], ["ep-1"])
        self.assertEqual(
            checkpoint["completed_raw_versions"]["ep-1"],
            json.loads(baseline_checkpoint_bytes)["completed_raw_versions"]["ep-1"],
        )

        report = collect_source(
            update_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="update.json",
        )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(update_adapter.catalog_calls, ["1"])
        self.assertEqual(update_adapter.episode_calls, ["ep-2"])
        self.assertEqual(
            (self.root / "baseline.json").read_bytes(),
            baseline_checkpoint_bytes,
        )
        merged = json.loads((self.root / "update.json").read_text(encoding="utf-8"))
        self.assertEqual(
            merged["completed_episode_ids"], ["ep-1", "ep-2"]
        )
        self.assertEqual(
            set(merged["completed_raw_versions"]), {"ep-1", "ep-2"}
        )

    def test_append_only_checkpoint_resumes_a_paused_suffix(self):
        first = EpisodeMetadata(
            "ep-1", "First", 1, "https://source.test/ep-1"
        )
        second = EpisodeMetadata(
            "ep-2", "Second", 2, "https://source.test/ep-2"
        )
        collect_source(
            SyntheticSourceAdapter(
                {None: CatalogPage((first,), None)},
                {"ep-1": b"first body"},
            ),
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="baseline.json",
        )
        limited_adapter = SyntheticSourceAdapter(
            {"1": CatalogPage((second,), None)},
            {"ep-1": b"first body", "ep-2": b"second body"},
            limited_episodes={"ep-2"},
        )
        prepare_append_only_checkpoint(
            limited_adapter,
            root=self.root,
            work_id="work-1",
            current_episodes=(first, second),
            baseline_episode_ids=["ep-1"],
            baseline_checkpoint_relative_path="baseline.json",
            checkpoint_relative_path="update.json",
        )
        paused = collect_source(
            limited_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="update.json",
        )
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["reason"], "rate_limited")

        retry_adapter = SyntheticSourceAdapter(
            {"1": CatalogPage((second,), None)},
            {"ep-1": b"first body", "ep-2": b"second body"},
        )
        resumed = prepare_append_only_checkpoint(
            retry_adapter,
            root=self.root,
            work_id="work-1",
            current_episodes=(first, second),
            baseline_episode_ids=["ep-1"],
            baseline_checkpoint_relative_path="baseline.json",
            checkpoint_relative_path="update.json",
        )
        self.assertEqual(resumed["status"], "paused")
        report = collect_source(
            retry_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="update.json",
        )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(retry_adapter.catalog_calls, [])
        self.assertEqual(retry_adapter.episode_calls, ["ep-2"])

    def test_append_only_checkpoint_rejects_changed_existing_metadata(self):
        first = EpisodeMetadata(
            "ep-1", "First", 1, "https://source.test/ep-1"
        )
        collect_source(
            SyntheticSourceAdapter(
                {None: CatalogPage((first,), None)},
                {"ep-1": b"first body"},
            ),
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="baseline.json",
        )
        changed = EpisodeMetadata(
            "ep-1", "Renamed", 1, "https://source.test/ep-1"
        )
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((changed,), None)},
            {"ep-1": b"first body"},
        )
        baseline_before = (self.root / "baseline.json").read_bytes()

        with self.assertRaisesRegex(ValueError, "metadata changed"):
            prepare_append_only_checkpoint(
                adapter,
                root=self.root,
                work_id="work-1",
                current_episodes=(changed,),
                baseline_episode_ids=["ep-1"],
                baseline_checkpoint_relative_path="baseline.json",
                checkpoint_relative_path="update.json",
            )

        self.assertFalse((self.root / "update.json").exists())
        self.assertEqual(
            (self.root / "baseline.json").read_bytes(), baseline_before
        )

    def test_full_refresh_hashes_changes_and_resumes_without_replacing_baseline(self):
        first = EpisodeMetadata(
            "ep-1", "First", 1, "https://source.test/ep-1"
        )
        second = EpisodeMetadata(
            "ep-2", "Second", 2, "https://source.test/ep-2"
        )
        baseline_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((first, second), None)},
            {"ep-1": b"same body", "ep-2": b"before"},
        )
        collect_source(
            baseline_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="baseline.json",
        )
        baseline_checkpoint_bytes = (self.root / "baseline.json").read_bytes()
        baseline_manifest = load_manifest(self.root / "source_manifest.json")
        baseline_raw_versions = {
            item["artifact_id"]: item["version_id"]
            for item in baseline_manifest["artifacts"]
            if item["kind"] == "raw_source"
        }

        limited_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((first, second), None)},
            {"ep-1": b"same body", "ep-2": b"after"},
            limited_episodes={"ep-2"},
        )
        limited_adapter.source_fingerprint = "c" * 64
        prepared = prepare_full_refresh_checkpoint(
            limited_adapter,
            root=self.root,
            work_id="work-1",
            current_episodes=(first, second),
            baseline_episode_ids=["ep-1", "ep-2"],
            baseline_catalog_sha256="a" * 64,
            baseline_checkpoint_relative_path="baseline.json",
            checkpoint_relative_path="refresh.json",
        )
        paused = collect_source(
            prepared["adapter"],
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="refresh.json",
        )
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["reason"], "rate_limited")
        self.assertEqual(limited_adapter.episode_calls, ["ep-1", "ep-2"])

        retry_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((first, second), None)},
            {"ep-1": b"same body", "ep-2": b"after"},
        )
        retry_adapter.source_fingerprint = "c" * 64
        resumed = prepare_full_refresh_checkpoint(
            retry_adapter,
            root=self.root,
            work_id="work-1",
            current_episodes=(first, second),
            baseline_episode_ids=["ep-1", "ep-2"],
            baseline_catalog_sha256="a" * 64,
            baseline_checkpoint_relative_path="baseline.json",
            checkpoint_relative_path="refresh.json",
        )
        report = collect_source(
            resumed["adapter"],
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="refresh.json",
        )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(retry_adapter.catalog_calls, [])
        self.assertEqual(retry_adapter.episode_calls, ["ep-2"])
        self.assertEqual(
            (self.root / "baseline.json").read_bytes(),
            baseline_checkpoint_bytes,
        )
        comparison = compare_full_refresh_versions(
            root=self.root,
            work_id="work-1",
            episode_ids=["ep-1", "ep-2"],
            baseline_checkpoint_relative_path="baseline.json",
            checkpoint_relative_path="refresh.json",
        )
        self.assertEqual(comparison["unchanged_count"], 1)
        self.assertEqual(comparison["changed_count"], 1)
        self.assertEqual(
            [item["episode_id"] for item in comparison["changed_episodes"]],
            ["ep-2"],
        )
        self.assertTrue(comparison["downstream_review_required"])
        final_manifest = load_manifest(self.root / "source_manifest.json")
        final_raw_versions = {}
        for item in final_manifest["artifacts"]:
            if item["kind"] == "raw_source":
                final_raw_versions.setdefault(item["artifact_id"], []).append(
                    item["version_id"]
                )
        for artifact_id, version_id in baseline_raw_versions.items():
            self.assertIn(version_id, final_raw_versions[artifact_id])
        self.assertEqual(
            len(final_raw_versions[source_artifact_id("work-1", "raw_source", "ep-1")]),
            1,
        )
        self.assertEqual(
            len(final_raw_versions[source_artifact_id("work-1", "raw_source", "ep-2")]),
            2,
        )

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

    def test_archives_work_metadata_versions_and_reuses_unchanged_snapshot(self):
        adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (EpisodeMetadata("ep-1", "Episode", 1),),
                    None,
                )
            },
            {"ep-1": b"synthetic raw"},
        )
        first_metadata = {"title": "Synthetic work", "tags": ["fixture"]}

        first_report = collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            work_metadata=first_metadata,
        )

        self.assertEqual(first_report["status"], "complete")
        manifest_path = self.root / "source_manifest.json"
        first_manifest = load_manifest(manifest_path)
        work_artifacts = [
            item for item in first_manifest["artifacts"] if item["kind"] == "work"
        ]
        self.assertEqual(len(work_artifacts), 1)
        first_artifact = work_artifacts[0]
        first_record = json.loads(
            (self.root / first_artifact["relative_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(first_record["metadata"], first_metadata)
        self.assertRegex(
            first_record["recorded_at_utc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )

        repeated = collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            work_metadata=first_metadata,
        )
        self.assertEqual(repeated["status"], "complete")
        repeated_manifest = load_manifest(manifest_path)
        self.assertEqual(
            len([item for item in repeated_manifest["artifacts"] if item["kind"] == "work"]),
            1,
        )

        updated_metadata = {"title": "Revised synthetic work", "tags": ["fixture"]}
        updated = collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            work_metadata=updated_metadata,
        )
        self.assertEqual(updated["status"], "complete")
        updated_manifest = load_manifest(manifest_path)
        updated_artifacts = [
            item for item in updated_manifest["artifacts"] if item["kind"] == "work"
        ]
        self.assertEqual(len(updated_artifacts), 2)
        self.assertEqual(
            updated_artifacts[-1]["parent_version_ids"],
            [first_artifact["version_id"]],
        )
        updated_record = json.loads(
            (self.root / updated_artifacts[-1]["relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(updated_record["metadata"], updated_metadata)
        self.assertEqual(adapter.episode_calls, ["ep-1"])
        self.assertEqual(
            verify_manifest_files(self.root, updated_manifest),
            len(updated_manifest["artifacts"]),
        )

    def test_work_metadata_artifact_counts_toward_archive_byte_limit(self):
        metadata = {"title": "Synthetic work " + "x" * 4096}
        manifest_path = self.root / "source_manifest.json"
        _persist_work_metadata(
            self.root,
            manifest_path,
            "work-1",
            metadata,
        )
        manifest_before = manifest_path.read_bytes()
        archive_bytes = verified_manifest_content_bytes(
            self.root,
            load_manifest(manifest_path),
        )
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), None)},
            {"ep-1": b"x"},
        )

        report = collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            work_metadata=metadata,
            max_archive_bytes=archive_bytes + 1,
        )

        self.assertEqual(report["status"], "paused")
        self.assertEqual(report["reason"], "archive_limit")
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        manifest = load_manifest(manifest_path)
        self.assertEqual([item["kind"] for item in manifest["artifacts"]], ["work"])
        self.assertEqual(adapter.catalog_calls, [None])
        self.assertEqual(adapter.episode_calls, ["ep-1"])

    def test_work_metadata_obeys_archive_byte_limit_before_writing(self):
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), None)},
            {"ep-1": b"synthetic raw"},
        )

        report = collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            work_metadata={"title": "Synthetic work"},
            max_archive_bytes=1,
        )

        self.assertEqual(report["status"], "paused")
        self.assertEqual(report["reason"], "archive_limit")
        self.assertFalse((self.root / "source_manifest.json").exists())
        checkpoint = json.loads(
            (self.root / "source_checkpoint.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checkpoint["status"], "paused")
        self.assertEqual(checkpoint["pause_reason"], "archive_limit")
        self.assertEqual(adapter.catalog_calls, [])
        self.assertEqual(adapter.episode_calls, [])

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

    def test_resume_rejects_a_different_destination_manifest(self):
        adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (
                        EpisodeMetadata("ep-1", "第 1 话", 1),
                        EpisodeMetadata("ep-2", "第 2 话", 2),
                    ),
                    None,
                )
            },
            {"ep-1": b"synthetic one", "ep-2": b"synthetic two"},
            limited_episodes={"ep-2"},
        )
        paused = collect_source(adapter, root=self.root, work_id="work-1")
        checkpoint_before = (self.root / "source_checkpoint.json").read_bytes()
        calls_before = (list(adapter.catalog_calls), list(adapter.episode_calls))
        self.assertEqual(paused["completed_count"], 1)

        with self.assertRaisesRegex(ValueError, "destination manifest"):
            collect_source(
                adapter,
                root=self.root,
                work_id="work-1",
                manifest_relative_path="alternate_manifest.json",
            )

        self.assertFalse((self.root / "alternate_manifest.json").exists())
        self.assertEqual(
            (self.root / "source_checkpoint.json").read_bytes(),
            checkpoint_before,
        )
        self.assertEqual(
            (adapter.catalog_calls, adapter.episode_calls),
            calls_before,
        )

        adapter.limited_episodes.clear()
        resumed = collect_source(adapter, root=self.root, work_id="work-1")
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(resumed["completed_count"], 2)

    def test_completed_checkpoint_rejects_a_different_destination_manifest(self):
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), None)},
            {"ep-1": b"synthetic raw"},
        )
        collect_source(adapter, root=self.root, work_id="work-1")
        checkpoint_before = (self.root / "source_checkpoint.json").read_bytes()

        with self.assertRaisesRegex(ValueError, "destination manifest"):
            collect_source(
                adapter,
                root=self.root,
                work_id="work-1",
                manifest_relative_path="alternate_manifest.json",
            )

        self.assertFalse((self.root / "alternate_manifest.json").exists())
        self.assertEqual(
            (self.root / "source_checkpoint.json").read_bytes(),
            checkpoint_before,
        )

    def test_source_artifact_ids_encode_identity_components_without_collisions(self):
        first_adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (EpisodeMetadata("x:episode:y", "First", 1),),
                    None,
                )
            },
            {"x:episode:y": b"synthetic first"},
        )
        second_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("y", "Second", 1),), None)},
            {"y": b"synthetic second"},
        )

        collect_source(
            first_adapter,
            root=self.root,
            work_id="w",
            checkpoint_relative_path="first_checkpoint.json",
        )
        collect_source(
            second_adapter,
            root=self.root,
            work_id="w:episode:x",
            checkpoint_relative_path="second_checkpoint.json",
        )

        manifest = load_manifest(self.root / "source_manifest.json")
        artifact_ids = [artifact["artifact_id"] for artifact in manifest["artifacts"]]
        self.assertEqual(len(artifact_ids), 4)
        self.assertEqual(len(set(artifact_ids)), 4)
        self.assertEqual(verify_manifest_files(self.root, manifest), 4)

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

    def test_empty_catalog_is_rejected_without_completing_checkpoint(self):
        adapter = SyntheticSourceAdapter({None: CatalogPage((), None)}, {})

        with self.assertRaisesRegex(ValueError, "empty catalog"):
            collect_source(adapter, root=self.root, work_id="work-1")

        checkpoint = json.loads(
            (self.root / "source_checkpoint.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checkpoint["status"], "in_progress")
        self.assertEqual(checkpoint["discovered_episode_ids"], [])
        self.assertEqual(adapter.catalog_calls, [None])
        self.assertEqual(adapter.episode_calls, [])
        self.assertFalse((self.root / "source_manifest.json").exists())

    def test_empty_intermediate_page_can_be_followed_by_episodes(self):
        adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage((), "page-2"),
                "page-2": CatalogPage(
                    (EpisodeMetadata("ep-1", "Episode", 1),),
                    None,
                ),
            },
            {"ep-1": b"synthetic raw"},
        )

        report = collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(adapter.catalog_calls, [None, "page-2"])

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

    def test_local_file_adapter_rejects_episode_over_byte_limit(self):
        source_root = self.root / "input"
        source_root.mkdir()
        (source_root / "episode.md").write_bytes(b"123456")

        with self.assertRaisesRegex(ValueError, "configured byte limit"):
            LocalFileAdapter(
                source_root,
                (LocalEpisodeFile(EpisodeMetadata("local-1", "Episode", 1), "episode.md"),),
                max_episode_bytes=5,
                max_catalog_bytes=100,
            )

    def test_local_file_adapter_rejects_catalog_over_total_byte_limit(self):
        source_root = self.root / "input"
        source_root.mkdir()
        (source_root / "one.md").write_bytes(b"123")
        (source_root / "two.md").write_bytes(b"456")

        with self.assertRaisesRegex(ValueError, "configured byte limit"):
            LocalFileAdapter(
                source_root,
                (
                    LocalEpisodeFile(EpisodeMetadata("local-1", "One", 1), "one.md"),
                    LocalEpisodeFile(EpisodeMetadata("local-2", "Two", 2), "two.md"),
                ),
                max_episode_bytes=5,
                max_catalog_bytes=5,
            )

    def test_local_file_adapter_bounds_reads_after_source_grows(self):
        source_root = self.root / "input"
        source_root.mkdir()
        source_file = source_root / "episode.md"
        source_file.write_bytes(b"12345")
        adapter = LocalFileAdapter(
            source_root,
            (LocalEpisodeFile(EpisodeMetadata("local-1", "Episode", 1), "episode.md"),),
            max_episode_bytes=5,
            max_catalog_bytes=10,
        )

        source_file.write_bytes(b"123456789")

        with self.assertRaisesRegex(ValueError, "configured byte limit"):
            adapter.fetch_episode("local-1")

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

    def test_archives_raw_page_html_with_source_lineage_and_exact_bytes(self):
        metadata = EpisodeMetadata(
            "ep-1", "Episode", 1, "https://source.test/ep-1"
        )
        page_html = b"<div class='episode'><ruby>raw markup</ruby></div>\r\n"
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((metadata,), None)},
            {"ep-1": b"visible parsed text"},
            page_html={"ep-1": page_html},
        )

        report = collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            max_archive_bytes=4096,
        )

        manifest = load_manifest(self.root / "source_manifest.json")
        metadata_artifact = next(
            item for item in manifest["artifacts"] if item["kind"] == "episode"
        )
        raw_artifact = next(
            item for item in manifest["artifacts"] if item["kind"] == "raw_source"
        )
        html_artifact = next(
            item for item in manifest["artifacts"] if item["kind"] == "raw_page_html"
        )
        self.assertEqual(report["status"], "complete")
        self.assertEqual(html_artifact["parent_version_ids"], [
            metadata_artifact["version_id"],
            raw_artifact["version_id"],
        ])
        self.assertEqual(
            (self.root / html_artifact["relative_path"]).read_bytes(),
            page_html,
        )
        self.assertEqual(
            (self.root / raw_artifact["relative_path"]).read_bytes(),
            b"visible parsed text",
        )
        self.assertEqual(verify_manifest_files(self.root, manifest), 3)
        self.assertEqual(
            verified_manifest_content_bytes(self.root, manifest),
            sum(
                len((self.root / item["relative_path"]).read_bytes())
                for item in manifest["artifacts"]
            ),
        )

    def test_changed_page_html_appends_capture_without_changing_visible_source(self):
        metadata = EpisodeMetadata("ep-1", "Episode", 1)
        pages = {None: CatalogPage((metadata,), None)}
        first = SyntheticSourceAdapter(
            pages,
            {"ep-1": b"visible parsed text"},
            page_html={"ep-1": b"<p>first capture</p>"},
        )
        collect_source(
            first,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="first.json",
        )
        first_manifest = load_manifest(self.root / "source_manifest.json")
        first_raw = next(
            item for item in first_manifest["artifacts"] if item["kind"] == "raw_source"
        )

        second = SyntheticSourceAdapter(
            pages,
            {"ep-1": b"visible parsed text"},
            page_html={"ep-1": b"<p>second capture</p>"},
        )
        collect_source(
            second,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="second.json",
        )

        manifest = load_manifest(self.root / "source_manifest.json")
        raw_versions = [
            item for item in manifest["artifacts"] if item["kind"] == "raw_source"
        ]
        html_versions = [
            item for item in manifest["artifacts"] if item["kind"] == "raw_page_html"
        ]
        latest_html = html_versions[-1]
        self.assertEqual(len(raw_versions), 1)
        self.assertEqual(len(html_versions), 2)
        self.assertEqual(first_raw["version_id"], raw_versions[-1]["version_id"])
        self.assertIn(raw_versions[-1]["version_id"], latest_html["parent_version_ids"])
        self.assertEqual(verify_manifest_files(self.root, manifest), 4)

    def test_raw_page_html_counts_toward_archive_limit_before_append(self):
        metadata = EpisodeMetadata("ep-1", "Episode", 1)
        pages = {None: CatalogPage((metadata,), None)}
        first = SyntheticSourceAdapter(
            pages,
            {"ep-1": b"visible parsed text"},
        )
        collect_source(
            first,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="text-only.json",
        )
        manifest_path = self.root / "source_manifest.json"
        manifest_before = manifest_path.read_bytes()
        existing_bytes = verified_manifest_content_bytes(
            self.root, load_manifest(manifest_path)
        )
        second = SyntheticSourceAdapter(
            pages,
            {"ep-1": b"visible parsed text"},
            page_html={"ep-1": b"<p>captured page</p>"},
        )

        report = collect_source(
            second,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="page-html.json",
            max_archive_bytes=existing_bytes,
        )

        self.assertEqual(report["status"], "paused")
        self.assertEqual(report["reason"], "archive_limit")
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertFalse(list((self.root / "raw_page_html").glob("**/*.html")))

    def test_archive_limit_preflights_episode_and_binds_resume_budget(self):
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Episode", 1),), None)},
            {"ep-1": b"synthetic raw"},
        )

        paused = collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            max_archive_bytes=1,
        )

        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["reason"], "archive_limit")
        self.assertFalse((self.root / "source_manifest.json").exists())
        checkpoint = json.loads(
            (self.root / "source_checkpoint.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checkpoint["pending_episodes"][0]["episode_id"], "ep-1")
        self.assertEqual(
            collect_source(
                adapter,
                root=self.root,
                work_id="work-1",
                max_archive_bytes=1,
            ),
            paused,
        )
        self.assertEqual(adapter.catalog_calls, [None])
        self.assertEqual(adapter.episode_calls, ["ep-1"])

        with self.assertRaisesRegex(ValueError, "source snapshot"):
            collect_source(
                adapter,
                root=self.root,
                work_id="work-1",
                max_archive_bytes=1024,
            )

        resumed = collect_source(
            adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="larger-budget.json",
            max_archive_bytes=1024,
        )
        self.assertEqual(resumed["status"], "complete")
        manifest = load_manifest(self.root / "source_manifest.json")
        self.assertLessEqual(
            verified_manifest_content_bytes(self.root, manifest),
            1024,
        )

    def test_archive_limit_counts_history_and_preflights_changed_versions(self):
        first_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Old title", 1),), None)},
            {"ep-1": b"synthetic raw v1"},
        )
        collect_source(first_adapter, root=self.root, work_id="work-1")
        first_manifest_bytes = (self.root / "source_manifest.json").read_bytes()
        existing_bytes = verified_manifest_content_bytes(
            self.root,
            load_manifest(self.root / "source_manifest.json"),
        )

        same_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "Old title", 1),), None)},
            {"ep-1": b"synthetic raw v1"},
        )
        repeated = collect_source(
            same_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="same-content.json",
            max_archive_bytes=existing_bytes,
        )
        self.assertEqual(repeated["status"], "complete")
        self.assertEqual(
            (self.root / "source_manifest.json").read_bytes(),
            first_manifest_bytes,
        )

        changed_adapter = SyntheticSourceAdapter(
            {None: CatalogPage((EpisodeMetadata("ep-1", "New title", 1),), None)},
            {"ep-1": b"synthetic raw v2"},
        )
        changed = collect_source(
            changed_adapter,
            root=self.root,
            work_id="work-1",
            checkpoint_relative_path="changed-content.json",
            max_archive_bytes=existing_bytes,
        )

        self.assertEqual(changed["status"], "paused")
        self.assertEqual(changed["reason"], "archive_limit")
        self.assertEqual(
            (self.root / "source_manifest.json").read_bytes(),
            first_manifest_bytes,
        )
        checkpoint = json.loads(
            (self.root / "changed-content.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checkpoint["completed_episode_ids"], [])
        self.assertEqual(checkpoint["pending_episodes"][0]["episode_id"], "ep-1")

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
        checkpoint.pop("manifest_relative_path")
        checkpoint.pop("completed_raw_versions")
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

    def test_legacy_checkpoint_without_fingerprint_refuses_migration(self):
        checkpoint = new_checkpoint("work-1", "legacy-source")
        checkpoint["schema_version"] = 2
        checkpoint.pop("source_fingerprint")
        checkpoint.pop("manifest_relative_path")
        checkpoint.pop("completed_raw_versions")
        (self.root / "source_checkpoint.json").write_text(
            json.dumps(checkpoint),
            encoding="utf-8",
        )
        adapter = SyntheticSourceAdapter(
            {
                None: CatalogPage(
                    (EpisodeMetadata("ep-1", "Episode", 1),),
                    None,
                )
            },
            {"ep-1": b"synthetic raw"},
        )
        checkpoint_before = (self.root / "source_checkpoint.json").read_bytes()

        with self.assertRaisesRegex(ValueError, "no source_fingerprint"):
            collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(
            (self.root / "source_checkpoint.json").read_bytes(),
            checkpoint_before,
        )
        self.assertFalse((self.root / "source_manifest.json").exists())
        self.assertEqual(adapter.catalog_calls, [])
        self.assertEqual(adapter.episode_calls, [])

    def test_checkpoint_rejects_complete_state_without_discovered_episodes(self):
        checkpoint = new_checkpoint("work-1", "snapshot-1")
        checkpoint["status"] = "complete"

        with self.assertRaisesRegex(ValueError, "contains no episodes"):
            validate_checkpoint(checkpoint)

    def test_legacy_checkpoint_with_completed_episodes_requires_new_checkpoint(self):
        checkpoint = new_checkpoint("work-1", "legacy-source")
        checkpoint.update(
            {
                "schema_version": 3,
                "status": "complete",
                "discovered_episode_ids": ["ep-1"],
                "completed_episode_ids": ["ep-1"],
            }
        )
        checkpoint.pop("manifest_relative_path")
        checkpoint.pop("completed_raw_versions")
        (self.root / "source_checkpoint.json").write_text(
            json.dumps(checkpoint),
            encoding="utf-8",
        )
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((), None)},
            {"ep-1": b"synthetic raw"},
        )
        checkpoint_before = (self.root / "source_checkpoint.json").read_bytes()

        with self.assertRaisesRegex(ValueError, "completed raw version bindings"):
            collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(
            (self.root / "source_checkpoint.json").read_bytes(),
            checkpoint_before,
        )
        self.assertEqual(adapter.catalog_calls, [])
        self.assertEqual(adapter.episode_calls, [])

    def test_v4_complete_checkpoint_without_raw_bindings_refuses_migration(self):
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((), None)},
            {"ep-1": b"synthetic raw"},
        )
        checkpoint = new_checkpoint(
            "work-1",
            adapter.source_fingerprint,
            "source_manifest.json",
        )
        checkpoint.update(
            {
                "schema_version": 4,
                "status": "complete",
                "discovered_episode_ids": ["ep-1"],
                "completed_episode_ids": ["ep-1"],
            }
        )
        checkpoint.pop("completed_raw_versions")
        (self.root / "source_checkpoint.json").write_text(
            json.dumps(checkpoint),
            encoding="utf-8",
        )
        checkpoint_before = (self.root / "source_checkpoint.json").read_bytes()

        with self.assertRaisesRegex(ValueError, "completed raw version bindings"):
            collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(
            (self.root / "source_checkpoint.json").read_bytes(),
            checkpoint_before,
        )
        self.assertEqual(adapter.catalog_calls, [])
        self.assertEqual(adapter.episode_calls, [])

    def test_v4_incomplete_checkpoint_preserves_manifest_binding(self):
        adapter = SyntheticSourceAdapter(
            {None: CatalogPage((), None)},
            {},
        )
        checkpoint = new_checkpoint(
            "work-1",
            adapter.source_fingerprint,
            "legacy-manifest.json",
        )
        checkpoint["schema_version"] = 4
        checkpoint.pop("completed_raw_versions")
        (self.root / "source_checkpoint.json").write_text(
            json.dumps(checkpoint),
            encoding="utf-8",
        )
        checkpoint_before = (self.root / "source_checkpoint.json").read_bytes()

        with self.assertRaisesRegex(ValueError, "destination manifest"):
            collect_source(adapter, root=self.root, work_id="work-1")

        self.assertEqual(
            (self.root / "source_checkpoint.json").read_bytes(),
            checkpoint_before,
        )
        self.assertEqual(adapter.catalog_calls, [])
        self.assertEqual(adapter.episode_calls, [])

    def test_oversized_metadata_fails_before_writing_source_artifacts(self):
        source_root = self.root / "input"
        source_root.mkdir()
        (source_root / "episode.md").write_bytes(b"source")
        adapter = LocalFileAdapter(
            source_root,
            (
                LocalEpisodeFile(
                    EpisodeMetadata("ep-1", "x" * (1024 * 1024), 1),
                    "episode.md",
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "metadata exceeds"):
            collect_source(adapter, root=self.root, work_id="work-1")

        self.assertFalse((self.root / "source_manifest.json").exists())
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()),
            ["input", "source_checkpoint.json"],
        )

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
