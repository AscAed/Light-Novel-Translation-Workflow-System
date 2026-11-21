import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.ingest_kakuyomu_pages import (
    _ai_edition_index_freshness,
    _load_catalog_snapshot,
)
from scripts.validate_source_editions import main as validate_source_editions_main
from source_editions import (
    _index_refresh_is_safe,
    prepare_source_editions,
    read_verified_ai_edition_bytes,
    safe_path_component,
    synchronize_edition_manifest_with_source_history,
    validate_source_editions,
    verify_ai_edition_index,
)
from source_editions import _prepare_human_text
from source_ingestion import (
    EpisodeMetadata,
    LocalEpisodeFile,
    LocalFileAdapter,
    collect_source,
    materialize_episode_markdown,
)
from source_manifest import (
    append_artifact,
    load_manifest,
    verify_current_normalized_source,
)


class SourceEditionsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.input_root = self.root / "input"
        self.source_root = self.root / "archive"
        self.human_root = self.root / "human"
        self.ai_root = self.root / "project" / "RAWs_AI"
        self.input_root.mkdir()
        self.source_root.mkdir()
        self.human_root.mkdir()
        self.ai_root.mkdir(parents=True)

        self.episodes = [
            EpisodeMetadata("101", "第1話", 1),
            EpisodeMetadata("102", "第2話", 2),
            EpisodeMetadata("103", "第3話", 3),
        ]
        self.source_bytes = {
            "101": (
                "第一段\n\n　｜漢字《かんじ》。｜強調《・・・》\n"
            ).encode("utf-8"),
            "102": "　　第二話の文章。\n".encode("utf-8"),
            "103": "第三話の文章。\r\n\r\n末尾。\r\n".encode("utf-8"),
        }
        adapter_episodes = []
        for episode in self.episodes:
            filename = f"{episode.episode_id}.txt"
            (self.input_root / filename).write_bytes(
                self.source_bytes[episode.episode_id]
            )
            adapter_episodes.append(
                LocalEpisodeFile(episode, filename)
            )
        collect_source(
            LocalFileAdapter(self.input_root, adapter_episodes),
            root=self.source_root,
            work_id="12345",
            checkpoint_relative_path="source_checkpoint.json",
        )
        for episode in self.episodes:
            artifact = materialize_episode_markdown(
                self.source_root,
                work_id="12345",
                episode_id=episode.episode_id,
            )
            artifact_path = self.source_root.joinpath(
                *artifact["relative_path"].split("/")
            )
            self.source_bytes[episode.episode_id] = artifact_path.read_bytes()
        self.catalog_path = self.source_root / "source_catalog.json"
        catalog = {
            "schema_version": 2,
            "work_id": "12345",
            "episodes": [
                {
                    "episode_id": episode.episode_id,
                    "title": episode.title,
                    "position": episode.position,
                    "page_url": (
                        "https://kakuyomu.jp/works/12345/episodes/"
                        + episode.episode_id
                    ),
                }
                for episode in self.episodes
            ],
            "chapters": [
                {
                    "group_id": "chapter-one",
                    "chapter_id": "chapter-one",
                    "title": "第一章: 起始/相遇?",
                    "level": 1,
                    "position_start": 1,
                    "position_end": 2,
                    "episode_ids": ["101", "102"],
                },
                {
                    "group_id": "chapter-two",
                    "chapter_id": "chapter-two",
                    "title": "第二章",
                    "level": 1,
                    "position_start": 3,
                    "position_end": 3,
                    "episode_ids": ["103"],
                },
            ],
        }
        self.catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _export(self, max_total_bytes=1024 * 1024, refresh_indexes=False):
        return prepare_source_editions(
            source_root=str(self.source_root),
            catalog_relative_path="source_catalog.json",
            manifest_relative_path="source_manifest.json",
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
            max_total_bytes=max_total_bytes,
            refresh_indexes=refresh_indexes,
        )

    def _append_unrelated_source_artifact(self):
        content = b"newly collected source"
        relative_path = "raw/newly-collected.bin"
        artifact_path = self.source_root / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(content)
        append_artifact(
            self.source_root / "source_manifest.json",
            {
                "artifact_id": "newly-collected-source",
                "version_id": "newly-collected-source-v1",
                "kind": "raw_source",
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "relative_path": relative_path,
                "parent_version_ids": [],
            },
        )

    @staticmethod
    def _tree_bytes(root):
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    def test_read_only_validator_recomputes_both_cleaning_profiles(self):
        self._export()
        roots_before = {
            "source": self._tree_bytes(self.source_root),
            "human": self._tree_bytes(self.human_root),
            "ai": self._tree_bytes(self.ai_root),
        }

        report = validate_source_editions(
            source_root=str(self.source_root),
            catalog_relative_path="source_catalog.json",
            human_root=str(self.human_root),
            ai_root=str(self.ai_root),
        )

        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["episode_count"], 3)
        self.assertGreater(report["source_bytes"], 0)
        self.assertGreater(report["ai_output_bytes"], 0)
        self.assertGreater(report["human_output_bytes"], 0)
        self.assertEqual(roots_before["source"], self._tree_bytes(self.source_root))
        self.assertEqual(roots_before["human"], self._tree_bytes(self.human_root))
        self.assertEqual(roots_before["ai"], self._tree_bytes(self.ai_root))

    def test_read_only_validator_cli_reports_counts_without_source_text(self):
        self._export()
        roots_before = {
            "source": self._tree_bytes(self.source_root),
            "human": self._tree_bytes(self.human_root),
            "ai": self._tree_bytes(self.ai_root),
        }
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = validate_source_editions_main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "source_catalog.json",
                    "--human-root",
                    str(self.human_root),
                    "--ai-root",
                    str(self.ai_root),
                ]
            )

        report = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["episode_count"], 3)
        self.assertNotIn("第一段", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(roots_before["source"], self._tree_bytes(self.source_root))
        self.assertEqual(roots_before["human"], self._tree_bytes(self.human_root))
        self.assertEqual(roots_before["ai"], self._tree_bytes(self.ai_root))

    def test_read_only_validator_rejects_modified_human_output(self):
        self._export()
        chapter_dir = safe_path_component(
            "第一章: 起始/相遇?",
            fallback="unused",
        )
        human_output = self.human_root / chapter_dir / "第1話.md"
        human_output.write_bytes(human_output.read_bytes() + b"tampered")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = validate_source_editions_main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "source_catalog.json",
                    "--human-root",
                    str(self.human_root),
                    "--ai-root",
                    str(self.ai_root),
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Human edition does not match current profile", stderr.getvalue())
        self.assertNotIn("第一段", stderr.getvalue())
        self.assertTrue(human_output.read_bytes().endswith(b"tampered"))

    def test_read_only_validator_rejects_unhashable_episode_id_cleanly(self):
        self._export()
        index_path = self.human_root / "SOURCE_MAP.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["episodes"][0]["episode_id"] = ["101"]
        index_path.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            result = validate_source_editions_main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "source_catalog.json",
                    "--human-root",
                    str(self.human_root),
                    "--ai-root",
                    str(self.ai_root),
                ]
            )

        self.assertEqual(result, 1)
        self.assertIn("Human edition index contains an invalid episode ID.", stderr.getvalue())
        self.assertNotIn("第一段", stderr.getvalue())

    def test_read_only_validator_does_not_create_missing_roots(self):
        missing_root = self.root / "missing-human"

        with self.assertRaises(FileNotFoundError):
            validate_source_editions(
                source_root=str(self.source_root),
                catalog_relative_path="source_catalog.json",
                human_root=str(missing_root),
                ai_root=str(self.ai_root),
            )

        self.assertFalse(missing_root.exists())

    def test_source_history_sync_preserves_editions_and_is_idempotent(self):
        self._export()
        previous_edition_manifest = load_manifest(
            self.source_root / "source_editions_manifest.json"
        )
        self._append_unrelated_source_artifact()

        first = synchronize_edition_manifest_with_source_history(
            source_root=str(self.source_root)
        )
        synced = load_manifest(
            self.source_root / "source_editions_manifest.json"
        )
        second = synchronize_edition_manifest_with_source_history(
            source_root=str(self.source_root)
        )

        synced_by_version = {
            artifact["version_id"]: artifact
            for artifact in synced["artifacts"]
        }
        for artifact in previous_edition_manifest["artifacts"]:
            self.assertEqual(synced_by_version[artifact["version_id"]], artifact)
        self.assertIn(
            "newly-collected-source-v1",
            synced_by_version,
        )
        self.assertEqual(first["status"], "updated")
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(first["edition_manifest_sha256"], second["edition_manifest_sha256"])

    def test_ai_index_freshness_marks_new_source_history_stale(self):
        self._export()
        first_finding, expected_sources = _ai_edition_index_freshness(
            source_root=self.source_root,
            ai_root=self.ai_root,
            catalog_relative_path="source_catalog.json",
            manifest_relative_path="source_manifest.json",
            edition_manifest_relative_path="source_editions_manifest.json",
        )
        self._append_unrelated_source_artifact()
        synchronize_edition_manifest_with_source_history(
            source_root=str(self.source_root)
        )
        stale_finding, stale_expected_sources = _ai_edition_index_freshness(
            source_root=self.source_root,
            ai_root=self.ai_root,
            catalog_relative_path="source_catalog.json",
            manifest_relative_path="source_manifest.json",
            edition_manifest_relative_path="source_editions_manifest.json",
        )

        self.assertEqual(first_finding["status"], "verified")
        self.assertEqual(stale_finding["status"], "stale")
        self.assertEqual(len(expected_sources), len(self.episodes))
        self.assertEqual(stale_expected_sources, expected_sources)

    def test_creates_human_and_ai_layouts_from_current_manifest_sources(self):
        report = self._export()
        snapshot = _load_catalog_snapshot(
            str(self.source_root),
            "source_catalog.json",
        )
        self.assertEqual(report["status"], "materialized")
        self.assertEqual(report["episode_count"], 3)
        self.assertEqual(report["chapter_count"], 2)
        self.assertEqual(report["created_files"], 15)

        human_index = json.loads(
            (self.human_root / "SOURCE_MAP.json").read_text(encoding="utf-8")
        )
        ai_index = json.loads(
            (self.ai_root / "catalog.json").read_text(encoding="utf-8")
        )
        self.assertEqual(human_index["edition"], "human_reading")
        self.assertEqual(ai_index["edition"], "ai")
        self.assertEqual(human_index["source_manifest"], ai_index["source_manifest"])
        self.assertEqual(human_index["catalog"]["sha256"], snapshot["sha256"])

        chapter_dir = safe_path_component(
            "第一章: 起始/相遇?",
            fallback="unused",
        )
        human_relative = f"{chapter_dir}/第1話.md"
        human_path = self.human_root.joinpath(*human_relative.split("/"))
        ai_relative = "chapters/001_chapter-one/episodes/0001_101.md"
        ai_path = self.ai_root.joinpath(*ai_relative.split("/"))
        human_text = human_path.read_text(encoding="utf-8")
        ai_text = ai_path.read_text(encoding="utf-8")
        self.assertIn("<ruby><rb>漢字</rb>", human_text)
        self.assertIn("<rt>かんじ</rt>", human_text)
        self.assertIn("style=\"text-emphasis: filled sesame;\"", human_text)
        self.assertIn("　", human_text)
        self.assertNotIn("｜漢字《かんじ》", human_text)
        self.assertIn("漢字《かんじ》", ai_text)
        self.assertIn("**強調**", ai_text)
        self.assertNotIn("　", ai_text)
        self.assertNotIn("｜漢字", ai_text)
        self.assertNotEqual(human_path.read_bytes(), ai_path.read_bytes())
        human_second = (
            self.human_root / chapter_dir / "第2話.md"
        ).read_text(encoding="utf-8")
        ai_second = (
            self.ai_root
            / "chapters"
            / "001_chapter-one"
            / "episodes"
            / "0002_102.md"
        ).read_text(encoding="utf-8")
        self.assertIn("　　第二話の文章。", human_second)
        self.assertIn("　第二話の文章。", ai_second)
        self.assertEqual(
            human_index["episodes"][0]["human_relative_path"],
            human_relative,
        )
        self.assertEqual(
            ai_index["episodes"][0]["ai_relative_path"],
            ai_relative,
        )
        self.assertEqual(
            human_index["episodes"][0]["source_sha256"],
            hashlib.sha256(self.source_bytes["101"]).hexdigest(),
        )
        self.assertEqual(
            human_index["source_basis"],
            ai_index["source_basis"],
        )
        self.assertEqual(
            human_index["episodes"][0]["raw_source_version_id"],
            ai_index["episodes"][0]["raw_source_version_id"],
        )
        self.assertEqual(
            human_index["episodes"][0]["edition_input_version_id"],
            human_index["episodes"][0]["raw_source_version_id"],
        )
        self.assertEqual(
            human_index["episodes"][0]["edition_input_sha256"],
            human_index["episodes"][0]["raw_source_sha256"],
        )
        self.assertEqual(
            human_index["episodes"][0]["output_sha256"],
            hashlib.sha256(human_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            ai_index["episodes"][0]["output_sha256"],
            hashlib.sha256(ai_path.read_bytes()).hexdigest(),
        )
        edition_manifest = load_manifest(
            self.source_root / "source_editions_manifest.json"
        )
        ai_artifact = verify_current_normalized_source(
            self.source_root,
            edition_manifest,
            ai_index["episodes"][0]["ai_edition_version_id"],
        )
        self.assertEqual(
            ai_artifact["relative_path"],
            ai_index["episodes"][0]["ai_archive_relative_path"],
        )
        self.assertEqual(
            self.source_root.joinpath(
                *ai_artifact["relative_path"].split("/")
            ).read_bytes(),
            ai_path.read_bytes(),
        )
        self.assertEqual(
            human_index["edition_manifest"],
            ai_index["edition_manifest"],
        )
        verified_index = verify_ai_edition_index(
            source_root=str(self.source_root),
            ai_root=str(self.ai_root),
            source_manifest_relative_path="source_manifest.json",
            edition_manifest_relative_path="source_editions_manifest.json",
        )
        self.assertEqual(len(verified_index["episodes_by_id"]), 3)
        self.assertEqual(
            verified_index["episodes_by_id"]["101"]["output_sha256"],
            hashlib.sha256(ai_path.read_bytes()).hexdigest(),
        )

    def test_identical_rerun_reuses_outputs_without_changing_them(self):
        first = self._export()
        first_map = (self.human_root / "SOURCE_MAP.json").read_bytes()

        second = self._export()

        self.assertEqual(first["created_files"], 15)
        self.assertEqual(second["created_files"], 0)
        self.assertEqual(second["reused_files"], 15)
        self.assertEqual(
            (self.human_root / "SOURCE_MAP.json").read_bytes(),
            first_map,
        )

    def test_ai_edition_reader_uses_and_verifies_raws_ai_mirror(self):
        self._export()
        index = json.loads(
            (self.ai_root / "catalog.json").read_text(encoding="utf-8")
        )
        episode = index["episodes"][0]
        mirror = self.ai_root / episode["ai_relative_path"]
        content = read_verified_ai_edition_bytes(
            str(self.ai_root),
            episode["ai_relative_path"],
            episode["output_sha256"],
        )

        self.assertEqual(content, mirror.read_bytes())
        mirror.write_bytes(b"tampered AI input")
        with self.assertRaisesRegex(ValueError, "does not match"):
            read_verified_ai_edition_bytes(
                str(self.ai_root),
                episode["ai_relative_path"],
                episode["output_sha256"],
            )

    def test_ai_index_verification_rejects_changed_catalog_at_same_path(self):
        self._export()
        catalog_path = self.source_root / "source_catalog.json"
        original_catalog = json.loads(
            catalog_path.read_text(encoding="utf-8")
        )
        changes = {
            "reordered": lambda value: value["episodes"].reverse(),
            "removed": lambda value: value["episodes"].pop(),
            "renamed": lambda value: value["episodes"][0].update(
                {"title": "Changed title"}
            ),
        }

        for label, change in changes.items():
            with self.subTest(change=label):
                changed_catalog = copy.deepcopy(original_catalog)
                change(changed_catalog)
                catalog_path.write_text(
                    json.dumps(changed_catalog, ensure_ascii=False),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    verify_ai_edition_index(
                        source_root=str(self.source_root),
                        ai_root=str(self.ai_root),
                        source_manifest_relative_path="source_manifest.json",
                        edition_manifest_relative_path=(
                            "source_editions_manifest.json"
                        ),
                    )

        catalog_path.write_text(
            json.dumps(original_catalog, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_ai_index_verification_does_not_read_archived_episode_bodies(self):
        self._export()

        with patch(
            "source_manifest._verify_artifact_file",
            side_effect=AssertionError("archive body read during AI setup"),
        ):
            verified = verify_ai_edition_index(
                source_root=str(self.source_root),
                ai_root=str(self.ai_root),
                source_manifest_relative_path="source_manifest.json",
                edition_manifest_relative_path="source_editions_manifest.json",
            )

        self.assertEqual(len(verified["episodes_by_id"]), len(self.episodes))

    def test_conflicting_existing_output_fails_before_creating_other_outputs(self):
        chapter_dir = safe_path_component(
            "第一章: 起始/相遇?",
            fallback="unused",
        )
        conflicting = self.human_root / chapter_dir / "第1話.md"
        conflicting.parent.mkdir()
        conflicting.write_bytes(b"keep this")

        with self.assertRaisesRegex(ValueError, "Existing source-edition output"):
            self._export()

        self.assertEqual(conflicting.read_bytes(), b"keep this")
        self.assertFalse((self.ai_root / "catalog.json").exists())
        self.assertFalse((self.human_root / "SOURCE_MAP.json").exists())
        self.assertFalse(
            (self.source_root / "source_editions_manifest.json").exists()
        )

    def test_manifest_source_tampering_fails_before_output(self):
        normalized = next(
            artifact
            for artifact in json.loads(
                (self.source_root / "source_manifest.json").read_text(
                    encoding="utf-8"
                )
            )["artifacts"]
            if artifact["kind"] == "normalized_source"
            and artifact["relative_path"]
        )
        source_file = self.source_root.joinpath(
            *normalized["relative_path"].split("/")
        )
        source_file.write_bytes(b"changed")

        with self.assertRaisesRegex(ValueError, "content hash does not match"):
            self._export()

        self.assertFalse((self.ai_root / "catalog.json").exists())
        self.assertFalse((self.human_root / "SOURCE_MAP.json").exists())
        self.assertFalse(
            (self.source_root / "source_editions_manifest.json").exists()
        )

    def test_total_size_limit_fails_before_output(self):
        with self.assertRaisesRegex(ValueError, "total byte limit"):
            self._export(max_total_bytes=1)

        self.assertFalse((self.ai_root / "catalog.json").exists())
        self.assertFalse((self.human_root / "SOURCE_MAP.json").exists())

    def test_refresh_indexes_only_updates_known_provenance_fields(self):
        self._export()
        map_path = self.human_root / "SOURCE_MAP.json"
        index = json.loads(map_path.read_text(encoding="utf-8"))
        index.pop("edition_manifest")
        for episode in index["episodes"]:
            for field in (
                "ai_edition_artifact_id",
                "ai_edition_version_id",
                "ai_archive_relative_path",
                "human_edition_artifact_id",
                "human_edition_version_id",
                "human_archive_relative_path",
            ):
                episode.pop(field)
        map_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "index differs"):
            self._export()

        refreshed = self._export(refresh_indexes=True)

        self.assertEqual(refreshed["updated_files"], 1)
        updated = json.loads(map_path.read_text(encoding="utf-8"))
        self.assertIn("edition_manifest", updated)
        self.assertIn(
            "ai_edition_version_id",
            updated["episodes"][0],
        )

    def test_index_refresh_accepts_append_only_catalog_changes(self):
        previous = {
            "schema_version": 2,
            "work_id": "12345",
            "edition": "ai",
            "source_manifest": {
                "relative_path": "source_manifest.json",
                "sha256": "a" * 64,
            },
            "edition_manifest": {
                "relative_path": "source_editions_manifest.json",
                "sha256": "b" * 64,
            },
            "catalog": {
                "relative_path": "source_catalog.json",
                "sha256": "c" * 64,
            },
            "work_metadata": {
                "title": "Work",
                "public_episode_count": 1,
                "last_episode_published_at": "2026-01-01T00:00:00Z",
            },
            "chapters": [
                {
                    "group_id": "chapter-one",
                    "title": "Chapter One",
                    "position_start": 1,
                    "position_end": 1,
                    "episode_ids": ["101"],
                }
            ],
            "episodes": [
                {
                    "episode_id": "101",
                    "position": 1,
                    "title": "Episode 1",
                    "source_version_id": "raw-101",
                    "output_sha256": "d" * 64,
                    "ai_edition_version_id": "ai-101",
                }
            ],
        }
        current = copy.deepcopy(previous)
        current["source_manifest"]["sha256"] = "e" * 64
        current["edition_manifest"]["sha256"] = "f" * 64
        current["catalog"]["sha256"] = "0" * 64
        current["work_metadata"]["public_episode_count"] = 2
        current["work_metadata"]["last_episode_published_at"] = (
            "2026-01-02T00:00:00Z"
        )
        current["chapters"][0]["position_end"] = 2
        current["chapters"][0]["episode_ids"].append("102")
        current["episodes"].append(
            {
                "episode_id": "102",
                "position": 2,
                "title": "Episode 2",
                "source_version_id": "raw-102",
                "output_sha256": "1" * 64,
                "ai_edition_version_id": "ai-102",
            }
        )

        self.assertTrue(
            _index_refresh_is_safe(
                json.dumps(previous).encode("utf-8"),
                json.dumps(current).encode("utf-8"),
            )
        )

        appended_chapter = copy.deepcopy(current)
        appended_chapter["catalog"]["relative_path"] = (
            "source_catalog.discovered.json"
        )
        appended_chapter["work_metadata"]["public_episode_count"] = 3
        appended_chapter["work_metadata"]["last_episode_published_at"] = (
            "2026-01-03T00:00:00Z"
        )
        appended_chapter["chapters"].append(
            {
                "group_id": "chapter-two",
                "title": "Chapter Two",
                "position_start": 3,
                "position_end": 3,
                "episode_ids": ["103"],
            }
        )
        appended_chapter["episodes"].append(
            {
                "episode_id": "103",
                "position": 3,
                "title": "Episode 3",
                "source_version_id": "raw-103",
                "output_sha256": "2" * 64,
                "ai_edition_version_id": "ai-103",
            }
        )
        self.assertTrue(
            _index_refresh_is_safe(
                json.dumps(previous).encode("utf-8"),
                json.dumps(appended_chapter).encode("utf-8"),
            )
        )

        appended_chapter["work_metadata"]["public_episode_count"] = 4
        self.assertFalse(
            _index_refresh_is_safe(
                json.dumps(previous).encode("utf-8"),
                json.dumps(appended_chapter).encode("utf-8"),
            )
        )

        current["episodes"][0]["source_version_id"] = "changed-old-source"
        self.assertFalse(
            _index_refresh_is_safe(
                json.dumps(previous).encode("utf-8"),
                json.dumps(current).encode("utf-8"),
            )
        )

    def test_refresh_indexes_preserves_unrecognized_index_changes(self):
        self._export()
        map_path = self.human_root / "SOURCE_MAP.json"
        index = json.loads(map_path.read_text(encoding="utf-8"))
        index["user_note"] = "preserve this edit"
        map_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "index differs"):
            self._export(refresh_indexes=True)

        self.assertIn(
            "user_note",
            json.loads(map_path.read_text(encoding="utf-8")),
        )

    def test_refresh_indexes_rejects_changed_edition_provenance(self):
        self._export()
        index_path = self.ai_root / "catalog.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["episodes"][0]["ai_edition_version_id"] = "user-edited-version"
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "index differs"):
            self._export(refresh_indexes=True)

        retained = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(
            retained["episodes"][0]["ai_edition_version_id"],
            "user-edited-version",
        )

    def test_safe_filename_components_handle_windows_reserved_and_invalid_names(self):
        self.assertEqual(
            safe_path_component("CON", fallback="fallback"),
            "_CON",
        )
        self.assertEqual(
            safe_path_component("Chapter: One/Two?", fallback="fallback"),
            "Chapter_ One_Two_",
        )

    def test_safe_filename_components_reserve_utf8_bytes_for_extension(self):
        component = safe_path_component(
            "語" * 200,
            fallback="fallback",
            extension=".md",
        )

        self.assertLessEqual(len((component + ".md").encode("utf-8")), 255)
        self.assertLessEqual(
            len((component + ".md").encode("utf-16-le")) // 2,
            100,
        )

    def test_source_and_edition_manifest_paths_must_differ(self):
        with self.assertRaisesRegex(ValueError, "must be different files"):
            prepare_source_editions(
                source_root=str(self.source_root),
                catalog_relative_path="source_catalog.json",
                manifest_relative_path="source_manifest.json",
                human_root=str(self.human_root),
                ai_root=str(self.ai_root),
                edition_manifest_relative_path="source_manifest.json",
            )

        self.assertEqual(list(self.human_root.rglob("*.md")), [])
        self.assertEqual(list(self.ai_root.rglob("*.md")), [])

    def test_human_markup_escapes_source_text_around_special_annotations(self):
        rendered = _prepare_human_text(
            '<script>alert("x")</script>｜語《ご》&<b>raw</b>'
        )

        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("<ruby><rb>語</rb>", rendered)
        self.assertIn("&amp;&lt;b&gt;raw&lt;/b&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<b>raw</b>", rendered)

    def test_output_roots_cannot_be_nested_inside_archive(self):
        with self.assertRaisesRegex(ValueError, "must be disjoint"):
            prepare_source_editions(
                source_root=str(self.source_root),
                catalog_relative_path="source_catalog.json",
                manifest_relative_path="source_manifest.json",
                human_root=str(self.source_root / "human-edition"),
                ai_root=str(self.ai_root),
            )

        self.assertFalse((self.source_root / "human-edition").exists())

    def test_output_roots_reject_symbolic_links_before_resolution(self):
        original_is_symlink = Path.is_symlink

        def is_symlink(path):
            if path == self.human_root:
                return True
            return original_is_symlink(path)

        with patch.object(Path, "is_symlink", autospec=True, side_effect=is_symlink):
            with self.assertRaisesRegex(ValueError, "cannot be symbolic links"):
                self._export()

    def test_ai_index_verification_rejects_overlapping_archive_and_ai_roots(self):
        overlapping_roots = (
            self.source_root,
            self.source_root / "RAWs_AI",
            self.root,
        )
        overlapping_roots[1].mkdir()

        for ai_root in overlapping_roots:
            with self.subTest(ai_root=ai_root):
                with self.assertRaisesRegex(ValueError, "must be disjoint"):
                    verify_ai_edition_index(
                        source_root=str(self.source_root),
                        ai_root=str(ai_root),
                        source_manifest_relative_path="source_manifest.json",
                        edition_manifest_relative_path=(
                            "source_editions_manifest.json"
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
