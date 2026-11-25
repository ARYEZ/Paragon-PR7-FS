"""PR7-FS's window, FreeFileSync's way: folder pairs -> Compare -> look over (and change) what each difference will do
-> Synchronize. The list is a plain Python list model (never QStandardItemModel: PR7-Z's crash).

Everything that asks goes through `_ask(kind, payload)` (tests set `answers[kind]`); comparing runs on a worker
thread unless `sync_jobs` is True (tests)."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPointF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QIcon, QKeySequence, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QTableView, QVBoxLayout,
                               QWidget)

from . import __version__, config, engine, family, finish, settings, theme, widgets
from .engine import (CONFLICT, DELETE_LEFT, DELETE_RIGHT, EQUAL, NOTHING, TO_LEFT, TO_RIGHT, Item, native)

ACTION_TEXT = {TO_RIGHT: "Copy to the right  →", TO_LEFT: "Copy to the left  ←", DELETE_LEFT: "Delete on the left",
               DELETE_RIGHT: "Delete on the right", NOTHING: "Do nothing"}
VIEWS = [("to_right", "Copy or update to the right"), ("to_left", "Copy or update to the left"),
         ("delete", "Deletions"), ("conflict", "Conflicts"), ("equal", "Equal items"), ("none", "No action")]
GLYPH_FOR_VIEW = {"to_right": "right", "to_left": "left", "delete": "del_right", "conflict": "conflict",
                  "equal": "equal", "none": "none"}


# --------------------------------------------------------------------------- the action glyphs
def glyph_colour(kind: str) -> str:
    return {"right": theme.LED_ORANGE, "left": theme.LED_ORANGE, "del_right": theme.METER_RED,
            "del_left": theme.METER_RED, "conflict": "#FFAA5A"}.get(kind, theme.TEXT_DIM)


_glyphs: dict = {}


def glyph(kind: str, size: int = 20) -> QIcon:
    key = (kind, size, theme.FINISH)
    if key in _glyphs:
        return _glyphs[key]
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(glyph_colour(kind))
    p.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    s = size
    path = QPainterPath()
    if kind in ("del_right", "del_left"):
        path.moveTo(s * .34, s * .3); path.lineTo(s * .66, s * .7)
        path.moveTo(s * .66, s * .3); path.lineTo(s * .34, s * .7)
        x, d = (s * .86, 1) if kind == "del_right" else (s * .14, -1)
        path.moveTo(x - d * s * .08, s * .38); path.lineTo(x, s * .5); path.lineTo(x - d * s * .08, s * .62)
    elif kind == "right":
        path.moveTo(s * .2, s * .5); path.lineTo(s * .8, s * .5)
        path.moveTo(s * .56, s * .28); path.lineTo(s * .8, s * .5); path.lineTo(s * .56, s * .72)
    elif kind == "left":
        path.moveTo(s * .8, s * .5); path.lineTo(s * .2, s * .5)
        path.moveTo(s * .44, s * .28); path.lineTo(s * .2, s * .5); path.lineTo(s * .44, s * .72)
    elif kind == "conflict":
        path.moveTo(s * .5, s * .22); path.lineTo(s * .5, s * .6)
        p.setBrush(c)
        p.drawEllipse(QPointF(s * .5, s * .78), 1.6, 1.6)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif kind == "equal":
        path.moveTo(s * .28, s * .42); path.lineTo(s * .72, s * .42)
        path.moveTo(s * .28, s * .6); path.lineTo(s * .72, s * .6)
    else:
        path.moveTo(s * .34, s * .5); path.lineTo(s * .66, s * .5)
    p.drawPath(path)
    p.end()
    _glyphs[key] = QIcon(pm)
    return _glyphs[key]


def glyph_of(it: Item) -> str:
    if it.action == TO_RIGHT:
        return "right"
    if it.action == TO_LEFT:
        return "left"
    if it.action in (DELETE_LEFT, DELETE_RIGHT):
        return "del_right" if it.action == DELETE_RIGHT else "del_left"
    if it.category == CONFLICT:
        return "conflict"
    return "equal" if it.category == EQUAL else "none"


def view_of(it: Item) -> str:
    if it.action == TO_RIGHT:
        return "to_right"
    if it.action == TO_LEFT:
        return "to_left"
    if it.action in (DELETE_LEFT, DELETE_RIGHT):
        return "delete"
    if it.category == CONFLICT:
        return "conflict"
    return "equal" if it.category == EQUAL else "none"


def when(ns: int) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ns / 1e9))


# --------------------------------------------------------------------------- the list
class DiffModel(QAbstractTableModel):
    """Rows are (pair index, Item); `all_rows` holds every item, `rows` the ones the view buttons show."""

    HEADERS = ["NAME", "SIZE", "MODIFIED", "", "NAME", "SIZE", "MODIFIED"]
    ACTION_COL = 3

    def __init__(self):
        super().__init__()
        self.all_rows: list[tuple[int, Item]] = []
        self.rows: list[tuple[int, Item]] = []
        self.show: set[str] = {v for v, _ in VIEWS} - {"equal"}       # FreeFileSync hides equal items at first
        self.pairs: list[tuple[str, str]] = []

    def set_items(self, rows, pairs):
        self.beginResetModel()
        self.all_rows, self.pairs = rows, pairs
        self._filter()
        self.endResetModel()

    def refilter(self):
        self.beginResetModel()
        self._filter()
        self.endResetModel()

    def _filter(self):
        self.rows = [r for r in self.all_rows if view_of(r[1]) in self.show]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 7

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def item(self, row: int) -> tuple[int, Item] | None:
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def changed(self, rows=None):
        if rows is None:
            self.dataChanged.emit(self.index(0, 0), self.index(max(0, len(self.rows) - 1), 6))

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        pair, it = self.rows[index.row()]
        col = index.column()
        if col == self.ACTION_COL:
            if role == Qt.ItemDataRole.DecorationRole:
                return glyph(glyph_of(it))
            if role == Qt.ItemDataRole.ToolTipRole:
                text = ACTION_TEXT.get(it.action, "")
                return f"{engine.CATEGORY_TEXT.get(it.category, '')}\n{text}" + (f"\n{it.note}" if it.note else "")
            return None
        side = it.left if col < 3 else it.right
        if side is None:
            return None
        c = col % 4 if col > 3 else col
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                parent = it.rel.rsplit("/", 1)[0] if "/" in it.rel else ""
                shown_parent = any(r[1].rel == parent and r[0] == pair for r in self.rows) if parent else True
                name = it.name if shown_parent else native(it.rel)
                return "    " * it.depth * shown_parent + name
            if c == 1:
                return "" if side.is_dir else engine.human(side.size)
            if c == 2:
                return when(side.mtime)
        if role == Qt.ItemDataRole.DecorationRole and c == 0:
            return widgets.file_icon("folder" if side.is_dir else widgets.kind_of(it.name), 18)
        if role == Qt.ItemDataRole.TextAlignmentRole and c == 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and it.category == EQUAL:
            return QColor(theme.TEXT_DIM)
        if role == Qt.ItemDataRole.ToolTipRole and c == 0:
            base = self.pairs[pair][0 if col < 3 else 1] if pair < len(self.pairs) else ""
            return os.path.join(base, native(it.rel))
        return None


class _Bridge(QObject):
    compared = Signal(object, object)      # rows | None, error | None
    progress = Signal(str)


# --------------------------------------------------------------------------- the window
class PairRow(QWidget):
    removed = Signal(object)

    def __init__(self, win, left="", right="", first=False):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 2, 18, 2)
        lay.setSpacing(8)
        lay.addWidget(_field("Left"))
        self.left = QLineEdit(left)
        self.left.setPlaceholderText("a folder")
        lay.addWidget(self.left, 1)
        bl = QPushButton("Browse…")
        bl.clicked.connect(lambda: self._browse(win, self.left))
        lay.addWidget(bl)
        self.swap = widgets.SmallKey("swap", "Swap sides")
        self.swap.clicked.connect(self.swap_sides)
        lay.addWidget(self.swap)
        lay.addWidget(_field("Right"))
        self.right = QLineEdit(right)
        self.right.setPlaceholderText("a folder")
        lay.addWidget(self.right, 1)
        br = QPushButton("Browse…")
        br.clicked.connect(lambda: self._browse(win, self.right))
        lay.addWidget(br)
        self.extra = widgets.SmallKey("add" if first else "close", "Add a folder pair" if first else "Remove this pair")
        lay.addWidget(self.extra)
        if not first:
            self.extra.clicked.connect(lambda: self.removed.emit(self))

    def _browse(self, win, edit):
        path = win._ask("folder", edit.text())
        if path:
            edit.setText(path)

    def swap_sides(self):
        a, b = self.left.text(), self.right.text()
        self.left.setText(b)
        self.right.setText(a)


def _field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def _dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


class MainWindow(QMainWindow):
    def __init__(self, cfg: config.Config | None = None):
        super().__init__()
        self.answers: dict = {}
        self.said: list = []
        self.sync_jobs = False
        self.cfg = cfg or config.load_last()
        self.config_path = ""
        self.bridge = _Bridge()
        self.bridge.compared.connect(self._compared)
        self.bridge.progress.connect(lambda t: self.status_text.setText(t))
        self.compared_pairs: list[tuple[str, str]] = []
        self.records: dict[int, engine.Record | None] = {}
        self.comparing = False
        self._cancel = False
        self.sync_dialog = None
        self.setWindowTitle("Paragon PR7-FS")
        self.resize(1280, 820)
        self._build()
        self.restyle()
        self.load_config(self.cfg)

    # ================================================================ building
    def _build(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = widgets.Header("FOLDER SYNC")
        lay.addWidget(self.header)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 6)
        bl.setSpacing(6)
        self.keys = {}
        for i, group in enumerate([[("open", "open", "Open"), ("save", "file", "Save")],
                                   [("compare", "compare", "Compare"), ("filter", "filter", "Filter"),
                                    ("sync", "sync", "Synchronize")],
                                   [("swap", "swap", "Swap Sides"), ("settings", "gear", "Settings")]]):
            if i:
                sep = QLabel()
                sep.setObjectName("sep")
                sep.setFixedSize(1, 40)
                bl.addSpacing(8)
                bl.addWidget(sep)
                bl.addSpacing(8)
            for name, icon, label in group:
                k = widgets.KeyButton(icon, label)
                k.setFixedSize(QSize(100, 62))
                self.keys[name] = k
                bl.addWidget(k)
        bl.addStretch(1)
        lay.addWidget(bar)
        self.keys["open"].clicked.connect(self.open_config)
        self.keys["save"].clicked.connect(self.save_config)
        self.keys["compare"].clicked.connect(self.compare)
        self.keys["filter"].clicked.connect(lambda: self.settings_dialog(1))
        self.keys["sync"].clicked.connect(self.synchronize)
        self.keys["swap"].clicked.connect(self.swap_all)
        self.keys["settings"].clicked.connect(lambda: self.settings_dialog(2))

        row = QHBoxLayout()
        row.setContentsMargins(18, 0, 18, 6)
        row.addWidget(_field("Compare by"))
        self.compare_box = QComboBox()
        for k, v in engine.COMPARE_TEXT.items():
            self.compare_box.addItem(v, k)
        self.compare_box.setFixedWidth(190)
        self.compare_box.currentIndexChanged.connect(self._compare_by)
        row.addWidget(self.compare_box)
        row.addSpacing(18)
        row.addWidget(_field("Filter"))
        self.filter_text = _dim("")
        self.filter_text.setMaximumWidth(380)
        row.addWidget(self.filter_text)
        row.addSpacing(18)
        row.addWidget(_field("Synchronize"))
        self.variant_box = QComboBox()
        for k, v in engine.VARIANT_TEXT.items():
            self.variant_box.addItem(v, k)
        self.variant_box.setFixedWidth(150)
        self.variant_box.currentIndexChanged.connect(self._variant)
        row.addWidget(self.variant_box)
        row.addStretch(1)
        lay.addLayout(row)
        self.pairs_box = QVBoxLayout()
        self.pairs_box.setContentsMargins(0, 2, 0, 6)
        self.pairs_box.setSpacing(4)
        self.pair_rows: list[PairRow] = []
        lay.addLayout(self.pairs_box)

        self.model = DiffModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(18, 18))
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_menu)
        self.table.clicked.connect(self._clicked)
        self.table.doubleClicked.connect(self._double)
        h = self.table.horizontalHeader()
        for c, mode in enumerate([QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.ResizeToContents,
                                  QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Fixed,
                                  QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.ResizeToContents,
                                  QHeaderView.ResizeMode.ResizeToContents]):
            h.setSectionResizeMode(c, mode)
        self.table.setColumnWidth(3, 46)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.addWidget(self.table)
        self.empty = _dim("Choose two folders, then Compare (F5).")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(self.empty)
        lay.addWidget(holder, 1)

        foot = QFrame()
        foot.setObjectName("foot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.setSpacing(4)
        fl.addWidget(_field("Show"))
        self.view_keys = {}
        for view, tip in VIEWS:
            b = QPushButton()
            b.setCheckable(True)
            b.setChecked(view in self.model.show)
            b.setToolTip(tip)
            b.setFixedSize(34, 28)
            b.toggled.connect(lambda on, v=view: self.set_view(v, on))
            self.view_keys[view] = b
            fl.addWidget(b)
        fl.addSpacing(16)
        self.status_text = _dim("")
        fl.addWidget(self.status_text)
        fl.addStretch(1)
        self.stats_text = QLabel("")
        self.stats_text.setObjectName("stats")
        fl.addWidget(self.stats_text)
        lay.addWidget(foot)
        self._menus()

    def _act(self, menu, text, slot, keys=None, key=None, checkable=False):
        a = QAction(text, self)
        if keys:
            a.setShortcut(QKeySequence(keys))
        a.setCheckable(checkable)
        a.triggered.connect(lambda *_: slot())
        menu.addAction(a)
        if key:
            self.acts[key] = a
        return a

    def _menus(self):
        self.acts: dict[str, QAction] = {}
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "New", self.new_config, "Ctrl+N", "new")
        self._act(m, "Open…", self.open_config, "Ctrl+O", "open")
        self._act(m, "Save", self.save_config, "Ctrl+S", "save")
        self._act(m, "Save As…", lambda: self.save_config(ask=True), "Ctrl+Shift+S", "save_as")
        m.addSeparator()
        self._act(m, "Exit", self.close, "Alt+F4")
        m = mb.addMenu("&Actions")
        self._act(m, "Compare", self.compare, "F5", "compare")
        self._act(m, "Synchronize", self.synchronize, "F9", "sync")
        self._act(m, "Swap Sides", self.swap_all, None, "swap")
        m = mb.addMenu("&Tools")
        self._act(m, "Comparison Settings…", lambda: self.settings_dialog(0), "F6", "compare_settings")
        self._act(m, "Filter Settings…", lambda: self.settings_dialog(1), "F7", "filter_settings")
        self._act(m, "Synchronization Settings…", lambda: self.settings_dialog(2), "F8", "sync_settings")
        m.addSeparator()
        fm = m.addMenu("Finish")
        group = QActionGroup(self)
        self.finish_acts = {}
        for name in ("obsidian", "aurora"):
            a = self._act(fm, name.upper(), lambda n=name: self.set_finish(n), checkable=True)
            group.addAction(a)
            self.finish_acts[name] = a
        self.finish_acts[theme.FINISH].setChecked(True)
        m = mb.addMenu("&Help")
        self._act(m, "Check for Updates…", self.check_updates, None, "updates")
        self._act(m, "About PR7-FS", self.about, None, "about")

    # ================================================================ look
    def restyle(self):
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.palette())
            app.setStyleSheet(theme.stylesheet())
        self.centralWidget().setStyleSheet(
            f"QWidget#central {{ background: {theme.BACKGROUND}; }} QLabel#sep {{ background: {theme.PANEL_EDGE}; }} "
            f"QFrame#foot {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }} "
            f"QLabel#stats {{ color: {theme.TEXT}; font-size: 11px; font-weight: 600; }}")
        self.header.update()
        for view, b in getattr(self, "view_keys", {}).items():
            b.setIcon(glyph(GLYPH_FOR_VIEW[view]))
        for a_name, a in getattr(self, "finish_acts", {}).items():
            a.setChecked(a_name == theme.FINISH)
        if hasattr(self, "model"):
            self.model.changed()

    def set_finish(self, name: str):
        theme.set_finish(name)
        finish.set(theme.FINISH)                 # every family app follows (finish.py)
        settings.set("finish", theme.FINISH)
        self.restyle()
        if self.sync_dialog is not None:
            self.sync_dialog.restyle()

    # ================================================================ asking
    def _ask(self, kind: str, payload=None):
        if kind in self.answers:
            a = self.answers[kind]
            return a(payload) if callable(a) else a
        if kind == "folder":
            return QFileDialog.getExistingDirectory(self, "Choose a Folder", payload or "")
        if kind == "open_file":
            return QFileDialog.getOpenFileName(self, "Open", payload or "", f"PR7-FS settings (*{config.EXT})")[0]
        if kind == "save_file":
            return QFileDialog.getSaveFileName(self, "Save As", payload or "", f"PR7-FS settings (*{config.EXT})")[0]
        if kind == "confirm":
            return QMessageBox.question(self, "PR7-FS", payload) == QMessageBox.StandardButton.Yes
        if kind == "settings":
            return payload.exec()
        return None

    def _say(self, kind: str, text: str):
        self.said.append((kind, text))
        if "say" in self.answers:
            self.answers["say"](kind, text)
            return
        icon = QMessageBox.Icon.Warning if kind == "error" else QMessageBox.Icon.Information
        QMessageBox(icon, "PR7-FS", text, parent=self).exec()

    # ================================================================ the setup
    def load_config(self, cfg: config.Config):
        self.cfg = cfg
        for r in self.pair_rows:
            r.setParent(None)
            r.deleteLater()
        self.pair_rows = []
        for i, (a, b) in enumerate(cfg.pairs or [["", ""]]):
            self.add_pair(a, b, first=(i == 0))
        self.compare_box.blockSignals(True)
        self.compare_box.setCurrentIndex(max(0, self.compare_box.findData(cfg.compare_by)))
        self.compare_box.blockSignals(False)
        self.variant_box.blockSignals(True)
        self.variant_box.setCurrentIndex(max(0, self.variant_box.findData(cfg.variant)))
        self.variant_box.blockSignals(False)
        self._show_filter()
        self.model.set_items([], [])
        self._after()

    def add_pair(self, left="", right="", first=False):
        row = PairRow(self, left, right, first=first or not self.pair_rows)
        if row.extra.toolTip().startswith("Add"):
            row.extra.clicked.connect(lambda: self.add_pair())
        row.removed.connect(self.remove_pair)
        self.pair_rows.append(row)
        self.pairs_box.addWidget(row)
        return row

    def remove_pair(self, row):
        if row in self.pair_rows and len(self.pair_rows) > 1:
            self.pair_rows.remove(row)
            row.setParent(None)
            row.deleteLater()

    def read_config(self) -> config.Config:
        self.cfg.pairs = [[r.left.text().strip(), r.right.text().strip()] for r in self.pair_rows]
        self.cfg.compare_by = self.compare_box.currentData()
        self.cfg.variant = self.variant_box.currentData()
        return self.cfg

    def _show_filter(self):
        ex = engine.patterns(self.cfg.exclude)
        inc = engine.patterns(self.cfg.include)
        text = ("include " + "; ".join(inc) + "   " if inc != ["*"] else "") + \
               ("exclude " + "; ".join(ex) if ex else "")
        self.filter_text.setText(text or "none")
        self.filter_text.setToolTip(text)

    def _compare_by(self, *_):
        self.cfg.compare_by = self.compare_box.currentData()
        if self.model.all_rows:
            self.compare()

    def _variant(self, *_):
        self.cfg.variant = self.variant_box.currentData()
        self.reassign()

    def new_config(self):
        self.config_path = ""
        self.load_config(config.Config())

    def open_config(self, path: str | None = None):
        path = path or self._ask("open_file", os.path.dirname(self.config_path) if self.config_path else "")
        if not path:
            return
        try:
            cfg = config.load(path)
        except (OSError, ValueError) as e:
            self._say("error", f"{os.path.basename(path)} isn't a PR7-FS settings file ({e}).")
            return
        self.config_path = path
        self.load_config(cfg)
        self.setWindowTitle(f"{os.path.basename(path)} · Paragon PR7-FS")

    def save_config(self, ask: bool = False):
        path = self.config_path
        if ask or not path:
            path = self._ask("save_file", path or "SyncSettings" + config.EXT)
        if not path:
            return
        if not path.endswith(config.EXT):
            path += config.EXT
        config.save(self.read_config(), path)
        self.config_path = path
        self.setWindowTitle(f"{os.path.basename(path)} · Paragon PR7-FS")

    def swap_all(self):
        for r in self.pair_rows:
            r.swap_sides()
        if self.model.all_rows:
            self.compare()

    # ================================================================ compare
    def compare(self):
        cfg = self.read_config()
        pairs = cfg.real_pairs()
        if not pairs:
            self._say("error", "Choose a folder on both sides first.")
            return
        for a, b in pairs:
            for p in (a, b):
                if not os.path.isdir(p):
                    self._say("error", f"{p} can't be found (or isn't a folder).")
                    return
            if os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b)):
                self._say("error", "Both sides are the same folder.")
                return
        flt, by = cfg.filter(), cfg.compare_by
        self.comparing, self._cancel = True, False
        self._enable()
        self.status_text.setText("Comparing…")

        def work():
            try:
                rows = []
                for i, (a, b) in enumerate(pairs):
                    got = {}

                    def side(key, base):
                        got[key] = engine.scan(base, flt, cancel=lambda: self._cancel)
                    ts = [threading.Thread(target=side, args=(k, p)) for k, p in (("l", a), ("r", b))]
                    if self.sync_jobs:
                        for t in ts:
                            t.run()
                    else:
                        for t in ts:
                            t.start()
                        for t in ts:
                            t.join()
                    self.bridge.progress.emit(f"Comparing  {native(a)}  ·  {len(got['l']) + len(got['r'])} items")
                    rows += [(i, it) for it in engine.compare(got["l"], got["r"], by, a, b)]
                return (rows, pairs), None
            except engine.Cancelled:
                return None, "cancelled"
            except Exception as e:      # noqa: BLE001 - shown to the user
                return None, str(e)

        if self.sync_jobs:
            self.bridge.compared.emit(*work())
        else:
            threading.Thread(target=lambda: self.bridge.compared.emit(*work()), daemon=True).start()

    def _compared(self, result, error):
        self.comparing = False
        if error:
            self.status_text.setText("")
            if error != "cancelled":
                self._say("error", f"The comparison failed: {error}")
            self._enable()
            return
        rows, pairs = result
        self.compared_pairs = pairs
        self.records = {i: engine.Record.load(a, b) for i, (a, b) in enumerate(pairs)}
        self.model.set_items(rows, pairs)
        self.reassign()
        config.save_last(self.read_config())

    def reassign(self):
        """The variant's actions for every item (after a compare, or when the variant changes)."""
        if not self.model.all_rows:
            self._after()
            return
        for i in range(len(self.compared_pairs)):
            items = [it for p, it in self.model.all_rows if p == i]
            engine.assign(items, self.cfg.variant, self.cfg.custom, self.records.get(i), self.cfg.detect_moves)
        self.model.refilter()
        self._after()

    def items(self, pair: int | None = None) -> list[Item]:
        return [it for p, it in self.model.all_rows if pair is None or p == pair]

    def _after(self):
        s = engine.stats(self.items())
        has = bool(self.model.all_rows)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        if has:
            moved = sum(1 for it in self.items() if it.move_from)
            self.status_text.setText(f"{s.differences} difference{'s' if s.differences != 1 else ''}  ·  "
                                     f"{s.equal} equal" + (f"  ·  {s.conflicts} conflict"
                                                           f"{'s' if s.conflicts != 1 else ''}" if s.conflicts else "")
                                     + (f"  ·  {moved} moved" if moved else "")
                                     + ("" if self.records.get(0) or self.cfg.variant != engine.TWO_WAY else
                                        "  ·  first Two way sync: deletions can't be told yet"))
            self.stats_text.setText(f"→  CREATE {s.create_right}   UPDATE {s.update_right}   DELETE {s.delete_right}"
                                    f"        ←  CREATE {s.create_left}   UPDATE {s.update_left}   DELETE "
                                    f"{s.delete_left}        {engine.human(s.bytes).upper()} TO COPY")
        else:
            self.stats_text.setText("")
        self._enable()

    def needs_record(self) -> bool:
        """Two way with a pair that has no last-sync record yet: a sync is worth running even with nothing to copy,
        to write the record (FreeFileSync does the same); without it the next deletion can't be told."""
        return self.cfg.variant == engine.TWO_WAY and any(self.records.get(i) is None
                                                          for i in range(len(self.compared_pairs)))

    def _enable(self):
        has = bool(self.model.all_rows) and not self.comparing
        self.keys["sync"].setEnabled(has and (not engine.stats(self.items()).nothing_to_do() or self.needs_record()))
        self.acts["sync"].setEnabled(self.keys["sync"].isEnabled())
        self.keys["compare"].setEnabled(not self.comparing)

    def set_view(self, view: str, on: bool):
        (self.model.show.add if on else self.model.show.discard)(view)
        self.model.refilter()

    # ================================================================ changing an action
    def selected(self) -> list[tuple[int, Item]]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.rows[r] for r in rows if r < len(self.model.rows)]

    def set_action(self, rows, action: str):
        for pair, it in rows:
            if action in engine.possible_actions(it):
                engine.set_action(self.items(pair), it, action)
                it.move_from = "" if action != it.action else it.move_from
        self.model.changed()
        self._after()

    def _clicked(self, index):
        if index.column() == DiffModel.ACTION_COL:
            row = self.model.item(index.row())
            if row is not None:
                self.action_menu([row], self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft()))

    def action_menu(self, rows, pos=None) -> QMenu:
        m = QMenu(self)
        possible = set(engine.possible_actions(rows[0][1]))
        for _, it in rows[1:]:
            possible &= set(engine.possible_actions(it))
        for a in engine.ACTIONS:
            if a in possible:
                kind = {TO_RIGHT: "right", TO_LEFT: "left", DELETE_LEFT: "del_left", DELETE_RIGHT: "del_right"}.get(
                    a, "none")
                m.addAction(glyph(kind), ACTION_TEXT[a], lambda a=a: self.set_action(rows, a))
        self.last_menu = m
        if pos is not None and "menu" not in self.answers:
            m.exec(pos)
        return m

    def _row_menu(self, pos):
        rows = self.selected()
        if not rows:
            return
        m = self.action_menu(rows)
        m.addSeparator()
        pair, it = rows[0]
        m.addAction("Exclude via Filter", lambda: self.exclude(rows))
        if len(rows) == 1:
            base_l, base_r = self.compared_pairs[pair]
            if it.left is not None:
                m.addAction("Show on the Left", lambda: self.show_in_folder(os.path.join(base_l, native(it.rel))))
            if it.right is not None:
                m.addAction("Show on the Right", lambda: self.show_in_folder(os.path.join(base_r, native(it.rel))))
        self.last_menu = m
        if "menu" not in self.answers:
            m.exec(self.table.viewport().mapToGlobal(pos))

    def exclude(self, rows):
        """FreeFileSync's Exclude via filter: the items' paths join the exclude list, and they leave the list."""
        pats = []
        for _, it in rows:
            pats.append("\\" + native(it.rel).replace("/", "\\") + ("\\" if it.is_dir else ""))
        self.cfg.exclude = "\n".join([p for p in engine.patterns(self.cfg.exclude)] + pats)
        self._show_filter()
        flt = self.cfg.filter()
        self.model.set_items([(p, it) for p, it in self.model.all_rows if flt.keep(it.rel, it.is_dir)],
                             self.compared_pairs)
        self._after()

    def show_in_folder(self, path: str):
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        launch = self.answers.get("launch", family.launch)
        if launch("PR7-E", [folder]):
            return
        opener = self.answers.get("url", QDesktopServices.openUrl)
        opener(QUrl.fromLocalFile(folder))

    def _double(self, index):
        row = self.model.item(index.row())
        if row is None or index.column() == DiffModel.ACTION_COL:
            return
        pair, it = row
        base = self.compared_pairs[pair][0 if index.column() < 3 else 1]
        side = it.left if index.column() < 3 else it.right
        if side is not None:
            opener = self.answers.get("url", QDesktopServices.openUrl)
            opener(QUrl.fromLocalFile(os.path.join(base, native(it.rel))))

    # ================================================================ settings and sync
    def settings_dialog(self, tab: int = 2):
        from .dialogs import SettingsDialog
        d = SettingsDialog(self, self.read_config(), tab)
        if self._ask("settings", d):
            before = (self.cfg.compare_by, self.cfg.include, self.cfg.exclude)
            d.apply(self.cfg)
            self.compare_box.setCurrentIndex(max(0, self.compare_box.findData(self.cfg.compare_by)))
            self.variant_box.blockSignals(True)
            self.variant_box.setCurrentIndex(max(0, self.variant_box.findData(self.cfg.variant)))
            self.variant_box.blockSignals(False)
            self._show_filter()
            if self.model.all_rows and before != (self.cfg.compare_by, self.cfg.include, self.cfg.exclude):
                self.compare()
            else:
                self.reassign()
            config.save_last(self.cfg)
        return d

    def synchronize(self):
        if not self.model.all_rows:
            self.compare()
            if not self.model.all_rows:
                return
        s = engine.stats(self.items())
        if s.nothing_to_do() and not self.needs_record():
            self._say("info", "There's nothing to synchronize.")
            return
        if self.cfg.deletion == "versioning" and not self.cfg.versions.strip():
            self._say("error", "Versioning is on, but no versioning folder is chosen (Synchronization settings).")
            return
        what = (f"Synchronize {engine.VARIANT_TEXT[self.cfg.variant].split()[0]}?\n\n"
                f"→  create {s.create_right}, update {s.update_right}, delete {s.delete_right}\n"
                f"←  create {s.create_left}, update {s.update_left}, delete {s.delete_left}\n"
                f"{engine.human(s.bytes)} to copy. Deleted and overwritten files go "
                + {"recycle": "to the Recycle Bin.", "permanent": "away for good.",
                   "versioning": f"to {self.cfg.versions}."}[self.cfg.deletion])
        if s.nothing_to_do():
            what = "Both sides are already alike. Synchronize anyway, so Two way remembers this state (and can tell " \
                   "a deleted file from a new one next time)?"
        if not self._ask("confirm", what):
            return
        from .dialogs import SyncDialog
        self.sync_dialog = SyncDialog(self)
        self.sync_dialog.start()
        return self.sync_dialog

    def synced(self):
        """After a sync: compare again, as FreeFileSync does, so the list shows what's left (usually nothing)."""
        config.save_last(self.read_config())
        self.compare()

    def check_updates(self):
        from . import update_ui
        update_ui.check(self, manual=True)

    def about(self):
        self._say("info", f"Paragon PR7-FS {__version__}\nFolder comparison and sync that works the way FreeFileSync "
                          "works.")

    def closeEvent(self, e):
        if self.sync_dialog is not None and self.sync_dialog.running():
            if not self._ask("confirm", "A synchronization is running. Stop it and quit?"):
                e.ignore()
                return
            self.sync_dialog.stop()
        self._cancel = True
        config.save_last(self.read_config())
        super().closeEvent(e)
