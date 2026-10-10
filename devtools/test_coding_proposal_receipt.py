"""Synthetic evidence binding; receipts never authorize proposal adoption."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from coding_proposal_receipt import (assert_sources_current, canonical_receipt, digest,
                                     verify_proposal_receipt)
from coding_task_journal import TaskJournal
from coding_task_runner import propose
from patch_applicability import check_patch


PATCH = "--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-old\n+new\n"


class SourceSnapshotOrchestrationTests(unittest.TestCase):
    def test_unrelated_edit_during_generation_is_not_verified(self):
        # Filesystem containment has separate integration coverage. This test
        # isolates orchestration; the changed source still accepts the first hunk.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = SimpleNamespace(resolve=lambda **kwargs: root / "synthetic-target")
            current = b"old\n"

            def read_bytes(*args):
                return current

            def generate(*args):
                nonlocal current
                current = b"old\n# concurrent edit\n"
                return PATCH

            with patch("coding_task_runner.selected_source_bytes", read_bytes, create=True), \
                    patch("coding_task_runner.selected_source", lambda *args: current.decode(), create=True), \
                    patch("coding_proposal_receipt.selected_source_bytes", read_bytes), \
                    patch("coding_task_runner.check_patch") as applicability:
                with self.assertRaisesRegex(ValueError, "source changed"):
                    propose(repo, "synthetic task", ["demo.py"], "synthetic-model",
                            root / "journals", root / "artifacts", generate=generate)
                applicability.assert_not_called()
            journal = next((root / "journals").glob("*.json"))
            self.assertEqual(TaskJournal(root / "journals", journal.stem).read()[-1].state, "failed")
            self.assertEqual(list((root / "artifacts").glob("*.patch")), [])


class ReceiptSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.receipt = self.root / "receipt.json"

    def test_canonical_receipt_is_order_independent_and_grants_no_authority(self):
        first = canonical_receipt("task", "target", {"b.py": "b" * 64, "a.py": "a" * 64}, "c" * 64)
        second = canonical_receipt("task", "target", {"a.py": "a" * 64, "b.py": "b" * 64}, "c" * 64)
        self.assertEqual(first, second)
        self.assertIs(json.loads(first)["authorization_granted"], False)

    def test_expected_digest_is_required_before_any_evidence_read(self):
        for expected in (None, "", "bad", "A" * 64, True):
            with self.subTest(expected=expected), patch.object(Path, "open") as opened:
                with self.assertRaises(ValueError):
                    verify_proposal_receipt(self.root, self.root / "patch", self.receipt, expected)
                opened.assert_not_called()

    def test_tampered_receipt_is_rejected_before_source_read(self):
        original = canonical_receipt("task", "target", {"a.py": "a" * 64}, "b" * 64)
        self.receipt.write_bytes(original + b" ")
        with patch("coding_proposal_receipt.selected_source_bytes") as source:
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                verify_proposal_receipt(self.root, self.root / "patch", self.receipt, digest(original))
            source.assert_not_called()

    def test_malformed_or_authorizing_receipt_is_rejected(self):
        valid = json.loads(canonical_receipt("task", "target", {"a.py": "a" * 64}, "b" * 64))
        variants = [{**valid, "version": True}, {**valid, "version": 2},
                    {**valid, "authorization_granted": True},
                    {**valid, "authorization_granted": 0},
                    {**valid, "task_id": "../task"}, {**valid, "source_sha256": {}},
                    {**valid, "source_sha256": {"a.py": "bad"}},
                    {**valid, "patch_sha256": "bad"}, {**valid, "extra": "claim"},
                    {**valid, "validation": "tests-passed"}, []]
        for item in variants:
            with self.subTest(item=item):
                contents = json.dumps(item).encode()
                self.receipt.write_bytes(contents)
                with self.assertRaisesRegex(ValueError, "Invalid proposal receipt"):
                    verify_proposal_receipt(self.root, self.root / "patch", self.receipt, digest(contents))

    def test_noncanonical_or_duplicate_fields_are_rejected(self):
        original = canonical_receipt("task", "target", {"a.py": "a" * 64}, "b" * 64)
        for contents in (original + b"\n", b'{"version":1,' + original[1:]):
            with self.subTest(contents=contents):
                self.receipt.write_bytes(contents)
                with self.assertRaisesRegex(ValueError, "not canonical"):
                    verify_proposal_receipt(self.root, self.root / "patch", self.receipt, digest(contents))

    def test_oversized_receipt_is_rejected(self):
        self.receipt.write_bytes(b"x" * 101)
        with patch("coding_proposal_receipt.MAX_RECEIPT_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "size limit"):
                verify_proposal_receipt(self.root, self.root / "patch", self.receipt, "a" * 64)

    def test_source_revalidation_keeps_exclusions_before_any_read(self):
        for name in ("data/example.py", "nested/DATA/example.py", "../example.py", ".env"):
            with self.subTest(name=name), patch.object(Path, "open") as opened:
                with self.assertRaises(ValueError):
                    assert_sources_current(self.root, {name: "a" * 64})
                opened.assert_not_called()


class ProposalReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.source = self.repo / "demo.py"
        self.source.write_bytes(b"old\n")
        self.journals = self.root / "journals"
        self.artifacts = self.root / "artifacts"

    def propose(self, generate=lambda *args: PATCH, **kwargs):
        return propose(self.repo, "synthetic task", ["demo.py"], "synthetic-model",
                       self.journals, self.artifacts, generate=generate, **kwargs)

    def verify(self, result, repo=None):
        return verify_proposal_receipt(repo or self.repo, Path(result["patch"]),
                                       Path(result["receipt"]), result["receipt_sha256"])

    def assert_failed_cleanly(self):
        self.assertFalse(list(self.artifacts.glob("*.patch")))
        self.assertFalse(list(self.artifacts.glob("*.receipt.json")))
        journal = next(self.journals.glob("*.json"))
        self.assertEqual(TaskJournal(self.journals, journal.stem).read()[-1].state, "failed")

    def test_receipt_binds_original_source_patch_target_and_journal(self):
        result = self.propose()
        receipt = self.verify(result)
        self.assertEqual(receipt["source_sha256"], {"demo.py": digest(b"old\n")})
        self.assertEqual(receipt["patch_sha256"], digest(PATCH.encode()))
        self.assertEqual(receipt["target"], str(self.repo.resolve(strict=True)))
        self.assertEqual(receipt["task_id"], result["task_id"])
        self.assertIs(receipt["authorization_granted"], False)
        self.assertNotIn("old\\n", Path(result["receipt"]).read_text())
        events = TaskJournal(self.journals, result["task_id"]).read()
        self.assertIn(result["receipt_sha256"], events[-1].details)
        self.assertEqual(self.source.read_bytes(), b"old\n")

    def test_source_change_during_generation_rejected_even_if_patch_still_applies(self):
        def generate(*args):
            self.source.write_bytes(b"old\n# unrelated edit\n")
            return PATCH

        with self.assertRaisesRegex(ValueError, "source changed"):
            self.propose(generate)
        self.assert_failed_cleanly()
        self.assertEqual(self.source.read_bytes(), b"old\n# unrelated edit\n")

    def test_changes_after_git_check_remove_patch_and_receipt(self):
        def changed_after_check(*args, **kwargs):
            check_patch(*args, **kwargs)
            self.source.write_bytes(b"old\n# later edit\n")

        with patch("coding_task_runner.check_patch", changed_after_check):
            with self.assertRaisesRegex(ValueError, "source changed"):
                self.propose()
        self.assert_failed_cleanly()

    def test_artifact_change_after_git_check_is_rejected(self):
        def tamper_after_check(*args, **kwargs):
            check_patch(*args, **kwargs)
            next(self.artifacts.glob("*.patch")).write_bytes(PATCH.replace("+new", "+other").encode())

        with patch("coding_task_runner.check_patch", tamper_after_check):
            with self.assertRaisesRegex(ValueError, "artifact digest mismatch"):
                self.propose()
        self.assert_failed_cleanly()

    def test_revalidation_rejects_later_source_patch_receipt_and_target_changes(self):
        result = self.propose()
        for change in ("source", "patch", "receipt", "target"):
            with self.subTest(change=change):
                self.source.write_bytes(b"old\n")
                Path(result["patch"]).write_bytes(PATCH.encode())
                contents = canonical_receipt(result["task_id"], str(self.repo.resolve(strict=True)),
                                              {"demo.py": digest(b"old\n")}, digest(PATCH.encode()))
                Path(result["receipt"]).write_bytes(contents)
                target = self.repo
                if change == "source":
                    self.source.write_bytes(b"old\n# edit\n")
                elif change == "patch":
                    Path(result["patch"]).write_bytes(PATCH.replace("+new", "+other").encode())
                elif change == "receipt":
                    Path(result["receipt"]).write_bytes(contents + b" ")
                else:
                    target = self.root / "different-target"
                    target.mkdir()
                    (target / "demo.py").write_bytes(b"old\n")
                with self.assertRaises(ValueError):
                    self.verify(result, target)

    def test_original_crlf_bytes_are_bound_even_when_text_is_unchanged(self):
        self.source.write_bytes(b"old\r\n")
        result = self.propose()
        self.assertEqual(self.verify(result)["source_sha256"], {"demo.py": digest(b"old\r\n")})
        self.source.write_bytes(b"old\n")
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.verify(result)

    def test_preexisting_receipt_is_preserved_on_exclusive_creation_failure(self):
        journal = TaskJournal.create(self.journals)
        self.artifacts.mkdir()
        existing = self.artifacts / f"{journal.task_id}.receipt.json"
        existing.write_bytes(b"unowned evidence")
        with patch("coding_task_runner.TaskJournal.create", return_value=journal):
            with self.assertRaises(FileExistsError):
                self.propose()
        self.assertEqual(existing.read_bytes(), b"unowned evidence")
        self.assertFalse(list(self.artifacts.glob("*.patch")))
        self.assertEqual(journal.read()[-1].state, "failed")

    def test_revocation_after_receipt_creation_removes_owned_evidence(self):
        def checkpoint():
            if list(self.artifacts.glob("*.receipt.json")):
                raise PermissionError("Synthetic revocation")

        with self.assertRaises(PermissionError):
            self.propose(checkpoint=checkpoint)
        self.assert_failed_cleanly()


if __name__ == "__main__":
    unittest.main()
