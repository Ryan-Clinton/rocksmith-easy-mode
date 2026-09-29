"""Find and drive a 7-Zip command-line binary.

The inner .7z inside each guitarcade psarc must be repacked with LZMA and
*no directory entries* - the stock archives have none, and a 7z that stores
them hangs the game on the Guitarcade loading screen. That is why files are
always added from an explicit list rather than by adding ".".
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


class SevenZipMissing(RuntimeError):
    pass


def find():
    """Path to a usable 7z binary, or None."""
    for name in ("7z", "7zz", "7za", "7z.exe", "7za.exe"):
        p = shutil.which(name)
        if p:
            return p
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if not base:
                continue
            for sub in ("7-Zip/7z.exe", "7-Zip/7za.exe"):
                p = Path(base) / sub
                if p.is_file():
                    return str(p)
    return None


def require():
    p = find()
    if not p:
        raise SevenZipMissing(
            "7-Zip was not found.\n"
            "  Linux:   sudo apt install p7zip-full   (or your distro's p7zip)\n"
            "  Windows: install 7-Zip from https://7-zip.org and make sure\n"
            "           7z.exe is on PATH or in Program Files\\7-Zip")
    return p


def _run(args, cwd=None):
    return subprocess.run(args, check=True, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, cwd=cwd)


def unpack(archive, dest):
    _run([require(), "x", "-o%s" % dest, str(archive), "-y"])


def pack(dest, workdir, members):
    """Pack *members* (paths relative to workdir) into *dest*.

    Returns the member count actually packed. Raises if 7z stored any
    directory entry.
    """
    listfile = Path(workdir).parent / "files.txt"
    listfile.write_text("\n".join(members) + "\n", encoding="utf-8")
    # 7z resolves the listed names relative to its own cwd, so it has to run
    # inside the work directory for the stored paths to come out right.
    _run([require(), "a", "-t7z", "-m0=LZMA", "-mx=9", "-md=96k", "-ms=off",
          str(dest), "@%s" % listfile], cwd=str(workdir))
    listing = subprocess.run([require(), "l", str(dest)], capture_output=True,
                             text=True, check=True).stdout
    dirs = [ln for ln in listing.splitlines() if " D...." in ln]
    if dirs:
        raise RuntimeError(
            "repacked 7z contains %d directory entries; the game would hang "
            "on the Guitarcade loading screen" % len(dirs))
    return len(members)


def members_of(workdir):
    """Every file under workdir as a sorted list of relative posix paths."""
    workdir = Path(workdir)
    return sorted(str(p.relative_to(workdir).as_posix())
                  for p in workdir.rglob("*") if p.is_file())
