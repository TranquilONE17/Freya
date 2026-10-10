import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from local_coding_agent import selected_source, validate_proposal, build_prompt, main


class LocalCodingAgentTests(unittest.TestCase):
    def test_cli_preserves_artifact_created_after_existence_check(self):
        proposal = "--- a/safe.py\n+++ b/safe.py\n@@ -1 +1 @@\n-a\n+b\n"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "proposal.patch"
            original_mkdir = Path.mkdir

            def racing_mkdir(path, *args, **kwargs):
                original_mkdir(path, *args, **kwargs)
                output.write_bytes(b"unowned artifact")

            with patch.object(sys, "argv", ["coding", "--repo", directory, "--model", "synthetic",
                                          "--task", "fix", "--file", "safe.py",
                                          "--output", str(output)]), \
                    patch("local_coding_agent.selected_source", return_value="a\n"), \
                    patch("local_coding_agent.ask_ollama", return_value=proposal), \
                    patch.object(Path, "mkdir", racing_mkdir):
                with self.assertRaises(FileExistsError):
                    main()
            self.assertEqual(output.read_bytes(), b"unowned artifact")

    def test_cli_writes_exact_lf_proposal_bytes(self):
        proposal = "--- a/safe.py\n+++ b/safe.py\n@@ -1 +1 @@\n-a\n+b\n"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "proposal.patch"
            with patch.object(sys, "argv", ["coding", "--repo", directory, "--model", "synthetic",
                                          "--task", "fix", "--file", "safe.py",
                                          "--output", str(output)]), \
                    patch("local_coding_agent.selected_source", return_value="a\n"), \
                    patch("local_coding_agent.ask_ollama", return_value=proposal), \
                    patch("builtins.print"):
                self.assertEqual(main(), 0)
            self.assertEqual(output.read_bytes(), proposal.encode("utf-8"))

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

    def test_cli_validator_rejects_truncated_and_trailing_content(self):
        valid = "--- a/safe.py\n+++ b/safe.py\n@@ -1 +1 @@\n-old\n+new\n"
        for proposal in (valid.rsplit("+new\n", 1)[0], valid + "model prose\n",
                         valid.replace("\n", "\r\n")):
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                validate_proposal(proposal, {"safe.py"})

    def test_personal_storage_rejected_before_any_file_read(self):
        # Every path and payload here is synthetic; no owner storage is used.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("data/example.py", "nested/data/example.py",
                         "Data/example.py", "nested/DATA/example.py"):
                with self.subTest(name=name):
                    with patch.object(Path, "read_text", side_effect=AssertionError("read")) as read:
                        with self.assertRaises(ValueError):
                            selected_source(root, name)
                        read.assert_not_called()

    def test_nonstorage_source_with_data_in_filename_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data_model.py").write_text("pass", encoding="utf-8")
            self.assertEqual(selected_source(root, "data_model.py"), "pass")


if __name__ == "__main__":
    unittest.main()
