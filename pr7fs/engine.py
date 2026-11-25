"""Comparing two folders (no Qt), the way FreeFileSync does: scan both sides through the filter, put every item in a
category, and give it an action from the sync variant.

- Filter: FreeFileSync's syntax. Patterns are separated by ";" or new lines; * and ? are wildcards; a pattern with a
  path separator is matched against the item's path relative to the folder, written with a leading "\\"
  ("\\.cache\\" = the folder .cache at the top, "*\\.git\\" = any .git folder); a pattern ending in "\\" means folders
  (and everything in them); a pattern without a separator also matches the bare name ("Thumbs.db", "*.tmp").
  Case-insensitive, as on Windows.
- Compare by: file time and size (2 s tolerance, FAT keeps even seconds), file content (byte for byte, when the sizes
  agree), or file size.
- Variants: Mirror, Update, Two way, Custom. Two way uses the last-sync record (.pr7fs.db in both folders, `Record`):
  an item missing on one side that the record lists was deleted there; one the record doesn't list is new; an item
  changed on both sides since the last sync is a conflict.

Paths inside the engine are relative, with "/" separators; `native()` turns them into the system's."""

from __future__ import annotations

import fnmatch
import json
import os
import stat
import uuid
from dataclasses import dataclass, field

TOLERANCE_NS = 2_000_000_000          # FreeFileSync's default: FAT file times are even seconds
RECORD = ".pr7fs.db"
TEMP_SUFFIX = ".pr7fs.tmp"
ALWAYS_OUT = (RECORD, "*" + TEMP_SUFFIX)

# categories
LEFT_ONLY, RIGHT_ONLY, LEFT_NEWER, RIGHT_NEWER, DIFFERENT, EQUAL, CONFLICT = (
    "left_only", "right_only", "left_newer", "right_newer", "different", "equal", "conflict")
CATEGORIES = [LEFT_ONLY, RIGHT_ONLY, LEFT_NEWER, RIGHT_NEWER, DIFFERENT, CONFLICT]
CATEGORY_TEXT = {LEFT_ONLY: "Item exists left only", RIGHT_ONLY: "Item exists right only",
                 LEFT_NEWER: "Left side is newer", RIGHT_NEWER: "Right side is newer",
                 DIFFERENT: "Items have different content", CONFLICT: "Conflict (can't tell which is newer)",
                 EQUAL: "Items are equal"}
# actions
TO_RIGHT, TO_LEFT, DELETE_LEFT, DELETE_RIGHT, NOTHING = "to_right", "to_left", "delete_left", "delete_right", "none"
ACTIONS = [TO_RIGHT, TO_LEFT, DELETE_LEFT, DELETE_RIGHT, NOTHING]

BY_TIME_SIZE, BY_CONTENT, BY_SIZE = "time_size", "content", "size"
COMPARE_TEXT = {BY_TIME_SIZE: "File time and size", BY_CONTENT: "File content", BY_SIZE: "File size"}
TWO_WAY, MIRROR, UPDATE, CUSTOM = "two_way", "mirror", "update", "custom"
VARIANT_TEXT = {TWO_WAY: "Two way  ⇄", MIRROR: "Mirror  →", UPDATE: "Update  →", CUSTOM: "Custom"}

MIRROR_ACTIONS = {LEFT_ONLY: TO_RIGHT, RIGHT_ONLY: DELETE_RIGHT, LEFT_NEWER: TO_RIGHT, RIGHT_NEWER: TO_RIGHT,
                  DIFFERENT: TO_RIGHT, CONFLICT: TO_RIGHT}
UPDATE_ACTIONS = {LEFT_ONLY: TO_RIGHT, RIGHT_ONLY: NOTHING, LEFT_NEWER: TO_RIGHT, RIGHT_NEWER: NOTHING,
                  DIFFERENT: TO_RIGHT, CONFLICT: NOTHING}


def native(rel: str) -> str:
    return rel.replace("/", os.sep)


# --------------------------------------------------------------------------- filter
def patterns(text: str) -> list[str]:
    return [p.strip() for p in text.replace("\r", "\n").replace(";", "\n").split("\n") if p.strip()]


@dataclass
class Filter:
    include: str = "*"
    exclude: str = ""

    def __post_init__(self):
        self._inc = [p.replace("/", "\\").casefold() for p in patterns(self.include)] or ["*"]
        self._exc = [p.replace("/", "\\").casefold() for p in patterns(self.exclude)] + list(ALWAYS_OUT)

    @staticmethod
    def _hit(pattern: str, path: str, name: str, is_dir: bool) -> bool:
        if pattern.endswith("\\"):                       # folders only
            return is_dir and fnmatch.fnmatchcase(path + "\\", pattern if pattern.startswith(("\\", "*")) else
                                                  "*\\" + pattern)
        if "\\" in pattern.strip("\\") or pattern.startswith("\\"):
            return fnmatch.fnmatchcase(path, pattern if pattern.startswith(("\\", "*")) else "*\\" + pattern)
        return fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(path, pattern)

    def excluded(self, rel: str, is_dir: bool) -> bool:
        """The item, or a folder it's in (a list filtered after the scan holds the contents of excluded folders)."""
        parts = rel.split("/")
        for i in range(1, len(parts) + 1):
            here = "/".join(parts[:i])
            folder = i < len(parts) or is_dir
            path = "\\" + here.replace("/", "\\").casefold()
            name = path.rsplit("\\", 1)[-1]
            if any(self._hit(p, path, name, folder) for p in self._exc if folder or i == len(parts)):
                if i == len(parts) or any(p.endswith("\\") and self._hit(p, path, name, True) for p in self._exc):
                    return True
        return False

    def included(self, rel: str, is_dir: bool) -> bool:
        """Folders are always walked (their contents may be included); files must match an include pattern."""
        if is_dir or self._inc == ["*"]:
            return True
        path = "\\" + rel.replace("/", "\\").casefold()
        name = path.rsplit("\\", 1)[-1]
        return any(self._hit(p, path, name, False) for p in self._inc)

    def keep(self, rel: str, is_dir: bool) -> bool:
        return self.included(rel, is_dir) and not self.excluded(rel, is_dir)


# --------------------------------------------------------------------------- scanning
@dataclass(frozen=True)
class Entry:
    size: int
    mtime: int          # nanoseconds
    is_dir: bool


class Cancelled(Exception):
    pass


def scan(base: str, flt: Filter | None = None, cancel=None, progress=None) -> dict[str, Entry]:
    """Every item under `base` the filter keeps (relative path -> Entry). Symbolic links and junctions are not
    followed (FreeFileSync's default skips them too); unreadable folders are left out."""
    flt = flt or Filter()
    out: dict[str, Entry] = {}
    stack = [""]
    while stack:
        if cancel is not None and cancel():
            raise Cancelled
        rel_dir = stack.pop()
        try:
            it = os.scandir(os.path.join(base, native(rel_dir)) if rel_dir else base)
        except OSError:
            continue
        with it:
            for e in it:
                rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
                try:
                    if e.is_symlink() or _is_junction(e):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                is_dir = stat.S_ISDIR(st.st_mode)
                if not flt.keep(rel, is_dir):
                    continue
                out[rel] = Entry(0 if is_dir else st.st_size, st.st_mtime_ns, is_dir)
                if is_dir:
                    stack.append(rel)
        if progress is not None:
            progress(len(out))
    return out


def _is_junction(e) -> bool:
    try:
        return bool(getattr(e, "is_junction", lambda: False)())
    except OSError:
        return False


# --------------------------------------------------------------------------- the last-sync record
@dataclass
class Record:
    """What both folders held after the last Two way sync: .pr7fs.db in each folder (hidden), with the pair's id so a
    record from another pairing is never trusted."""
    pair: str
    items: dict[str, tuple[int, int, bool]]

    @staticmethod
    def path(base: str) -> str:
        return os.path.join(base, RECORD)

    @staticmethod
    def read(base: str) -> "Record | None":
        try:
            with open(Record.path(base), encoding="utf-8") as f:
                data = json.load(f)
            return Record(data["pair"], {k: (v[0], v[1], bool(v[2])) for k, v in data["items"].items()})
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return None

    @staticmethod
    def load(left: str, right: str) -> "Record | None":
        a, b = Record.read(left), Record.read(right)
        if a is None or b is None or a.pair != b.pair:
            return None
        return a

    def write(self, left: str, right: str) -> None:
        data = json.dumps({"version": 1, "pair": self.pair,
                           "items": {k: [s, m, d] for k, (s, m, d) in sorted(self.items.items())}})
        for base in (left, right):
            path = Record.path(base)
            _unhide(path)
            tmp = path + TEMP_SUFFIX
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, path)
            _hide(path)

    def entry(self, rel: str) -> Entry | None:
        v = self.items.get(rel)
        return Entry(v[0], v[1], v[2]) if v else None

    @staticmethod
    def after(left: dict[str, Entry], right: dict[str, Entry], pair: str | None = None) -> "Record":
        """The record of two scans: every item both sides hold alike."""
        items = {}
        for rel, a in left.items():
            b = right.get(rel)
            if b is not None and same(a, b, BY_TIME_SIZE):
                items[rel] = (a.size, max(a.mtime, b.mtime), a.is_dir)
        return Record(pair or new_pair(), items)


def new_pair() -> str:
    """A fresh id for a pairing with no record yet: every pairing its own, so another pairing's record is never
    trusted."""
    return uuid.uuid4().hex


def _hide(path: str) -> None:
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)              # FILE_ATTRIBUTE_HIDDEN


def _unhide(path: str) -> None:
    if os.name == "nt" and os.path.exists(path):
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(path, 0x80)             # NORMAL: a hidden file can't be replaced


# --------------------------------------------------------------------------- comparing
def same(a: Entry, b: Entry, by: str) -> bool:
    if a.is_dir or b.is_dir:
        return a.is_dir == b.is_dir
    if by == BY_SIZE:
        return a.size == b.size
    return a.size == b.size and abs(a.mtime - b.mtime) <= TOLERANCE_NS


def same_content(p: str, q: str, chunk: int = 1 << 20) -> bool:
    with open(p, "rb") as f, open(q, "rb") as g:
        while True:
            x, y = f.read(chunk), g.read(chunk)
            if x != y:
                return False
            if not x:
                return True


@dataclass
class Item:
    rel: str
    left: Entry | None
    right: Entry | None
    category: str = EQUAL
    action: str = NOTHING
    note: str = ""              # why it's a conflict, a move ("moved from ..."), ...
    move_from: str = ""         # Two way's detected moves: the other side's old path to rename

    @property
    def is_dir(self) -> bool:
        e = self.left or self.right
        return bool(e and e.is_dir)

    @property
    def depth(self) -> int:
        return self.rel.count("/")

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    def bytes_to_copy(self) -> int:
        if self.action == TO_RIGHT and self.left and not self.left.is_dir:
            return self.left.size
        if self.action == TO_LEFT and self.right and not self.right.is_dir:
            return self.right.size
        return 0


def categorize(rel: str, a: Entry | None, b: Entry | None, by: str, left: str = "", right: str = "") -> Item:
    it = Item(rel, a, b)
    if a is None:
        it.category = RIGHT_ONLY
    elif b is None:
        it.category = LEFT_ONLY
    elif a.is_dir != b.is_dir:
        it.category, it.note = CONFLICT, "a folder on one side, a file on the other"
    elif a.is_dir:
        it.category = EQUAL
    elif by == BY_CONTENT:
        if a.size != b.size:
            it.category = DIFFERENT
        else:
            try:
                eq = same_content(os.path.join(left, native(rel)), os.path.join(right, native(rel)))
            except OSError as e:
                it.category, it.note = CONFLICT, f"couldn't be read ({e.strerror or e})"
                return it
            it.category = EQUAL if eq else DIFFERENT
    elif by == BY_SIZE:
        it.category = EQUAL if a.size == b.size else DIFFERENT
    elif same(a, b, BY_TIME_SIZE):
        it.category = EQUAL
    elif abs(a.mtime - b.mtime) <= TOLERANCE_NS:
        it.category, it.note = CONFLICT, "same time, different size"
    else:
        it.category = LEFT_NEWER if a.mtime > b.mtime else RIGHT_NEWER
    return it


def _order(rel: str):
    return [p.casefold() for p in rel.split("/")]


def compare(left: dict[str, Entry], right: dict[str, Entry], by: str = BY_TIME_SIZE, left_base: str = "",
            right_base: str = "") -> list[Item]:
    """Every item of both sides, in tree order (folders before their contents, names without case)."""
    rels = sorted(set(left) | set(right), key=_order)
    return [categorize(r, left.get(r), right.get(r), by, left_base, right_base) for r in rels]


# --------------------------------------------------------------------------- actions
def _changed(now: Entry | None, then: Entry | None) -> bool:
    if now is None or then is None:
        return (now is None) != (then is None)
    return not same(now, then, BY_TIME_SIZE)


def assign(items: list[Item], variant: str, custom: dict | None = None, record: Record | None = None,
           detect_moves: bool = False) -> list[Item]:
    """Give every item its action for the variant (Two way uses the record when there is one)."""
    if variant == TWO_WAY:
        _two_way(items, record, detect_moves)
    else:
        table = MIRROR_ACTIONS if variant == MIRROR else UPDATE_ACTIONS if variant == UPDATE else (custom or {})
        for it in items:
            it.action = NOTHING if it.category == EQUAL else table.get(it.category, NOTHING)
    _folders_follow(items)
    return items


def _two_way(items: list[Item], record: Record | None, detect_moves: bool) -> None:
    for it in items:
        it.note = it.note if it.category == CONFLICT else ""
        if it.category == EQUAL:
            it.action = NOTHING
            continue
        if record is None:              # no record yet: both ways, newer wins; can't tell deletions from new files
            it.action = {LEFT_ONLY: TO_RIGHT, RIGHT_ONLY: TO_LEFT, LEFT_NEWER: TO_RIGHT,
                         RIGHT_NEWER: TO_LEFT}.get(it.category, NOTHING)
            if it.category == DIFFERENT:
                it.category, it.note = CONFLICT, "different content, no last sync to compare with"
            continue
        then = record.entry(it.rel)
        lc, rc = _changed(it.left, then), _changed(it.right, then)
        if it.category == LEFT_ONLY:
            if then is None:
                it.action = TO_RIGHT                                       # new on the left
            elif lc:
                it.category, it.action, it.note = CONFLICT, NOTHING, "deleted on the right, changed on the left"
            else:
                it.action, it.note = DELETE_LEFT, "deleted on the right"
        elif it.category == RIGHT_ONLY:
            if then is None:
                it.action = TO_LEFT
            elif rc:
                it.category, it.action, it.note = CONFLICT, NOTHING, "deleted on the left, changed on the right"
            else:
                it.action, it.note = DELETE_RIGHT, "deleted on the left"
        elif it.category == CONFLICT and it.note:
            it.action = NOTHING
        elif lc and not rc:
            it.action = TO_RIGHT
        elif rc and not lc:
            it.action = TO_LEFT
        else:
            it.category, it.action = CONFLICT, NOTHING
            it.note = "changed on both sides since the last sync"
    if detect_moves and record is not None:
        _moves(items, record)


def _moves(items: list[Item], record: Record) -> None:
    """A file renamed or moved on one side since the last sync shows as "deleted there" + "new there" with the same
    size and time: rename it on the other side instead of copying it again and deleting the old one."""
    for side_new, side_del, new_act, del_act in ((LEFT_ONLY, LEFT_ONLY, TO_RIGHT, DELETE_RIGHT),
                                                 (RIGHT_ONLY, RIGHT_ONLY, TO_LEFT, DELETE_LEFT)):
        gone = {}
        for it in items:
            if it.action == del_act and not it.is_dir:
                e = it.right if del_act == DELETE_RIGHT else it.left
                if e is not None:
                    gone.setdefault((e.size, e.mtime // 1_000_000_000), it)
        for it in items:
            if it.action != new_act or it.is_dir:
                continue
            e = it.left if new_act == TO_RIGHT else it.right
            old = gone.pop((e.size, e.mtime // 1_000_000_000), None) if e else None
            if old is not None:
                it.move_from, it.note = old.rel, f"moved from {native(old.rel)}"
                old.action, old.note = NOTHING, f"moved to {native(it.rel)}"


def _folders_follow(items: list[Item]) -> None:
    """A folder that's deleted takes its contents with it; contents copied need their folder created."""
    by_rel = {it.rel: it for it in items}
    for it in items:
        if it.action in (TO_RIGHT, TO_LEFT):
            parent = it.rel.rsplit("/", 1)[0] if "/" in it.rel else ""
            while parent:
                p = by_rel.get(parent)
                if p is not None and p.action in (DELETE_LEFT, DELETE_RIGHT):
                    # a folder deleted on one side but with new contents copied into it: keep the folder
                    p.action, p.note = (TO_RIGHT if it.action == TO_RIGHT else TO_LEFT), "has new contents"
                parent = parent.rsplit("/", 1)[0] if "/" in parent else ""


def set_action(items: list[Item], target: Item, action: str) -> None:
    """The user's choice for one item (the middle column); a folder's contents follow it, as in FreeFileSync."""
    target.action = action
    if target.is_dir:
        prefix = target.rel + "/"
        for it in items:
            if it.rel.startswith(prefix) and it.category != EQUAL:
                it.action = action if _possible(it, action) else NOTHING


def _possible(it: Item, action: str) -> bool:
    return {TO_RIGHT: it.left is not None, TO_LEFT: it.right is not None, DELETE_LEFT: it.left is not None,
            DELETE_RIGHT: it.right is not None, NOTHING: True}[action]


def possible_actions(it: Item) -> list[str]:
    return [a for a in ACTIONS if _possible(it, a)]


# --------------------------------------------------------------------------- statistics
@dataclass
class Stats:
    create_right: int = 0
    update_right: int = 0
    delete_right: int = 0
    create_left: int = 0
    update_left: int = 0
    delete_left: int = 0
    bytes: int = 0
    conflicts: int = 0
    differences: int = 0
    equal: int = 0
    counts: dict = field(default_factory=dict)

    def nothing_to_do(self) -> bool:
        return not any((self.create_right, self.update_right, self.delete_right, self.create_left,
                        self.update_left, self.delete_left))


def stats(items: list[Item]) -> Stats:
    s = Stats()
    for it in items:
        s.counts[it.category] = s.counts.get(it.category, 0) + 1
        if it.category == EQUAL:
            s.equal += 1
            continue
        s.differences += 1
        if it.category == CONFLICT:
            s.conflicts += 1
        if it.action == TO_RIGHT:
            if it.right is None or it.move_from:
                s.create_right += 1
            else:
                s.update_right += 1
        elif it.action == TO_LEFT:
            if it.left is None or it.move_from:
                s.create_left += 1
            else:
                s.update_left += 1
        elif it.action == DELETE_RIGHT:
            s.delete_right += 1
        elif it.action == DELETE_LEFT:
            s.delete_left += 1
        if not it.move_from:
            s.bytes += it.bytes_to_copy()
    return s


def human(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.2f} {unit}"
        n /= 1000
    return ""
