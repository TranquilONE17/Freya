# Design proposal: human-approved development, and working without the internet

**Status: proposal for owner review. Nothing here is adopted, approved, or
implemented.** It records requirements the owner discussed and a design that would
meet them. No ADR is approved by this document and no capability is enabled by it.

- Requirements in this document carry provisional labels **NEW-M to NEW-X**. They
  continue from the pending amendments NEW-A to NEW-L and, like them, get final IDs
  only at reconciliation. No existing requirement or ADR ID is reused.
- Where this document cites NEW-A to NEW-L it is citing **pending proposals**, not
  adopted requirements. The design depends on several of them; that dependency is
  itself a decision for the owner (see D1).
- Baseline references (ARCH-, CAP-, SEC-, ORCH-, OPS-, OBS-, TEST-) are to
  *Freya Foundation v1.1*.

## 1. What the owner asked for

1. Freya should be able to help develop repositories, including her own source, and
   edit approved local files. **Every change needs explicit human authority.**
2. Losing the internet must pause remote operations without trapping Freya or taking
   local control away from the human.

## 2. Where the code is today

These facts shape the prerequisites. They come from `CLAUDE.md` and the code on
`main` at c2dd3ef.

| Area | Today | Consequence |
|---|---|---|
| Identity | Every action is attributed to a fixed `local-owner` principal. There are no authenticated sessions or client scopes. | There is no session that could hold "may approve". Approval cannot be built yet. |
| Window | Loopback only, a single-use key exchanged for a session cookie. `CLAUDE.md` says this is "a first step, not the authenticated gateway of the baseline". | The window cannot yet be the "authenticated local interface" the workflow requires. |
| Voice | Always-on listening; speech is ambient input, not authentication. | Speech must never approve anything (pending NEW-I). |
| Broker | Policy check, availability check, audit record before execution, outcome after. No operation IDs, effect classes, journal, or reconciliation. | Mutating and remote operations need the missing parts (CAP-010, CAP-011, ORCH-006). |
| Isolation | Hyper-V is the preferred profile; untrusted execution is disabled until validated. | Running a repository's tests is running untrusted code (ARCH-017). It stays disabled until isolation is validated. |
| Model tools | Read-only system tools and `image.generate`. Tool results are untrusted content. | Nothing the model says or reads may count as approval (CTX-001, CTX-002). |
| Start-up | Whisper and Kokoro are loaded through libraries that can contact their model hub. Behaviour with no internet has not been tested. | Listed as an open item in Part B, not assumed to work. |

## 3. Proposed requirements

### Part A: human-approved development

- **NEW-M — Granted targets.** Development capabilities act only on repositories and
  folders the owner has explicitly granted, each recorded as a policy entry with its
  canonical location and the operations allowed there (inspect, propose, apply,
  check, commit, publish). Granting is an owner action. Finding a path, or being told
  one by a model or a document, grants nothing.
- **NEW-N — Excluded targets.** Regardless of grants, these are never readable into a
  proposal or writable by one: secrets and credential stores; `data/freya_memory.db`
  and other personal databases; the control database, policy, and audit records; the
  deployed Freya installation and its configuration (pending NEW-D). Exclusion is
  enforced on the resource actually opened, after resolving links, junctions, and
  reparse points (CAP-008), not on the path text.
- **NEW-O — Proposals live in staging.** A request for a proposal authorizes writes
  to one place only: a staging area Freya owns, for that proposal, within a size
  limit. Inspecting a target authorizes no writes at all. Staging never overlaps a
  target.
- **NEW-P — The approved thing is the exact patch.** Core, not the model, computes
  the diff shown to the human from the staged files and the target's current
  contents. An approval is bound to: the proposal, the target, and for every file its
  path, the digest of the content it will replace (or "absent"), and the digest of
  the content it will become. It also carries policy revision and expiry, as pending
  NEW-A requires. Any difference at apply time means the approval is stale and a new
  one is needed.
- **NEW-Q — Who can approve.** Only a control in an authenticated, approval-capable
  local client can grant approval. Model output, tool results, document text, and
  ambient voice cannot create, grant, or relay it, and the approval response does not
  pass through model context (pending NEW-A, NEW-I).
- **NEW-R — Applying.** Apply writes only the approved files, only to the designated
  target, after re-resolving every path and re-checking every digest. It never
  discards uncommitted work: content that differs from what was approved stops the
  apply. Applying is journalled so an interrupted apply can be finished or undone,
  never left half-done silently (OPS-008).
- **NEW-S — Checks are execution.** Running tests, builds, linters, or any command
  from a repository is execution of that repository's code. It needs its own
  authorization naming the command, and runs only in a validated isolation profile
  (ARCH-017, SEC-013), never in Core or under an identity that can reach Core
  storage or credentials. A separate process or virtual environment is not enough.
- **NEW-T — One approval per consequence.** Commit, push, opening a pull request,
  merging, deploying, and restarting Freya are separate operations. Each needs its
  own approval; approving a patch approves none of them. For Freya's own source,
  changes are made in a separate checkout and reach the running installation only
  through review and the update path (pending NEW-D); deploy and restart are each
  approved separately.

### Part B: offline operation and recovery

- **NEW-U — Local work does not need the internet.** Inspecting, proposing, reviewing
  a diff, approving, applying, running authorized local checks, and making approved
  local commits work with no internet. Publishing is optional and separate; local
  progress never waits on it.
- **NEW-V — Network operations are bounded.** Every network operation has a connect
  timeout, a total timeout, a retry limit, and can be cancelled. Read-only operations
  may retry within the limit. Operations with effects are not retried automatically
  (CAP-011). A failure releases locks and resources, and the interface stays
  responsive throughout.
- **NEW-W — State survives a restart, authority does not grow.** Proposals, approval
  records, and operation state are stored locally with checksums. After a restart
  they are shown, not run: nothing queued executes on its own, and restored state is
  never treated as a new authorization (ORCH-006, OPS-013). A saved approval is
  re-validated against the exact patch and the target's current contents before any
  use, and may have expired.
- **NEW-X — Unknown remote outcomes are reconciled first.** A dropped connection can
  leave it unknown whether a push, pull request, or merge happened. That operation is
  marked unknown-outcome. Before any retry Freya checks the remote's actual state; a
  retry needs human authorization that discloses the unresolved first attempt
  (CAP-011). Completed local edits and commits are kept when publishing fails.

  Also under NEW-X: the human can always cancel, retry, discard, or restart from the
  local interface, and Freya says which operations are paused and why. Local
  capabilities, including Ollama when its models and services are present, carry on
  (baseline failure table: "Internet lost").

## 4. Design

### 4.1 Components

```
 authenticated window ── approval control ──► Approval service (Core)
        │                                           │
        ▼                                           ▼
   Capability broker ── policy, audit, journal ── Operation store (control DB)
        │
        ├─► dev.inspect / dev.propose   ─► Development worker (restricted identity)
        ├─► dev.apply / dev.commit      ─►   own staging area + dedicated worktrees
        ├─► dev.check                   ─► Isolation provider (validated profile only)
        └─► dev.publish.*               ─► Remote worker (network, bounded, cancellable)
```

- **Core** holds grants, approvals, the journal, and the audit log. It computes diffs
  and digests. It runs no repository code and no `git`.
- **Development worker**: a separate process under a restricted identity with access
  to staging and granted targets only. It reads files, writes staged files, applies
  approved patches, and makes local commits. It has no network access and no access
  to Core storage. It is trusted Freya code doing file I/O; it does not run code from
  the repository.
- **Isolated check runner**: the only place repository code runs (NEW-S).
- **Remote worker**: the only component that touches the network for development
  work. It holds no approval authority and only carries out journalled operations.

`git` deserves care: run in a repository, it can execute what the repository
configures (hooks, filters, file-system monitors, custom commands). The worker would
therefore invoke it with those features disabled, or the affected operations move
into isolation. Which one is decision D5.

### 4.2 Workflow

| Step | Capability | Effect class (CAP-010) | Needs |
|---|---|---|---|
| Inspect a granted target | `dev.inspect` | read-only | grant (NEW-M) |
| Prepare a proposal | `dev.propose` | writes to staging only | grant; a human request for a proposal (NEW-O) |
| Show the diff | Core | none | Core-computed diff (NEW-P) |
| Approve | approval service | none | approval-capable session (NEW-Q) |
| Apply | `dev.apply` | idempotent for its operation ID | valid approval; digests match (NEW-R) |
| Run a check | `dev.check` | execution | its own approval; validated isolation (NEW-S) |
| Commit locally | `dev.commit` | idempotent for its operation ID | its own approval (NEW-T) |
| Push, open PR, merge | `dev.publish.*` | non-idempotent | its own approval each; reconciliation (NEW-X) |
| Deploy, restart | update path | non-idempotent | its own approval each (NEW-T) |

Every row is a broker invocation: policy decision, audit record before dispatch,
outcome after (OBS-006).

### 4.3 Targets and uncommitted work

- For a **repository**, the default target is a worktree Freya creates on a proposal
  branch, in a location she owns. The owner's checked-out working tree is not
  modified. This is the simplest way to protect uncommitted work, and it is how
  Freya's own source would be handled.
- Applying **in place** to a granted folder or the owner's working tree is possible
  only when that target is designated in the approval. The digest check in NEW-R
  then protects uncommitted work: if a file is not exactly what the human saw in the
  diff, the apply stops. Replaced content is kept until the owner dismisses it.
- Whether in-place apply is offered at all is decision D4.

### 4.4 Approval binding

```
approval = {
  approval_id, operation_id, proposal_id, target_id,
  files: [{ path, before_digest | absent, after_digest, mode }],
  digest_of_all_the_above, policy_revision, expires_at,
  decided_by_session, decided_at
}
```

At apply time the worker re-resolves each path through the granted root (CAP-008),
re-hashes each file, and Core compares the result with the approval. A mismatch, an
expired approval, a changed policy revision, or a second use each end in "stale:
ask again". The approval screen shows the same diff Core hashed, and names the
target and the operation in plain words.

### 4.5 Connectivity and operation state

Connectivity is treated as a property of capabilities, not a global mode: a
capability that needs the internet is unavailable while it is absent, exactly as a
capability is unavailable today while its provider is unhealthy. Local capabilities
are unaffected.

Operation states, stored in the control database by a **new** migration:

```
proposed ─► approved ─► dispatched ─► succeeded
                │            ├──────► failed            (known: nothing happened)
                │            └──────► unknown-outcome ─► reconciled ─► succeeded | failed
                └─► expired | discarded | stale
```

- The intent is journalled before dispatch (ORCH-006). A crash after dispatch leaves
  `dispatched` with no outcome, which is read as `unknown-outcome` on restart.
- **Reconciling** is read-only and bounded: for a push, compare the remote branch
  with the intended commit; for a pull request, look it up by head branch and by the
  operation ID written into its description; for a merge, read the pull request's
  state. Until the remote can be reached the operation stays `unknown-outcome` and is
  shown as paused, with the reason.
- **After a restart**: `approved` operations are listed as "approved, not run" and
  need the human to start them, at which point they are re-validated. Nothing runs by
  itself.
- **Cancel** ends the remote worker's process tree and records the outcome as failed
  or unknown, whichever is true.

Proposed limits, all configurable and all pending validation: 10 s to connect, 120 s
in total, at most two retries for read-only operations, none for operations with
effects.

### 4.6 Open item: starting with no internet

Freya's speech components load models through libraries that can contact a model
hub. During the speech benchmark such a contact was observed from Freya's own
process. Whether Freya starts cleanly and promptly with no internet has **not been
tested**. Phase 1 includes testing it and, if needed, loading only from files
already on disk (in line with pending NEW-J).

## 5. Prerequisites

None of the development capabilities are enabled until these are implemented and
validated. Several are owner actions or pending ADRs.

1. Authenticated sessions and per-client scopes replacing `local-owner`
   (ADR-017, GUI-003).
2. The approval object and approval-capable client scope (pending NEW-A), with the
   ambient-input scope (pending NEW-I).
3. Broker operation IDs, effect classes, a pre-dispatch journal, and reconciliation
   (CAP-010, CAP-011, ORCH-006, ADR-018).
4. A restricted identity for the development worker, and ACLs on Core storage
   (owner action; `CLAUDE.md` lists the service identity as not started).
5. A validated isolation profile for checks (ADR-014, SEC-013). Until then
   `dev.check` does not exist.
6. Filesystem target resolution that resists traversal and link substitution
   (CAP-008).

## 6. Phases

Each phase ends with its tests passing and an owner decision to continue. A later
phase is not started because an earlier one finished.

| Phase | Delivers | Changes anything outside Freya? |
|---|---|---|
| 0 | This document and the owner's decisions | No |
| 1 | Connectivity reporting; bounded network helper; offline start-up tested; operation store and journal | No |
| 2 | Prerequisites 1 to 3: sessions, scopes, approval objects | No |
| 3 | Grants and exclusions; `dev.inspect` (read-only) | No |
| 4 | Staging, proposals, Core-computed diff and approval screen | No (staging only) |
| 5 | `dev.apply` and `dev.commit` to a dedicated worktree | Yes, after approval |
| 6 | `dev.check` in validated isolation | Runs repository code, isolated |
| 7 | `dev.publish.*` with reconciliation | Yes, remote effects |
| 8 | Freya's own source: separate checkout, review, approved deploy and restart | Yes |

## 7. Tests

All deterministic: a scripted fake remote, a fake clock, and process interruption at
named points. No test depends on real network conditions or on sleeping.

- **Approval**: approval attempted from model output, a tool result, document text,
  and a voice-scoped session is refused. A file changed after approval, a changed
  target, an expired approval, and a reused approval are each refused as stale.
- **Paths**: traversal, absolute paths, links, junctions, and reparse points that
  leave a granted root or reach an excluded target are refused on the resource
  actually opened.
- **Uncommitted work**: an apply over a file edited since the diff was shown stops
  and changes nothing.
- **Interruption**: the process is ended at each journal transition during apply and
  during publish; on restart the operation is finished, undone, or `unknown-outcome`,
  and nothing runs without the human (in the spirit of TEST-007).
- **Network**: refused connection, timeout, a connection dropped before and after
  the remote acted, and cancellation mid-operation. Locks are released, the interface
  answers, local commits survive.
- **Uncertain outcome**: a push and a pull-request creation whose reply is lost are
  reconciled to exactly one effect; a retry is offered only with the first attempt
  disclosed, and never produces a duplicate.
- **Offline**: with the network unavailable, inspect, propose, diff, approve, apply,
  and local commit all work; publishing is reported as paused with the reason; a chat
  turn with Ollama still works.

## 8. Decisions needed from the owner

Nothing in phases 1 to 8 should start until these are answered.

- **D1. Build on the pending amendments?** This design relies on NEW-A (approval
  objects), NEW-D (protected Core targets), and NEW-I (ambient input), which are not
  adopted. Either adopt them (or their reconciled form) first, or say how approval
  should work without them.
- **D2. Is this alpha work?** The baseline names "self-development workflows" among
  its goals. I did not find these capabilities in the alpha implementation order
  (V1-004), but I did not read every section for it. Decide whether they are alpha
  work, or follow it.
- **D3. What counts as the authenticated approval interface?** Recommended: wait for
  the authenticated gateway (ADR-017). The alternative, accepting today's loopback
  window for approvals, means anything running as the same Windows user could
  approve.
- **D4. In-place apply.** Recommended: dedicated worktree only at first; in-place
  apply to the owner's working tree or a plain folder later, if at all.
- **D5. How `git` is run.** Recommended: in the worker with hooks, filters, and
  monitors disabled for local operations; anything that cannot be made safe that way
  moves into isolation.
- **D6. Checks before isolation is validated.** Recommended: none. The alternative,
  running tests under a restricted Windows account, is not an isolation boundary
  under ARCH-017.
- **D7. Which remote operations exist.** Recommended: push and open a pull request
  first; merge, deploy, and restart later, each separately approved. Freya never
  merges her own pull requests without a human approval of that merge.
- **D8. Approval lifetime and retention.** Proposed: approvals expire after 15
  minutes unused; proposals and replaced file contents are kept 30 days. Both are
  starting values to confirm.
- **D9. Network limits.** Proposed values are in section 4.5.
- **D10. Requirement labels.** Confirm NEW-M to NEW-X as provisional labels, or
  supply the IDs to use.

## 9. Not covered

- The pull request for the four window review findings is separate:
  https://github.com/TranquilONE17/Freya/pull/11.
- This document changes no code, policy, configuration, or system setting, and
  proposes no change to system software, Windows features, ACLs, or service accounts
  beyond listing the prerequisites that would need the owner.
- Development on other devices, and anything federated, is out of scope (SEC-035
  unchanged).
