# Inert proposal recovery inspection

Status: development-only read-only inspection. Provisional **NEW-CODE-RECOVERY**;
no architecture/ADR adoption, runtime activation or new authorization mechanism.
Foundation v1.1 and the existing proposal-only boundary remain authoritative.

`coding_proposal_recovery.inspect_proposal` inspects one caller-selected task in
trusted, quiescent staging roots outside the source repository. It discovers no
tasks, writes no files, changes no journal state, acquires no writer lock, starts
no process/model, and never resumes, repairs, applies or deletes a proposal.

| Classification | Meaning |
| --- | --- |
| invalid-journal | Missing, oversized, partial, unsafe or schema/history-invalid journal |
| interrupted | Requested/generating/proposed history has no completed validation record; even plausible artifacts stay inert |
| failed / rejected | Terminal recorded outcome; leftovers remain unchanged |
| legacy-unbound | Verified record predates a bound receipt |
| incomplete | Bound verified record is missing a patch or receipt |
| untrusted-evidence | No independently held receipt digest, or it disagrees with the journal |
| invalid-evidence | Unsafe staging artifact or inconsistent task/patch binding |
| stale-or-invalid | Current source, target, patch or receipt cannot be revalidated |
| evidence-current | Selected content matches at inspection against a separately supplied receipt digest; no authority is restored |

Every result explicitly sets `authorization_granted: false` and
`resume_allowed: false`. Reasons are fixed codes; persisted details and exception
text are never echoed. The journal read is bounded to 256,000 bytes, validates
exact event fields, identity, sequence/type, finite timestamps, details length,
initial state and transition history, and rejects duplicate JSON fields.
Task identifiers/digests are validated before reads; excluded storage roots,
staging/source overlap, and direct symlink/reparse artifacts are refused.

An independently held digest must come from trusted provenance outside the stored
receipt/journal under inspection. Supplying the digest found in that same journal
does not establish independent trust. A current result is still unsigned,
point-in-time evidence, not approval, acceptance, execution permission or a
guarantee against hostile parent substitution/concurrent mutation. The caller
must select trusted roots and quiescent tasks; this is not a filesystem sandbox.

```powershell
$env:PYTHONPATH = 'src;devtools'
python devtools/coding_proposal_recovery.py --repo <synthetic-source> `
  --journal-dir <trusted-staging-journals> --output-dir <trusted-staging-artifacts> `
  --task-id <one-task-id>
```

Without separately held evidence the report cannot classify verified artifacts as
current. `--expected-receipt-sha256` permits read-only revalidation when provenance
is available. Command success means inspection completed, not that evidence passed;
consumers must read `classification`. Invalid caller configuration exits with 2.

Tests preserve byte-for-byte snapshots of synthetic storage, forbid transitions,
generation and subprocess calls during inspection, cover interrupted/terminal/
legacy/missing/untrusted/malformed records, source/artifact changes, task/patch
binding mismatches, and unsafe paths. Platform symlink limitations are explicit
skips. Trusted cleanup, reconciliation, immutable execution inputs, authenticated
approval and validated worker/isolation gates remain separate future milestones.
