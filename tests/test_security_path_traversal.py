import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import (
    read_child_text,
    read_relative_text,
    resolve_child_path,
    resolve_relative_path,
    write_new_child_text,
    write_new_relative_text,
    write_text_atomically,
)


class TestChapterPathBoundaries(unittest.TestCase):
    def test_rejects_path_components_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                resolve_child_path(temp_dir, "../outside.md", allow_missing=True)
            with self.assertRaises(ValueError):
                resolve_child_path(temp_dir, r"C:\outside.md", allow_missing=True)

    def test_reads_a_regular_child_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            chapter = Path(temp_dir) / "chapter.md"
            chapter.write_text("chapter", encoding="utf-8")
            self.assertEqual(read_child_text(temp_dir, chapter.name), "chapter")

    def test_reads_and_creates_files_under_explicit_relative_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "卷一"
            output_dir = root / "译文"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "第1話.md").write_text("synthetic source", encoding="utf-8")

            self.assertEqual(
                read_relative_text(str(root), "卷一/第1話.md"),
                "synthetic source",
            )
            write_new_relative_text(
                str(root), "译文/第1話.md", "synthetic translation"
            )
            self.assertEqual(
                (output_dir / "第1話.md").read_text(encoding="utf-8"),
                "synthetic translation",
            )

    def test_relative_path_rejects_absolute_and_traversal_components(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for relative_path in (
                "../outside.md",
                "卷一/../outside.md",
                "/outside.md",
                r"卷一\chapter.md",
                r"C:\outside.md",
                "卷一/chapter:stream.md",
            ):
                with self.subTest(relative_path=relative_path):
                    with self.assertRaises(ValueError):
                        resolve_relative_path(
                            temp_dir, relative_path, allow_missing=True
                        )

    def test_relative_write_requires_existing_parent_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "parent directories"):
                write_new_relative_text(
                    temp_dir, "missing/chapter.md", "synthetic translation"
                )

    def test_rejects_symlinked_relative_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "root"
            outside = Path(temp_dir) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "chapter.md").write_text("private", encoding="utf-8")
            link = root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlink creation is unavailable: {exc}")

            with self.assertRaises(ValueError):
                read_relative_text(str(root), "linked/chapter.md")
            with self.assertRaises(ValueError):
                write_new_relative_text(
                    str(root), "linked/new.md", "synthetic translation"
                )

    def test_rejects_symlinked_chapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "raw"
            root.mkdir()
            outside = Path(temp_dir) / "outside.md"
            outside.write_text("private", encoding="utf-8")
            link = root / "chapter.md"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlink creation is unavailable: {exc}")

            with self.assertRaises(ValueError):
                read_child_text(str(root), link.name)

    def test_rejects_dangling_output_link(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "translated"
            root.mkdir()
            outside = Path(temp_dir) / "created-outside.md"
            link = root / "chapter.md"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlink creation is unavailable: {exc}")

            with self.assertRaises(ValueError):
                write_new_child_text(str(root), link.name, "translation")
            self.assertFalse(outside.exists())

    def test_atomic_write_preserves_previous_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "translation_memory.json"
            target.write_text('{"chapters": {}}', encoding="utf-8")

            with patch("utils.os.replace", side_effect=OSError("simulated failure")):
                with self.assertRaisesRegex(OSError, "simulated failure"):
                    write_text_atomically(str(target), '{"chapters": {"new": []}}')

            self.assertEqual(target.read_text(encoding="utf-8"), '{"chapters": {}}')
            self.assertEqual([item.name for item in Path(temp_dir).iterdir()], [target.name])


if __name__ == "__main__":
    unittest.main()
