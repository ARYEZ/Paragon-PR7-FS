"""Screenshots of the real PR7-FS window on generated folders (nothing of the user's):
QT_SCALE_FACTOR=2 python tools/screenshots.py OUT_DIR

compare.png (after Compare, OBSIDIAN), settings.png (Synchronization settings, AURORA), sync.png (a sync running)."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PR7FS_DATA"] = tempfile.mkdtemp()
os.environ["PR7FS_TRASH"] = tempfile.mkdtemp()
_family = Path(tempfile.mkdtemp()) / "finish"
_family.write_text("obsidian")
os.environ["PARAGON_FAMILY_FILE"] = str(_family)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())

from pr7fs import config, engine, theme  # noqa: E402
from pr7fs.main_window import MainWindow  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
root = Path(tempfile.mkdtemp())
left, right = root / "Studio" / "ELSEWORLD", root / "Backup" / "ELSEWORLD"
T = int(time.time()) - 86400


def put(base, rel, size, age):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        f.truncate(size)
    os.utime(p, (T + age, T + age))


for rel, size, age in (("Footage/A001_C0006.mov", 342_000_000, 0), ("Footage/A001_C0007.mov", 297_000_000, 60),
                       ("Footage/B002_C0001.mov", 118_000_000, 0), ("Projects/ELSEWORLD_edit_v12.drp", 48_100_000, 900),
                       ("Projects/ELSEWORLD_grade.drx", 2_400_000, 0), ("Projects/credits.txt", 4_000, 500),
                       ("old_render.mp4", 102_000_000, 0), ("notes_for_mix.md", 2_000, 800)):
    put(left, rel, size, age)
for rel, size, age in (("Footage/B002_C0001.mov", 118_000_000, 0), ("Projects/ELSEWORLD_edit_v12.drp", 47_600_000, 0),
                       ("Projects/ELSEWORLD_grade.drx", 2_600_000, 700), ("Projects/credits.txt", 5_000, 501),
                       ("Music/Last Light (stems).zip", 61_200_000, 0), ("notes_for_mix.md", 2_000, 0)):
    put(right, rel, size, age)


def spin(s):
    end = time.time() + s
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


w = MainWindow(config.Config(pairs=[[str(left), str(right)]], variant=engine.TWO_WAY))
w.sync_jobs = True
w.answers.update({"say": lambda k, t: None, "confirm": lambda t: True})
w.resize(1280, 760)
w.show()
w.compare()
w.view_keys["equal"].setChecked(True)
w.table.selectRow(next(i for i, (_, it) in enumerate(w.model.rows) if it.rel == "Projects/credits.txt"))
spin(0.3)
w.grab().save(str(out / "compare.png"))

from pr7fs.dialogs import SettingsDialog  # noqa: E402
w.set_finish("aurora")
d = SettingsDialog(w, w.cfg, 2)
d.resize(1000, 620)
d.show()
spin(0.3)
d.grab().save(str(out / "settings.png"))
d.close()
w.set_finish("obsidian")

w.sync_jobs = False
w.variant_box.setCurrentIndex(w.variant_box.findData(engine.MIRROR))
dlg = w.synchronize()
end = time.time() + 30
while dlg.running() and sum(s.progress.bytes_done for s in dlg.runs) < 300_000_000 and time.time() < end:
    spin(0.05)
if dlg.current is not None:
    dlg.toggle_pause()
spin(0.6)
dlg.resize(1000, 680)
dlg.grab().save(str(out / "sync.png"))
dlg.stop()
spin(0.5)
w.close()
print("ok", out)
