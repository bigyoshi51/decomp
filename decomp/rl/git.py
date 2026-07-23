from __future__ import annotations

import functools
import subprocess
import threading
from pathlib import Path


class GitError(RuntimeError):
    pass


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise GitError(f"not a Git checkout: {self.root}")
        if Path(result.stdout.strip()).resolve() != self.root:
            raise GitError(f"not the root of a Git checkout: {self.root}")
        self._batch_check_process: subprocess.Popen[bytes] | None = None
        self._batch_read_process: subprocess.Popen[bytes] | None = None
        self._batch_check_lock = threading.Lock()
        self._batch_read_lock = threading.Lock()

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise GitError(result.stderr.strip() or "git command failed")
        return result

    @functools.lru_cache(maxsize=32768)
    def object_id(self, revision: str, path: str) -> str | None:
        spec = f"{revision}:{path}"
        with self._batch_check_lock:
            process = self._batch_check()
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(spec.encode() + b"\n")
            process.stdin.flush()
            line = process.stdout.readline().decode(errors="replace").strip()
        fields = line.split()
        if len(fields) != 2 or fields[1] == "missing":
            return None
        return fields[0] if fields[1] == "blob" else None

    @functools.lru_cache(maxsize=32)
    def show_object_text(self, object_id: str) -> str | None:
        data = self._read_batch_object(object_id)
        return data.decode(errors="replace") if data is not None else None

    def show_text(self, revision: str, path: str) -> str | None:
        object_id = self.object_id(revision, path)
        return self.show_object_text(object_id) if object_id else None

    @functools.lru_cache(maxsize=128)
    def show_bytes(self, revision: str, path: str) -> bytes | None:
        # Fixture builders generally read one private object and then live for
        # the whole rollout. A one-shot process avoids retaining two cat-file
        # workers per task while the streaming path remains available for the
        # provenance resolver's thousands of historical text reads.
        result = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=self.root,
            capture_output=True,
        )
        return result.stdout if result.returncode == 0 else None

    def archive(self, revision: str, *, exclude: tuple[str, ...] = ()) -> bytes:
        command = ["git", "archive", "--format=tar", revision, "--", "."]
        command.extend(f":(exclude){path}" for path in exclude)
        result = subprocess.run(command, cwd=self.root, capture_output=True)
        if result.returncode != 0:
            raise GitError(
                result.stderr.decode(errors="replace").strip() or "git archive failed"
            )
        return result.stdout

    @functools.lru_cache(maxsize=8192)
    def history(self, path: str, revision: str = "HEAD") -> tuple[str, ...]:
        result = self.run(
            "log", "--follow", "--format=%H", revision, "--", path, check=False
        )
        if result.returncode != 0:
            return ()
        return tuple(line for line in result.stdout.splitlines() if line)

    @functools.lru_cache(maxsize=8192)
    def pickaxe(self, path: str, text: str, revision: str = "HEAD") -> tuple[str, ...]:
        """Find commits where the number of exact occurrences changed."""
        result = self.run(
            "log", "--format=%H", f"-S{text}", revision, "--", path, check=False
        )
        if result.returncode != 0:
            return ()
        return tuple(line for line in result.stdout.splitlines() if line)

    @functools.lru_cache(maxsize=32)
    def latest_commits_under(self, path: str, revision: str = "HEAD") -> dict[str, str]:
        """Return each current path's newest touching commit in one Git walk."""
        marker = "__DECOMP_COMMIT__"
        result = self.run(
            "log",
            f"--format={marker}%H",
            "--name-only",
            revision,
            "--",
            path,
            check=False,
        )
        if result.returncode != 0:
            return {}
        current: str | None = None
        latest: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if line.startswith(marker):
                current = line.removeprefix(marker)
            elif line and current is not None:
                latest.setdefault(line, current)
        return latest

    @functools.lru_cache(maxsize=8192)
    def parent(self, revision: str) -> str | None:
        result = self.run("rev-parse", f"{revision}^", check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    @functools.lru_cache(maxsize=8192)
    def exists(self, revision: str, path: str) -> bool:
        return self.object_id(revision, path) is not None

    def resolve(self, revision: str) -> str:
        return self.run("rev-parse", revision).stdout.strip()

    def _batch_check(self) -> subprocess.Popen[bytes]:
        process = self._batch_check_process
        if process is None or process.poll() is not None:
            process = subprocess.Popen(
                ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                cwd=self.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._batch_check_process = process
        return process

    def _batch_read(self) -> subprocess.Popen[bytes]:
        process = self._batch_read_process
        if process is None or process.poll() is not None:
            process = subprocess.Popen(
                ["git", "cat-file", "--batch"],
                cwd=self.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._batch_read_process = process
        return process

    def _read_batch_object(self, object_id: str) -> bytes | None:
        with self._batch_read_lock:
            process = self._batch_read()
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(object_id.encode() + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().decode(errors="replace").strip()
            fields = header.split()
            if len(fields) != 3 or fields[1] != "blob":
                return None
            size = int(fields[2])
            data = process.stdout.read(size)
            process.stdout.read(1)
            return data

    @functools.lru_cache(maxsize=8192)
    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return (
            self.run(
                "merge-base", "--is-ancestor", ancestor, descendant, check=False
            ).returncode
            == 0
        )
