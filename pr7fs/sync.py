"""Synchronizing (no Qt): carrying out the compared items' actions, FreeFileSync's way.

Order: detected moves (renames), deletions (deepest first, so a folder's contents go before it), new folders (top
first), then file copies. Copies are fail-safe: written next to the target as "<name>.pr7fs.tmp" and only then put in
place (os.replace), so a cut-off sync never leaves a half file under the real name; the file time is copied exactly.
A file that is deleted or overwritten goes, by the settings, to the Recycle Bin, away for good, or into the versioning
folder (FreeFileSync's three namings). Two way rewrites the last-sync record afterwards, from fresh scans: an item that
failed is simply not in it, so the next run sees it again."""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field

from . import engine, trash
from .engine import DELETE_LEFT, DELETE_RIGHT, TO_LEFT, TO_RIGHT, Item, native

RECYCLE, PERMANENT, VERSIONING = "recycle", "permanent", "versioning"
STAMP_FILE, STAMP_FOLDER, REPLACE = "stamp_file", "stamp_folder", "replace"
NAMING_TEXT = {STAMP_FILE: "Time stamp (file)", STAMP_FOLDER: "Time stamp (folder)", REPLACE: "Replace"}
STAMP = "%Y-%m-%d %H%M%S"


@dataclass
class Settings:
    deletion: str = RECYCLE
    versions: str = ""              # the versioning folder
    naming: str = STAMP_FILE
    keep_days: int = 0              # 0 = forever
    ignore_errors: bool = False


@dataclass
class Progress:
    items_done: int = 0
    items_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    current: str = ""
    started: float = field(default_factory=time.time)
    errors: list = field(default_factory=list)          # (path, message)
    log: list = field(default_factory=list)             # (time, action, text)

    def speed(self) -> float:
        t = time.time() - self.started
        return self.bytes_done / t if t > 0.5 else 0.0

    def remaining(self) -> float | None:
        s = self.speed()
        return (self.bytes_total - self.bytes_done) / s if s > 0 else None


class Stopped(Exception):
    pass


class Sync:
    """One run. `ask(path, message) -> "retry"|"ignore"|"ignore_all"|"cancel"` decides on errors (unless the settings
    say to ignore them); `pause()` / `resume()` / `stop()` from any thread."""

    def __init__(self, left: str, right: str, items: list[Item], settings: Settings | None = None, ask=None,
                 report=None, two_way_pair: str | None = None, flt: engine.Filter | None = None):
        self.left, self.right = left, right
        self.items = [it for it in items if it.action not in (engine.NOTHING,)]
        self.settings = settings or Settings()
        self.ask = ask
        self.report = report                        # called with the Progress now and then
        self.two_way_pair = two_way_pair            # a pair id: write the record after (Two way only)
        self.flt = flt or engine.Filter()
        self.progress = Progress(items_total=len(self.items),
                                 bytes_total=sum(it.bytes_to_copy() for it in self.items if not it.move_from))
        self._stop = threading.Event()
        self._go = threading.Event()
        self._go.set()
        self._ignore_all = False
        self.stamp = time.strftime(STAMP)
        self.done = False
        self.report_every = 0.1                     # seconds between progress reports (tests: 0)

    # -------------------------------------------------------------- control
    def pause(self):
        self._go.clear()

    def resume(self):
        self._go.set()

    def stop(self):
        self._stop.set()
        self._go.set()

    @property
    def paused(self) -> bool:
        return not self._go.is_set()

    def _check(self):
        self._go.wait()
        if self._stop.is_set():
            raise Stopped

    def _tell(self, force=False):
        if self.report is not None:
            now = time.time()
            if force or now - getattr(self, "_told", 0) > self.report_every:
                self._told = now
                self.report(self.progress)

    # -------------------------------------------------------------- running
    def run(self) -> Progress:
        p = self.progress
        moves = [it for it in self.items if it.move_from]
        deletes = sorted((it for it in self.items if it.action in (DELETE_LEFT, DELETE_RIGHT)),
                         key=lambda it: (-it.depth, it.rel))
        folders = sorted((it for it in self.items if it.action in (TO_LEFT, TO_RIGHT) and it.is_dir
                          and not it.move_from), key=lambda it: (it.depth, it.rel))
        files = [it for it in self.items if it.action in (TO_LEFT, TO_RIGHT) and not it.is_dir and not it.move_from]
        try:
            for it in moves:
                self._do(it, self._move)
            for it in deletes:
                self._do(it, self._delete)
            for it in folders:
                self._do(it, self._folder)
            for it in files:
                self._do(it, self._copy)
            if self.two_way_pair:
                self._write_record()
            if self.settings.deletion == VERSIONING and self.settings.keep_days > 0 and self.settings.versions:
                self._clean_versions()
            self.done = True
        except Stopped:
            p.log.append((time.time(), "stop", "Stopped"))
        self._tell(force=True)
        return p

    def _do(self, it: Item, fn):
        while True:
            self._check()
            try:
                fn(it)
                break
            except Stopped:
                raise
            except OSError as e:
                msg = f"{e.strerror or e}" + (f": {e.filename}" if getattr(e, "filename", None) else "")
                choice = "ignore" if (self.settings.ignore_errors or self._ignore_all) else (
                    self.ask(native(it.rel), msg) if self.ask else "ignore")
                if choice == "retry":
                    continue
                self.progress.errors.append((native(it.rel), msg))
                self.progress.log.append((time.time(), "error", f"{native(it.rel)}: {msg}"))
                if choice == "ignore_all":
                    self._ignore_all = True
                if choice == "cancel":
                    raise Stopped
                break
        self.progress.items_done += 1
        self._tell()

    def _paths(self, it: Item, to_right: bool) -> tuple[str, str]:
        src_base, dst_base = (self.left, self.right) if to_right else (self.right, self.left)
        return os.path.join(src_base, native(it.rel)), os.path.join(dst_base, native(it.rel))

    def _move(self, it: Item):
        to_right = it.action == TO_RIGHT
        base = self.right if to_right else self.left
        old, new = os.path.join(base, native(it.move_from)), os.path.join(base, native(it.rel))
        self.progress.current = f"Moving  {native(it.move_from)}  →  {native(it.rel)}"
        os.makedirs(os.path.dirname(new) or base, exist_ok=True)
        os.replace(old, new)
        self.progress.log.append((time.time(), "move_right" if to_right else "move_left",
                                  f"Moved  {native(it.move_from)}  →  {native(it.rel)}"
                                  + ("" if to_right else "  (on the left)")))

    def _delete(self, it: Item):
        base = self.right if it.action == DELETE_RIGHT else self.left
        path = os.path.join(base, native(it.rel))
        self.progress.current = f"Deleting  {path}"
        if not os.path.lexists(path):
            return
        if it.is_dir:
            if os.listdir(path):                 # its contents went first; anything left was filtered out: keep
                if self.settings.deletion == PERMANENT:
                    shutil.rmtree(path)
                else:
                    self._discard(path, base, it.rel)
            else:
                os.rmdir(path)
        else:
            self._discard(path, base, it.rel)
        side = "right" if it.action == DELETE_RIGHT else "left"
        self.progress.log.append((time.time(), f"delete_{side}", f"Deleted  {native(it.rel)}  (on the {side})"))

    def _discard(self, path: str, base: str, rel: str):
        """A file (or folder) that's going away: the Recycle Bin, gone, or into the versioning folder."""
        s = self.settings
        if s.deletion == PERMANENT:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                _writable(path)
                os.remove(path)
        elif s.deletion == VERSIONING and s.versions:
            dst = self.version_path(rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst) and s.naming == REPLACE:
                (shutil.rmtree if os.path.isdir(dst) else os.remove)(dst)
            shutil.move(path, dst)
        else:
            trash.send(path)

    def version_path(self, rel: str) -> str:
        s = self.settings
        if s.naming == STAMP_FOLDER:
            return os.path.join(s.versions, self.stamp, native(rel))
        if s.naming == REPLACE:
            return os.path.join(s.versions, native(rel))
        stem, ext = os.path.splitext(native(rel))
        return os.path.join(s.versions, f"{stem} {self.stamp}{ext}")

    def _folder(self, it: Item):
        src, dst = self._paths(it, it.action == TO_RIGHT)
        if os.path.isfile(dst):                  # a file where a folder goes (the type conflict, decided)
            self._discard(dst, os.path.dirname(dst), it.rel)
        os.makedirs(dst, exist_ok=True)
        try:
            st = os.stat(src)
            os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass
        side = "right" if it.action == TO_RIGHT else "left"
        self.progress.log.append((time.time(), f"to_{side}", f"Created folder  {native(it.rel)}"
                                  + ("" if side == "right" else "  (on the left)")))

    def _copy(self, it: Item):
        to_right = it.action == TO_RIGHT
        src, dst = self._paths(it, to_right)
        self.progress.current = f"Copying  {native(it.rel)}  →  {os.path.dirname(dst)}"
        self._tell(force=True)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + engine.TEMP_SUFFIX
        st = os.stat(src)
        try:
            with open(src, "rb") as f, open(tmp, "wb") as g:
                while True:
                    self._check()
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    g.write(chunk)
                    self.progress.bytes_done += len(chunk)
                    self._tell()
            shutil.copystat(src, tmp)
            os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
            existed = os.path.lexists(dst)
            if existed:
                if os.path.isdir(dst):
                    self._discard(dst, os.path.dirname(dst), it.rel)
                elif self.settings.deletion != PERMANENT:
                    self._discard(dst, os.path.dirname(dst), it.rel)      # the old one kept (bin / versions)
                else:
                    _writable(dst)
            os.replace(tmp, dst)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        side = "right" if to_right else "left"
        verb = "Updated" if existed else "Created"
        self.progress.log.append((time.time(), f"to_{side}", f"{verb}  {native(it.rel)}  ({engine.human(st.st_size)})"
                                  + ("" if to_right else "  (on the left)")))

    def _write_record(self):
        left = engine.scan(self.left, self.flt)
        right = engine.scan(self.right, self.flt)
        engine.Record.after(left, right, self.two_way_pair).write(self.left, self.right)

    def _clean_versions(self):
        """Versions older than "keep for" go (by the time stamp in their name, else the file's own time)."""
        limit = time.time() - self.settings.keep_days * 86400
        root = self.settings.versions
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            for n in filenames:
                p = os.path.join(dirpath, n)
                when = _stamp_of(n) or _stamp_of(os.path.relpath(dirpath, root).split(os.sep)[0])
                try:
                    if (when or os.path.getmtime(p)) < limit:
                        os.remove(p)
                except OSError:
                    pass
            for d in dirnames:
                try:
                    os.rmdir(os.path.join(dirpath, d))          # only empty ones
                except OSError:
                    pass


def _stamp_of(name: str) -> float | None:
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2} \d{6})", name)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1), STAMP))
    except ValueError:
        return None


def _writable(path: str):
    try:
        mode = os.stat(path).st_mode
        if not mode & 0o200:
            os.chmod(path, mode | 0o200)          # a read-only file (FreeFileSync overwrites those too)
    except OSError:
        pass
