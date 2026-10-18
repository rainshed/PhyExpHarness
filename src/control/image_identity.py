"""Verify executable image identity separately from changing BuildKit attestations.

Raw index identities are preserved. Equivalence is only available when the actual
index and its single executable manifest can both be checked by SHA-256.
"""
import hashlib
import json
import subprocess
from pathlib import Path

INDEX = 'application/vnd.oci.image.index.v1+json'
MANIFEST = 'application/vnd.oci.image.manifest.v1+json'


def checked_identity(image_id, index_raw, manifest_raw):
    digest = lambda raw: 'sha256:'+hashlib.sha256(raw).hexdigest()
    if digest(index_raw) != image_id: raise ValueError('Image index hash mismatch')
    index = json.loads(index_raw)
    executable = [m for m in index['manifests'] if m.get('platform', {}).get('os') not in [None, 'unknown']
                  and m.get('annotations', {}).get('vnd.docker.reference.type') != 'attestation-manifest']
    if len(executable) != 1: raise ValueError('Ambiguous executable image platform')
    selected = executable[0]
    if selected['mediaType'] != MANIFEST or digest(manifest_raw) != selected['digest']:
        raise ValueError('Executable manifest hash mismatch')
    manifest = json.loads(manifest_raw)
    if not manifest.get('config', {}).get('digest') or not manifest.get('layers'):
        raise ValueError('Incomplete executable image manifest')
    return {'indexDigest': image_id, 'executionDigest': selected['digest'], 'platform': selected['platform'],
            'configDigest': manifest['config']['digest'], 'layerDigests': [x['digest'] for x in manifest['layers']]}


def resolve(image_id, directory):
    """Read local build evidence; absence never implies image equivalence."""
    if not isinstance(image_id,str) or not image_id.startswith('sha256:'): raise ValueError('Image identity unavailable')
    directory = Path(directory) / image_id.replace(':', '-')
    if (directory/'index.json').is_file() and (directory/'manifest.json').is_file():
        result = checked_identity(image_id, (directory/'index.json').read_bytes(), (directory/'manifest.json').read_bytes())
        return {**result, 'proofPath': str(directory)}
    command = lambda *args: subprocess.check_output(['docker','buildx','history',*args], stderr=subprocess.DEVNULL, timeout=5)
    refs = command('ls','--format','{{.Ref}}').decode().splitlines()
    for ref in refs[:100]:
        ref = ref.rsplit('/',1)[-1]
        record = json.loads(command('inspect','--format','json',ref))
        if not any(a.get('Digest') == image_id and a.get('Type') == INDEX for a in record.get('Attachments', [])): continue
        index_raw = command('inspect','attachment',ref,'--type',INDEX)
        index = json.loads(index_raw)
        platforms = [m['platform'] for m in index['manifests'] if m.get('platform',{}).get('os') not in [None,'unknown']]
        if len(platforms) != 1: raise ValueError('Ambiguous executable image platform')
        platform = platforms[0]['os']+'/'+platforms[0]['architecture']
        manifest_raw = command('inspect','attachment',ref,'--type',MANIFEST,'--platform',platform)
        result = checked_identity(image_id,index_raw,manifest_raw)
        directory.mkdir(parents=True,exist_ok=True)
        for name,raw in [('index.json',index_raw),('manifest.json',manifest_raw),('build-record.json',json.dumps(record,indent=2).encode())]:
            file=directory/name;file.write_bytes(raw);file.chmod(0o444)
        return {**result,'proofPath':str(directory)}
    raise ValueError('No verifiable build record for image index')
