# Revision-bound proposal validation receipts

Status: development-only proposal evidence. Provisional label **NEW-CODE-RECEIPTS**;
no architecture requirement/ADR is adopted and no runtime capability is activated.
Foundation v1.1 remains authoritative. These receipts are not approval records.

## Contract

The runner captures the original bytes of every selected file before generation.
It checks those bytes again before staging, when making the disposable Git-check
copy, and before publishing its verified journal event. A source change anywhere
in a selected file fails the proposal even when its patch still applies. Original
CRLF/LF bytes have different digests; existing universal-newline prompt and Git-copy
behavior is preserved.

Successful results keep the existing task/state/patch/sha256 fields and add
`receipt` and `receipt_sha256`. The canonical UTF-8 JSON sidecar contains:
- schema version 1 and task identity;
- canonical target location;
- path-to-SHA-256 map for all selected original source bytes;
- exact proposed patch SHA-256;
- validation kind `structural-and-git-apply-check`;
- `authorization_granted: false`.

The receipt uses exclusive creation, flush and fsync. Its digest is recorded in
the verified journal event. Normal failures/revocation remove only the patch and
receipt created by that task; pre-existing unowned evidence remains untouched.

`verify_proposal_receipt(repo, patch_path, receipt_path, expected_receipt_sha256)`
is read-only. Its expected digest must come from an independently trusted result
or journal, not from the receipt being checked. Evidence paths must come from a
trusted staging caller. It validates bounded canonical schema, target identity,
patch digest/structure, and current selected-source digests through the same source
exclusions. It does not run Git, apply a patch, grant approval, or execute code.
Callers must recheck at each later use; a restored verified label is insufficient.

## Validation

Synthetic tests cover source edits during generation and after Git checking,
artifact tampering, later source/target/patch/receipt changes, exact CRLF binding,
exclusive creation collisions, revocation after receipt creation, malformed and
oversized evidence, duplicate JSON fields, and excluded paths before reads.
The broker-to-real-HTTP integration also checks receipt/journal/artifact agreement.
Windows/Linux coding CI discovers all cases. Local sandbox path-resolution errors
remain explicit blockers for filesystem integration, not successful checks.

## Limits and next gates

The receipt is unsigned and is not tamper-proof when an attacker controls both
it and the separately held digest/journal. It is an observation over selected
file content, not an entire Git revision, file mode, unselected dependency tree,
test result, or source identity resistant to hostile reparse-point substitution.
The sequential reads are not an atomic multi-file filesystem snapshot; a change
and restoration between observations can evade detection. Revalidation is also a
point-in-time check, not permission for a later action.

Crash leftovers remain inert and require review/recovery; this change does not
add automatic restart, apply, resume, promotion, or publication. Authenticated
approval, policy-revision/expiry binding, validated worker/isolation boundaries,
immutable execution inputs, and held-out acceptance remain separate gates.
