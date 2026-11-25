"""PR7-FS's dialogs: Settings (Comparison, Filter, Synchronization) and the Synchronize window."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections import deque

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import config, engine, sync, theme, widgets
from .engine import (CATEGORIES, CATEGORY_TEXT, DELETE_LEFT, DELETE_RIGHT, NOTHING, TO_LEFT, TO_RIGHT, native)

VARIANT_HELP = {engine.TWO_WAY: "Changes on either side go to the other, deletions included.",
                engine.MIRROR: "The right side becomes a copy of the left: files only on the right are deleted.",
                engine.UPDATE: "New and newer files go from left to right; nothing is deleted.",
                engine.CUSTOM: "Choose the action for each kind of difference."}
WHEN_DONE = [("nothing", "Do nothing"), ("sleep", "Sleep"), ("shutdown", "Shut down"), ("close", "Close PR7-FS")]


def field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def _glyph_kind(action: str) -> str:
    return {TO_RIGHT: "right", TO_LEFT: "left", DELETE_LEFT: "del_left", DELETE_RIGHT: "del_right"}.get(action, "none")


# --------------------------------------------------------------------------- Settings
class SettingsDialog(QDialog):
    def __init__(self, win, cfg: config.Config, tab: int = 2):
        super().__init__(win)
        from .main_window import ACTION_TEXT, glyph
        self._glyph, self._text = glyph, ACTION_TEXT
        self.setWindowTitle("Settings · PR7-FS")
        self.resize(1000, 640)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # ---- comparison
        page = QWidget()
        g = QGridLayout(page)
        g.setContentsMargins(18, 16, 18, 16)
        g.addWidget(field("Compare by"), 0, 0)
        self.by_group = QButtonGroup(self)
        self.by = {}
        helps = {engine.BY_TIME_SIZE: "Files are equal when their size and modified time agree (within 2 seconds). "
                                      "Fast; the newer one wins.",
                 engine.BY_CONTENT: "Files with the same size are read byte for byte. Slow, but certain.",
                 engine.BY_SIZE: "Files are equal when their size agrees."}
        for i, (k, text) in enumerate(engine.COMPARE_TEXT.items()):
            b = QRadioButton(text)
            b.setStyleSheet("font-weight: 600;")
            self.by_group.addButton(b)
            self.by[k] = b
            b.setChecked(cfg.compare_by == k)
            g.addWidget(b, 1 + i * 2, 0)
            d = dim(helps[k])
            d.setContentsMargins(30, 0, 0, 8)
            g.addWidget(d, 2 + i * 2, 0)
        g.setRowStretch(8, 1)
        self.tabs.addTab(page, "COMPARISON")

        # ---- filter
        page = QWidget()
        g = QGridLayout(page)
        g.setContentsMargins(18, 16, 18, 16)
        g.addWidget(field("Include"), 0, 0)
        self.include = QPlainTextEdit(cfg.include)
        g.addWidget(self.include, 1, 0)
        g.addWidget(field("Exclude"), 0, 1)
        self.exclude = QPlainTextEdit(cfg.exclude)
        g.addWidget(self.exclude, 1, 1)
        help_ = dim("One pattern a line (or separated by ;). * and ? are wildcards. \\Folder\\ is a folder at the top "
                    "of each side, *\\Folder\\ any folder with that name, *.tmp any file ending .tmp. "
                    "Patterns are matched without case.")
        help_.setWordWrap(True)
        g.addWidget(help_, 2, 0, 1, 2)
        reset = QPushButton("Defaults")
        reset.clicked.connect(lambda: (self.include.setPlainText(config.Config().include),
                                       self.exclude.setPlainText(config.Config().exclude)))
        g.addWidget(reset, 3, 1, Qt.AlignmentFlag.AlignRight)
        self.tabs.addTab(page, "FILTER")

        # ---- synchronization
        page = QWidget()
        g = QGridLayout(page)
        g.setContentsMargins(18, 16, 18, 16)
        g.setHorizontalSpacing(24)
        g.setVerticalSpacing(8)
        g.addWidget(field("Variant"), 0, 0)
        self.variant_group = QButtonGroup(self)
        self.variants = {}
        for i, (k, text) in enumerate(engine.VARIANT_TEXT.items()):
            b = QRadioButton(text)
            b.setStyleSheet("font-weight: 600;")
            self.variant_group.addButton(b)
            self.variants[k] = b
            b.setChecked(cfg.variant == k)
            b.toggled.connect(self._variant)
            g.addWidget(b, 1 + i * 2, 0)
            d = dim(VARIANT_HELP[k])
            d.setWordWrap(True)
            d.setMaximumWidth(380)
            d.setContentsMargins(30, 0, 0, 8)
            g.addWidget(d, 2 + i * 2, 0)
        self.moves = QCheckBox("Detect moved files")
        self.moves.setChecked(cfg.detect_moves)
        self.moves.setToolTip("Two way: a file renamed or moved on one side is renamed on the other, not copied again")
        g.addWidget(self.moves, 9, 0)
        g.addWidget(field("What happens to each difference"), 0, 1, 1, 2)
        self.custom = dict(cfg.custom)
        self.action_keys = {}
        for i, cat in enumerate(CATEGORIES):
            g.addWidget(QLabel(CATEGORY_TEXT[cat]), 1 + i, 1)
            b = QPushButton()
            b.setIconSize(QSize(22, 22))
            b.setFixedSize(52, 30)
            b.clicked.connect(lambda _=False, c=cat: self._cycle(c))
            self.action_keys[cat] = b
            g.addWidget(b, 1 + i, 2)
        g.addWidget(field("Deleted and overwritten files"), 8, 1, 1, 2)
        row = QHBoxLayout()
        row.setSpacing(24)
        self.del_group = QButtonGroup(self)
        self.deletion = {}
        for k, text in ((sync.RECYCLE, "Recycle Bin"), (sync.PERMANENT, "Permanent"), (sync.VERSIONING, "Versioning")):
            b = QRadioButton(text)
            self.del_group.addButton(b)
            self.deletion[k] = b
            b.setChecked(cfg.deletion == k)
            b.toggled.connect(self._enable)
            row.addWidget(b)
        row.addStretch(1)
        g.addLayout(row, 9, 1, 1, 2)
        vrow = QHBoxLayout()
        self.versions = QLineEdit(cfg.versions)
        self.versions.setPlaceholderText("the versioning folder")
        vrow.addWidget(self.versions, 1)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(lambda: self.versions.setText(win._ask("folder", self.versions.text())
                                                                  or self.versions.text()))
        vrow.addWidget(self.browse)
        g.addLayout(vrow, 10, 1, 1, 2)
        nrow = QHBoxLayout()
        nrow.addWidget(dim("Naming"))
        self.naming = QComboBox()
        for k, v in sync.NAMING_TEXT.items():
            self.naming.addItem(v, k)
        self.naming.setCurrentIndex(max(0, self.naming.findData(cfg.naming)))
        nrow.addWidget(self.naming)
        nrow.addSpacing(12)
        nrow.addWidget(dim("Keep for"))
        self.keep = QComboBox()
        for days, text in ((0, "Forever"), (7, "7 days"), (30, "30 days"), (90, "90 days"), (365, "A year")):
            self.keep.addItem(text, days)
        self.keep.setCurrentIndex(max(0, self.keep.findData(cfg.keep_days)))
        nrow.addWidget(self.keep)
        nrow.addStretch(1)
        g.addLayout(nrow, 11, 1, 1, 2)
        g.addWidget(field("On errors"), 12, 1, 1, 2)
        erow = QHBoxLayout()
        erow.setSpacing(24)
        self.err_group = QButtonGroup(self)
        self.show_errors = QRadioButton("Show a message")
        self.ignore_errors = QRadioButton("Ignore and continue")
        for b in (self.show_errors, self.ignore_errors):
            self.err_group.addButton(b)
            erow.addWidget(b)
        (self.ignore_errors if cfg.ignore_errors else self.show_errors).setChecked(True)
        erow.addStretch(1)
        g.addLayout(erow, 13, 1, 1, 2)
        g.setRowStretch(14, 1)
        g.setColumnStretch(1, 1)
        self.tabs.addTab(page, "SYNCHRONIZATION")
        self.tabs.setCurrentIndex(tab)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._variant()

    def variant(self) -> str:
        return next(k for k, b in self.variants.items() if b.isChecked())

    def table(self) -> dict:
        v = self.variant()
        if v == engine.MIRROR:
            return dict(engine.MIRROR_ACTIONS)
        if v == engine.UPDATE:
            return dict(engine.UPDATE_ACTIONS)
        if v == engine.TWO_WAY:
            return {engine.LEFT_ONLY: TO_RIGHT, engine.RIGHT_ONLY: TO_LEFT, engine.LEFT_NEWER: TO_RIGHT,
                    engine.RIGHT_NEWER: TO_LEFT, engine.DIFFERENT: NOTHING, engine.CONFLICT: NOTHING}
        return self.custom

    def _variant(self, *_):
        custom = self.variant() == engine.CUSTOM
        t = self.table()
        for cat, b in self.action_keys.items():
            a = t.get(cat, NOTHING)
            b.setIcon(self._glyph(_glyph_kind(a), 22))
            b.setToolTip(self._text[a] + ("" if custom else "  (choose Custom to change it)"))
            b.setEnabled(custom)
        self.moves.setEnabled(self.variant() == engine.TWO_WAY)
        self._enable()

    def _cycle(self, cat: str):
        """Custom: each click moves to the next action that fits the difference (FreeFileSync's buttons)."""
        options = {engine.LEFT_ONLY: [TO_RIGHT, DELETE_LEFT, NOTHING],
                   engine.RIGHT_ONLY: [TO_LEFT, DELETE_RIGHT, NOTHING]}.get(cat, [TO_RIGHT, TO_LEFT, NOTHING])
        cur = self.custom.get(cat, NOTHING)
        self.custom[cat] = options[(options.index(cur) + 1) % len(options)] if cur in options else options[0]
        self._variant()

    def _enable(self, *_):
        on = self.deletion[sync.VERSIONING].isChecked()
        for w in (self.versions, self.browse, self.naming, self.keep):
            w.setEnabled(on)

    def apply(self, cfg: config.Config):
        cfg.compare_by = next(k for k, b in self.by.items() if b.isChecked())
        cfg.include = self.include.toPlainText().strip() or "*"
        cfg.exclude = self.exclude.toPlainText().strip()
        cfg.variant = self.variant()
        cfg.custom = dict(self.custom)
        cfg.detect_moves = self.moves.isChecked()
        cfg.deletion = next(k for k, b in self.deletion.items() if b.isChecked())
        cfg.versions = self.versions.text().strip()
        cfg.naming = self.naming.currentData()
        cfg.keep_days = int(self.keep.currentData())
        cfg.ignore_errors = self.ignore_errors.isChecked()


# --------------------------------------------------------------------------- Synchronize
class SpeedGraph(QWidget):
    def __init__(self):
        super().__init__()
        self.samples: deque = deque(maxlen=240)
        self.setMinimumHeight(130)

    def add(self, v: float):
        self.samples.append(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.fillRect(r, QColor(theme.WIDGET))
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        for i in range(1, 4):
            y = r.top() + r.height() * i / 4
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        if len(self.samples) < 2:
            return
        top = max(max(self.samples), 1.0) * 1.15
        n = self.samples.maxlen
        pts = [QPointF(r.left() + r.width() * i / n, r.bottom() - r.height() * v / top)
               for i, v in enumerate(self.samples)]
        area = QPainterPath(QPointF(pts[0].x(), r.bottom()))
        for q in pts:
            area.lineTo(q)
        area.lineTo(pts[-1].x(), r.bottom())
        p.fillPath(area, theme.family_gradient(r.left(), 0, r.right(), 0, theme.LIT, .28))
        line = QPainterPath(pts[0])
        for q in pts[1:]:
            line.lineTo(q)
        p.setPen(QPen(theme.family_gradient(r.left(), 0, r.right(), 0), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)       # no brush: an open path's chord would be filled (PR7-SM's lesson)
        p.drawPath(line)
        p.setPen(QColor(theme.TEXT_DIM))
        f = QFont("Inter", 1)
        f.setPixelSize(10)
        p.setFont(f)
        if max(self.samples) > 0:                       # a scale only once there's a speed to show
            p.drawText(QRectF(r.left() + 6, r.top() + 4, 200, 14), Qt.AlignmentFlag.AlignLeft,
                       engine.human(top / 1.15) + "/s")


class _Relay(QObject):
    progress = Signal(object)
    question = Signal(str, str)
    finished = Signal()


class SyncDialog(QDialog):
    """Runs the sync of every pair on a worker thread; an error waits for Retry / Ignore / Ignore all / Cancel (unless
    the settings ignore errors)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Synchronizing · PR7-FS")
        self.resize(1000, 680)
        self.setObjectName("syncdlg")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = widgets.Header("SYNCHRONIZING")
        lay.addWidget(self.header)
        body = QVBoxLayout()
        body.setContentsMargins(20, 14, 20, 16)
        body.setSpacing(10)
        self.now = QLabel("Starting…")
        self.now.setStyleSheet("font-weight: 600;")
        body.addWidget(self.now)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        body.addWidget(self.bar)
        g = QGridLayout()
        g.setHorizontalSpacing(30)
        self.values = {}
        for i, k in enumerate(("Items", "Data", "Speed", "Elapsed", "Remaining", "Errors")):
            g.addWidget(field(k), 0, i)
            v = QLabel("–")
            v.setStyleSheet("font-size: 14px; font-weight: 600;")
            g.addWidget(v, 1, i)
            self.values[k] = v
        body.addLayout(g)
        self.graph = SpeedGraph()
        body.addWidget(self.graph, 1)
        self.log = QTableWidget(0, 3)
        self.log.setHorizontalHeaderLabels(["TIME", "", "WHAT"])
        self.log.verticalHeader().setVisible(False)
        self.log.setShowGrid(False)
        self.log.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.log.setFixedHeight(170)
        body.addWidget(self.log)
        keys = QHBoxLayout()
        keys.addWidget(field("When finished"))
        self.when = QComboBox()
        for k, v in WHEN_DONE:
            self.when.addItem(v, k)
        self.when.setCurrentIndex(max(0, self.when.findData(win.cfg.when_done)))
        keys.addWidget(self.when)
        keys.addStretch(1)
        self.pause_key = widgets.KeyButton("pause", "Pause")
        self.stop_key = widgets.KeyButton("stop", "Stop")
        self.close_key = widgets.KeyButton("close", "Close")
        for k in (self.pause_key, self.stop_key, self.close_key):
            k.setFixedSize(QSize(92, 62))
            keys.addWidget(k)
        self.close_key.hide()
        body.addLayout(keys)
        lay.addLayout(body, 1)
        self.relay = _Relay()
        self.relay.progress.connect(self._progress)
        self.relay.question.connect(self._question)
        self.relay.finished.connect(self._finished)
        self.pause_key.clicked.connect(self.toggle_pause)
        self.stop_key.clicked.connect(self.stop)
        self.close_key.clicked.connect(self.accept)
        self.current: sync.Sync | None = None
        self.runs: list[sync.Sync] = []
        self.thread: threading.Thread | None = None
        self._answer = None
        self._answered = threading.Event()
        self._stopped = False
        self._logged = 0
        self.restyle()

    def restyle(self):
        self.setStyleSheet(f"QDialog#syncdlg {{ background: {theme.BACKGROUND}; }}")
        self.header.update()

    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        win = self.win
        cfg = win.cfg
        flt = cfg.filter()
        jobs = []
        for i, (a, b) in enumerate(win.compared_pairs):
            items = [it for it in win.items(i)]
            pair = None
            if cfg.variant == engine.TWO_WAY:
                rec = win.records.get(i)
                pair = rec.pair if rec else engine.new_pair()
            jobs.append(sync.Sync(a, b, items, cfg.sync_settings(), ask=self._ask_from_worker,
                                  report=self.relay.progress.emit, two_way_pair=pair, flt=flt))
        self.runs = jobs
        self.started = time.time()

        def work():
            for s in jobs:
                if self._stopped:
                    break
                self.current = s
                s.run()
                if not s.done:
                    break
            self.relay.finished.emit()
        if win.sync_jobs:
            work()
        else:
            self.thread = threading.Thread(target=work, daemon=True)
            self.thread.start()
            if "sync_dialog" not in win.answers:
                self.show()

    def _ask_from_worker(self, path: str, message: str) -> str:
        if "error" in self.win.answers:
            return self.win.answers["error"](path, message)
        self._answered.clear()
        self.relay.question.emit(path, message)
        self._answered.wait()
        return self._answer

    def _question(self, path: str, message: str):
        box = QMessageBox(QMessageBox.Icon.Warning, "PR7-FS", f"{path}\n\n{message}", parent=self)
        retry = box.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        ignore = box.addButton("Ignore", QMessageBox.ButtonRole.ActionRole)
        ignore_all = box.addButton("Ignore All", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        c = box.clickedButton()
        self._answer = "retry" if c is retry else "ignore" if c is ignore else "ignore_all" if c is ignore_all \
            else "cancel"
        self._answered.set()

    def totals(self):
        items = sum(s.progress.items_total for s in self.runs)
        done = sum(s.progress.items_done for s in self.runs)
        b_total = sum(s.progress.bytes_total for s in self.runs)
        b_done = sum(s.progress.bytes_done for s in self.runs)
        errors = [e for s in self.runs for e in s.progress.errors]
        return items, done, b_total, b_done, errors

    def _progress(self, p: sync.Progress):
        items, done, b_total, b_done, errors = self.totals()
        frac = (b_done / b_total) if b_total else (done / items if items else 1.0)
        self.bar.setValue(int(min(1.0, frac) * 1000))
        self.now.setText(p.current or "…")
        elapsed = time.time() - self.started
        speed = b_done / elapsed if elapsed > 0.5 else 0.0
        self.values["Items"].setText(f"{done} of {items}")
        self.values["Data"].setText(f"{engine.human(b_done)} of {engine.human(b_total)}")
        self.values["Speed"].setText(engine.human(speed) + "/s" if speed else "–")
        self.values["Elapsed"].setText(_hms(elapsed))
        self.values["Remaining"].setText(_hms((b_total - b_done) / speed) if speed and b_total > b_done else "–")
        self.values["Errors"].setText(str(len(errors)))
        self.graph.add(speed)
        logs = [x for s in self.runs for x in s.progress.log]
        from .main_window import glyph
        for t, kind, text in logs[self._logged:]:
            r = self.log.rowCount()
            self.log.insertRow(r)
            self.log.setItem(r, 0, QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(t))))
            g = QTableWidgetItem()
            g.setIcon(glyph({"to_right": "right", "move_right": "right", "to_left": "left", "move_left": "left",
                             "delete_right": "del_right", "delete_left": "del_left", "error": "conflict"}.get(
                kind, "none")))
            self.log.setItem(r, 1, g)
            self.log.setItem(r, 2, QTableWidgetItem(text))
        self._logged = len(logs)
        self.log.scrollToBottom()

    def toggle_pause(self):
        s = self.current
        if s is None:
            return
        if s.paused:
            s.resume()
            self.pause_key.label, self.pause_key.icon_name = "PAUSE", "pause"
            self.header.subtitle = "SYNCHRONIZING"
        else:
            s.pause()
            self.pause_key.label, self.pause_key.icon_name = "RESUME", "play"
            self.header.subtitle = "PAUSED"
        self.pause_key.update()
        self.header.update()

    def stop(self):
        self._stopped = True
        if self.current is not None:
            self.current.stop()
        self._answer = "cancel"
        self._answered.set()

    def _finished(self):
        self._progress(self.current.progress if self.current else sync.Progress())
        items, done, b_total, b_done, errors = self.totals()
        ok = all(s.done for s in self.runs) and not self._stopped
        elapsed = time.time() - self.started
        if not ok:
            title, text = "STOPPED", f"Stopped after {done} of {items} items."
        elif errors:
            title, text = "COMPLETED WITH ERRORS", f"{done} items, {len(errors)} error{'s' if len(errors) != 1 else ''}."
        else:
            title, text = "COMPLETED", f"{done} items, {engine.human(b_done)} in {_hms(elapsed)}."
        self.header.subtitle = title
        self.header.update()
        self.now.setText(text)
        self.result = (title, text, errors)
        self.pause_key.hide()
        self.stop_key.hide()
        self.close_key.show()
        self._write_log(title, text)
        self.win.synced()
        if ok:
            self.when_done(self.when.currentData())

    def _write_log(self, title, text):
        folder = os.path.join(config.data_dir(), "logs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("%Y-%m-%d %H%M%S") + " sync.txt")
        lines = [f"PR7-FS  {title}  {text}"] + [f"{a}  {native(b)}" for a, b in self.win.compared_pairs]
        lines += [time.strftime("%H:%M:%S", time.localtime(t)) + "  " + msg for s in self.runs
                  for t, _, msg in s.progress.log]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self.log_path = path
        except OSError:
            self.log_path = ""

    def when_done(self, action: str):
        run = self.win.answers.get("system", lambda args: subprocess.Popen(args, creationflags=0x08000000
                                                                            if sys.platform == "win32" else 0))
        if action == "close":
            self.accept()
            self.win.close()
        elif action == "shutdown":
            run(["shutdown", "/s", "/t", "60", "/c", "PR7-FS finished. Run 'shutdown /a' to cancel."]
                if sys.platform == "win32" else ["systemctl", "poweroff"])
        elif action == "sleep":
            run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"] if sys.platform == "win32"
                else ["systemctl", "suspend"])

    def closeEvent(self, e):
        if self.running():
            self.stop()
        super().closeEvent(e)


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"
