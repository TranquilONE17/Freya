"""Synthetic broker-to-HTTP proposals; no model calls or patch execution.

Only the HTTP connection destination is redirected to an ephemeral loopback port.
Policy, audit, broker, source checks, journal, parser and Git check remain real.
"""
import hashlib
import http.client
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from freya.core.audit.log import SqliteAuditLog
from freya.core.capabilities import CapabilityBroker, CapabilityRegistry
from freya.core.persistence.control_store import ControlStore
from freya.core.policy.engine import SqlitePolicyEngine
from freya.core.providers import ProviderRegistry

from coding_broker_adapter import register_coding_proposal
from coding_capability_contract import CODING_PROPOSE
from coding_task_journal import TaskJournal
from coding_proposal_receipt import verify_proposal_receipt


REAL_CONNECTION = http.client.HTTPConnection
SOURCE = b"answer = 1\n"
PROPOSAL = "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-answer = 1\n+answer = 2\n"


class ProposalServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


class ProposalHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, request))
        body = (json.dumps({"response": self.server.proposal, "done": True}) + "\n").encode()
        headers = (b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\n"
                   + f"Content-Length: {len(body)}\r\n\r\n".encode())
        if self.server.stall:
            self.connection.sendall(headers + body[:5])
            self.server.sent.set()
            self.connection.settimeout(2)
            try:
                if not self.connection.recv(1):
                    self.server.peer_closed.set()
            except OSError:
                pass
            self.close_connection = True
        else:
            self.connection.sendall(headers + body)


class CodingProposalHTTPIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.source = self.repo / "example.py"
        self.source.write_bytes(SOURCE)
        self.journals = root / "journals"
        self.artifacts = root / "artifacts"
        self.store = ControlStore(root / "synthetic-control.db")
        self.addCleanup(self.store.close)
        self.policy = SqlitePolicyEngine(self.store)
        self.audit = SqliteAuditLog(self.store)
        self.assertTrue(self.audit.start().verification.ok)
        self.providers = ProviderRegistry()
        self.capabilities = CapabilityRegistry(self.providers)
        self.plane = SimpleNamespace(providers=self.providers, capabilities=self.capabilities)
        self.broker = CapabilityBroker(self.capabilities, self.policy, self.audit)
        self.server = ProposalServer(("127.0.0.1", 0), ProposalHandler)
        self.server.requests = []
        self.server.proposal = PROPOSAL
        self.server.stall = False
        self.server.sent = threading.Event()
        self.server.peer_closed = threading.Event()
        self.worker = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.worker.start()
        self.addCleanup(self.close_server)

        def connection(host, port, **kwargs):
            self.assertEqual((host, port), ("127.0.0.1", 11434))
            return REAL_CONNECTION("127.0.0.1", self.server.server_port, **kwargs)

        self.client = patch("local_coding_agent.http.client.HTTPConnection", connection)
        self.client.start()
        self.addCleanup(self.client.stop)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        self.assertFalse(self.worker.is_alive())
        self.assertFalse(any(t.name.startswith("freya-ollama-reader-")
                             for t in threading.enumerate()))

    def register(self, checkpoint=None):
        register_coding_proposal(self.plane, repo=self.repo, journal_dir=self.journals,
                                 output_dir=self.artifacts, model="synthetic-model",
                                 checkpoint=checkpoint)

    def grant(self):
        self.policy.add_rule("local-owner", CODING_PROPOSE, "allow", "Synthetic grant")

    def invoke(self):
        return self.broker.invoke(CODING_PROPOSE, "synthetic task canary", ["example.py"])

    def assert_audit(self, result, kinds, outcome):
        rows = self.store.execute("SELECT * FROM audit_event ORDER BY event_id").fetchall()
        self.assertEqual([row["kind"] for row in rows], kinds)
        self.assertEqual(rows[-1]["outcome"], outcome)
        self.assertTrue(all(row["operation_id"] == result.operation_id for row in rows))
        self.assertTrue(all(row["actor"] == "local-owner" for row in rows))
        self.assertTrue(all(row["capability"] == CODING_PROPOSE for row in rows))
        self.assertNotIn("synthetic task canary", json.dumps([dict(row) for row in rows]))
        self.assertNotIn("answer = 1", json.dumps([dict(row) for row in rows]))
        self.assertTrue(self.audit.verify().ok)

    def assert_failed_proposal(self, result, proposed=False):
        self.assertEqual(result.outcome, "failed-known", result.error)
        journals = list(self.journals.glob("*.json"))
        self.assertEqual(len(journals), 1)
        states = [event.state for event in TaskJournal(self.journals, journals[0].stem).read()]
        expected = ["requested", "generating"]
        if proposed:
            expected.append("proposed")
        self.assertEqual(states, expected + ["failed"])
        self.assertEqual(list(self.artifacts.glob("*.receipt.json")), [])
        self.assertFalse(list(self.artifacts.glob("*.patch")))
        self.assertEqual(self.source.read_bytes(), SOURCE)
        self.assert_audit(result, ["dispatch", "outcome"], "failed-known")

    def test_granted_proposal_has_matching_artifact_journal_and_audit(self):
        self.register()
        self.grant()
        result = self.invoke()
        self.assertEqual(result.outcome, "succeeded", result.error)
        proposal = result.result
        self.assertEqual(proposal["state"], "verified")
        artifact = Path(proposal["patch"]).read_bytes()
        self.assertEqual(artifact, PROPOSAL.encode())
        self.assertEqual(proposal["sha256"], hashlib.sha256(artifact).hexdigest())
        events = TaskJournal(self.journals, proposal["task_id"]).read()
        self.assertEqual([event.state for event in events],
                         ["requested", "generating", "proposed", "verified"])
        self.assertIn(proposal["sha256"], events[2].details)
        receipt = verify_proposal_receipt(self.repo, Path(proposal["patch"]),
                                          Path(proposal["receipt"]), proposal["receipt_sha256"])
        self.assertEqual(receipt["source_sha256"], {"example.py": hashlib.sha256(SOURCE).hexdigest()})
        self.assertIn(proposal["receipt_sha256"], events[-1].details)
        self.assertIs(receipt["authorization_granted"], False)
        self.assertEqual(self.source.read_bytes(), SOURCE)
        self.assertEqual(len(self.server.requests), 1)
        path, request = self.server.requests[0]
        self.assertEqual(path, "/api/generate")
        self.assertEqual(request["model"], "synthetic-model")
        self.assertIs(request["stream"], True)
        self.assertIn(SOURCE.decode(), request["prompt"])
        self.assert_audit(result, ["dispatch", "outcome"], "succeeded")

    def test_denied_request_does_not_reach_http_or_create_task(self):
        self.register()
        result = self.invoke()
        self.assertEqual(result.outcome, "denied")
        self.assertEqual(self.server.requests, [])
        self.assertFalse(self.journals.exists())
        self.assertFalse(self.artifacts.exists())
        self.assert_audit(result, ["decision"], "denied")

    def test_unverified_audit_prevents_http_dispatch(self):
        self.register()
        self.grant()
        # A real, unstarted audit instance refuses its pre-dispatch write.
        broker = CapabilityBroker(self.capabilities, self.policy, SqliteAuditLog(self.store))
        result = broker.invoke(CODING_PROPOSE, "synthetic task", ["example.py"])
        self.assertEqual(result.outcome, "denied")
        self.assertEqual(self.server.requests, [])
        self.assertFalse(self.journals.exists())
        self.assertEqual(self.store.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0], 0)
        self.assertTrue(self.audit.verify().ok)

    def test_invalid_http_proposal_fails_with_no_usable_artifact(self):
        self.register()
        self.grant()
        self.server.proposal = "synthetic model prose, not a patch"
        self.assert_failed_proposal(self.invoke())
        self.assertEqual(len(self.server.requests), 1)

    def test_inapplicable_http_patch_is_removed_after_git_rejects_it(self):
        self.register()
        self.grant()
        self.server.proposal = PROPOSAL.replace("-answer = 1", "-answer = 9")
        self.assert_failed_proposal(self.invoke(), proposed=True)
        self.assertEqual(len(self.server.requests), 1)

    def test_policy_revocation_during_http_closes_request_and_records_failure(self):
        revoked = False

        def revoke_after_reader_starts():
            nonlocal revoked
            if (not revoked and self.server.sent.is_set()
                    and any(t.name.startswith("freya-ollama-reader-")
                            for t in threading.enumerate())):
                self.policy.add_rule("local-owner", CODING_PROPOSE, "deny", "Synthetic revoke")
                revoked = True

        self.register(checkpoint=revoke_after_reader_starts)
        self.grant()
        self.server.stall = True
        self.assert_failed_proposal(self.invoke())
        self.assertTrue(revoked)
        self.assertTrue(self.server.peer_closed.wait(1), "Revoked request stayed open")
        self.assertEqual(len(self.server.requests), 1)
        self.assertFalse(self.policy.decide("local-owner", CODING_PROPOSE).allow)


if __name__ == "__main__":
    unittest.main()
