"""Mock-up pictures of PR7-FS, drawn offscreen with real Qt widgets in the family theme (every folder, file and number is
made up): QT_SCALE_FACTOR=2 python tools/mockup.py OUT_DIR

1_compare.png    the window after Compare: the folder pair, each side's files, the action in the middle, the view
                 filters and what Synchronize will do (OBSIDIAN)
2_settings.png   Synchronization settings: Two way / Mirror / Update / Custom, the action for each kind of
                 difference, deletion handling, versioning (AURORA)
3_sync.png       Synchronize running: progress, speed, the current file, pause / stop (OBSIDIAN)
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,  # noqa: E402
                               QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QButtonGroup)

from pr7fs import theme, widgets  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/mockup")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setFont(QFont("Inter", 10))


def style():
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())


def field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def combo(*items, width=None):
    c = QComboBox()
    c.addItems(list(items))
    if width:
        c.setFixedWidth(width)
    return c


def toolbar(groups):
    bar = QWidget()
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(16, 10, 16, 6)
    lay.setSpacing(6)
    for i, group in enumerate(groups):
        if i:
            sep = QLabel()
            sep.setFixedSize(1, 40)
            sep.setStyleSheet(f"background: {theme.PANEL_EDGE};")
            lay.addSpacing(8)
            lay.addWidget(sep)
            lay.addSpacing(8)
        for icon, label in group:
            k = widgets.KeyButton(icon, label)
            k.setFixedSize(QSize(100, 62))
            lay.addWidget(k)
    lay.addStretch(1)
    return bar


# ----------------------------------------------------------------- the action glyphs of the middle column
ACTION_COLOURS = {"right": "#F07A2A", "left": "#F07A2A", "del_right": theme.METER_RED, "del_left": theme.METER_RED,
                  "conflict": "#FFAA5A", "equal": "#8A8A92", "none": "#8A8A92"}


def action_icon(kind, size=20):
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(ACTION_COLOURS[kind])
    p.setPen(QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    s = size
    path = QPainterPath()
    if kind in ("del_right", "del_left"):          # a red cross, with a small pointer to the side it deletes on
        path.moveTo(s * .34, s * .3); path.lineTo(s * .66, s * .7)
        path.moveTo(s * .66, s * .3); path.lineTo(s * .34, s * .7)
        x = s * (.86 if kind == "del_right" else .14)
        d = 1 if kind == "del_right" else -1
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
        path.moveTo(s * .3, s * .5); path.lineTo(s * .7, s * .5)
    p.drawPath(path)

    p.end()
    return QIcon(pm)


def file_icon(folder=False):
    return widgets.file_icon("folder" if folder else "file", 18)


# ----------------------------------------------------------------- 1: the compared folders
ROWS = [   # (depth, folder?, left (name, size, date) | None, action, right | None)
    (0, True, ("Footage", "", "2026-11-24 21:10"), "equal", ("Footage", "", "2026-11-24 21:10")),
    (1, False, ("A001_C0006.mov", "3.42 GB", "2026-11-24 18:02"), "right", None),
    (1, False, ("A001_C0007.mov", "2.97 GB", "2026-11-24 18:09"), "right", None),
    (1, False, ("B002_C0001.mov", "1.18 GB", "2026-11-23 16:44"), "equal", ("B002_C0001.mov", "1.18 GB",
                                                                           "2026-11-23 16:44")),
    (0, True, ("Projects", "", "2026-11-25 09:31"), "equal", ("Projects", "", "2026-11-25 09:31")),
    (1, False, ("ELSEWORLD_edit_v12.drp", "48.1 MB", "2026-11-25 09:30"), "right", ("ELSEWORLD_edit_v12.drp",
                                                                                   "47.6 MB", "2026-11-22 23:58")),
    (1, False, ("ELSEWORLD_grade.drx", "2.4 MB", "2026-11-21 14:12"), "left", ("ELSEWORLD_grade.drx", "2.6 MB",
                                                                              "2026-11-24 10:05")),
    (1, False, ("credits.txt", "4 KB", "2026-11-25 08:40"), "conflict", ("credits.txt", "5 KB", "2026-11-25 08:52")),
    (0, True, None, "left", ("Music", "", "2026-11-20 12:00")),
    (1, False, None, "left", ("Last Light (stems).zip", "612 MB", "2026-11-20 12:01")),
    (0, False, ("old_render.mp4", "1.02 GB", "2026-10-02 19:33"), "right", None),
    (0, False, ("notes_for_mix.md", "2 KB", "2026-11-19 22:41"), "right", ("notes_for_mix.md", "2 KB",
                                                                         "2026-11-18 20:15")),
]


def side_cells(t, r, base, entry, depth, folder):
    if entry is None:
        for c in range(3):
            t.setItem(r, base + c, QTableWidgetItem(""))
        return
    name, size, date = entry
    it = QTableWidgetItem(("      " * depth) + name)
    it.setIcon(file_icon(folder))
    t.setItem(r, base, it)
    s = QTableWidgetItem(size)
    s.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    t.setItem(r, base + 1, s)
    t.setItem(r, base + 2, QTableWidgetItem(date))


def compare_window():
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header("FOLDER SYNC"))
    lay.addWidget(toolbar([[("open", "Open"), ("file", "Save")],
                           [("compare", "Compare"), ("filter", "Filter"), ("sync", "Synchronize")],
                           [("swap", "Swap Sides"), ("gear", "Settings")]]))
    variants = QHBoxLayout()
    variants.setContentsMargins(18, 0, 18, 6)
    variants.addWidget(field("Compare by"))
    variants.addWidget(combo("File time and size", "File content", "File size", width=190))
    variants.addSpacing(18)
    variants.addWidget(field("Filter"))
    variants.addWidget(dim("exclude  *.tmp; \\.cache\\; Thumbs.db"))
    variants.addSpacing(18)
    variants.addWidget(field("Synchronize"))
    variants.addWidget(combo("Two way  ⇄", "Mirror  →", "Update  →", "Custom", width=150))
    variants.addStretch(1)
    lay.addLayout(variants)
    pair = QHBoxLayout()
    pair.setContentsMargins(18, 4, 18, 8)
    pair.setSpacing(8)
    pair.addWidget(field("Left"))
    pair.addWidget(QLineEdit(r"D:\Studio\ELSEWORLD"), 1)
    pair.addWidget(QPushButton("Browse…"))
    pair.addWidget(widgets.SmallKey("swap", "Swap sides"))
    pair.addWidget(field("Right"))
    pair.addWidget(QLineEdit(r"\\NAS\Backup\ELSEWORLD"), 1)
    pair.addWidget(QPushButton("Browse…"))
    lay.addLayout(pair)
    t = QTableWidget(len(ROWS), 7)
    t.setHorizontalHeaderLabels(["NAME", "SIZE", "MODIFIED", "", "NAME", "SIZE", "MODIFIED"])
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    t.setIconSize(QSize(18, 18))
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    h = t.horizontalHeader()
    for c, mode in enumerate([QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.ResizeToContents,
                              QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Fixed,
                              QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.ResizeToContents,
                              QHeaderView.ResizeMode.ResizeToContents]):
        h.setSectionResizeMode(c, mode)
    t.setColumnWidth(3, 46)
    for r, (depth, folder, left, action, right) in enumerate(ROWS):
        side_cells(t, r, 0, left, depth, folder)
        mid = QTableWidgetItem()
        mid.setIcon(action_icon(action))
        t.setItem(r, 3, mid)
        side_cells(t, r, 4, right, depth, folder)
        t.setRowHeight(r, 30)
        if action == "equal":
            for c in range(7):
                if t.item(r, c):
                    t.item(r, c).setForeground(QColor(theme.TEXT_DIM))
    t.selectRow(7)
    holder = QWidget()
    hl = QVBoxLayout(holder)
    hl.setContentsMargins(16, 0, 16, 0)
    hl.addWidget(t)
    lay.addWidget(holder, 1)
    foot = QFrame()
    foot.setStyleSheet(f"QFrame {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }}")
    fl = QHBoxLayout(foot)
    fl.setContentsMargins(16, 8, 16, 8)
    fl.setSpacing(4)
    fl.addWidget(field("Show"))
    for kind, tip, on in (("right", "Left only / left newer", True), ("left", "Right only / right newer", True),
                          ("conflict", "Conflicts", True), ("equal", "Equal", True), ("del_right", "Deletions", True)):
        b = QPushButton()
        b.setIcon(action_icon(kind))
        b.setCheckable(True)
        b.setChecked(on)
        b.setToolTip(tip)
        b.setFixedSize(34, 28)
        fl.addWidget(b)
    fl.addSpacing(16)
    fl.addWidget(dim("12 differences  ·  3 equal  ·  1 conflict"))
    fl.addStretch(1)
    stats = QLabel("→  CREATE 4   UPDATE 2   DELETE 0        ←  CREATE 2   UPDATE 1   DELETE 0        "
                   "7.54 GB TO COPY")
    stats.setStyleSheet(f"color: {theme.TEXT}; font-size: 11px; font-weight: 600;")
    fl.addWidget(stats)
    lay.addWidget(foot)
    w.resize(1280, 780)
    return w


# ----------------------------------------------------------------- 2: synchronization settings
def settings_window():
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header("SYNCHRONIZATION SETTINGS"))
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "COMPARISON")
    tabs.addTab(QWidget(), "FILTER")
    page = QWidget()
    tabs.addTab(page, "SYNCHRONIZATION")
    tabs.setCurrentIndex(2)
    g = QGridLayout(page)
    g.setContentsMargins(18, 16, 18, 16)
    g.setHorizontalSpacing(24)
    g.setVerticalSpacing(8)
    g.addWidget(field("Variant"), 0, 0)
    group = QButtonGroup(w)
    variants = [("Two way  ⇄", "Changes on either side go to the other, deletions included."),
                ("Mirror  →", "The right side becomes a copy of the left: files only on the right are deleted."),
                ("Update  →", "New and newer files go from left to right; nothing is deleted."),
                ("Custom", "Choose the action for each kind of difference.")]
    for i, (name, desc) in enumerate(variants):
        b = QRadioButton(name)
        b.setStyleSheet("font-weight: 600;")
        group.addButton(b)
        b.setChecked(i == 1)
        g.addWidget(b, 1 + i * 2, 0)
        d = dim(desc)
        d.setWordWrap(True)
        d.setMaximumWidth(380)
        d.setContentsMargins(30, 0, 0, 8)
        g.addWidget(d, 2 + i * 2, 0)
    g.addWidget(QCheckBox("Detect moved files"), 9, 0)
    g.addWidget(field("What happens to each difference"), 0, 1, 1, 2)
    acts = [("Item exists left only", "right"), ("Item exists right only", "del_right"),
            ("Left side is newer", "right"), ("Right side is newer", "right"),
            ("Items have different content", "right"), ("Conflict (can't tell which is newer)", "right")]
    for i, (what, act) in enumerate(acts):
        g.addWidget(QLabel(what), 1 + i, 1)
        b = QPushButton()
        b.setIcon(action_icon(act, 22))
        b.setIconSize(QSize(22, 22))
        b.setFixedSize(52, 30)
        g.addWidget(b, 1 + i, 2)
    g.addWidget(field("Deleted and overwritten files"), 8, 1, 1, 2)
    row = QHBoxLayout()
    row.setSpacing(24)
    deletion = QButtonGroup(w)                   # each set of choices its own group (siblings are one set otherwise)
    for i, name in enumerate(("Recycle Bin", "Permanent", "Versioning")):
        b = QRadioButton(name)
        deletion.addButton(b)
        b.setChecked(i == 2)
        row.addWidget(b)
    row.addStretch(1)
    g.addLayout(row, 9, 1, 1, 2)
    vrow = QHBoxLayout()
    vrow.addWidget(QLineEdit(r"\\NAS\Backup\ELSEWORLD.versions"), 1)
    vrow.addWidget(QPushButton("Browse…"))
    g.addLayout(vrow, 10, 1, 1, 2)
    nrow = QHBoxLayout()
    nrow.addWidget(dim("Naming"))
    nrow.addWidget(combo("Time stamp (file)", "Time stamp (folder)", "Replace", width=190))
    nrow.addSpacing(12)
    nrow.addWidget(dim("Keep for"))
    nrow.addWidget(combo("30 days", "7 days", "Forever", width=110))
    nrow.addStretch(1)
    g.addLayout(nrow, 11, 1, 1, 2)
    g.addWidget(field("On errors"), 12, 1, 1, 2)
    erow = QHBoxLayout()
    erow.setSpacing(24)
    errors = QButtonGroup(w)
    for i, name in enumerate(("Show a message", "Ignore and continue")):
        b = QRadioButton(name)
        errors.addButton(b)
        b.setChecked(i == 0)
        erow.addWidget(b)
    erow.addStretch(1)
    g.addLayout(erow, 13, 1, 1, 2)
    g.setRowStretch(14, 1)
    g.setColumnStretch(1, 1)
    holder = QWidget()
    hl = QVBoxLayout(holder)
    hl.setContentsMargins(16, 12, 16, 0)
    hl.addWidget(tabs)
    lay.addWidget(holder, 1)
    keys = QHBoxLayout()
    keys.setContentsMargins(16, 10, 16, 14)
    keys.addStretch(1)
    ok = QPushButton("OK")
    ok.setFixedWidth(110)
    keys.addWidget(ok)
    cancel = QPushButton("Cancel")
    cancel.setFixedWidth(110)
    keys.addWidget(cancel)
    lay.addLayout(keys)
    w.resize(1100, 720)
    return w


# ----------------------------------------------------------------- 3: synchronizing
class SpeedGraph(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(150)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.fillRect(r, QColor(theme.WIDGET))
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        for i in range(1, 4):
            y = r.top() + r.height() * i / 4
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        pts = []
        n = 120
        for i in range(int(n * .62)):
            v = .55 + .2 * math.sin(i / 7) + .12 * math.sin(i / 2.3) + (.1 if 30 < i < 44 else 0)
            pts.append(QPointF(r.left() + r.width() * i / n, r.bottom() - r.height() * min(.95, v)))
        area = QPainterPath(QPointF(pts[0].x(), r.bottom()))
        for q in pts:
            area.lineTo(q)
        area.lineTo(pts[-1].x(), r.bottom())
        g = theme.family_gradient(r.left(), 0, r.right(), 0, theme.LIT, .28)
        p.fillPath(area, g)
        line = QPainterPath(pts[0])
        for q in pts[1:]:
            line.lineTo(q)
        p.setPen(QPen(theme.family_gradient(r.left(), 0, r.right(), 0), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(line)
        p.setPen(QColor(theme.TEXT_DIM))
        f = QFont("Inter", 1)
        f.setPixelSize(10)
        p.setFont(f)
        p.drawText(QRectF(r.left() + 6, r.top() + 4, 200, 14), Qt.AlignmentFlag.AlignLeft, "180 MB/s")


def sync_window():
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header("SYNCHRONIZING"))
    body = QVBoxLayout()
    body.setContentsMargins(20, 14, 20, 16)
    body.setSpacing(10)
    now = QLabel(r"Copying  Footage\A001_C0007.mov  →  \\NAS\Backup\ELSEWORLD\Footage")
    now.setStyleSheet("font-weight: 600;")
    body.addWidget(now)
    bar = QProgressBar()
    bar.setValue(62)
    bar.setTextVisible(False)
    bar.setFixedHeight(10)
    body.addWidget(bar)
    g = QGridLayout()
    g.setHorizontalSpacing(30)
    stats = [("Items", "5 of 9"), ("Data", "4.71 GB of 7.54 GB"), ("Speed", "126 MB/s"),
             ("Elapsed", "00:00:37"), ("Remaining", "00:00:22"), ("Errors", "0")]
    for i, (k, v) in enumerate(stats):
        g.addWidget(field(k), 0, i)
        lab = QLabel(v)
        lab.setStyleSheet("font-size: 14px; font-weight: 600;")
        g.addWidget(lab, 1, i)
    body.addLayout(g)
    body.addWidget(SpeedGraph(), 1)
    log = QTableWidget(4, 3)
    log.setHorizontalHeaderLabels(["TIME", "", "WHAT"])
    log.verticalHeader().setVisible(False)
    log.setShowGrid(False)
    log.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    for r, (t, k, what) in enumerate([("14:02:51", "right", r"Created  Footage\A001_C0006.mov  (3.42 GB)"),
                                      ("14:03:19", "right", r"Updated  Projects\ELSEWORLD_edit_v12.drp"),
                                      ("14:03:19", "left", r"Updated  Projects\ELSEWORLD_grade.drx  (on the left)"),
                                      ("14:03:20", "right", r"Versioned  notes_for_mix.md  →  .versions\2026-11-25 140320")]):
        log.setItem(r, 0, QTableWidgetItem(t))
        a = QTableWidgetItem()
        a.setIcon(action_icon(k))
        log.setItem(r, 1, a)
        log.setItem(r, 2, QTableWidgetItem(what))
    log.setFixedHeight(150)
    body.addWidget(log)
    keys = QHBoxLayout()
    keys.addWidget(field("When finished"))
    keys.addWidget(combo("Do nothing", "Sleep", "Shut down", "Close PR7-FS", width=180))
    keys.addStretch(1)
    for icon, label in (("pause", "Pause"), ("stop", "Stop")):
        k = widgets.KeyButton(icon, label)
        k.setFixedSize(QSize(92, 62))
        keys.addWidget(k)
    body.addLayout(keys)
    lay.addLayout(body, 1)
    w.resize(1000, 700)
    return w


def shoot(widget, name):
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / name))
    widget.close()


theme.set_finish("obsidian")
style()
shoot(compare_window(), "1_compare.png")
theme.set_finish("aurora")
style()
shoot(settings_window(), "2_settings.png")
theme.set_finish("obsidian")
style()
shoot(sync_window(), "3_sync.png")
print("ok", out)
