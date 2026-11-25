"""A sync setup (no Qt), as FreeFileSync's configurations: the folder pairs, how to compare, the filter and the sync
settings, saved as a .pr7fs file (JSON). The last one used is kept in the data folder and opened at the next start.

<data> = %APPDATA%\\Paragon\\PR7-FS (PR7FS_DATA in tests)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field

from . import engine, sync

EXT = ".pr7fs"


def data_dir() -> str:
    d = os.environ.get("PR7FS_DATA") or (
        os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Paragon", "PR7-FS") if sys.platform == "win32"
        else os.path.join(os.path.expanduser("~"), ".local", "share", "paragon", "pr7-fs"))
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class Config:
    pairs: list = field(default_factory=lambda: [["", ""]])        # [left, right] per pair
    compare_by: str = engine.BY_TIME_SIZE
    include: str = "*"
    exclude: str = "\\System Volume Information\\\n\\$Recycle.Bin\\\n\\RECYCLE?\\\n*\\desktop.ini\n*\\thumbs.db"
    variant: str = engine.TWO_WAY
    custom: dict = field(default_factory=lambda: dict(engine.MIRROR_ACTIONS))
    detect_moves: bool = True
    deletion: str = sync.RECYCLE
    versions: str = ""
    naming: str = sync.STAMP_FILE
    keep_days: int = 0
    ignore_errors: bool = False
    when_done: str = "nothing"

    def filter(self) -> engine.Filter:
        return engine.Filter(self.include, self.exclude)

    def sync_settings(self) -> sync.Settings:
        return sync.Settings(self.deletion, self.versions, self.naming, self.keep_days, self.ignore_errors)

    def real_pairs(self) -> list[tuple[str, str]]:
        return [(a.strip(), b.strip()) for a, b in self.pairs if a.strip() and b.strip()]


def save(cfg: Config, path: str) -> None:
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"pr7fs": 1, **asdict(cfg)}, f, indent=1)
    os.replace(tmp, path)


def load(path: str) -> Config:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "pairs" not in data:
        raise ValueError("not a PR7-FS configuration")
    known = Config.__dataclass_fields__
    cfg = Config(**{k: v for k, v in data.items() if k in known})
    cfg.pairs = [[str(p[0]), str(p[1])] for p in cfg.pairs if isinstance(p, (list, tuple)) and len(p) == 2] \
        or [["", ""]]
    for k in list(cfg.custom):
        if k not in engine.CATEGORIES or cfg.custom[k] not in engine.ACTIONS:
            del cfg.custom[k]
    return cfg


def last_path() -> str:
    return os.path.join(data_dir(), "last" + EXT)


def load_last() -> Config:
    try:
        return load(last_path())
    except (OSError, ValueError, TypeError):
        return Config()


def save_last(cfg: Config) -> None:
    try:
        save(cfg, last_path())
    except OSError:
        pass
