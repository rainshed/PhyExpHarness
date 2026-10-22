import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.control.history_storage import plan, apply, restore, eligible
from src.execution.bundle.freeze import freeze
from src.execution.bundle.manifest import verify
from src.exporting.project import export_project

ROOT = Path(__file__).resolve().parents[2]


class HistoryStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='phyexp history ')
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name).resolve()
        self.session = self.data / 'migration'
        self.recipe = json.loads((ROOT / 'recipes/h0-sol.json').read_text())
        self.bundles = [freeze(ROOT, self.data / 'objects/sha256',
                              {**self.recipe, 'notes': 'version-' + str(i)}, legacy=True) for i in range(3)]
        with closing(sqlite3.connect(self.data / 'control.sqlite')) as db, db:
            for table in ('campaigns', 'candidates', 'trials', 'meta_sessions', 'operations'):
                db.execute('CREATE TABLE ' + table + '(id TEXT PRIMARY KEY, data TEXT)')
            for i, bundle in enumerate(self.bundles):
                campaign = {'id': 'campaign-' + str(i), 'state': 'running' if i == 2 else 'finished'}
                candidate = {'id': 'candidate-' + str(i), 'campaignId': campaign['id'],
                             'bundleId': bundle['id'], 'bundlePath': bundle['path'], 'score': i}
                db.execute('INSERT INTO campaigns VALUES (?,?)', (campaign['id'], json.dumps(campaign)))
                db.execute('INSERT INTO candidates VALUES (?,?)', (candidate['id'], json.dumps(candidate)))
        for bundle in self.bundles:
            module = Path(bundle['path']) / 'node_modules/original'
            module.mkdir(parents=True);(module / 'index.js').write_text('reconstructible installation')
        self.original = {b['id']: {name: (Path(b['path']) / name).read_bytes()
                                   for name in ['bundle.json', *b['manifest']['files']]} for b in self.bundles}
        self.db_before = self.snapshot()
        self.addCleanup(patch.stopall)
        patch('src.control.history_storage.prepare_dependencies', side_effect=self.dependencies).start()
        self.preview = patch('src.control.history_storage._preview', return_value='checks/fixture').start()

    def snapshot(self):
        with closing(sqlite3.connect(self.data / 'control.sqlite')) as db, db:
            return {t: db.execute('SELECT * FROM ' + t + ' ORDER BY id').fetchall()
                    for t in ('campaigns', 'candidates', 'trials', 'meta_sessions', 'operations')}

    def dependencies(self, *_):
        root = self.data / 'cache/dependencies/fixture-generation'
        module = root / 'node_modules/fixture'
        module.mkdir(parents=True, exist_ok=True)
        (module / 'index.js').write_text('locked shared dependency')
        return root

    def test_closed_history_shares_payload_and_keeps_ids_paths_exports_and_database(self):
        pending = plan(self.data, self.session)
        self.assertEqual(len(pending['bundles']), 2)
        self.assertEqual(len(pending['excluded']), 1)
        result = apply(self.session)
        self.assertEqual(result['bundles'], 2)
        self.assertEqual(len(result['sharedInstallations']), 1)
        a, b, active = [Path(row['path']) for row in self.bundles]
        self.assertTrue(os.path.samefile(a / 'run.py', b / 'run.py'))
        self.assertEqual((a / 'node_modules').resolve(), (b / 'node_modules').resolve())
        self.assertFalse((active / 'node_modules').is_symlink())
        self.assertEqual(self.db_before, self.snapshot())
        for row in self.bundles:
            self.assertEqual(verify(row['path'])['id'], row['id'])
            self.assertEqual(self.original[row['id']], {p: (Path(row['path']) / p).read_bytes()
                                                       for p in self.original[row['id']]})
        exported = export_project(a, self.data / 'export')
        self.assertEqual(verify(exported['path'])['id'], self.bundles[0]['id'])
        self.assertFalse((Path(exported['path']) / 'node_modules').exists())
        self.assertEqual(apply(self.session), result)  # idempotent resume
        self.assertEqual(plan(self.data,self.data/'second-plan')['bundles'],[])

    def test_shared_bundle_referenced_by_open_campaign_is_excluded(self):
        with closing(sqlite3.connect(self.data / 'control.sqlite')) as db, db:
            row = {'id': 'shared', 'campaignId': 'campaign-2',
                   'bundleId': self.bundles[0]['id'], 'bundlePath': self.bundles[0]['path']}
            db.execute('INSERT INTO candidates VALUES (?,?)', ('shared', json.dumps(row)))
        self.assertEqual([b['bundleId'] for b in eligible(self.data)['bundles']], [self.bundles[1]['id']])

    def test_failed_native_check_keeps_old_installation_and_can_resume(self):
        plan(self.data, self.session)
        self.preview.side_effect = RuntimeError('native assembly failed')
        with self.assertRaises(RuntimeError):apply(self.session)
        for bundle in self.bundles:
            self.assertFalse((Path(bundle['path']) / 'node_modules').is_symlink())
            verify(bundle['path'])
        self.preview.side_effect = None
        self.assertEqual(apply(self.session)['bundles'], 2)

    def test_state_change_after_plan_blocks_before_mutation(self):
        plan(self.data, self.session)
        with closing(sqlite3.connect(self.data / 'control.sqlite')) as db, db:
            db.execute('UPDATE campaigns SET data=? WHERE id=?',
                       (json.dumps({'id': 'campaign-0', 'state': 'running'}), 'campaign-0'))
        with self.assertRaisesRegex(ValueError, 'no longer idle'):apply(self.session)
        self.assertFalse((Path(self.bundles[0]['path']) / 'node_modules').is_symlink())

    def test_source_restore_has_exact_bytes_and_separate_inodes(self):
        plan(self.data, self.session);apply(self.session)
        bundle = self.bundles[0]
        restore(self.session, bundle['id'])
        self.assertEqual(verify(bundle['path'])['id'], bundle['id'])
        self.assertEqual(self.original[bundle['id']], {p: (Path(bundle['path']) / p).read_bytes()
                                                     for p in self.original[bundle['id']]})
        self.assertFalse(os.path.samefile(Path(bundle['path']) / 'run.py', Path(self.bundles[1]['path']) / 'run.py'))
        self.assertEqual(self.db_before, self.snapshot())

    def test_corrupt_backup_refuses_restore(self):
        plan(self.data, self.session);apply(self.session)
        bundle = self.bundles[0]
        (self.session / 'backups' / (bundle['id'] + '.zip')).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Backup integrity'):restore(self.session, bundle['id'])
        verify(bundle['path'])

    def test_interruption_after_commit_keeps_old_cache_until_resume(self):
        pending=plan(self.data,self.session)
        remove=shutil.rmtree
        def interrupted(path,*args,**kwargs):
            if Path(path).parent==self.session/'quarantine':
                raise OSError('interrupted cleanup')
            return remove(path,*args,**kwargs)
        with patch('src.control.history_storage.shutil.rmtree',side_effect=interrupted):
            with self.assertRaisesRegex(OSError,'interrupted cleanup'):apply(self.session)
        first=pending['bundles'][0]
        journal=self.session/'entries'/(first['bundleId']+'.json')
        state=json.loads(journal.read_text())
        self.assertEqual(state['phase'],'committed')
        self.assertTrue((self.session/state['quarantine']).is_dir())
        self.assertTrue((Path(first['path'])/'node_modules').is_symlink())
        self.assertEqual(verify(first['path'])['id'],first['bundleId'])
        self.assertEqual(apply(self.session)['bundles'],2)
        self.assertFalse((self.session/state['quarantine']).exists())

    def test_direct_running_process_is_excluded_before_replacing_files(self):
        pending=plan(self.data,self.session)
        first=pending['bundles'][0]
        with patch('src.control.history_storage.subprocess.check_output',return_value='node '+first['path']+'/run.py'):
            with self.assertRaisesRegex(ValueError,'process still references'):apply(self.session)
        self.assertFalse((Path(first['path'])/'node_modules').is_symlink())
