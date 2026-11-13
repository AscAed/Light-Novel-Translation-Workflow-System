import tempfile
import unittest
from pathlib import Path

from utils import read_child_text, resolve_child_path, write_new_child_text


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


if __name__ == "__main__":
    unittest.main()
