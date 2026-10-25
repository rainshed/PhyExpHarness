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
        with (self.root.parent / 'objects.lock').open('a') as lock:
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
        """Metadata roots plus filesystem references; publication and collection share a lock."""
        removed = 0
        with self.locked():
            if callable(protected):protected=protected()
            for file in self.root.glob('.publishing-*'):
                info=file.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_mtime<before:
                    file.unlink();removed+=info.st_blocks*512
            for file in self.root.glob('*/*'):
                if file.is_symlink() or not re.fullmatch('[0-9a-f]{64}', file.name): continue
                info = file.stat()
                if file.name not in protected and info.st_nlink == 1 and info.st_mtime < before:
                    file.unlink(); removed += info.st_blocks * 512
        return removed
