"""Remember which papers each subscriber has received (their PMIDs and DOIs, in
seen/<subscriber>.json), safely when more than one run is involved:

- run_lock():       only one run at a time in this folder (a second one exits right away).
- load_seen(sid):   local seen/<sid>.json plus the copy on GitHub, so a laptop run doesn't
                    repost what the scheduled GitHub run already posted.
- save_seen(sid):   re-reads the file before adding to it, and writes a temp file that then
                    replaces it, so a crash can't leave it half-written.

Also merges one seen file into another (the GitHub workflow uses this):
    python -m digest.store merge FROM.json INTO.json
"""
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager

try:
    import fcntl                        # macOS / Linux
except ImportError:                     # Windows: runs without the lock
    fcntl = None

SEEN_DIR = "seen"
LOCK_FILE = ".digest.lock"
_fetched = {}                           # git fetch runs once per run: {"ok": bool}


def seen_path(sid):
    return os.path.join(SEEN_DIR, f"{sid}.json")


def read_seen(path):
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return set(json.load(f))


def _git(*args, timeout):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, env=env, timeout=timeout)


def remote_seen(sid):
    """seen/<sid>.json as last pushed to GitHub (the upstream branch). Skipped on GitHub itself,
    where the checkout is already current. Empty if git or the network fails, or it isn't there yet."""
    if os.getenv("GITHUB_ACTIONS"):
        return set()
    try:
        if "ok" not in _fetched:
            _fetched["ok"] = False
            r = _git("fetch", "--quiet", timeout=30)
            _fetched["ok"] = r.returncode == 0
            if not _fetched["ok"]:
                print(f"Note: couldn't fetch from GitHub ({r.stderr.strip() or 'git fetch failed'}); "
                      "using local seen files only.")
        if not _fetched["ok"]:
            return set()
        ref = f"@{{u}}:{SEEN_DIR}/{sid}.json"
        if _git("cat-file", "-e", ref, timeout=10).returncode != 0:
            return set()                # not on GitHub yet (e.g. a new subscriber)
        return set(json.loads(_git("show", ref, timeout=10).stdout))
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        print(f"Note: couldn't read {SEEN_DIR}/{sid}.json from GitHub ({e}); using the local copy only.")
        return set()


def load_seen(sid):
    return read_seen(seen_path(sid)) | remote_seen(sid)


def atomic_write(path, text, prefix):
    """Write text to path through a temp file (named prefix*.tmp) that then replaces it,
    so a crash can't leave the file half-written."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)                    # atomic: readers see the old or new file, never half
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _write_seen(path, new_ids):
    """Add new_ids to the seen file at path without losing anything written since the run started."""
    seen = read_seen(path) | set(new_ids)
    atomic_write(path, json.dumps(sorted(seen), indent=1), prefix=".seen-")


def save_seen(sid, new_ids):
    _write_seen(seen_path(sid), new_ids)


@contextmanager
def run_lock():
    """Stop a second digest run from starting in this folder while one is going.
    The OS drops the lock when the process ends, even if it crashes."""
    if fcntl is None:
        yield
        return
    with open(LOCK_FILE, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("Another digest run is already going in this folder; try again when it finishes.")
        yield


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "merge":
        sys.exit("Usage: python -m digest.store merge FROM.json INTO.json")
    _write_seen(sys.argv[3], read_seen(sys.argv[2]))
