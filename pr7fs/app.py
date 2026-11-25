"""Start PR7-FS.

    PR7-FS.exe [SETTINGS.pr7fs]         the window (one per user: a later start hands its settings file over)
    PR7-FS.exe --batch SETTINGS.pr7fs   compare and synchronize with no window, as FreeFileSync's batch jobs (for
                                        Windows' Task Scheduler); errors are skipped and logged. Exit code 0 = done,
                                        1 = done with errors, 2 = failed
    PR7-FS.exe --version
    PR7-FS.exe --selftest OUT.json      make two real folders, compare, Mirror, then Two way twice (a deletion carried
                                        across by the record), and write what happened (CI runs the installed exe)
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys
import time

TIMEOUT_MS = 1500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "Paragon-PR7-FS-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def hand_over(paths: list[str]) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(server_name())
    if not s.waitForConnected(TIMEOUT_MS):
        return False
    s.write(json.dumps({"open": [os.path.abspath(p) for p in paths]}).encode() + b"\n")
    s.flush()
    s.waitForBytesWritten(TIMEOUT_MS)
    if not s.waitForDisconnected(TIMEOUT_MS):
        s.disconnectFromServer()
    return True


def listen(window):
    """Later starts bring this window to the front and open their settings file (PR7-R's hand-off, with its Windows
    fix: data already waiting when the connection is accepted is read at once)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()

        def read():
            buf.extend(bytes(sock.readAll()))
            if b"\n" not in buf:
                return
            try:
                msg = json.loads(buf.split(b"\n", 1)[0])
            except ValueError:
                msg = {}
            buf.clear()
            window.showNormal()
            window.raise_()
            window.activateWindow()
            paths = msg.get("open") or []
            if paths and paths[0].endswith(".pr7fs"):
                window.open_config(paths[0])
            sock.disconnectFromServer()
        sock.readyRead.connect(read)
        if sock.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def batch(path: str, log=None) -> int:
    """Compare and synchronize a saved setup without a window: errors are skipped (and logged), never asked."""
    from . import config, engine, sync
    cfg = config.load(path)
    flt = cfg.filter()
    st = cfg.sync_settings()
    st.ignore_errors = True
    lines, errors, failed = [f"PR7-FS batch  {path}  {time.strftime('%Y-%m-%d %H:%M:%S')}"], 0, False
    for a, b in cfg.real_pairs():
        if not (os.path.isdir(a) and os.path.isdir(b)):
            lines.append(f"FAILED  {a}  |  {b}: a folder can't be found")
            failed = True
            continue
        left, right = engine.scan(a, flt), engine.scan(b, flt)
        items = engine.compare(left, right, cfg.compare_by, a, b)
        record = engine.Record.load(a, b) if cfg.variant == engine.TWO_WAY else None
        engine.assign(items, cfg.variant, cfg.custom, record, cfg.detect_moves)
        pair = (record.pair if record else engine.new_pair()) if cfg.variant == engine.TWO_WAY else None
        s = sync.Sync(a, b, items, st, two_way_pair=pair, flt=flt)
        p = s.run()
        errors += len(p.errors)
        n = engine.stats(items)
        lines.append(f"{a}  |  {b}:  →{n.create_right + n.update_right} ←{n.create_left + n.update_left} "
                     f"×{n.delete_left + n.delete_right}  {engine.human(p.bytes_done)}  {len(p.errors)} errors")
        lines += ["  " + msg for _, _, msg in p.log]
    folder = os.path.join(config.data_dir(), "logs")
    os.makedirs(folder, exist_ok=True)
    out = log or os.path.join(folder, time.strftime("%Y-%m-%d %H%M%S") + " batch.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 2 if failed else (1 if errors else 0)


def selftest(out: str) -> int:
    import tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PR7FS_DATA"] = tempfile.mkdtemp()
    os.environ["PR7FS_TRASH"] = tempfile.mkdtemp()
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
    app = QApplication.instance() or QApplication(sys.argv[:1])
    result: dict = {}
    try:
        from . import __version__, config, engine, theme
        from .main_window import MainWindow
        theme.load_fonts()
        work = tempfile.mkdtemp(prefix="pr7fs-selftest-")
        left, right = os.path.join(work, "left"), os.path.join(work, "right")
        for rel, text in (("a.txt", "alpha"), ("sub/b.txt", "beta"), ("sub/deep/c.bin", "c" * 100000)):
            os.makedirs(os.path.dirname(os.path.join(left, rel)), exist_ok=True)
            with open(os.path.join(left, rel), "w") as f:
                f.write(text)
        os.makedirs(right)
        with open(os.path.join(right, "stale.txt"), "w") as f:
            f.write("old")
        cfg = config.Config(pairs=[[left, right]], variant=engine.MIRROR)
        w = MainWindow(cfg)
        w.sync_jobs = True
        w.answers.update({"say": lambda k, t: None, "confirm": lambda t: True, "sync_dialog": True})
        w.compare()
        before = engine.stats(w.items())
        w.synchronize()
        mirrored = sorted(os.path.relpath(os.path.join(d, n), right).replace(os.sep, "/")
                          for d, _, ns in os.walk(right) for n in ns)
        w.variant_box.setCurrentIndex(w.variant_box.findData(engine.TWO_WAY))
        w.compare()
        w.synchronize()                                       # writes the record
        os.remove(os.path.join(left, "a.txt"))
        w.compare()
        deletion = [it.action for it in w.items() if it.rel == "a.txt"]
        w.synchronize()
        result = {"version": __version__, "to_copy": before.create_right, "deleted_stale": before.delete_right,
                  "mirrored": mirrored, "record": engine.Record.load(left, right) is not None,
                  "two_way_deletion": deletion == [engine.DELETE_RIGHT] and
                  not os.path.exists(os.path.join(right, "a.txt")),
                  "fonts": "Inter" in QFontDatabase.families()}
        result["ok"] = mirrored == ["a.txt", "sub/b.txt", "sub/deep/c.bin"] and result["two_way_deletion"] \
            and result["record"]
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        import traceback
        result = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    app.clipboard().clear()
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or not argv[0].startswith("--"):
        return _window(argv)
    # a command-line mode (the installer, CI, Task Scheduler): an unexpected error must end the process with a code;
    # in the windowed exe it would otherwise open an error box that waits for a click nobody gives
    try:
        return _command(argv)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - reported, then a failing exit code
        import traceback
        if sys.stderr is not None:
            sys.stderr.write(traceback.format_exc())
        return 2


def _command(argv: list[str]) -> int:
    if argv[:1] == ["--version"]:
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--selftest"] and len(argv) == 2:
        return selftest(argv[1])
    if argv[:1] == ["--batch"] and len(argv) == 2:
        return batch(argv[1])
    print(__doc__)
    return 1


def _window(argv: list[str]) -> int:
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-FS")
    if hand_over(argv):
        return 0
    from . import finish
    theme.set_finish(finish.start(settings.get("finish", "obsidian")))
    theme.load_fonts()
    app.setPalette(theme.palette())
    from PySide6.QtGui import QIcon
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    w = MainWindow()
    from PySide6.QtCore import QTimer
    _follow = QTimer(w)                      # one finish for the family: follow another app's switch (finish.py)
    _follow.timeout.connect(lambda: finish.follow(theme.FINISH, w.set_finish))
    _follow.start(2000)
    listen(w)
    w.show()
    if argv and argv[0].endswith(".pr7fs"):
        QTimer.singleShot(0, lambda: w.open_config(argv[0]))
    from . import update_ui
    update_ui.start(w)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
