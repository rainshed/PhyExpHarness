"""Read the same complete logical logs as the host writer, including crash windows."""
import gzip
import hashlib
import io
import json
import codecs
from pathlib import Path


def iter_log(file):
    """Yield a verified snapshot one segment at a time, without joining history."""
    file=Path(file);folder=Path(str(file)+'.segments');index_file=folder/'index.json'
    for _ in range(4):
        if folder.is_symlink() or index_file.is_symlink():raise ValueError('Invalid log index path')
        revision=index_file.read_bytes() if index_file.exists() else None
        index=json.loads(revision) if revision is not None else {'version':'segmented-log-v1','segments':[]}
        if index.get('version')!='segmented-log-v1':raise ValueError('Invalid segmented log')
        tail=file.read_bytes()
        if (index_file.read_bytes() if index_file.exists() else None)!=revision:continue
        pending=index.get('pending')
        if pending and tail:
            n=pending['bytes']
            if len(tail)<n or hashlib.sha256(tail[:n]).hexdigest()!=pending['sha256']:
                raise ValueError('Interrupted log rotation inconsistent')
            tail=tail[n:]
        break
    else:raise ValueError('Log changed during reading; retry')
    for i,segment in enumerate(index['segments']):
        if segment['name']!=f'{i:08d}.gz' or type(segment['bytes']) is not int or not 0<=segment['bytes']<=256*1024**2:raise ValueError('Invalid segment identity')
        path=folder/segment['name']
        if folder.is_symlink() or path.is_symlink():raise ValueError('Invalid segment path')
        compressed=path.read_bytes()
        if hashlib.sha256(compressed).hexdigest()!=segment['storedSha256']:raise ValueError('Compressed log segment damaged')
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:raw=stream.read(segment['bytes']+1)
        if len(raw)!=segment['bytes'] or hashlib.sha256(raw).hexdigest()!=segment['sha256']:raise ValueError('Log content damaged')
        yield raw
    yield tail


def iter_log_lines(file):
    decoder=codecs.getincrementaldecoder('utf-8')();pending=''
    for chunk in iter_log(file):
        lines=(pending+decoder.decode(chunk)).split('\n');pending=lines.pop()
        yield from lines
    pending+=decoder.decode(b'',final=True)
    if pending:yield pending


def read_log(file):
    """Compatibility for callers that explicitly need a complete bounded body."""
    return b''.join(iter_log(file))
