"""Prepare shared Runner images without invalidating IDs already used by Trials."""
import fcntl
import hashlib
import json
import re
import subprocess
from pathlib import Path

from src.execution.host.single_run import write_json

INPUTS = ('package.json', 'package-lock.json', 'src/execution/runner/Dockerfile',
          'install-runner.mjs')


def _image_id(reference):
    result = subprocess.run(['docker', 'image', 'inspect', reference, '--format', '{{.Id}}'],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        # An inaccessible engine is not a cache miss and must not trigger a build.
        subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                       capture_output=True, text=True, check=True, timeout=10)
        if any(text in result.stderr.lower() for text in ('no such image', 'no such object')):
            return None
        raise ValueError('Cannot inspect Runner image: '+reference)
    image = result.stdout.strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('Invalid Runner image identity: '+reference)
    return image


def prepare_runner_image(bundle_path, cache, log):
    """Cache verified build inputs, serialize by shared tag, and retain exact IDs.

    Receipts are platform state, not changes to the frozen Bundle. Retained tags
    are intentionally not removed here: a different Campaign may still use them.
    """
    root, cache = Path(bundle_path), Path(cache)
    tag = json.loads((root/'bundle.json').read_text())['runnerImage']
    if not re.fullmatch(r'phyexp-runner:[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}', tag):
        raise ValueError('Invalid Runner image tag')
    inputs = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in INPUTS}
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    # Different plugin Bundles share a tag; locking by Bundle ID is insufficient.
    lock_key = hashlib.sha256(tag.encode()).hexdigest()
    with (cache/(lock_key+'.lock')).open('a') as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        receipt = cache/(lock_key+'-'+key+'.json')

        def command(args, **kwargs):
            log.write('$ '+json.dumps(args)+'\n'); log.flush()
            subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=True,
                           timeout=300, **kwargs)

        def retain(image):
            reference = 'phyexp-runner:retained-'+image.removeprefix('sha256:')
            command(['docker', 'image', 'tag', image, reference])
            return reference

        current = _image_id(tag)
        stored = json.loads(receipt.read_text()) if receipt.is_file() else None
        expected = None
        if stored:
            if stored.get('schemaVersion') != 1 or stored.get('inputs') != inputs or stored.get('tag') != tag:
                raise ValueError('Runner image preparation receipt mismatch')
            expected = stored['image']
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', expected):
                raise ValueError('Invalid cached Runner image identity')
            if _image_id(expected) != expected:
                expected = None
        if expected:
            retained = retain(expected)
            if current != expected:
                if current:
                    retain(current)
                command(['docker', 'image', 'tag', expected, tag])
            action = 'reused'
        else:
            # Preserve the previous tag target before any build moves that tag,
            # including the first migration from installations without receipts.
            if current:
                retain(current)
            command(['node', 'install-runner.mjs'], cwd=root)
            expected = _image_id(tag)
            if not expected:
                raise ValueError('Runner build did not produce the expected image')
            retained = retain(expected)
            action = 'built'
        if _image_id(tag) != expected or _image_id(retained) != expected:
            raise ValueError('Runner image changed during preparation')
        result = {'schemaVersion': 1, 'inputs': inputs, 'image': expected,
                  'tag': tag, 'retainedTag': retained}
        write_json(receipt, result)
        log.write(f'Runner image {action}: {tag} {expected}\n'); log.flush()
        return {**result, 'action': action}
