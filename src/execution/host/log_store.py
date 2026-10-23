"""Read the same complete logical logs as the host writer, including crash windows."""
import gzip
import hashlib
import io
import json
from pathlib import Path


def read_log(file):
    file=Path(file);folder=Path(str(file)+'.segments');index_file=folder/'index.json'
    if not index_file.exists():return file.read_bytes()
    if folder.is_symlink() or index_file.is_symlink():raise ValueError('Invalid log index path')
    for _ in range(4):
        revision=index_file.read_bytes();index=json.loads(revision)
        if index.get('version')!='segmented-log-v1':raise ValueError('Invalid segmented log')
        parts=[]
        for i,segment in enumerate(index['segments']):
            if segment['name']!=f'{i:08d}.gz' or type(segment['bytes']) is not int or not 0<=segment['bytes']<=256*1024**2:raise ValueError('Invalid segment identity')
            path=folder/segment['name']
            if path.is_symlink():raise ValueError('Invalid segment path')
            compressed=path.read_bytes()
            if hashlib.sha256(compressed).hexdigest()!=segment['storedSha256']:raise ValueError('Compressed log segment damaged')
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:raw=stream.read(segment['bytes']+1)
            if len(raw)!=segment['bytes'] or hashlib.sha256(raw).hexdigest()!=segment['sha256']:raise ValueError('Log content damaged')
            parts.append(raw)
        tail=file.read_bytes()
        pending=index.get('pending')
        if pending and tail:
            n=pending['bytes']
            if len(tail)<n or hashlib.sha256(tail[:n]).hexdigest()!=pending['sha256']:
                if index_file.read_bytes()!=revision:continue
                raise ValueError('Interrupted log rotation inconsistent')
            tail=tail[n:]
        parts.append(tail)
        if index_file.read_bytes()==revision:return b''.join(parts)
    raise ValueError('Log changed during reading; retry')
