"""Compare and sync on real folders: every test checks what ends up on disk."""
import os

import pytest

from conftest import put, tree
from pr7fs import engine, sync
from pr7fs.engine import (CONFLICT, DELETE_LEFT, DELETE_RIGHT, DIFFERENT, EQUAL, LEFT_NEWER, LEFT_ONLY, MIRROR,
                          NOTHING, RIGHT_NEWER, RIGHT_ONLY, TO_LEFT, TO_RIGHT, TWO_WAY, UPDATE)


def run(left, right, variant, by=engine.BY_TIME_SIZE, settings=None, flt=None, detect_moves=False, ask=None):
    flt = flt or engine.Filter()
    a, b = engine.scan(str(left), flt), engine.scan(str(right), flt)
    items = engine.compare(a, b, by, str(left), str(right))
    record = engine.Record.load(str(left), str(right)) if variant == TWO_WAY else None
    engine.assign(items, variant, record=record, detect_moves=detect_moves)
    pair = (record.pair if record else engine.new_pair()) if variant == TWO_WAY else None
    s = sync.Sync(str(left), str(right), items, settings, ask=ask, two_way_pair=pair, flt=flt)
    s.run()
    return items, s


def acts(items):
    return {it.rel: (it.category, it.action) for it in items if it.category != EQUAL}


def test_filter_syntax():
    f = engine.Filter(exclude="*.tmp; \\.cache\\\n*\\.git\\;Thumbs.db")
    assert f.excluded("render.TMP", False) and f.excluded("a/b/c.tmp", False)
    assert f.excluded(".cache", True) and not f.excluded("sub/.cache", True)          # \ at the start: the top only
    assert f.excluded(".git", True) and f.excluded("x/y/.git", True)
    assert f.excluded("photos/thumbs.db", False) and not f.excluded("photos/thumbs.dbx", False)
    assert f.excluded(".pr7fs.db", False) and f.excluded("a/b.mov.pr7fs.tmp", False)   # ours, always out
    inc = engine.Filter(include="*.mov\n\\Docs\\*")
    assert inc.keep("x/clip.MOV", False) and inc.keep("Docs/notes.txt", False) and not inc.keep("x/notes.txt", False)
    assert inc.keep("anything", True)                                                 # folders are walked
    assert f.excluded(".cache/deep/file.txt", False) and not f.excluded("sub/.cache.txt", False)   # inside a folder


def test_scan_skips_what_it_should(sides):
    left, _, _ = sides
    put(left, "a.txt")
    put(left, "sub/b.txt")
    put(left, ".cache/c.txt")
    (left / ".pr7fs.db").write_text("{}")
    if hasattr(os, "symlink"):
        os.symlink(left / "sub", left / "link")
    got = engine.scan(str(left), engine.Filter(exclude="\\.cache\\"))
    assert set(got) == {"a.txt", "sub", "sub/b.txt"} and got["sub"].is_dir and got["a.txt"].size == 1


def test_categories_by_time_size_content_size(sides):
    left, right, _ = sides
    put(left, "same.txt", "abc", 0); put(right, "same.txt", "abc", 1)        # 1 s apart: equal (2 s tolerance)
    put(left, "newer_left.txt", "v2", 100); put(right, "newer_left.txt", "v1", 0)
    put(left, "newer_right.txt", "v1", 0); put(right, "newer_right.txt", "v22", 100)
    put(left, "sizes.txt", "aa", 0); put(right, "sizes.txt", "aaa", 0)        # same time, other size
    put(left, "only_left.txt"); put(right, "only_right.txt")
    put(left, "kind"); (right / "kind").mkdir()
    a, b = engine.scan(str(left)), engine.scan(str(right))
    c = {it.rel: it for it in engine.compare(a, b)}
    assert c["same.txt"].category == EQUAL and c["newer_left.txt"].category == LEFT_NEWER
    assert c["newer_right.txt"].category == RIGHT_NEWER and c["only_left.txt"].category == LEFT_ONLY
    assert c["only_right.txt"].category == RIGHT_ONLY
    assert c["sizes.txt"].category == CONFLICT and "same time" in c["sizes.txt"].note
    assert c["kind"].category == CONFLICT and "folder" in c["kind"].note
    put(left, "content.txt", "abcd", 0); put(right, "content.txt", "abce", 500)
    a, b = engine.scan(str(left)), engine.scan(str(right))
    by_content = {it.rel: it.category for it in engine.compare(a, b, engine.BY_CONTENT, str(left), str(right))}
    assert by_content["content.txt"] == DIFFERENT and by_content["same.txt"] == EQUAL
    assert by_content["newer_left.txt"] == DIFFERENT                          # "v2" and "v1": other bytes
    by_size = {it.rel: it.category for it in engine.compare(a, b, engine.BY_SIZE)}
    assert by_size["content.txt"] == EQUAL and by_size["sizes.txt"] == DIFFERENT


def test_mirror_makes_the_right_a_copy_and_bins_the_rest(sides):
    left, right, trash = sides
    put(left, "Footage/A001.mov", "film" * 1000, 50)
    put(left, "Projects/edit.drp", "v12", 100); put(right, "Projects/edit.drp", "v11", 0)
    put(right, "Projects/grade.drx", "newer on the right", 200); put(left, "Projects/grade.drx", "old", 0)
    put(right, "Music/stems.zip", "zip")
    items, s = run(left, right, MIRROR)
    assert tree(right) == tree(left) and s.done and not s.progress.errors
    assert (trash / "stems.zip").read_bytes() == b"zip" and (trash / "grade.drx").exists()   # deleted and overwritten
    assert os.path.getmtime(right / "Footage/A001.mov") == os.path.getmtime(left / "Footage/A001.mov")
    assert not any(p.name.endswith(".pr7fs.tmp") for p in right.rglob("*"))


def test_update_never_deletes(sides):
    left, right, _ = sides
    put(left, "new.txt"); put(right, "theirs.txt")
    put(left, "a.txt", "old", 0); put(right, "a.txt", "newer", 100)
    items, _ = run(left, right, UPDATE)
    assert (right / "new.txt").exists() and (right / "theirs.txt").exists()
    assert (right / "a.txt").read_text() == "newer" and not (left / "theirs.txt").exists()


def test_two_way_with_the_record(sides):
    left, right, trash = sides
    put(left, "both.txt", "same", 0); put(right, "both.txt", "same", 0)
    put(left, "l.txt", "from left", 10); put(right, "r.txt", "from right", 10)
    items, s = run(left, right, TWO_WAY)                          # first run: no record, both ways
    assert acts(items) == {"l.txt": (LEFT_ONLY, TO_RIGHT), "r.txt": (RIGHT_ONLY, TO_LEFT)}
    assert tree(left) == tree(right) and engine.Record.load(str(left), str(right)) is not None
    assert (left / ".pr7fs.db").exists() and (right / ".pr7fs.db").exists()
    # changes on both sides since that sync
    os.remove(left / "l.txt")                                     # deleted on the left
    put(right, "new_right.txt", "hello", 300)                     # new on the right
    put(left, "both.txt", "changed left", 400)                    # changed on the left only
    put(left, "r.txt", "left edit", 500); put(right, "r.txt", "right edit!", 600)   # changed on both: conflict
    items, s = run(left, right, TWO_WAY)
    assert acts(items) == {"l.txt": (RIGHT_ONLY, DELETE_RIGHT), "new_right.txt": (RIGHT_ONLY, TO_LEFT),
                           "both.txt": (LEFT_NEWER, TO_RIGHT), "r.txt": (CONFLICT, NOTHING)}
    assert not (right / "l.txt").exists() and (trash / "l.txt").exists()          # the deletion went across
    assert (left / "new_right.txt").read_text() == "hello" and (right / "both.txt").read_text() == "changed left"
    assert (left / "r.txt").read_text() == "left edit" and (right / "r.txt").read_text() == "right edit!"  # untouched
    # deleted on the right but changed on the left since: a conflict, nothing lost
    os.remove(right / "both.txt")
    put(left, "both.txt", "edited again", 700)
    items, _ = run(left, right, TWO_WAY)
    assert acts(items)["both.txt"] == (CONFLICT, NOTHING) and (left / "both.txt").exists()


def test_a_record_from_another_pairing_is_ignored(sides, tmp_path):
    left, right, _ = sides
    put(left, "a.txt"); put(right, "a.txt")
    run(left, right, TWO_WAY)
    other = tmp_path / "other"
    other.mkdir()
    put(other, "a.txt")
    run(left, other, TWO_WAY)                                     # left's record now belongs to (left, other)
    assert engine.Record.load(str(left), str(right)) is None
    os.remove(right / "a.txt")
    items, _ = run(left, right, TWO_WAY)                          # without a trusted record: copied back, not deleted
    assert acts(items)["a.txt"] == (LEFT_ONLY, TO_RIGHT) and (right / "a.txt").exists()


def test_detected_moves_are_renamed_not_copied(sides):
    left, right, _ = sides
    put(left, "old/clip.mov", "x" * 50000, 0); put(right, "old/clip.mov", "x" * 50000, 0)
    run(left, right, TWO_WAY)
    (left / "new").mkdir()
    os.replace(left / "old/clip.mov", left / "new/clip.mov")
    items, s = run(left, right, TWO_WAY, detect_moves=True)
    mv = next(it for it in items if it.rel == "new/clip.mov")
    assert mv.move_from == "old/clip.mov" and s.progress.bytes_total == 0
    assert (right / "new/clip.mov").exists() and not (right / "old/clip.mov").exists()
    assert engine.stats(items).create_right == 2 and engine.stats(items).bytes == 0   # the folder "new" + the move


def test_versioning_keeps_what_is_replaced_or_deleted(sides, tmp_path):
    left, right, _ = sides
    versions = tmp_path / "versions"
    put(left, "doc/notes.md", "new", 100); put(right, "doc/notes.md", "old", 0)
    put(right, "gone.txt", "bye")
    st = sync.Settings(deletion=sync.VERSIONING, versions=str(versions), naming=sync.STAMP_FILE)
    items, s = run(left, right, MIRROR, settings=st)
    kept = sorted(p.relative_to(versions).as_posix() for p in versions.rglob("*") if p.is_file())
    assert kept == [f"doc/notes {s.stamp}.md", f"gone {s.stamp}.txt"]
    assert (versions / f"doc/notes {s.stamp}.md").read_text() == "old" and (right / "doc/notes.md").read_text() == "new"
    put(left, "doc/notes.md", "newer", 200)
    st2 = sync.Settings(deletion=sync.VERSIONING, versions=str(tmp_path / "v2"), naming=sync.STAMP_FOLDER)
    _, s2 = run(left, right, MIRROR, settings=st2)
    assert (tmp_path / "v2" / s2.stamp / "doc" / "notes.md").read_text() == "new"
    put(left, "doc/notes.md", "newest", 300)
    st3 = sync.Settings(deletion=sync.VERSIONING, versions=str(tmp_path / "v3"), naming=sync.REPLACE)
    run(left, right, MIRROR, settings=st3)
    assert (tmp_path / "v3" / "doc" / "notes.md").read_text() == "newer"
    old = versions / "doc" / "notes 2020-01-01 120000.md"                 # an old version, past "keep for"
    old.write_text("ancient")
    put(left, "doc/notes.md", "again", 400)
    st4 = sync.Settings(deletion=sync.VERSIONING, versions=str(versions), naming=sync.STAMP_FILE, keep_days=30)
    run(left, right, MIRROR, settings=st4)
    assert not old.exists() and (versions / f"doc/notes {s.stamp}.md").exists()


def test_permanent_deletion(sides):
    left, right, trash = sides
    put(right, "x/y.txt")
    run(left, right, MIRROR, settings=sync.Settings(deletion=sync.PERMANENT))
    assert tree(right) == {} and not trash.exists()


def test_a_stopped_copy_leaves_nothing_half_written(sides):
    left, right, _ = sides
    big = left / "big.bin"
    big.write_bytes(os.urandom(8 << 20))
    put(right, "big.bin", "the old one", 0)
    a, b = engine.scan(str(left)), engine.scan(str(right))
    items = engine.assign(engine.compare(a, b), MIRROR)
    holder = {}

    def report(p):
        if p.bytes_done > 0:
            holder["s"].stop()
    s = sync.Sync(str(left), str(right), items, report=report)
    holder["s"] = s
    s.report_every = 0
    s.run()
    assert not s.done and (right / "big.bin").read_text() == "the old one"
    assert not (right / "big.bin.pr7fs.tmp").exists()


def test_errors_are_asked_retried_or_ignored(sides):
    left, right, _ = sides
    put(left, "a.txt", "a"); put(left, "b.txt", "b")
    a, b = engine.scan(str(left)), engine.scan(str(right))
    items = engine.assign(engine.compare(a, b), MIRROR)
    os.remove(left / "a.txt")                        # gone after the compare: copying it fails
    asked = []

    def ask(path, msg):
        asked.append(path)
        if len(asked) == 1:
            put(left, "a.txt", "back again")         # fixed before Retry
            return "retry"
        return "ignore"
    s = sync.Sync(str(left), str(right), items, ask=ask)
    s.run()
    assert asked == ["a.txt"] and (right / "a.txt").read_text() == "back again" and not s.progress.errors
    os.remove(left / "b.txt")
    put(left, "c.txt")
    items = engine.assign(engine.compare(engine.scan(str(left)), engine.scan(str(right))), MIRROR)
    os.remove(left / "c.txt")
    s = sync.Sync(str(left), str(right), items, ask=lambda p, m: "ignore")
    s.run()
    assert [e[0] for e in s.progress.errors] == ["c.txt"] and not (right / "b.txt").exists()   # the rest still done


def test_folders_follow_and_stats(sides):
    left, right, _ = sides
    put(left, "dir/a.txt", "aa"); put(left, "dir/sub/b.txt", "bbb")
    items = engine.compare(engine.scan(str(left)), engine.scan(str(right)))
    engine.assign(items, MIRROR)
    s = engine.stats(items)
    assert (s.create_right, s.bytes, s.differences) == (4, 5, 4)
    d = next(it for it in items if it.rel == "dir")
    engine.set_action(items, d, NOTHING)
    assert all(it.action == NOTHING for it in items)
    engine.set_action(items, d, TO_RIGHT)
    assert all(it.action == TO_RIGHT for it in items)
    assert engine.possible_actions(d) == [TO_RIGHT, DELETE_LEFT, NOTHING]
    assert engine.human(7_540_000_000) == "7.54 GB"


@pytest.mark.parametrize("variant", [MIRROR, TWO_WAY])
def test_a_type_conflict_can_be_settled(sides, variant):
    left, right, _ = sides
    put(left, "thing", "a file")
    (right / "thing").mkdir()
    put(right, "thing/inner.txt")
    items = engine.compare(engine.scan(str(left)), engine.scan(str(right)))
    engine.assign(items, variant)
    t = next(it for it in items if it.rel == "thing")
    assert t.category == CONFLICT
    engine.set_action(items, t, TO_RIGHT)
    for it in items:
        if it.rel == "thing/inner.txt":
            it.action = DELETE_RIGHT
    sync.Sync(str(left), str(right), items).run()
    assert (right / "thing").is_file() and (right / "thing").read_text() == "a file"
