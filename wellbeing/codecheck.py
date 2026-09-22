"""Is this machine running the same code as the bundle in Drive?

Code travels between the Mac and the Windows machine as a zip in Drive. Nothing
otherwise reports that a machine is running an older copy, and a stale copy is
how the two ends drift apart -- so `where` compares them.
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path, PurePosixPath

from . import archive

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = "PhoneUsageCode/adb_usage_stats.zip"
TOP = "adb_usage_stats/"
# The files that make up the application; data and binaries are excluded. Both
# sides are filtered by the same rule, so a nested file can never match on one
# side and not the other.
def _wanted(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    if parts[:1] == ("wellbeing",) and rel.endswith((".py", ".html")):
        return True
    return len(parts) == 1 and (rel.endswith(".sh") or rel == "requirements.txt")


def _local_files() -> dict[str, bytes]:
    out = {}
    for path in sorted(ROOT.rglob("*.py")) + sorted(ROOT.rglob("*.html")) + \
                sorted(ROOT.glob("*.sh")) + sorted(ROOT.glob("requirements.txt")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(ROOT))
        if _wanted(rel) and "__pycache__" not in rel:
            out[rel] = path.read_bytes()
    return out


def _bundle_files() -> dict[str, bytes] | None:
    root = archive.drive_root()
    if root is None:
        return None
    try:
        with zipfile.ZipFile(root / BUNDLE) as z:
            return {n[len(TOP):]: z.read(n) for n in z.namelist()
                    if n.startswith(TOP) and not n.endswith("/") and _wanted(n[len(TOP):])}
    except (FileNotFoundError, OSError, zipfile.BadZipFile):
        return None


def digest(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode())
        h.update(hashlib.sha256(files[name]).digest())
    return h.hexdigest()[:12]


def compare() -> tuple[str, list[str], str]:
    """Returns (state, differing file names, local digest)."""
    local = _local_files()
    bundle = _bundle_files()
    if bundle is None:
        return "unknown", [], digest(local)
    if digest(local) == digest(bundle):
        return "same", [], digest(local)
    differing = sorted(set(local) | set(bundle))
    return "differs", [n for n in differing if local.get(n) != bundle.get(n)], digest(local)
