"""Bounded foreground wait: a hard-mounted NFS outage stays in a child process."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading


def restore(cold, sha):
    requests=cold.data/'archive-requests';requests.mkdir(exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='restore-',dir=requests));receipt=work/'result.json'
    process=subprocess.Popen([sys.executable,'-m','src.evidence.cold_io',str(cold.data),sha,str(receipt)],
        cwd=Path(__file__).resolve().parents[2],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    def cleanup():
        process.wait();shutil.rmtree(work,ignore_errors=True)
    try:
        process.wait(timeout=(cold.policy or {}).get('restoreTimeoutSeconds',30))
    except subprocess.TimeoutExpired:
        process.kill()
        # A hard NFS mount can keep even SIGKILL pending. Never wait for it in
        # an HTTP handler; its object lock also prevents duplicate restores.
        threading.Thread(target=cleanup,daemon=True).start()
        raise TimeoutError('Archive restoration timed out; local execution remains available') from None
    try:
        if not receipt.exists():raise OSError('Archive restore worker exited without a receipt')
        result=json.loads(receipt.read_text())
        if result.get('error'):
            kind={'ValueError':ValueError,'FileNotFoundError':FileNotFoundError,'TimeoutError':TimeoutError}.get(result['kind'],OSError)
            raise kind(result['error'])
    finally:shutil.rmtree(work,ignore_errors=True)


if __name__=='__main__':
    from .cold import ColdArchive
    from .objects import atomic_json
    data,sha,receipt=sys.argv[1:]
    try:
        ColdArchive(data)._restore(sha);result={'ok':True}
    except Exception as error:result={'error':str(error)[:500],'kind':type(error).__name__}
    atomic_json(receipt,result)
