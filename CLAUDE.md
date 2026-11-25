# Paragon PR7-FS: notes for Claude

**Paragon PR7-FS** is the owner's personal folder comparison and sync: Python (**PySide6**) that **works the way
FreeFileSync works**, in the Paragon family look (PR7-Z ... PR7-SM, PR7-HB `ARYEZ/Paragon-PR7-HB`). Windows 10/11 x64 is
the target; it runs on Linux for tests. The owner writes Python; explain the why.

## How it's built

- `pr7fs/engine.py` (no Qt): `Filter` (FreeFileSync's syntax: `;` / new lines, `\x\` = a folder at the top, `*\x\`
  anywhere, a bare name matches names; case-insensitive; a path is excluded when a folder it's in is; `.pr7fs.db` and
  `*.pr7fs.tmp` always out), `scan` (os.scandir, links / junctions not followed), `compare` -> `Item`s in tree order
  with a category (left / right only, left / right newer, different, equal, conflict; 2 s time tolerance),
  `assign` (Mirror / Update tables, Custom, Two way), `set_action` (a folder's contents follow), `stats`.
- **Two way's record** (`Record`): `.pr7fs.db` (JSON, hidden) in both folders = what both held alike after the last
  sync, with a pair id (`new_pair()` for a pairing with none: never reuse ids). Trusted only when both files exist and
  the ids match. In the list: on one side + in the record = deleted on the other (or a conflict if changed since);
  not in the record = new; changed on both sides = conflict. No record yet: both ways, newer wins, and the window
  still allows a sync with nothing to copy (`needs_record`) so the record gets written. `_moves` turns "deleted +
  new with the same size and time" into a rename.
- `pr7fs/sync.py` (no Qt): `Sync.run` order: moves, deletions (deepest first), folders, files. Copies to
  `<name>.pr7fs.tmp` then os.replace, exact mtime. Deleted / overwritten: `trash.send` (Recycle Bin), permanent, or
  versioning (`version_path`: stamp per file / per folder / replace; `keep_days` cleanup). Errors -> `ask(path, msg)`
  retry / ignore / ignore_all / cancel (or `ignore_errors`). pause / resume / stop from any thread. Two way rewrites the
  record from fresh scans afterwards.
- `pr7fs/trash.py`: SHFileOperationW with FOF_ALLOWUNDO and no prompts (PR7-E's); **PR7FS_TRASH** points it at a
  folder: tests always set it.
- `pr7fs/config.py` (no Qt): `Config` (pairs, compare_by, include / exclude with FreeFileSync's default excludes,
  variant, custom, detect_moves, deletion, versions, naming, keep_days, ignore_errors, when_done), .pr7fs JSON files,
  the last one in <data>/last.pr7fs. <data> = %APPDATA%\Paragon\PR7-FS, **PR7FS_DATA** in tests.
- `pr7fs/main_window.py`: `DiffModel` (plain list model of (pair, Item); `all_rows` / `rows` by the view buttons,
  equal hidden at first), `PairRow`s, compare on a thread (both sides at once; inline when `sync_jobs`), the middle
  column's action menu, Exclude via Filter, `_ask` / `answers` / `said`. `dialogs.py`: `SettingsDialog` (three tabs;
  radios in QButtonGroups: siblings are one set otherwise), `SyncDialog` (a worker thread; errors wait on an Event
  while the GUI asks; log in <data>/logs; `when_done` uses `answers["system"]` in tests).
- `pr7fs/app.py`: one window per user (QLocalSocket hand-off of a .pr7fs, PR7-R's Windows fix); command-line modes
  never let an error escape (PR7-IS's lesson); `--batch FILE` (errors skipped and logged; exit 0 / 1 / 2),
  `--selftest OUT.json` (CI runs it on the installed exe).
- Installer `installer/pr7fs.iss` (per user, AppId {D573AEAF-B102-484A-AD03-42624DC18A25} permanent; the .pr7fs file
  type with "Synchronize now (batch)", HKCU); CI installs it, `tools/verify_install.py installed|uninstalled` (a batch
  run with the real Recycle Bin). Spec: file details, no UPX, PyInstaller's bootloader built in CI, Defender scan.
- Updates: `pr7fs/updates.py` / `update_ui.py` (the family's files, keep them in step; with PR7-U installed,
  update_ui offers it); `family.py`: the family's AppIds (PR7-FS included).
- `pr7fs/finish.py` (no Qt): the family's finish (OBSIDIAN / AURORA), one choice for every app:
  HKCU\Software\Paragon\Family "Finish" (a file elsewhere; PARAGON_FAMILY_FILE in tests, conftest). `finish.start`
  at start-up, `set_finish` saves it, app.py's 2 s timer `finish.follow`s another app's switch. The same file in every
  family app: keep them in step.

## The look (family rules)

- Theme is PR7-HB's (OBSIDIAN + AURORA, tabs and sliders). Colours: the family's only, the action glyphs included
  (orange copies, red deletions, amber conflicts); Inter; labels UPPER CASE; file names keep their case.
- The PR7-FS mark: PR7 `Logo.cpp` geometry plus F (PR7-F's) and S (PR7-IS's); icon "7FS" by `tools/make_icon.py`,
  wizard art by `tools/make_installer_art.py`. Mock-up: `tools/mockup.py`. Check visuals with
  `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT` (the real window on generated folders).

## Rules

- Behaviour questions: do what FreeFileSync does (variants, categories, filter syntax, deletion handling).
- Tests: `python -m pytest` (offscreen) on real folders with set file times; every sync is checked on disk. Never the
  real settings, data folder or Recycle Bin (conftest), or, outside CI, the registry.
- Releases: bump `__version__` in `pr7fs/__init__.py` and add a `## x.y.z` section to CHANGELOG.md, then push: CI
  publishes that version by itself once every check has passed. Run workflow / `v*` tags still work.
