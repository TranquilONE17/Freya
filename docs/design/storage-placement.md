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

## Not built

- Moving anything. A move of the memory database needs a backup first and the owner's
  say; so does changing where backups are written.
- A setting for where each kind of data lives. Today every path is fixed under
  `data/`, next to the source tree.
- Placing new data by this plan as it is created.
