# ADR-015: Persistence and Recovery

**Status: recorded from implementation, 2026-10-22. Not approved.** This records what
the code on the release line already decides, so the decision can be read, argued
with and approved or reversed. It does not claim the decision is validated, and no
acceptance test is passed by it. Baseline: *Freya Foundation v1.1*, section 22.

**Baseline summary:** Replaceable persistence contracts; SQLite and canonical-file alpha profile; journal, deletion ledger, recovery/migration guarantees; configurable operational targets pending validation.

## What the code decided

- Three SQLite databases behind `ControlStore` (`core/persistence/control_store.py`):
  memory, control (policy and audit), usage. Shipped migrations are never edited.
  The connection is shared between threads, so rows are read under its lock.
- Backup on close, at most once an hour, to a dated folder on another drive, using
  SQLite's backup API; it refuses the same drive and never deletes
  (`storage/backup.py`).
- Bulk stores can be moved to another drive by copy, verify, switch
  (`storage/move.py`), and `storage/placement.py` reports where each store should
  live. All under one `data_dir()` once C-4 (#38) merges.
- Explicit forgetting is one transaction; a deletion ledger records it
  (`memory/deletion_ledger.py`).
- No encryption at rest.

## Validation owed

- The 24 h RPO / 4 h RTO targets have never been measured. A restore drill: delete a
  scratch `data/`, restore from the last backup, time it.
- Restore quarantine: a backup taken before a forgetting restores the forgotten
  fact. MEM-008 is not met (CLAUDE.md says so).
- Backup encryption and key recovery.
- SQLite durability settings (each audited call costs 30 to 60 ms in synchronous
  writes; provisional).
