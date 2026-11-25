import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(tempfile.mkdtemp(prefix="family-"), "finish")  # never the real choice
os.environ["PR7FS_DATA"] = tempfile.mkdtemp(prefix="pr7fs-data-")     # never the real data folder
os.environ["PR7FS_TRASH"] = tempfile.mkdtemp(prefix="pr7fs-trash-")   # never the real Recycle Bin

T0 = int(time.time()) - 86400 * 3            # a fixed "earlier" for file times


def put(base: Path, rel: str, text: str = "x", age: int = 0) -> Path:
    """A real file with a chosen time: `age` seconds after T0."""
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode())
    t = (T0 + age) * 1_000_000_000
    os.utime(p, ns=(t, t))
    return p


def tree(base: Path) -> dict:
    """Every file under base -> its bytes (the record file left out)."""
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.name != ".pr7fs.db":
            out[p.relative_to(base).as_posix()] = p.read_bytes()
        elif p.is_dir():
            out[p.relative_to(base).as_posix() + "/"] = None
    return out


@pytest.fixture
def sides(tmp_path, monkeypatch):
    trash = tmp_path / "trash"
    monkeypatch.setenv("PR7FS_TRASH", str(trash))
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    return left, right, trash


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)           # never the real settings
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    from pr7fs import theme
    theme.load_fonts()
    yield app
    app.clipboard().clear()


@pytest.fixture
def window(qapp, sides):
    """The real window on two real folders (comparing and syncing inline)."""
    from pr7fs import config, engine
    from pr7fs.main_window import MainWindow
    left, right, _ = sides
    w = MainWindow(config.Config(pairs=[[str(left), str(right)]], variant=engine.MIRROR))
    w.sync_jobs = True
    w.answers.update({"say": lambda kind, text: None, "confirm": lambda t: True, "sync_dialog": True,
                      "menu": True})
    w.show()
    yield w
    w.close()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del w
    import gc
    gc.collect()          # on the main thread now (PR7-U's lesson)
