# Where Freya's data is kept

Status: a first step, written 2026-10-09. It works out a plan and reports it. It
moves nothing, and Freya does not yet place new data by it.

## The owner's rule

All long-term data stays on this machine, and where each kind lives follows from what
the drive is good at.

| Drive | Good at | Suited to |
|---|---|---|
| SSD | Fast lookups and frequent small writes | Databases and their indexes, settings, anything read during a turn, model files loaded often |
| Hard disk | Large capacity, long sequential reads and writes | Generated images and clips, imported media, avatar models, logs, backups |

A backup belongs on a different drive from what it protects, whatever the drive types.

## What is built

`freya.storage.placement` lists every store under `data/` with what it needs (fast,
bulk, or a copy kept elsewhere), asks Windows which drive is an SSD and which a hard
disk, and says where each store would best live. Placement goes by drive type, not
drive letter. Where Windows does not say what a drive is, it gives no advice.

```powershell
python -m freya.storage.placement
```

It reads file sizes only, never contents. A test fails if the code starts writing a
store under `data/` that the list does not name.

## What it found on this workstation (2026-10-09)

One NVMe SSD (C:) and one hard disk (D:). Everything is on the SSD.

- The databases, settings, voice models (about 20 GB) and voice engine environments
  (about 10 GB) are where they should be.
- The data that would suit the hard disk (avatar models, converted-avatar leftovers,
  images, media, voice benchmarks, logs) comes to under 300 MB in total. Moving it
  would free almost nothing today. It matters later, as images, media and clips grow.
- **The backups are on the same drive as the databases they protect.** This is the
  one finding worth acting on now: if the SSD fails, the memory database and its
  backup go together.

The largest files Freya uses are the Ollama models, which Ollama keeps in its own
folder outside `data/`. They are loaded often and belong on the SSD; they are not part
of this plan.

## Backups

Looking at the backups showed that there were none to speak of: the `backups` folder
held one copy of the memory database, made once when the conversation tables were
added. Nothing copied the databases regularly, against the baseline's target of losing
at most a day's data.

`freya.storage.backup` makes a dated backup on another drive:

```powershell
python -m freya.storage.backup            # make one, on the other drive
python -m freya.storage.backup --check D:\FreyaBackups\2026-10-09_170618
```

- It copies the memory, control and usage databases with SQLite's own backup, which
  gives a consistent copy even while Freya is running, and checks each copy.
- It copies the small settings files, including the cloud settings, the screening
  lists and the record of sent briefs.
- It refuses a target on the same drive as the data.
- Each run makes a new folder with a manifest of sizes and checksums. It never moves
  or deletes anything, so old backups are not cleared away; that is not built.
- It does not copy images, media, voice clips or models.

The first backup was made on 2026-10-09 to `D:\FreyaBackups`, at the owner's request.
It is personal data, on an unencrypted drive, like the data it copies.

Not built: making a backup automatically (when Freya closes, or daily), removing old
ones, restoring from one, and checking that a restored copy works. Until a backup is
made automatically, it is only as recent as the last time the command was run.

## Moving bulk data off the SSD

The owner asked (2026-10-09) to keep on the SSD only what needs to be there. That is
not done yet, and it should not be done by copying folders by hand:

- Every store's location is fixed in its own module, next to the source tree. Moving
  a folder without changing the code would make Freya start an empty one.
- Some stores are referred to from others (the avatar library lists model files; the
  media library records where files are). Each needs checking for how it records a
  location before its folder moves.
- It has to be done with Freya closed.

The amount involved today is under 300 MB, so nothing is lost by doing it properly:
one setting for where bulk data lives, each bulk store reading it, and a move that
copies, checks, switches over, and leaves the originals for the owner to remove.

## Not built

- Moving anything. A move of the memory database needs a backup first and the owner's
  say; so does changing where backups are written.
- A setting for where each kind of data lives. Today every path is fixed under
  `data/`, next to the source tree.
- Placing new data by this plan as it is created.
