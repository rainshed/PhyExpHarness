import hashlib
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path
from src.evidence.objects import Objects


class ArtifactObjectsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.objects=Objects(self.root)

    def test_closed_archive_and_evidence_share_bytes_and_keep_original_manifest(self):
        raw=self.root/'trial';raw.mkdir();file=raw/'result.json';file.write_bytes(b'complete result')
        sha=hashlib.sha256(file.read_bytes()).hexdigest()
        manifest={'files':{'result.json':{'sha256':sha,'bytes':file.stat().st_size}}}
        (raw/'archive-manifest.json').write_text(json.dumps(manifest))
        obj=self.objects.put(file.read_bytes());record=self.objects.archive(raw)
        self.assertTrue(os.path.samefile(obj,file));self.assertEqual(record['files']['result.json']['sha256'],sha)
        self.assertEqual(json.loads((raw/'archive-manifest.json').read_text()),manifest)
        self.assertEqual(self.objects.archive(raw),record)
        self.assertEqual(self.objects.prune(set(),time.time()+1),0)

    def test_damage_and_wrong_expected_digest_never_replace_source(self):
        file=self.root/'raw';file.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'digest'):self.objects.share(file,'0'*64)
        self.assertEqual(file.read_bytes(),b'keep')
        obj=self.objects.put(b'keep');obj.chmod(0o600);obj.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'damaged'):self.objects.put(b'keep')
        self.assertEqual(file.read_bytes(),b'keep')

    def test_only_unreferenced_old_objects_are_collected(self):
        a=self.objects.put(b'protected');b=self.objects.put(b'garbage');c=self.objects.put(b'view')
        os.link(c,self.root/'view')
        self.objects.prune({a.name},time.time()-1);self.assertTrue(b.exists())
        self.objects.prune({a.name},time.time()+1)
        self.assertTrue(a.exists());self.assertFalse(b.exists());self.assertTrue(c.exists())

    def test_stale_publish_temporary_file_is_removed_but_recent_and_links_survive(self):
        self.objects.put(b'initialize')
        stale=self.objects.root/'.publishing-stale';stale.write_bytes(b'unfinished');os.utime(stale,(0,0))
        recent=self.objects.root/'.publishing-recent';recent.write_bytes(b'active')
        link=self.objects.root/'.publishing-link';link.symlink_to(recent)
        self.objects.prune(set(),time.time()-60)
        self.assertFalse(stale.exists());self.assertTrue(recent.exists());self.assertTrue(link.is_symlink())

    def test_directory_scan_does_not_block_concurrent_publication(self):
        original = Path.glob
        published = []
        with ThreadPoolExecutor(max_workers=1) as pool:
            def scan(path, pattern):
                if path == self.objects.root and pattern == '*/*':
                    published.append(pool.submit(Objects(self.root).put, b'during scan').result(timeout=2))
                yield from original(path, pattern)
            with patch.object(Path, 'glob', scan):
                self.objects.prune(set(), time.time() - 60)
        self.assertEqual(published[0].read_bytes(), b'during scan')

    def test_new_metadata_reference_after_discovery_prevents_deletion(self):
        obj = self.objects.put(b'new reference');calls = []
        def roots():
            calls.append(True)
            return set() if len(calls) == 1 else {obj.name}
        self.assertEqual(self.objects.prune(roots, time.time() + 1), 0)
        self.assertEqual(len(calls), 2);self.assertTrue(obj.exists())

    def test_concurrent_file_changes_are_rechecked_before_deletion(self):
        linked = self.objects.put(b'new link');recent = self.objects.put(b'renewed')
        gone = self.objects.put(b'collected elsewhere');replaced = self.objects.put(b'now a link')
        target = self.root/'outside';target.write_bytes(b'keep');calls = []
        before = time.time() + 1
        def roots():
            calls.append(True)
            if len(calls) == 2:
                os.link(linked, self.root/'view');os.utime(recent, (before + 1, before + 1))
                gone.unlink();replaced.unlink();replaced.symlink_to(target)
            return set()
        self.assertEqual(self.objects.prune(roots, before), 0)
        self.assertTrue(linked.exists());self.assertTrue(recent.exists())
        self.assertTrue(replaced.is_symlink());self.assertEqual(target.read_bytes(), b'keep')

    def test_each_collection_batch_refreshes_reachability(self):
        objects = [self.objects.put(str(n).encode()) for n in range(101)];calls = []
        def roots():
            calls.append(True)
            return {p.name for p in objects} if len(calls) == 3 else set()
        self.objects.prune(roots, time.time() + 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sum(p.exists() for p in objects), 1)

    def test_symlinks_and_missing_official_files_are_rejected(self):
        raw=self.root/'trial';raw.mkdir();(raw/'link').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'symbolic'):self.objects.archive(raw)
        (raw/'link').unlink();(raw/'archive-manifest.json').write_text(json.dumps({'files':{'missing':{'sha256':'0'*64}}}))
        with self.assertRaisesRegex(ValueError,'incomplete'):self.objects.archive(raw)
        self.assertFalse((raw/'artifact-archive.json').exists())
