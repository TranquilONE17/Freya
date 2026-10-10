"""Read-only recovery classification with synthetic files and no model calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_proposal_recovery import inspect_proposal
from coding_task_journal import TaskJournal
from coding_task_runner import propose

PATCH = "--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-old\n+new\n"


class RecoveryFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "demo.py").write_bytes(b"old\n")
        self.journals = self.root / "journals"
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.journal = TaskJournal.create(self.journals)

    def inspect(self, expected=None):
        return inspect_proposal(self.repo, self.journals, self.artifacts,
                                 self.journal.task_id, expected)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def assert_inert(self, expected_classification, expected=None):
        before = self.snapshot()
        with patch("coding_task_runner.propose") as generate, \
                patch("subprocess.run") as execute, \
                patch.object(TaskJournal, "transition") as transition:
            result = self.inspect(expected)
        self.assertEqual(result["classification"], expected_classification, result)
        self.assertIs(result["authorization_granted"], False)
        self.assertIs(result["resume_allowed"], False)
        generate.assert_not_called()
        execute.assert_not_called()
        transition.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        return result

class RecoveryInspectionTests(RecoveryFixture, unittest.TestCase):
    def test_unknown_task_does_not_discover_or_create_files(self):
        before = self.snapshot()
        with patch.object(Path, "glob") as discover, patch.object(Path, "open") as opened:
            result = inspect_proposal(self.repo, self.journals, self.artifacts, "missing-task")
        self.assertEqual(result["classification"], "invalid-journal")
        self.assertIs(result["resume_allowed"], False)
        discover.assert_not_called()
        opened.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_interrupted_states_and_partial_artifacts_are_preserved(self):
        for state in ("requested", "generating", "proposed"):
            with self.subTest(state=state):
                if state != "requested":
                    self.journal.transition(state)
                (self.artifacts / f"{self.journal.task_id}.patch").write_bytes(b"partial patch")
                (self.artifacts / f"{self.journal.task_id}.receipt.json").write_bytes(b"partial receipt")
                (self.journals / f"{self.journal.task_id}.crash.tmp").write_bytes(b"crash residue")
                result = self.assert_inert("interrupted")
                self.assertEqual(result["journal_state"], state)

    def test_terminal_failed_and_rejected_records_never_resume(self):
        self.journal.transition("failed", "synthetic untrusted error canary")
        result = self.assert_inert("failed")
        self.assertNotIn("canary", json.dumps(result))
        self.journal = TaskJournal.create(self.journals)
        self.journal.transition("rejected")
        self.assert_inert("rejected")

    def test_legacy_verified_label_is_not_current_evidence(self):
        self.journal.transition("generating")
        self.journal.transition("proposed", "sha256=" + "a" * 64)
        self.journal.transition("verified", "git apply --check passed on disposable copy")
        self.assert_inert("legacy-unbound")

    def bound_record(self):
        self.journal.transition("generating")
        self.journal.transition("proposed", "sha256=" + "b" * 64)
        self.journal.transition("verified", "receipt_sha256=" + "a" * 64 + "; git apply --check passed")
        (self.artifacts / f"{self.journal.task_id}.patch").write_bytes(b"untrusted patch")
        (self.artifacts / f"{self.journal.task_id}.receipt.json").write_bytes(b"untrusted receipt")

    def test_stored_receipt_digest_is_not_independent_trust(self):
        self.bound_record()
        with patch("coding_proposal_recovery.verify_proposal_receipt") as verify:
            self.assert_inert("untrusted-evidence")
            self.assert_inert("untrusted-evidence", "c" * 64)
        verify.assert_not_called()

    def test_missing_verified_artifact_is_incomplete(self):
        self.bound_record()
        (self.artifacts / f"{self.journal.task_id}.receipt.json").unlink()
        self.assert_inert("incomplete", "a" * 64)

    def test_partial_oversized_or_malformed_journal_is_invalid_without_payload_echo(self):
        original = self.journal.path.read_bytes()
        event = json.loads(original)[0]
        variants = [b"partial synthetic canary", b"[]",
                    json.dumps([{**event, "sequence": True}]).encode(),
                    json.dumps([{**event, "timestamp": float("nan")}]).encode(),
                    json.dumps([{**event, "details": 123}]).encode(),
                    json.dumps([{**event, "state": "verified"}]).encode(),
                    json.dumps([{**event, "task_id": "other-task"}]).encode(),
                    b'[{"task_id":"x","task_id":"y"}]']
        for contents in variants:
            with self.subTest(contents=contents):
                self.journal.path.write_bytes(contents)
                result = self.assert_inert("invalid-journal")
                self.assertNotIn("canary", json.dumps(result))
        self.journal.path.write_bytes(b"x" * 101)
        with patch("coding_proposal_recovery.MAX_JOURNAL_BYTES", 100):
            self.assert_inert("invalid-journal")

    def test_traversal_excluded_roots_and_invalid_digest_are_refused_before_open(self):
        with patch.object(Path, "open") as opened:
            for task in ("../other", "", "A", "a" * 129):
                with self.subTest(task=task), self.assertRaises(ValueError):
                    inspect_proposal(self.repo, self.journals, self.artifacts, task)
            with self.assertRaises(ValueError):
                self.inspect("bad")
            with self.assertRaises(ValueError):
                inspect_proposal(self.repo, self.root / "data", self.artifacts, self.journal.task_id)
            with self.assertRaises(ValueError):
                inspect_proposal(self.repo, self.repo / "journals", self.artifacts, self.journal.task_id)
            opened.assert_not_called()

    def test_symlinked_journal_is_not_read(self):
        original = self.journal.path.read_bytes()
        self.journal.path.unlink()
        target = self.root / "synthetic-private.json"
        target.write_bytes(original)
        try:
            self.journal.path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable")
        with patch.object(Path, "open") as opened:
            result = self.inspect()
        self.assertEqual(result["classification"], "invalid-journal")
        opened.assert_not_called()

    def test_symlinked_artifact_is_not_revalidated(self):
        self.bound_record()
        artifact = self.artifacts / f"{self.journal.task_id}.patch"
        artifact.unlink()
        target = self.root / "synthetic-private.patch"
        target.write_bytes(b"synthetic private canary")
        try:
            artifact.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable")
        with patch("coding_proposal_recovery.verify_proposal_receipt") as verify:
            result = self.inspect("a" * 64)
        self.assertEqual(result["classification"], "invalid-evidence")
        verify.assert_not_called()


class VerifiedRecoveryTests(RecoveryFixture, unittest.TestCase):
    # Only these additional cases need the real source-path/Git pipeline.
    def make_proposal(self):
        result = propose(self.repo, "synthetic task", ["demo.py"], "synthetic-model",
                         self.journals, self.artifacts, generate=lambda *args: PATCH)
        self.journal = TaskJournal(self.journals, result["task_id"])
        return result

    def test_matching_evidence_is_current_but_never_resumed(self):
        result = self.make_proposal()
        self.assert_inert("evidence-current", result["receipt_sha256"])

    def test_changed_source_patch_or_receipt_is_stale_or_invalid(self):
        for change in ("source", "patch", "receipt"):
            with self.subTest(change=change):
                (self.repo / "demo.py").write_bytes(b"old\n")
                result = self.make_proposal()
                if change == "source":
                    (self.repo / "demo.py").write_bytes(b"old\n# concurrent edit\n")
                elif change == "patch":
                    Path(result["patch"]).write_bytes(PATCH.replace("+new", "+other").encode())
                else:
                    Path(result["receipt"]).write_bytes(b"partial receipt")
                self.assert_inert("stale-or-invalid", result["receipt_sha256"])

    def test_journal_patch_digest_cannot_override_bound_receipt(self):
        result = self.make_proposal()
        events = json.loads(self.journal.path.read_bytes())
        events[2]["details"] = "sha256=" + "c" * 64
        self.journal.path.write_text(json.dumps(events), encoding="utf-8")
        self.assert_inert("invalid-evidence", result["receipt_sha256"])

    def test_receipt_from_another_task_cannot_be_reused(self):
        result = self.make_proposal()
        self.journal = TaskJournal.create(self.journals)
        self.journal.transition("generating")
        self.journal.transition("proposed", "sha256=" + result["sha256"])
        self.journal.transition("verified", "receipt_sha256=" + result["receipt_sha256"]
                                 + "; git apply --check passed")
        (self.artifacts / f"{self.journal.task_id}.patch").write_bytes(Path(result["patch"]).read_bytes())
        (self.artifacts / f"{self.journal.task_id}.receipt.json").write_bytes(Path(result["receipt"]).read_bytes())
        self.assert_inert("invalid-evidence", result["receipt_sha256"])


if __name__ == "__main__":
    unittest.main()
