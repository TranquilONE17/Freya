# Design proposal: human-approved development, and working without the internet

**Status: design proposal with the owner's decisions recorded (section 8, two
rounds, given 2026-10-08). Nothing here is implemented, and no capability is enabled.** The
decisions settle how this design should proceed. They do not approve any ADR, adopt
the pending amendments into the architecture, or assign requirement IDs; those
remain matters for reconciliation.

- Requirements in this document carry provisional labels **NEW-M to NEW-Z, NEW-AA, and NEW-AB**. They
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

### Added requirement: changing her own code with no connection

Stated by the owner on 2026-10-08, after the decisions in section 8.

- **NEW-Y — Self-development does not depend on a remote.** Freya must be able to
  change her own code while GitHub (or any remote host) cannot be reached. The whole
  path works locally: propose, review, approve, apply, commit, bring the change into
  the local main line, update the installed copy, and restart. Each step that has a
  consequence is still separately approved (NEW-T). A pull request is a way to
  publish and get further review when a connection exists; it is never a
  precondition for a change taking effect.

  This fits pending NEW-D, which requires "human review and the update path", not a
  hosted pull request. Offline, the human review is the approval screen showing the
  exact diff.

### Added requirement: beta testing, then offering the change to other nodes

Stated by the owner on 2026-10-08: Freya should be able to change her local code,
beta test it, and then upload it to other nodes if they become available or choose
to upgrade.

- **NEW-Z — A change is tried before it becomes the installed version.** An approved
  change to Freya's own code is first installed as a *candidate* alongside the
  current version, and run on trial. The current version stays installed and can be
  returned to at any time without a connection. A candidate becomes the installed
  version only by a separate owner approval to promote it. This is the staged,
  health-checked update with a tested way back that OPS-001 and OPS-011 already
  require, applied to her own changes.
- **NEW-AA — Other nodes are offered a release; each decides for itself.** A promoted
  version can be packaged as a release, identified by an exact digest and signed
  (EXT-006, OPS-002). Other nodes are *offered* it when they can be reached; nothing
  is installed on a node by another node. Each node verifies the release, decides
  under its own authority whether and when to upgrade, stages and health-checks it,
  and keeps its own way back (OPS-001). A node that is unreachable or declines simply
  stays on its version. A signature shows where a release came from; it is not
  permission to install it. Being connected to a node gives no authority over it
  (DIST-003, SEC-035, SEC-037).

### Added requirement: uploading her code automatically

Stated by the owner on 2026-10-08: the upload of her new code to git should be
automatic, as long as she can roll back to an earlier version if needed.

- **NEW-AB — Publishing her own code is automatic under a standing grant.** Pushing
  Freya's own committed changes to her designated remote does not need an approval
  each time. It happens under a standing authorization the owner gives once and can
  withdraw, recorded as policy, naming the repository, the remote, and the branches
  it covers. Each push is still a broker invocation with an audit record. The
  condition the owner attached is part of the requirement: an automatic push is
  allowed only while an earlier version can be returned to, locally and on the
  remote.

  **This changes an earlier decision.** NEW-T and decision D7 said every push needs
  its own approval. For Freya's own code, the owner has replaced that with a standing
  grant. It also departs from the original brief, which asked for separate approval
  of pushes. Per-action approval still applies to everything NEW-AB does not name:
  changing files, promoting a candidate, merging, and other repositories.

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
therefore invoke it with those features disabled (decision D5), with a test that
plants a hook and a filter in a repository and proves neither runs. Anything that
cannot be disabled that way moves into isolation.

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
- Applying **in place** to the owner's working tree or to a plain folder is **not
  part of this design** (decision D4). A granted folder that is not a git repository
  can be inspected but not edited. Adding in-place apply later would need a new
  proposal.
- The digest check in NEW-R still applies inside the worktree: if a file is not
  exactly what the human saw in the diff, the apply stops.

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

Starting limits (decision D9), configurable and pending validation: 10 s to connect,
120 s in total, at most two retries for read-only operations. Operations with
effects are never retried automatically; that is a rule (CAP-011), not a setting.

### 4.6 Changing her own code with no connection (NEW-Y)

`git` itself needs no network: history, branches, commits, and merges are all local.
Only fetch, push, and pull requests reach a remote. So the offline path is:

| Step | Where it happens | Needs a connection? | Approval |
|---|---|---|---|
| Propose, show the diff | staging, Core | No | none (a proposal changes nothing) |
| Apply and commit | Freya's separate working copy | No | the patch; then the commit |
| Merge into the local main line | local repository | No | its own |
| Update the installed copy | installed copy, from an approved local commit | No | its own |
| Restart | the running Freya | No | its own |
| Push, open a pull request | remote | Yes; paused while offline | each its own, whenever a connection returns |

What this adds to the design:

- **Local review stands in for the pull request.** The approval screen is the
  review. Because there is no second reviewer or CI run offline, the update step
  shows the complete difference between the installed version and the commit being
  installed, not just the last patch.
- **The installed copy must be separate from the working copy.** Today Freya runs
  directly from the development checkout (an editable install), so editing the
  checkout edits the running program. Pending NEW-D says the deployed installation is
  not a development working copy. Separating them is a prerequisite for this path.
- **An update must be undoable without a connection.** Offline there is nowhere to
  fetch a known-good copy from. The update step keeps the previous installed version
  and, if the new one does not start and pass its start-up checks (including audit
  verification), restores the previous one and says so. Going back is not a new
  change and needs no new approval; going forward again does.
- **Catching up later.** Local commits made offline are published only when the
  owner approves a push. If the remote has moved in the meantime, that is a normal
  divergence for the owner to resolve; Freya does not force-push or rewrite history.
- **Checks.** Decision D6 still holds: Freya runs no repository code, her own
  included, until isolation is validated. Until then an offline self-change is
  reviewed by reading the diff, and the owner runs the tests.

Decision D11 settles when these steps are built: together with the ability to change
code, after the alpha (D2). Merging on the remote stays later (D7).

### 4.7 Beta testing and offering releases to other nodes (NEW-Z, NEW-AA)

```
 working copy ──approve──► candidate ──approve──► installed ──approve──► release
 (her changes)            (on trial)             (this node)            (offered)
                              │                       ▲                     │
                              └── fails or rejected ──┘                     ▼
                                  back to installed            other nodes: verify,
                                                               decide, stage, try,
                                                               keep their own way back
```

**On this node**

- Two installed slots: *current* and *candidate*. Installing a candidate does not
  remove the current version.
- A trial is the candidate actually running as Freya. Two kinds are possible, and
  both are supported, in order (decision D12):
  - *Side by side*: the candidate runs as a second instance on scratch data, while
    the current version keeps serving. Nothing of the owner's is at risk, but it
    does not exercise real memory, policy, or voice.
  - *In place*: the candidate takes over, with the owner's data, for a trial the
    owner starts and ends. Real use, real data, so it needs the data safeguards
    below.
- A candidate that fails to start, fails audit verification, or fails its health
  checks is stopped and the current version resumes, automatically.
- **Data is the hard part.** A candidate that changes the control or memory database
  format cannot simply be backed out by reinstalling the old code (OPS-001, OPS-011).
  A candidate with a migration is tried in place only after a verified backup, and
  going back means restoring that backup. `CLAUDE.md` already requires a backup before
  any change to the memory database's schema.
- What may run during a trial is still bounded by decision D6: a candidate is code
  the owner has read and approved, running through the update path. Automated test
  runs of unreviewed code still wait for validated isolation.

**Other nodes**

- A release is a bundle: the exact commit, its dependency lock, a manifest with
  digests, the version and data-format compatibility it declares, and a signature.
- Offers are pulled or accepted, never pushed into effect. A node that becomes
  reachable is told a release exists; a node can also ask. Transfer can be directly
  between nodes on a local network, so it does not depend on GitHub.
- Each node repeats NEW-Z for itself: verify, stage as a candidate, try, promote, and
  keep the previous version.
- Who approves on another node depends on who administers it. An independently
  administered node always decides on its own (SEC-035). A node the owner also
  administers is upgraded on the owner's approval given on that node, for that node
  (decision D13); one approval covering several named nodes may be added later.
- A release is signed by the owner at the approval step, with a key held in Windows'
  protected key storage (decision D14).
- Mixed versions must keep working while nodes upgrade at different times, which
  needs the compatibility and version negotiation the baseline already asks of the
  gateway (GUI-003).

**What this depends on that does not exist**

- Other nodes. The baseline defers distributed workers and federation: the alpha is
  one workstation, and those features stay disabled until their tests exist
  (DIST-007, TEST-010). NEW-AA is recorded now so that the release format and the
  "each node decides" rule are designed in; it cannot be built or enabled before
  node identity and authenticated node-to-node transport exist.
- Signing keys, and where they are kept (EXT-006). A release signed by a key the
  model could reach would prove nothing.
- The separate installed copy (prerequisite 7).

### 4.8 Automatic upload, and going back (NEW-AB)

**What is pushed, and when.** Only commits that came from changes the owner
approved, in Freya's own working copy. Nothing is pushed from anywhere else. Whether
Both, to different places (decision D15): every commit is uploaded at once to a
work-in-progress branch, and a promoted version is uploaded separately and marked.

**Where it goes.** Two branches of Freya's own, named in the standing grant: one for
work in progress and one for promoted versions (decision D16). The main branch is
never written by an automatic upload; it changes only by a merge the owner approves,
as `CLAUDE.md` already requires.

**What "roll back" can and cannot mean.** This is the condition the owner set, so it
is worth being exact:

- *Locally*, going back is complete: the previous installed version is kept
  (NEW-Z), and every earlier commit is in the local repository.
- *On the remote*, going back means publishing a new commit that undoes the change,
  or moving the release marker back to an earlier version. Earlier versions are
  marked (tagged) when promoted so there is always a named one to return to.
- *What cannot be undone*: once code is uploaded, it has left this computer. It can
  be reverted, but not reliably un-published; copies may exist. History is never
  rewritten or force-pushed to hide a change, because that would also destroy the
  record needed to go back.

So the safeguard that matters most happens **before** the push:

- **Nothing sensitive is uploaded.** The excluded targets (NEW-N) are never in a
  commit. Each automatic push is preceded by a check for secrets, credentials, and
  personal data in what is about to be sent; a finding stops the push and asks the
  owner. Uploading is a disclosure outside this computer (pending NEW-B), which is
  why it gets this check even though it no longer gets a per-push approval.
- **The way back is verified first.** No automatic push happens unless a previous
  version is installed or installable locally and a marked earlier version exists.

**Work that did not work is kept, and labelled.** The owner asked that changes which
fail or are rejected stay on the work-in-progress branch, marked as not working, so
that a coding agent can refer to them later. So an unsuccessful change is never
deleted or hidden; it is recorded:

- Every change gets an **attempt record**: a small file in an `attempts/` folder on
  the work-in-progress branch, one per attempt, so it travels with the code and can
  be read without special tools. The commit is also tagged, for example
  `attempt/<id>/failed`, so the state is visible from the history alone.
- The record states: what the change was meant to do; the commits it covers; its
  **status** (`in-progress`, `failed-side-by-side`, `failed-trial`, `rejected`,
  `superseded`, or `promoted`); at which stage it stopped; what was observed (which
  check failed, the error, or the owner's stated reason for rejecting it); and what
  replaced it, if anything.
- **The status is written by Core from what actually happened**, not by the model. A
  model-written summary of what was tried and why it may have failed can be
  included, and is labelled as that. This matters because a later agent will rely
  on the label: "not working" has to mean a check really failed or the owner really
  rejected it.
- A non-working attempt is never on the promoted branch, never tagged as known-good,
  and never offered to other nodes. Its label is not removed if someone later reuses
  the idea; the new attempt gets its own record and points back to the old one.
- Attempt records are uploaded like everything else, so the pre-upload check applies
  to them. Error output is included only after that check, because logs are a common
  place for a secret or personal detail to appear.
- For an agent reading them later, these records are reference material, not
  instructions (CTX-001): they say what was tried and what happened, and grant
  nothing.

**Offline, and after a restart.** While the remote cannot be reached, pushes wait and
Freya says so. NEW-W says recovery must not silently run queued changes or treat
restored state as new authority. An automatic push is consistent with that only
because its authority is the standing grant, checked again at the moment of
sending, not the queued item: when the connection returns Freya re-reads the grant,
re-runs the checks above, reconciles what the remote already has (NEW-X), and
announces the push. If the grant has been withdrawn, nothing is sent.

**Withdrawing it.** The owner can turn the standing grant off at any time from the
local interface; pushes then go back to needing approval each time.

### 4.9 Open item: starting with no internet

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

7. An installed copy of Freya that is separate from the development checkout, with
   the previous version kept for going back (pending NEW-D; needed by NEW-Y).

## 6. Phases

Each phase ends with its tests passing and an owner decision to continue. A later
phase is not started because an earlier one finished. The "When" column follows
decision D2.

| Phase | Delivers | Changes anything outside Freya? | When |
|---|---|---|---|
| 0 | This document and the owner's decisions | No | Done |
| 1 | Connectivity reporting; bounded network helper; offline start-up tested; operation store and journal | No | Alpha |
| 2 | Grants and exclusions; `dev.inspect` (read-only) | No | Alpha |
| 3 | Sessions, scopes, approval objects (prerequisites 1 to 3) | No | Alpha, already planned |
| 4 | Staging, proposals, Core-computed diff and approval screen | No (staging only) | After alpha |
| 5 | `dev.apply` and `dev.commit` to a dedicated worktree; for Freya's own source, local merge, candidate install, side-by-side and real-data trials, promotion, restart, and the way back (NEW-Y, NEW-Z; D11, D12). Needs the separate installed copy. | Yes, after approval | After alpha |
| 6 | `dev.check` in validated isolation | Runs repository code, isolated | After alpha, once isolation is validated |
| 7 | Automatic upload of her own code to her two branches under the standing grant, with the pre-upload check (NEW-AB; D15 to D17); approved push and pull request for other repositories; reconciliation | Yes, remote effects | After alpha |
| 8 | Merge on the remote, each separately approved | Yes | Later, by a new owner decision |
| 9 | Signed releases offered to other nodes, approved on each node (NEW-AA; D13, D14) | Yes, on other nodes, by their own decision | Not before distributed features are enabled |

Phase 2 reads granted repositories with `git`, so it needs the restricted worker
identity (prerequisite 4, an owner action) even though it changes nothing.

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
- **Attempt records**: a change that fails the side-by-side run, fails its trial, or
  is rejected gets a record and tag with the matching status, written from the
  actual outcome; a model cannot set or change a status; a non-working attempt
  cannot be promoted, tagged known-good, or packaged as a release; a record
  containing a planted secret is held by the pre-upload check.
- **Offline**: with the network unavailable, inspect, propose, diff, approve, apply,
  and local commit all work; publishing is reported as paused with the reason; a chat
  turn with Ollama still works.

## 8. Owner decisions

Given by the owner on 2026-10-08, one at a time, each with the options and a
recommendation laid out. They direct this design. They are not ADR approvals.

| | Question | Decision |
|---|---|---|
| D1 | Build on pending NEW-A, NEW-D, NEW-I? | Yes, as the working basis. They stay marked pending until reconciliation settles their wording and IDs. |
| D2 | Alpha work, or after? | Split. Offline handling and read-only inspection of granted targets go into the alpha. Anything that changes files, runs code, or publishes comes after. |
| D3 | Which screen may grant approvals? | The signed-in gateway only (ADR-017), once it exists. Today's loopback window may not. |
| D4 | Where may approved changes be written? | Only to a separate working copy Freya manages. The owner's own folders are never written to. In-place apply is not planned. |
| D5 | How is `git` run? | In the restricted worker with hooks, filters, and monitors switched off, with tests proving a planted hook does not run. What cannot be disabled moves into isolation. |
| D6 | Checks before isolation is validated? | None. Freya runs no repository code until the Hyper-V profile is validated. The owner runs tests until then. |
| D7 | Which remote operations? | Push and open a pull request first, each separately approved. Merge, deploy, and restart later, one at a time. Freya never merges, deploys, or restarts without approval of that specific action. |
| D8 | Approval lifetime and retention | Approvals expire **60 minutes** after being granted if unused. Unused proposals and replaced file contents are kept 30 days. Starting values, adjustable. |
| D9 | Network limits | 10 s to connect, 120 s in total, two retries for read-only operations, none for operations with effects. Starting values, adjustable. |
| D10 | Requirement labels | Keep NEW-M to NEW-X as provisional labels until reconciliation assigns IDs. |

A note on D8: the owner chose 60 minutes over the 15 proposed. A longer lifetime
means an approval can be used later than it was given, so the binding in section
4.4 carries the weight: whatever the lifetime, an approval is good for one use, of
one exact patch, on a target whose files are still exactly what was shown.

**Changed afterwards.** D7 said a push needs its own approval each time. The owner
later decided that uploading Freya's own code should be automatic provided she can
return to an earlier version (NEW-AB, section 4.8). D7 still stands for opening a
pull request, merge, deploy, and restart, and for repositories other than her own.

### Second round of decisions

Given by the owner on 2026-10-08, one at a time, after the added requirements
NEW-Y to NEW-AB. As before, they direct this design and approve no ADR.

| | Question | Decision |
|---|---|---|
| D11 | When are local merge, update, and restart built? | Together with the ability to change code, so the change, beta test, use loop works from the first version, offline too. Each step is still separately approved. Remote merge stays later (D7). |
| D12 | What is a beta test? | Both kinds, in order: a change first runs side by side on scratch data; only if that passes can the owner start a trial on real data, after a verified backup. |
| D13 | Upgrades on other nodes the owner administers | Approved on each node, for that node, to begin with. One approval covering several named nodes may be added later by a separate decision. Independently administered nodes always decide for themselves. |
| D14 | Who signs a release? | The owner, with a key kept in Windows' protected key storage, out of reach of any agent, model, or guest, and used only at the owner's approval of a release. A hardware security key may be adopted later by a separate decision. |
| D15 | When does the automatic upload happen? | Both, to different places: every commit is uploaded at once to a work-in-progress branch as a backup; promoted versions are uploaded separately and marked as known-good. Work that fails or is rejected stays on the work-in-progress branch, labelled as not working, for later reference. |
| D16 | Which branch do promoted versions go to? | A dedicated branch of Freya's own. The main branch changes only by a merge the owner approves. `CLAUDE.md`'s rule against committing directly to `main` stands. |
| D17 | What does the pre-upload check do on a finding? | It holds the upload and shows the owner what was found. Items the owner confirms as harmless are remembered and not flagged again; anything new still stops. |

Two notes on these:

- **D15 means unpromoted work is uploaded, and the owner wants it kept.** Changes
  that later fail a trial or are rejected stay on the work-in-progress branch. The
  owner asked that they be marked as not working so a future coding agent can refer
  to them; section 4.8 describes the attempt record and tag that do this. The
  pre-upload check (D17) applies to both branches and to the records.
- **D17's remembered items are a list the owner maintains.** An item cleared by
  mistake stays cleared until removed, so the list is shown in the interface and
  each entry can be withdrawn.

### Still open

- Nothing from the two rounds above. New questions will be numbered from D18.

## 9. Not covered

- The pull request for the four window review findings is separate:
  https://github.com/TranquilONE17/Freya/pull/11.
- This document changes no code, policy, configuration, or system setting, and
  proposes no change to system software, Windows features, ACLs, or service accounts
  beyond listing the prerequisites that would need the owner.
- Development on other devices, and anything federated, is out of scope (SEC-035
  unchanged).
