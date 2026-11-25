# Changelog

## 0.1.2

- The family list (`family.py`) knows the four newest Paragon apps: PR7-HX (hex editor), PR7-DB (SQLite browser),
  PR7-UN (uninstaller) and PR7-LN (launcher), so links between the apps and the PR7-U offer find them.

## 0.1.1

- The family's list knows the newest apps (PR7-HB, PR7-FS, PR7-AR, PR7-WM), so links between apps and Check for Updates find them.

## 0.1.0

- First release: folder comparison and sync that works the way FreeFileSync works.
- Compare by file time and size, content or size; one or more folder pairs; both sides scanned at once.
- Two way (with the last-sync record, so deletions go across and changes on both sides become conflicts), Mirror,
  Update and Custom; moved files detected.
- Change any item's action; Exclude via Filter; FreeFileSync's filter patterns.
- Recycle Bin, permanent or versioning (three namings, keep for N days); fail-safe copies; errors asked or skipped.
- The sync window: progress, speed graph, log, pause, stop, When finished.
- Settings files (.pr7fs) and `--batch` for scheduled syncs.
- One finish for the whole family (OBSIDIAN / AURORA), Check for updates, and PR7-U knows it.
