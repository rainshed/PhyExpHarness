"""Real Docker regression for Runner preparation; no model or official task calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.control.runner_images import prepare_runner_image


def prepare(root, cache, log):
    with Path(log).open('a') as stream:
        return prepare_runner_image(root, cache, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    suffix = uuid.uuid4().hex[:12]
    tag = 'phyexp-runner:repro-'+suffix
    container = 'phyexp-runner-repro-'+suffix
    retained = set()
    report = {'modelRequests': 0, 'officialTasks': 0, 'containersStarted': 0, 'tag': tag}

    def docker(*arguments, check=True):
        return subprocess.run(['docker', *arguments], capture_output=True, text=True,
                              check=check, timeout=30)

    def inspect(reference):
        return docker('image', 'inspect', reference, '--format', '{{.Id}}').stdout.strip()

    def track(image):
        retained.add('phyexp-runner:retained-'+image.removeprefix('sha256:'))

    try:
        with tempfile.TemporaryDirectory(prefix='phyexp-runner-repro-') as temporary:
            temp = Path(temporary)
            bundles = []
            for name in ['candidate-a', 'candidate-b']:
                root = temp/name
                (root/'src/execution/runner').mkdir(parents=True)
                (root/'package.json').write_text('{}\n')
                (root/'package-lock.json').write_text('{}\n')
                (root/'src/execution/runner/Dockerfile').write_text(
                    f'FROM scratch\nLABEL phyexp.runner-repro={suffix}\nCOPY package.json /marker\n')
                shutil.copyfile(ROOT/'templates/standalone/install-runner.mjs', root/'install-runner.mjs')
                (root/'bundle.json').write_text(json.dumps({'id': name, 'runnerImage': tag}))
                bundles.append(root)
            with ProcessPoolExecutor(2) as pool:
                futures = [pool.submit(prepare, root, temp/'cache', output/f'prepare-{i}.log')
                           for i, root in enumerate(bundles)]
                prepared = [future.result(timeout=90) for future in futures]
            for item in prepared:
                track(item['image'])
            assert sorted(item['action'] for item in prepared) == ['built', 'reused'], prepared
            expected = prepared[0]['image']
            assert prepared[1]['image'] == expected
            report['concurrentPreparations'] = prepared
            time.sleep(1.1)
            with (output/'forced-rebuild.log').open('w') as log:
                subprocess.run(['node', 'install-runner.mjs'], cwd=bundles[0], stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=90)
            displaced = inspect(tag)
            track(displaced)
            report['forcedRebuildImage'] = displaced
            assert inspect(expected) == expected
            created = docker('create', '--pull=never', '--name', container, expected, '/never-executed')
            report['oldImageContainerCreated'] = bool(created.stdout.strip())
            docker('container', 'rm', container)
            restored = prepare(bundles[1], temp/'cache', output/'restore.log')
            assert restored['action'] == 'reused' and inspect(tag) == expected
            assert inspect(displaced) == displaced
            report['restoredPreparation'] = restored
            report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        docker('container', 'rm', container, check=False)
        # Only tags belonging to this unique synthetic image are removed.
        cleanup = [docker('image', 'rm', ref, check=False).returncode
                   for ref in [tag, *sorted(retained)]]
        report['cleanupReturnCodes'] = cleanup
        report['remainingTags'] = [
            ref for ref in [tag, *sorted(retained)]
            if docker('image', 'inspect', ref, check=False).returncode == 0]
        (output/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    if report['remainingTags']:
        raise RuntimeError('Synthetic image cleanup incomplete')
    print(json.dumps({'status': report['status'], 'evidence': str(output/'result.json')}))


if __name__ == '__main__':
    main()
