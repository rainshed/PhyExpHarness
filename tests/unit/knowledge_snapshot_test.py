"""Regress a live controller surviving a rebuild of the generated SDK reference."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.control.knowledge import KnowledgePack
from src.control.service import ControlService
from src.control.store import Refused

ROOT=Path(__file__).resolve().parents[2]


class KnowledgeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.reference=self.root/'source/knowledge/plugin-sdk/reference'
        shutil.copytree(ROOT/'knowledge/plugin-sdk/reference',self.reference)
        self.service=ControlService(ROOT,self.root/'data',self.root/'quantum','http://127.0.0.1:1')
        self.service.source=self.root/'source'
        shutil.copytree(ROOT/'templates/harness/default',self.service.source/'templates/harness/default')
        (self.service.source/'schemas/execution').mkdir(parents=True)
        shutil.copyfile(ROOT/'schemas/execution/process-resources.json',self.service.source/'schemas/execution/process-resources.json')
        task=self.root/'quantum/harbor_tasks/time_budgeted_hamlearn_10q'
        task.mkdir(parents=True)
        (task/'task.toml').write_text('[agent]\ntimeout_sec = 3600\n')
        self.old_id=self.service.knowledge.manifest['id']
        self.config={'name':'Snapshot regression','solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
                     'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},
                     'tasks':['time_budgeted_hamlearn_10q'],'wallTimeSeconds':7200,'concurrency':1}
        self.composition=patch('src.control.service.freeze_meta',return_value={})
        self.operation=patch.object(self.service,'_operation',return_value={})
        self.composition.start();self.operation.start()

    def tearDown(self):
        self.operation.stop();self.composition.stop()
        self.service.pool.shutdown(wait=True)
        self.temp.cleanup()

    def rebuild(self):
        manifest=json.loads((self.reference/'manifest.json').read_text())
        document=self.reference/manifest['documents']['overview']['file']
        document.write_text('Updated SDK reference\n')
        manifest['documents']['overview']['sha256']=hashlib.sha256(document.read_bytes()).hexdigest()
        manifest.pop('id')
        manifest['id']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        (self.reference/'manifest.json').write_text(json.dumps(manifest))
        return manifest['id']

    def test_live_create_uses_current_verified_pack_and_history_stays_pinned(self):
        first=self.service.create(self.config,'first')
        updated=self.rebuild()
        second=self.service.create(self.config,'second')
        self.assertNotEqual(updated,self.old_id)
        self.assertEqual(first['config']['knowledgePackId'],self.old_id)
        self.assertEqual(second['config']['knowledgePackId'],updated)
        self.assertEqual(self.service.knowledge_for(first['id']).manifest['id'],self.old_id)
        self.assertEqual(self.service.knowledge_for(second['id']).read('overview')['text'],'Updated SDK reference\n')
        shutil.rmtree(self.reference)
        # A response lost after create may be retried even when the working source is absent.
        self.assertEqual(self.service.create(self.config,'second')['id'],second['id'])
        self.assertEqual(len(self.service.store.list('campaigns')),2)

    def test_incomplete_rebuild_fails_before_persisting_campaign_or_partial_pack(self):
        (self.reference/'overview.txt').write_text('Partial rebuild')
        with self.assertRaisesRegex(Refused,'未创建活动'):
            self.service.create(self.config,'retry')
        self.assertEqual(self.service.store.list('campaigns'),[])
        self.assertEqual(list((self.service.data/'knowledge-packs').iterdir()),[])
        updated=self.rebuild()
        self.assertEqual(self.service.create(self.config,'retry')['config']['knowledgePackId'],updated)
        self.assertEqual(len(self.service.store.list('campaigns')),1)

    def test_bad_existing_archive_is_rejected_without_rewriting_it(self):
        first=self.service.create(self.config,'first')
        path=self.service.data/'knowledge-packs'/self.old_id/'overview.txt'
        path.write_text('Damaged frozen document')
        with self.assertRaisesRegex(Refused,'未创建活动'):
            self.service.create(self.config,'second')
        self.assertEqual(path.read_text(),'Damaged frozen document')
        self.assertEqual([c['id'] for c in self.service.store.list('campaigns')],[first['id']])

    def test_snapshot_is_stable_after_source_changes_and_rejects_symlinks(self):
        pack=KnowledgePack(self.reference,'0.2.1-rc.2')
        frozen=pack.snapshot(self.root/'packs')
        self.rebuild()
        self.assertEqual(frozen.manifest['id'],self.old_id)
        self.assertNotEqual(frozen.read('overview')['text'],'Updated SDK reference\n')
        target=self.reference/'overview.txt';target.unlink();target.symlink_to(self.root/'outside')
        with self.assertRaisesRegex(ValueError,'escapes pack'):
            KnowledgePack(self.reference,'0.2.1-rc.2')
