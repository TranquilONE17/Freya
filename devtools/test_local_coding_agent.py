import tempfile
import unittest
from pathlib import Path
from local_coding_agent import selected_source, validate_proposal, build_prompt


class LocalCodingAgentTests(unittest.TestCase):
    def test_selected_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe.py").write_text("x = 1")
            self.assertEqual(selected_source(root, "safe.py"), "x = 1")
            with self.assertRaises(ValueError):
                selected_source(root, "../other.py")

    def test_reject_unselected_patch(self):
        patch = "--- a/secret.py\n+++ b/secret.py\n@@ -1 +1 @@\n-a\n+b\n"
        with self.assertRaises(ValueError):
            validate_proposal(patch, {"safe.py"})

    def test_valid_patch(self):
        patch = "--- a/safe.py\n+++ b/safe.py\n@@ -1 +1 @@\n-a\n+b\n"
        validate_proposal(patch, {"safe.py"})

    def test_prompt_contains_task(self):
        self.assertIn("fix bug", build_prompt("fix bug", [("a.py", "pass")]))


if __name__ == "__main__":
    unittest.main()
