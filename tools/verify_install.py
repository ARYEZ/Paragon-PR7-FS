"""Check a real install of PR7-FS-Setup.exe (CI, Windows): verify_install.py installed|uninstalled

`installed`: the files, the Start menu entry, the uninstall entry, the .pr7fs file type, the installed exe's
--selftest (two real folders compared, mirrored, then Two way twice: a deletion carried across by the record) and a
--batch run of a saved setup, with the real Recycle Bin (CI only). `uninstalled`: all of it gone."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-FS"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-FS.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{D573AEAF-B102-484A-AD03-42624DC18A25}_is1"


def value(root, path, name=""):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-FS.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7fs" / "fonts" / "Inter-Regular.ttf"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(HKCU, UNINSTALL, "DisplayName") == "Paragon PR7-FS", "Installed apps entry", p)
    check(value(HKCU, r"Software\Classes\.pr7fs") == "Paragon.PR7FS.Settings", ".pr7fs files open in PR7-FS", p)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.json"
        try:
            subprocess.run([str(exe), "--selftest", str(out)], timeout=180, check=False)
        except subprocess.TimeoutExpired:
            pass
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        check(got.get("ok") is True and got.get("fonts") is True, f"the installed exe compares and syncs ({got})", p)
        # a batch run with the real Recycle Bin: Mirror deletes a file on the right
        left, right = Path(d) / "L", Path(d) / "R"
        left.mkdir(); right.mkdir()
        (left / "keep.txt").write_text("keep")
        (right / "stale.txt").write_text("stale")
        cfg = Path(d) / "job.pr7fs"
        cfg.write_text(json.dumps({"pr7fs": 1, "pairs": [[str(left), str(right)]], "variant": "mirror"}))
        r = subprocess.run([str(exe), "--batch", str(cfg)], timeout=120, check=False)
        check(r.returncode == 0 and (right / "keep.txt").exists() and not (right / "stale.txt").exists(),
              f"--batch mirrors, the stale file to the Recycle Bin (exit {r.returncode})", p)
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-FS.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(HKCU, UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        check(value(HKCU, r"Software\Classes\Paragon.PR7FS.Settings") is None, "the .pr7fs file type removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
