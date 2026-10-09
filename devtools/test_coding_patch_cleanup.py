"""Revocation after patch creation must remove the artifact."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_task_runner import propose


class PatchCleanupTests(unittest.TestCase):
    def test_revocation_after_patch_written_removes_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "example.py").write_text("answer = 1\n")
            count = 0

            def checkpoint():
                nonlocal count
                count += 1
                if count == 4:
                    raise PermissionError("grant revoked")

            diff = "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-answer = 1\n+answer = 2\n"
            with self.assertRaises(PermissionError):
                propose(repo, "change answer", ["example.py"], "mock",
                        root / "journal", root / "patches",
                        generate=lambda *args: diff, checkpoint=checkpoint)
            self.assertEqual(list((root / "patches").glob("*.patch")), [])
            self.assertEqual((repo / "example.py").read_text(), "answer = 1\n")
            journal_files = list((root / "journal").glob("*.json"))
            self.assertEqual(len(journal_files), 1)


if __name__ == "__main__":
    unittest.main()
