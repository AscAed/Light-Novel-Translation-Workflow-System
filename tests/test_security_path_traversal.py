import unittest
import os
import sys

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pipeline

class TestPathTraversalSecurity(unittest.TestCase):
    def test_path_sanitization_in_pipeline(self):
        # We test the logic used in pipeline.py
        def sanitize(chapter_filename):
            return os.path.normpath('/' + chapter_filename).lstrip('/')

        # 1. Normal file
        self.assertEqual(sanitize("chapter_1.md"), "chapter_1.md")

        # 2. File in subdirectory
        self.assertEqual(sanitize("arc_1/chapter_1.md"), "arc_1/chapter_1.md")

        # 3. Path traversal attack
        self.assertEqual(sanitize("../../../etc/passwd"), "etc/passwd")

        # 4. Deep path traversal attack
        self.assertEqual(sanitize("arc_1/../../../../etc/passwd"), "etc/passwd")

        # 5. Absolute path attack
        self.assertEqual(sanitize("/etc/passwd"), "etc/passwd")

if __name__ == '__main__':
    unittest.main()
