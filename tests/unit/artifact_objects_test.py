import hashlib
import json
import os
import tempfile
import time
import unittest
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

    def test_symlinks_and_missing_official_files_are_rejected(self):
        raw=self.root/'trial';raw.mkdir();(raw/'link').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'symbolic'):self.objects.archive(raw)
        (raw/'link').unlink();(raw/'archive-manifest.json').write_text(json.dumps({'files':{'missing':{'sha256':'0'*64}}}))
        with self.assertRaisesRegex(ValueError,'incomplete'):self.objects.archive(raw)
        self.assertFalse((raw/'artifact-archive.json').exists())
