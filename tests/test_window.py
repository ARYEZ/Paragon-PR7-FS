"""The window driven like a user; every sync is checked on disk."""
import json
import os

from conftest import put, tree
from pr7fs import app, config, engine
from pr7fs.engine import DELETE_RIGHT, NOTHING, TO_RIGHT


def names(w):
    return [it.rel for _, it in w.model.rows]


def test_compare_shows_the_differences(window, sides):
    w = window
    left, right, _ = sides
    put(left, "same.txt", "s", 0); put(right, "same.txt", "s", 0)
    put(left, "Footage/A001.mov", "film" * 100, 10)
    put(right, "old.txt", "bye")
    w.compare()
    assert names(w) == ["Footage", "Footage/A001.mov", "old.txt"]          # equal items hidden, as FreeFileSync
    assert "→  CREATE 2   UPDATE 0   DELETE 1" in w.stats_text.text() and "400 bytes" in w.stats_text.text().lower()
    w.view_keys["equal"].setChecked(True)
    assert "same.txt" in names(w)
    assert w.model.data(w.model.index(names(w).index("old.txt"), 3), 3).startswith("Item exists right only")
    assert w.keys["sync"].isEnabled()
    w.synchronize()
    assert tree(right) == tree(left)
    assert w.model.rows == [] or all(it.category == engine.EQUAL for _, it in w.model.rows)   # compared again


def test_changing_an_action_in_the_middle_column(window, sides):
    w = window
    left, right, _ = sides
    put(left, "keep_here.txt"); put(left, "copy_me.txt"); put(right, "dont_delete.txt")
    w.compare()
    row = names(w).index("keep_here.txt")
    w._clicked(w.model.index(row, 3))
    texts = [a.text() for a in w.last_menu.actions()]
    assert texts == ["Copy to the right  →", "Delete on the left", "Do nothing"]
    w.last_menu.actions()[2].trigger()
    w.table.selectRow(names(w).index("dont_delete.txt"))
    w.set_action(w.selected(), NOTHING)
    assert "→  CREATE 1   UPDATE 0   DELETE 0" in w.stats_text.text()
    w.synchronize()
    assert sorted(os.listdir(right)) == ["copy_me.txt", "dont_delete.txt"]


def test_exclude_via_filter(window, sides):
    w = window
    left, right, _ = sides
    put(left, "cache/x.bin"); put(left, "real.txt")
    w.compare()
    w.table.selectRow(names(w).index("cache"))
    w.exclude(w.selected())
    assert names(w) == ["real.txt"] and "\\cache\\" in w.cfg.exclude and "\\cache\\" in w.filter_text.text()
    w.synchronize()
    assert sorted(os.listdir(right)) == ["real.txt"]


def test_two_way_through_the_window(window, sides):
    w = window
    left, right, trash = sides
    put(left, "a.txt", "a"); put(right, "a.txt", "a")
    w.variant_box.setCurrentIndex(w.variant_box.findData(engine.TWO_WAY))
    w.compare()
    assert w.needs_record() and w.keys["sync"].isEnabled()                # nothing to copy, but no record yet
    asked = []
    w.answers["confirm"] = lambda t: asked.append(t) or True
    w.synchronize()
    assert "remembers" in asked[-1] and engine.Record.load(str(left), str(right)) is not None
    assert not w.needs_record()
    os.remove(left / "a.txt")
    put(right, "b.txt", "new on the right", 100)
    w.compare()
    acts = {it.rel: it.action for it in w.items()}
    assert acts == {"a.txt": DELETE_RIGHT, "b.txt": engine.TO_LEFT}
    w.synchronize()
    assert sorted(os.listdir(right)) == [".pr7fs.db", "b.txt"] and (left / "b.txt").exists()
    assert (trash / "a.txt").exists()


def test_settings_versioning_and_custom(window, sides, tmp_path):
    w = window
    left, right, _ = sides
    put(left, "doc.txt", "new", 100); put(right, "doc.txt", "old", 0)
    put(right, "extra.txt")

    def choose(d):
        d.deletion["versioning"].setChecked(True)
        d.versions.setText(str(tmp_path / "versions"))
        d.variants[engine.CUSTOM].setChecked(True)
        while d.custom.get(engine.RIGHT_ONLY) != NOTHING:               # cycle: right only -> do nothing
            d._cycle(engine.RIGHT_ONLY)
        assert d.action_keys[engine.RIGHT_ONLY].isEnabled()
        return True
    w.answers["settings"] = choose
    w.compare()
    w.settings_dialog(2)
    assert w.cfg.variant == engine.CUSTOM and w.variant_box.currentData() == engine.CUSTOM
    acts = {it.rel: it.action for it in w.items()}
    assert acts["extra.txt"] == NOTHING and acts["doc.txt"] == TO_RIGHT
    w.synchronize()
    versions = list((tmp_path / "versions").glob("doc *.txt"))
    assert len(versions) == 1 and versions[0].read_text() == "old" and (right / "extra.txt").exists()


def test_versioning_without_a_folder_is_refused(window, sides):
    w = window
    left, _, _ = sides
    put(left, "x.txt")
    w.cfg.deletion = "versioning"
    w.cfg.versions = ""
    w.compare()
    assert w.synchronize() is None and "versioning folder" in w.said[-1][1]


def test_errors_are_asked_and_reported(window, sides):
    w = window
    left, right, _ = sides
    put(left, "a.txt"); put(left, "b.txt")
    w.compare()
    os.remove(left / "a.txt")
    seen = []
    w.answers["error"] = lambda path, msg: seen.append(path) or "ignore"
    d = w.synchronize()
    assert seen == ["a.txt"] and (right / "b.txt").exists()
    assert d.result[0] == "COMPLETED WITH ERRORS" and os.path.exists(d.log_path)


def test_several_folder_pairs(window, sides, tmp_path):
    w = window
    left, right, _ = sides
    l2, r2 = tmp_path / "l2", tmp_path / "r2"
    l2.mkdir(); r2.mkdir()
    put(left, "one.txt"); put(l2, "two.txt")
    row = w.add_pair(str(l2), str(r2))
    w.compare()
    assert sorted(names(w)) == ["one.txt", "two.txt"]
    w.synchronize()
    assert (right / "one.txt").exists() and (r2 / "two.txt").exists()
    w.remove_pair(row)
    assert len(w.pair_rows) == 1


def test_settings_files_and_the_last_session(window, sides, tmp_path):
    w = window
    left, right, _ = sides
    w.cfg.exclude = "*.tmp"
    path = tmp_path / "Backup.pr7fs"
    w.answers["save_file"] = str(path)
    w.save_config(ask=True)
    data = json.loads(path.read_text())
    assert data["pairs"] == [[str(left), str(right)]] and data["exclude"] == "*.tmp" and data["variant"] == "mirror"
    w.new_config()
    assert w.pair_rows[0].left.text() == ""
    w.open_config(str(path))
    assert w.pair_rows[0].left.text() == str(left) and w.cfg.exclude == "*.tmp" and "Backup.pr7fs" in w.windowTitle()
    put(left, "x.txt")
    w.compare()                                            # a compare keeps the setup for the next start
    assert config.load_last().pairs == [[str(left), str(right)]]
    (tmp_path / "bad.pr7fs").write_text("not json")
    w.open_config(str(tmp_path / "bad.pr7fs"))
    assert "isn't a PR7-FS settings file" in w.said[-1][1]


def test_batch_runs_without_a_window(sides, tmp_path):
    left, right, trash = sides
    put(left, "a.txt", "a"); put(left, "sub/b.txt", "b"); put(right, "stale.txt")
    cfg = config.Config(pairs=[[str(left), str(right)]], variant=engine.MIRROR)
    path = tmp_path / "job.pr7fs"
    config.save(cfg, str(path))
    log = tmp_path / "log.txt"
    assert app.batch(str(path), str(log)) == 0
    assert tree(right) == tree(left) and (trash / "stale.txt").exists() and "→3" in log.read_text()   # sub, a.txt, sub/b.txt
    config.save(config.Config(pairs=[[str(left), str(tmp_path / "missing")]]), str(path))
    assert app.batch(str(path), str(log)) == 2


def test_when_finished_and_show_in_folder(window, sides):
    w = window
    left, right, _ = sides
    put(left, "a.txt")
    w.cfg.when_done = "shutdown"
    calls = []
    w.answers["system"] = calls.append
    w.compare()
    w.synchronize()
    assert calls and calls[0][0] in ("shutdown", "systemctl")
    launched = []
    w.answers["launch"] = lambda appname, args: launched.append((appname, args)) or True
    w.show_in_folder(str(right / "a.txt"))
    assert launched == [("PR7-E", [str(right)])]


def test_errors_before_comparing(window, sides, tmp_path):
    w = window
    left, _, _ = sides
    w.pair_rows[0].right.setText(str(tmp_path / "nowhere"))
    w.compare()
    assert "can't be found" in w.said[-1][1]
    w.pair_rows[0].right.setText(str(left))
    w.compare()
    assert "same folder" in w.said[-1][1]


def test_selftest(tmp_path):
    out = tmp_path / "st.json"
    assert app.selftest(str(out)) == 0
    assert json.loads(out.read_text())["ok"]


def test_version(capsys):
    from pr7fs import __version__
    assert app.main(["--version"]) == 0 and capsys.readouterr().out.strip() == __version__
