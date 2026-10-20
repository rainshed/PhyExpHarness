import hashlib
import json
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from src.control.runner_images import INPUTS, prepare_runner_image


class RunnerImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root/'cache'
        self.tag = 'phyexp-runner:shared'
        self.refs = {}
        self.builds = 0
        self.commands = []
        self.unavailable = False
        self.build_failure = False
        self.a = self.bundle('a')
        self.b = self.bundle('b')
        self.patch = patch('src.control.runner_images.subprocess.run', side_effect=self.command)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.temp.cleanup)

    def bundle(self, name):
        root = self.root/name
        for filename in INPUTS:
            path = root/filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(filename)
        (root/'bundle.json').write_text(json.dumps({'id': name, 'runnerImage': self.tag}))
        return root

    def image(self, text):
        return 'sha256:'+hashlib.sha256(text.encode()).hexdigest()

    def command(self, args, **kwargs):
        self.commands.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            if self.unavailable:
                return subprocess.CompletedProcess(args, 1, '', 'Cannot connect to the Docker daemon')
            reference = args[3]
            value = self.refs.get(reference)
            if reference.startswith('sha256:') and reference in self.refs.values():
                value = reference
            return subprocess.CompletedProcess(args, 0 if value else 1, value or '', '' if value else 'No such image')
        if args[:2] == ['docker', 'info']:
            if self.unavailable:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, '29.8.2', '')
        if args[:3] == ['docker', 'image', 'tag']:
            self.assertIn(args[3], self.refs.values())
            self.refs[args[4]] = args[3]
        elif args == ['node', 'install-runner.mjs']:
            self.builds += 1
            time.sleep(.02)  # Allow competing preparations to enter the lock.
            if self.build_failure:
                raise subprocess.CalledProcessError(1, args)
            # Model the observed Docker behavior: an unreferenced old ID vanishes.
            self.refs[self.tag] = self.image('build-'+str(self.builds))
        else:
            self.fail('Unexpected command: '+str(args))
        return subprocess.CompletedProcess(args, 0, '', '')

    def prepare(self, bundle=None, log='installation.log'):
        with (self.root/log).open('a') as stream:
            return prepare_runner_image(bundle or self.a, self.cache, stream)

    def test_different_plugin_bundles_reuse_one_image(self):
        first = self.prepare(self.a)
        second = self.prepare(self.b)
        self.assertEqual(first['image'], second['image'])
        self.assertEqual(second['action'], 'reused')
        self.assertEqual(self.builds, 1)

    def test_concurrent_candidates_share_image_lock(self):
        start = threading.Barrier(2)

        def prepare(bundle, name):
            start.wait(timeout=3)
            return self.prepare(bundle, name)

        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(prepare, self.a, 'a.log')
            b = pool.submit(prepare, self.b, 'b.log')
            self.assertEqual(a.result(timeout=5)['image'], b.result(timeout=5)['image'])
        self.assertEqual(self.builds, 1)

    def test_first_preparation_preserves_existing_unreceipted_image(self):
        old = self.image('previous-installation')
        self.refs[self.tag] = old
        result = self.prepare()
        self.assertNotEqual(old, result['image'])
        self.assertIn(old, self.refs.values())
        self.assertIn(result['image'], self.refs.values())

    def test_changed_build_input_retains_previous_image(self):
        first = self.prepare()
        (self.b/'package.json').write_text('changed package metadata')
        second = self.prepare(self.b)
        self.assertNotEqual(first['image'], second['image'])
        self.assertEqual(self.refs[first['retainedTag']], first['image'])
        self.assertEqual(self.builds, 2)

    def test_moved_tag_restores_cached_image_and_preserves_displaced_image(self):
        first = self.prepare()
        displaced = self.image('external-build')
        self.refs[self.tag] = displaced
        second = self.prepare()
        self.assertEqual(second['image'], first['image'])
        self.assertEqual(self.refs[self.tag], first['image'])
        self.assertIn(displaced, self.refs.values())
        self.assertEqual(self.builds, 1)

    def test_deleted_tag_reuses_retained_image_without_rebuilding(self):
        first = self.prepare()
        del self.refs[self.tag]
        self.assertEqual(self.prepare()['image'], first['image'])
        self.assertEqual(self.builds, 1)

    def test_missing_cached_image_is_rebuilt(self):
        first = self.prepare()
        self.refs = {k: v for k, v in self.refs.items() if v != first['image']}
        second = self.prepare()
        self.assertNotEqual(first['image'], second['image'])
        self.assertEqual(self.builds, 2)

    def test_docker_unavailable_never_triggers_build(self):
        self.unavailable = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare()
        self.assertEqual(self.builds, 0)
        self.assertFalse(list(self.cache.glob('*.json')))

    def test_build_failure_keeps_old_image_and_publishes_no_receipt(self):
        old = self.image('old')
        self.refs[self.tag] = old
        self.build_failure = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare()
        self.assertIn(old, self.refs.values())
        self.assertFalse(list(self.cache.glob('*.json')))


if __name__ == '__main__':
    unittest.main()
