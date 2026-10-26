"""Batch projection for the single-host NFS deployment's immutable active views."""
import mimetypes
import os
import re
import stat
from pathlib import Path
from .cold import ColdArchive
from .objects import Objects
from .files import VERSION
from src.control.store import Refused


class EvidenceViews:
    def __init__(self, files, campaign):
        self.files=files;self.campaign=campaign
        self.root=files.directory(campaign)/'evidence'
        self.objects=Objects(files.service.data);self.cold=ColdArchive(files.service.data)
        self.directories=set()

    def directory(self, path):
        if path not in self.directories:
            path.mkdir(parents=True,exist_ok=True)
            if path.resolve()!=path.absolute():raise Refused('Evidence directory traverses a symlink')
            self.directories.add(path)

    def project(self, row):
        if row['campaignId']!=self.campaign:raise Refused('Cross-Campaign evidence')
        sha=row['sha256']
        if not re.fullmatch('[0-9a-f]{64}',sha):raise Refused('Invalid evidence digest')
        source=self.objects.path(sha)
        if Path(row['path'])!=source:raise Refused('Evidence object identity mismatch')
        trial=row.get('trialId')
        if trial and (Path(trial).name!=trial or trial in ('.','..')):raise Refused('Invalid evidence trial identity')
        suffix=Path(str(row.get('source',{}).get('archive',''))).suffix
        if not re.fullmatch(r'\.[a-zA-Z0-9]{1,12}',suffix):suffix='.txt'
        relative=Path('trials')/trial/(sha+suffix) if trial else Path('objects')/(sha+suffix)
        target=self.root/relative
        self.directory(target.parent)
        # Check each object shard's ancestry once, never follow a body symlink.
        self.directory(source.parent)
        try:original=source.lstat();published=target.lstat()
        except FileNotFoundError:
            # Existing archive restoration and eviction use this same local lock.
            self.cold.materialize(sha)
            with self.cold.lock(sha):
                original=source.lstat()
                if not stat.S_ISREG(original.st_mode):raise Refused('Evidence object is not a regular file')
                try:os.link(source,target,follow_symlinks=False)
                except FileExistsError:pass
                published=target.lstat()
        if not stat.S_ISREG(original.st_mode) or not stat.S_ISREG(published.st_mode):raise Refused('Evidence view is not a regular file')
        if (original.st_dev,original.st_ino)!=(published.st_dev,published.st_ino) or published.st_size!=row['bytes']:
            raise Refused('Evidence view identity mismatch')
        # Active campaign views are deliberately excluded from archive eviction.
        # Their hard links pin the inode; a per-row archive DB write is unnecessary.
        return {'ref':'evidence:'+row['id'],'kind':'evidence','campaignId':self.campaign,'trialId':trial,
            'path':'/evidence/'+relative.as_posix(),'mediaType':mimetypes.guess_type('file'+suffix)[0] or 'application/octet-stream',
            'encoding':'binary' if suffix=='.gz' else row.get('encoding','utf-8'),'bytes':row['bytes'],'sha256':sha,
            'source':row['source'],'version':row['policy'],'viewVersion':VERSION,'availability':'available',
            'completeness':'complete','observedAt':self.files.store.clock(),**({'storageEncoding':'gzip'} if suffix=='.gz' else {})}
