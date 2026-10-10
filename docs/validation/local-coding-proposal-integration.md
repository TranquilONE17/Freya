# Local coding proposal integration milestone

Status: development-only synthetic validation. No runtime capability, policy grant,
patch application, repository-code execution, or deployment is enabled by this work.
Foundation v1.1 remains authoritative; pending architecture proposals remain pending.

Provisional validation label: **NEW-CODE-HTTP-INTEGRATION**. This is evidence for the
existing proposal alpha, not adoption of an architecture requirement or ADR.

## Acceptance checks

`devtools/test_coding_proposal_http_integration.py` exercises the opt-in adapter
through the real broker, SQLite policy and hash-chained audit, task journal, strict
patch parser, and trusted Git applicability check against a disposable source copy.
Only HTTP connection destination is redirected to a synthetic ephemeral loopback
server. Neither transport nor proposal generation is mocked; no model is called.

| Trigger | Required outcome |
| --- | --- |
| Explicit synthetic grant and applicable HTTP proposal | One request; exact LF artifact and matching digest; requested/generating/proposed/verified journal; matching dispatch/outcome audit; unchanged target |
| No grant | Denied; no HTTP request or task artifacts; audited denial |
| Unstarted audit writer | Denied before HTTP dispatch; no task or audit event |
| Invalid proposal from HTTP | Failed journal and audited failure; no usable artifact |
| Structurally valid but inapplicable patch | Git check rejects; proposed artifact removed; failed journal and audit; unchanged target |
| Policy revoked while HTTP reader is active | Request socket closes; reader retires; failed journal and audit; no patch artifact |

Audit checks verify the chain, operation identity, actor, capability and outcome;
synthetic task/source canaries must not appear as audit payloads. Every fixture uses
explicit disposable storage paths and closes the synthetic server, database and
response reader. Nothing uses owner storage or personal browser profiles.

## Running

Use the existing project environment with source/devtools imports:

```powershell
$env:PYTHONPATH = 'src;devtools'
python -m unittest test_coding_proposal_http_integration -v
```

The existing Windows/Linux offline coding CI discovers this module automatically.
Local Windows sandbox path-resolution failures can prevent broker registration;
such a run is blocked, not passed. CI execution results are recorded in PR #19.

## What this does not prove

The journal's `verified` state means structural/applicability checks succeeded; it
does not grant approval or establish source-revision-bound acceptance. These tests
do not validate real Ollama generation, GPU cancellation, authenticated sessions,
worker identity/ACL isolation, adversarial filesystem races, generated-code
execution, browser/hardware behavior, full Freya acceptance, or production readiness.
Closing a request socket does not guarantee a model runtime stops its GPU work.

The next activation gates remain owner-approved Foundation reconciliation, identity
and approval contracts, validated worker/isolation boundaries, and revision-bound
receipts. Those are separate milestones; deferred capabilities stay disabled.
