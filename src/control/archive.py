"""One independent archive process; NFS stalls never hold the control tick."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from src.evidence.cold import ColdArchive
from src.evidence.objects import atomic_json

class Archives:
    def __init__(self, service):
        self.service=service;self.child=None;self.last=0
    def schedule(self):
        cold=ColdArchive(self.service.data)
        if not cold.configured() or time.time()-self.last<60:return
        if self.child and self.child.poll() is None:return
        lockfile=Path(self.service.data)/'archive-worker.lock'
        with lockfile.open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
        self.last=time.time()
        with (Path(self.service.data)/'archive-worker.log').open('a') as log:
            self.child=subprocess.Popen([sys.executable,'-m','src.control.archive',str(self.service.data)],
                cwd=self.service.source,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)

def work(data):
    from .store import Store
    data=Path(data);cold=ColdArchive(data)
    with (data/'archive-worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        lock.seek(0);lock.truncate();json.dump({'pid':os.getpid(),'startedAt':time.time()},lock);lock.flush()
        try:
            os.nice(10)
            atomic_json(cold.state,{'state':'running','pid':os.getpid(),'heartbeat':time.time()})
            cold.cycle(Store(data/'control.sqlite'))
        except Exception as error:
            atomic_json(cold.state,{'state':'retry','error':str(error)[:500],'finishedAt':time.time()})
            raise

if __name__=='__main__':work(sys.argv[1])
