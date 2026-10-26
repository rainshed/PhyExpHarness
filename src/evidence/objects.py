from src.execution.host.storage_layout import lock_path, managed
"""Immutable, content-addressed artifact bodies; paths are read-only reference views."""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

POLICY = 'shared-artifacts-v1'


def enabled(config):
    return config.get('storagePolicy') == POLICY


def digest_file(file):
    digest = hashlib.sha256()
    with Path(file).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(file, value):
    file = Path(file); file.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.publishing-', dir=file.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, file)
    finally:
        if os.path.exists(name): os.unlink(name)


class Objects:
    def __init__(self, data):
        self.root = Path(data) / 'artifacts' / 'sha256'

    @contextlib.contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (lock_path(self.root.parent / 'objects.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def path(self, sha):
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError('Invalid artifact identity')
        return self.root / sha[:2] / sha

    def _publish(self, chunks, expected=None):
        self.root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.publishing-', dir=self.root)
        sha = hashlib.sha256()
        try:
            with os.fdopen(fd, 'wb') as stream:
                for chunk in chunks: stream.write(chunk); sha.update(chunk)
                stream.flush(); os.fsync(stream.fileno())
            key = sha.hexdigest()
            if expected is not None and key != expected: raise ValueError('Artifact digest mismatch')
            target = self.path(key); target.parent.mkdir(exist_ok=True)
            os.chmod(name, 0o444)
            try: os.link(name, target)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or digest_file(target) != key:
                    raise ValueError('Stored artifact is damaged')
            return target
        finally:
            os.unlink(name)

    def put(self, data):
        with self.locked(): return self._publish([data])

    def share(self, source, expected=None):
        """Only call for a closed producer. Detect changes before replacing its view."""
        source = Path(source)
        if managed(source):
            return self._share_closed(source, expected)
        with self.locked():
            before = source.lstat()
            if not stat.S_ISREG(before.st_mode): raise ValueError('Archive source must be a regular file')
            with source.open('rb') as stream:
                target = self._publish(iter(lambda: stream.read(1024 * 1024), b''), expected)
            after = source.lstat()
            if (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns):
                raise ValueError('Archive source changed during publication')
            if not os.path.samefile(source, target):
                fd, pending = tempfile.mkstemp(prefix='.sharing-', dir=source.parent); os.close(fd); os.unlink(pending)
                try:
                    os.link(target, pending)  # EXDEV fails safely: no false deduplication claim.
                    os.replace(pending, source)
                finally:
                    if os.path.exists(pending): os.unlink(pending)
            return {'sha256': target.name, 'bytes': after.st_size}

    def _share_closed(self, source, expected):
        before = source.lstat()
        if not stat.S_ISREG(before.st_mode): raise ValueError('Archive source must be a regular file')
        sha = digest_file(source)
        if expected is not None and sha != expected: raise ValueError('Artifact digest mismatch')
        target = self.path(sha)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Verify bytes before taking the publication lock; no copy through local disk.
        if target.exists() and (target.is_symlink() or digest_file(target) != sha):
            raise ValueError('Stored artifact is damaged')
        with self.locked():
            after = source.lstat()
            if (before.st_ino,before.st_dev,before.st_size,before.st_mtime_ns) != (after.st_ino,after.st_dev,after.st_size,after.st_mtime_ns):
                raise ValueError('Archive source changed during publication')
            try: os.link(source,target)
            except FileExistsError: pass
            os.chmod(target,0o444)
            if not os.path.samefile(source,target):
                fd,pending=tempfile.mkstemp(prefix='.sharing-',dir=source.parent)
                os.close(fd);os.unlink(pending)
                try:
                    os.link(target,pending);os.replace(pending,source)
                finally:
                    if os.path.exists(pending):os.unlink(pending)
        return {'sha256':sha,'bytes':before.st_size}

    def archive(self, directory):
        """Called after producer exit and accounting; preserves the original byte layout."""
        directory = Path(directory).resolve(); marker = directory / 'artifact-archive.json'
        if marker.exists(): return json.loads(marker.read_text())
        official = directory / 'archive-manifest.json'
        expected = json.loads(official.read_text()).get('files', {}) if official.exists() else {}
        files = {}
        for source in sorted(directory.rglob('*')):
            if source.is_symlink(): raise ValueError('Archive contains a symbolic link')
            if not source.is_file() or source.name.startswith(('.sharing-', '.publishing-')): continue
            relative = source.relative_to(directory).as_posix()
            files[relative] = self.share(source, expected.get(relative, {}).get('sha256'))
        if set(expected) - set(files): raise ValueError('Official archive is incomplete')
        result = {'version': POLICY, 'files': files, 'complete': True}
        atomic_json(marker, result)
        return result

    def prune(self, protected, before):
        """Discover outside the publication lock; recheck every deletion inside it."""
        def eligible(file, temporary):
            try:info = file.lstat()
            except FileNotFoundError:return None
            return info if stat.S_ISREG(info.st_mode) and info.st_mtime < before and (temporary or info.st_nlink == 1) else None

        # An old reachability snapshot may retain garbage until the next pass,
        # but must never authorize deletion. Large directory scans must not hold
        # the lock shared by evidence publication, plugin saves and H0 creation.
        roots = protected() if callable(protected) else protected
        candidates = [(file, True) for file in self.root.glob('.publishing-*') if eligible(file, True)]
        candidates += [(file, False) for file in self.root.glob('*/*')
                       if re.fullmatch('[0-9a-f]{64}', file.name) and file.name not in roots and eligible(file, False)]
        removed = 0
        for start in range(0, len(candidates), 100):
            with self.locked():
                roots = protected() if callable(protected) else protected
                for file, temporary in candidates[start:start + 100]:
                    if not temporary and file.name in roots:continue
                    info = eligible(file, temporary)
                    if info is not None:
                        file.unlink(); removed += info.st_blocks * 512
        return removed
