import copy
import io
import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import project_bundle_test as base
from src.execution.bundle.plugin_reading import candidate_plugins, plugin_key, project_plugins, source_view, resolve_reference, _bytes
from src.execution.bundle.manifest import resolve
from src.execution.bundle.project import source_tar, snapshot, freeze_project
from src.execution.bundle.manifest import digest
from src.reporting.tables import build_tables, plugin_changes
from src.exporting.project import export_project
from src.control.inspection import plugin_source
from src.control.store import Store, Refused
from src.control.research import Research


class ProjectPluginReadingTests(unittest.TestCase):
    def frozen(self):
        contents, _ = snapshot(self.source)
        self.artifact.write_bytes(source_tar(contents))
        receipt = {'artifactSha256': digest(self.artifact.read_bytes()), 'status': 'passed',
                   'inputs': {'sourceModes': contents.modes}}
        with patch('src.execution.bundle.project.build', return_value=(self.artifact, receipt)):
            return freeze_project(base.ROOT, self.root/'objects', self.source, {}, self.root/'cache', io.StringIO(), {})

    def setUp(self):
        base.ProjectTests.setUp(self)
        self.spec['plugins'] = [{'name': 'clock', 'version': '1', 'path': 'plugins/clock', 'config': {}}]
        self.metadata = {'name': 'clock', 'version': '1', 'entry': 'index.mjs',
                         'displayName': '动态时钟', 'functionSummary': '更新剩余时间',
                         'mechanism': '装配时读取截止时间，不自动终止计算。', 'categories': ['prompt-context']}
        self.plugin = self.source / 'plugins/clock'; self.plugin.mkdir(parents=True)
        (self.plugin / 'index.mjs').write_text('export const clock = 1;')
        self.write_spec()
        _bytes.cache_clear()

    def write_spec(self):
        (self.source / 'harness.json').write_text(json.dumps(self.spec))
        (self.plugin / 'plugin.json').write_text(json.dumps(self.metadata))

    def candidate(self, frozen, legacy=True, id='candidate'):
        return {'id': id, 'bundleId': frozen['id'], 'bundlePath': frozen['path'],
                'plugins': copy.deepcopy(self.spec['plugins']) if legacy else frozen['plugins'],
                'executionContract': 'harbor-process-v1', 'project': copy.deepcopy(self.spec)}

    def test_freeze_to_reading_and_source_without_mutating_history(self):
        frozen = self.frozen(); candidate = self.candidate(frozen); before = copy.deepcopy(candidate)
        bundle_bytes = (Path(frozen['path']) / 'bundle.json').read_bytes()
        p = build_tables([candidate], [], [])['plugins'][0]
        self.assertEqual(p['displayName'], '动态时钟')
        self.assertEqual(p['functionSummary'], self.metadata['functionSummary'])
        self.assertEqual(p['mechanism'], self.metadata['mechanism'])
        self.assertEqual(p['categories'], ['prompt-context'])
        self.assertEqual(len(p['digest']), 64)
        self.assertEqual(frozen['plugins'][0]['digest'], p['digest'])
        self.assertEqual(source_view(candidate, p['id'], 'index.mjs')['content'], 'export const clock = 1;')
        self.assertEqual(source_view(candidate, plugin_key(candidate['plugins'][0]))['files'], ['index.mjs', 'plugin.json'])
        self.assertEqual(candidate, before)
        self.assertEqual((Path(frozen['path']) / 'bundle.json').read_bytes(), bundle_bytes)
        self.assertNotIn('digest', json.loads(bundle_bytes)['plugins'][0])

    def test_identity_separates_code_not_unrelated_project_or_config(self):
        a = self.candidate(self.frozen())
        self.spec['plugins'][0]['config'] = {'enabled': True}; self.write_spec()
        (self.source / 'run.sh').write_text('#!/bin/sh\nexit 1\n')
        b = self.candidate(self.frozen(), id='second')
        self.assertEqual(candidate_plugins(a)[0]['digest'], candidate_plugins(b)[0]['digest'])
        self.assertIn('configured', {x['kind'] for x in plugin_changes(a, b)})
        (self.plugin / 'index.mjs').write_text('export const clock = 2;')
        c = self.candidate(self.frozen(), id='third')
        self.assertNotEqual(candidate_plugins(a)[0]['digest'], candidate_plugins(c)[0]['digest'])
        self.assertEqual(len(build_tables([a, b, c], [], [])['plugins']), 2)
        self.assertIn('updated', {x['kind'] for x in plugin_changes(b, c)})

    def test_portable_export_source_after_original_store_removed(self):
        frozen = self.frozen(); before = project_plugins(frozen['path'])
        exported = export_project(frozen['path'], self.root / 'exports')
        shutil.rmtree(self.root / 'objects'); shutil.rmtree(self.source)
        candidate = self.candidate({**frozen, 'path': exported['path']})
        self.assertEqual(candidate_plugins(candidate)[0]['digest'], before[0]['digest'])
        self.assertIn('clock = 1', source_view(candidate, plugin_key(before[0]), 'index.mjs')['content'])
        self.assertEqual(resolve(exported['path']).manifest['id'], frozen['id'])

    def test_recorded_executable_mode_changes_plugin_identity(self):
        a = self.frozen(); (self.plugin/'index.mjs').chmod(0o755); b = self.frozen()
        self.assertNotEqual(a['plugins'][0]['digest'], b['plugins'][0]['digest'])

    def test_cache_never_reads_artifact_and_detects_tampering_or_missing_source(self):
        frozen = self.frozen(); candidate = self.candidate(frozen)
        _bytes.cache_clear(); original = Path.read_bytes
        def read(path):
            self.assertNotEqual(path.name, 'candidate.tar')
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            candidate_plugins(candidate); count = _bytes.cache_info().misses
            candidate_plugins(candidate)
            self.assertEqual(_bytes.cache_info().misses, count)
        source = resolve(frozen['path']).asset('candidate/plugins/clock/index.mjs')
        source.chmod(0o644); source.write_text('export const clock = 2;')
        self.assertEqual(candidate_plugins(candidate)[0]['readingStatus'], 'unavailable')
        with self.assertRaisesRegex(ValueError, 'mismatch'): source_view(candidate, plugin_key(candidate['plugins'][0]))
        source.unlink()
        self.assertEqual(candidate_plugins(candidate)[0]['readingStatus'], 'unavailable')

    def test_meta_materials_read_sources_without_scanning_built_artifact(self):
        from src.evidence.materials import Materials
        frozen=self.frozen();candidate=self.candidate(frozen)
        exported=export_project(frozen['path'],self.root/'exports')
        store=SimpleNamespace(get=lambda *_:{'id':'campaign'},list=lambda *_:[candidate])
        materials=Materials(SimpleNamespace(store=store))
        original=Path.read_bytes
        def read(path):
            self.assertNotEqual(path.name,'candidate.tar','Reading navigation must not revalidate the executable artifact')
            return original(path)
        for location in (frozen['path'],exported['path']):
            candidate['bundlePath']=location
            with patch.object(Path,'read_bytes',read):
                self.assertEqual(json.loads(materials._version(candidate))['bundleId'],frozen['id'])
                records=list(materials._records('campaign','plugin'))
                source=next(r for r in records if r['source']['asset']=='candidate/plugins/clock/index.mjs')
                self.assertEqual(source['_load'](),'export const clock = 1;')
        candidate['bundlePath']=frozen['path']
        resolved=resolve(frozen['path']);source=resolved.asset('candidate/plugins/clock/index.mjs')
        source.chmod(0o644);source.write_text('tampered')
        with self.assertRaisesRegex(ValueError,'mismatch'):
            materials._plugin(candidate,'candidate/plugins/clock/index.mjs')
        with self.assertRaises(Refused):materials._plugin(candidate,'candidate/../recipe.json')

    def test_missing_metadata_and_undeclared_path_remain_readable(self):
        (self.plugin / 'plugin.json').unlink()
        a = self.candidate(self.frozen())
        p = build_tables([a], [], [])['plugins'][0]
        self.assertEqual(p['categories'], []); self.assertEqual(p['functionSummary'], '功能说明尚未提供')
        self.assertEqual(source_view(a, p['id'])['files'], ['index.mjs'])
        self.spec['plugins'][0].pop('path'); self.write_spec()
        a = self.candidate(self.frozen()); (self.source / 'run.sh').write_text('other')
        b = self.candidate(self.frozen(), id='b')
        self.assertEqual(len(build_tables([a, b], [], [])['plugins']), 2)
        self.assertIsNone(candidate_plugins(a)[0]['digest'])

    def test_invalid_metadata_or_unsafe_paths_do_not_block_freeze(self):
        for value in ['../escape', '/etc', 'missing']:
            self.spec['plugins'][0]['path'] = value; self.write_spec()
            frozen = self.frozen()
            self.assertEqual(frozen['plugins'][0]['readingStatus'], 'unavailable')
        self.spec['plugins'][0]['path'] = 'plugins/clock'; self.metadata['name'] = 'different'; self.write_spec()
        self.assertEqual(self.frozen()['plugins'][0]['readingStatus'], 'unavailable')

    def test_nested_source_and_file_path_cannot_escape_plugin(self):
        (self.plugin/'nested').mkdir(); (self.plugin/'nested/a.txt').write_text('nested')
        candidate = self.candidate(self.frozen()); key = plugin_key(candidate_plugins(candidate)[0])
        result = source_view(candidate, key, 'nested/a.txt')
        self.assertTrue(Path(result['directory'], 'nested/a.txt').exists())
        for name in ['../../harness.json', '/etc/passwd', 'harness.json']:
            with self.assertRaises(ValueError): source_view(candidate, key, name)

    def test_user_source_route_reports_unavailable_not_keyerror(self):
        frozen = self.frozen()
        target = self.root/'objects/sha256'; target.mkdir()
        for path in list((self.root/'objects').iterdir()):
            if path != target: shutil.move(str(path), target/path.name)
        candidate = self.candidate({**frozen, 'path': str(target/frozen['id'])})
        service = SimpleNamespace(data=self.root, store=SimpleNamespace(get=lambda *_: candidate))
        key = plugin_key(candidate['plugins'][0])
        self.assertEqual(plugin_source(service, candidate['id'], key)['files'], ['index.mjs', 'plugin.json'])
        with self.assertRaises(Refused): plugin_source(service, candidate['id'], key, '../outside')

    def test_ambiguous_old_key_cannot_choose_an_unrelated_source(self):
        second = self.source/'plugins/other'; shutil.copytree(self.plugin, second)
        (second/'index.mjs').write_text('export const clock = 2;')
        self.spec['plugins'].append({**self.spec['plugins'][0], 'path':'plugins/other'})
        self.write_spec(); candidate = self.candidate(self.frozen())
        old_key = plugin_key(candidate['plugins'][0])
        self.assertIsNone(resolve_reference(candidate, old_key))
        with self.assertRaisesRegex(ValueError, 'unambiguous'): source_view(candidate, old_key)
        p = candidate_plugins(candidate)[1]
        self.assertIn('clock = 2', source_view(candidate, plugin_key(p), 'index.mjs')['content'])

    def test_candidate_scoped_history_links_and_validation_preserve_stored_records(self):
        store = Store(self.root/'control.sqlite'); research = Research(store, self.root)
        model = {'provider': 'openai-codex', 'model': 'gpt-6-sol', 'reasoningEffort': 'medium'}
        campaign = store.create({'solver':model, 'meta':model, 'tasks':['time_budgeted_hamlearn_10q'],
                                 'wallTimeSeconds':1000, 'concurrency':1}, 'fixture')['id']
        frozen = self.frozen()
        a = store.candidate(campaign, {**frozen, 'plugins':copy.deepcopy(self.spec['plugins'])}, 'old')
        old_key = plugin_key(a['plugins'][0]); new_key = plugin_key(candidate_plugins(a)[0])
        record = {'kind':'motivation', 'state':'proposed', 'summary':'测试动机', 'problem':'时间未知',
                  'hypothesis':'时钟有帮助', 'change':'加入提示', 'validation':'测试', 'limitations':[],
                  'nextStep':'验证', 'factAt':store.clock(), 'plugins':[{'candidateId':a['id'], 'pluginKey':old_key}]}
        saved = research.save(campaign, record, 0, 'old', author='user')
        # Simulate the pre-fix link's null digest identity.
        link = store.put('research_links', {'id':'legacy-link','campaignId':campaign,'candidateId':a['id'],
                         'bundleId':a['bundleId'], 'recordId':saved['recordId'], 'recordRevision':1,
                         'recordedAt':store.clock(), 'plugins':[{'pluginKey':old_key,'digest':None}]})
        before = store.list('research_records',campaign), store.list('research_links',campaign)
        (self.plugin/'index.mjs').write_text('export const clock = 2;')
        other = self.frozen(); b = store.candidate(campaign, {**other, 'plugins':copy.deepcopy(self.spec['plugins'])}, 'other')
        self.assertEqual(research.overview(campaign, pluginKey=new_key)['total'], 1)
        self.assertEqual(research.overview(campaign, pluginKey=plugin_key(candidate_plugins(b)[0]))['total'], 0)
        detail = research.detail(campaign,saved['recordId'],1)
        self.assertEqual(detail['record']['plugins'][0]['pluginKey'], new_key)
        self.assertEqual(detail['record']['plugins'][0]['storedPluginKey'], old_key)
        self.assertEqual(detail['candidateLinks'][0]['plugins'][0]['pluginKey'], new_key)
        self.assertEqual(before, (store.list('research_records',campaign), store.list('research_links',campaign)))
        research.save(campaign, {**record,'plugins':[{'candidateId':a['id'],'pluginKey':new_key}]}, 0, 'current', author='user')
        with self.assertRaises(Refused):
            research.save(campaign, {**record,'plugins':[{'candidateId':b['id'],'pluginKey':new_key}]}, 0, 'wrong', author='user')
