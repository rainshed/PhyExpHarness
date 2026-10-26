import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.execution.bundle.project import snapshot, source_tar, validate_artifact, freeze_project
from src.execution.bundle.manifest import resolve, infrastructure_identity, digest
from src.exporting.project import export_project

ROOT = Path(__file__).resolve().parents[2]


class ProjectTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.root = Path(t.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.spec = {'runContract': 'harbor-process-v1', 'entrypoint': ['run.sh'],
            'framework': {'name': 'arbitrary-framework', 'version': '1'}, 'profile': {'tools': ['custom']},
            'build': {'image': 'build-image', 'argv': ['/bin/sh', '-c', 'chmod +x run.sh'], 'locks': ['lock.json']},
            'plugins': [{'name': 'anything', 'capabilities': ['new-capability']}]}
        for name, value in {'harness.json': json.dumps(self.spec), 'lock.json': '{}',
                            'run.sh': '#!/bin/sh\nexit 0\n', 'task.txt': 'time_budgeted_hamlearn_10q'}.items():
            (self.source / name).write_text(value)
        self.artifact = self.root / 'artifact.tar'

    def frozen(self):
        self.artifact.write_bytes(source_tar(snapshot(self.source)[0]))
        with patch('src.execution.bundle.project.build', return_value=(self.artifact,
            {'artifactSha256': digest(self.artifact.read_bytes()), 'status': 'passed'})):
            return freeze_project(ROOT, self.root / 'objects', self.source, {'model': 'fixed'}, self.root / 'cache', io.StringIO(), {})

    def test_complete_project_identity_and_portable_sources(self):
        a = self.frozen(); resolved = resolve(a['path'])
        self.assertEqual(resolved.manifest['project'], self.spec)
        self.assertEqual(resolved.asset('candidate/task.txt').read_text(), 'time_budgeted_hamlearn_10q')
        self.spec['profile'] = {'sessions': 3}
        (self.source / 'harness.json').write_text(json.dumps(self.spec))
        b = self.frozen()
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(infrastructure_identity(a['manifest']), infrastructure_identity(b['manifest']))
        self.assertEqual(resolve(a['path']).manifest['project']['profile'], {'tools': ['custom']})

    def test_internal_source_link_allowed_escape_rejected(self):
        (self.source / 'internal').symlink_to('task.txt')
        self.assertEqual(snapshot(self.source)[0]['internal'], snapshot(self.source)[0]['task.txt'])
        (self.source / 'escape').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'escapes'): snapshot(self.source)

    def test_artifact_capacity_and_entrypoint(self):
        self.artifact.write_bytes(source_tar(snapshot(self.source)[0]))
        validate_artifact(self.artifact, ['run.sh'], 10000)
        with self.assertRaisesRegex(ValueError, 'capacity'): validate_artifact(self.artifact, ['run.sh'], 1)
        with self.assertRaisesRegex(ValueError, 'missing'): validate_artifact(self.artifact, ['missing'], 10000)

    def test_artifact_rejects_escape_and_device(self):
        for kind, target in [(tarfile.SYMTYPE, '/etc'), (tarfile.CHRTYPE, '')]:
            with tarfile.open(self.artifact, 'w') as archive:
                item = tarfile.TarInfo('run.sh'); item.type = kind; item.linkname = target; archive.addfile(item)
            with self.assertRaises(ValueError): validate_artifact(self.artifact, ['run.sh'], 10000)

    def test_docker_tar_root_directory_is_valid_but_root_links_are_rejected(self):
        for root_name in ('.', './'):
            with self.subTest(root_name=root_name):
                with tarfile.open(self.artifact, 'w') as archive:
                    root = tarfile.TarInfo(root_name); root.type = tarfile.DIRTYPE
                    archive.addfile(root)
                    entry = tarfile.TarInfo('./run.sh'); entry.size = 2
                    archive.addfile(entry, io.BytesIO(b'ok'))
                validate_artifact(self.artifact, ['run.sh'], 10000)
        with tarfile.open(self.artifact, 'w') as archive:
            root = tarfile.TarInfo('.'); root.type = tarfile.SYMTYPE; root.linkname = '/outside'
            archive.addfile(root)
        with self.assertRaisesRegex(ValueError, 'root must be a directory'):
            validate_artifact(self.artifact, ['run.sh'], 10000)

    def test_frozen_artifact_tampering_rejected(self):
        frozen = self.frozen(); artifact = resolve(frozen['path']).asset('candidate.tar')
        artifact.chmod(0o644); artifact.write_bytes(b'changed')
        with self.assertRaises(ValueError): resolve(frozen['path'])

    def test_export_is_self_contained_and_reports_whole_project_changes(self):
        from src.exporting.validate import relocate
        from src.execution.bundle.manifest import read_plugins
        from src.reporting.tables import plugin_changes
        a=self.frozen();record=export_project(a['path'],self.root/'exports')
        self.assertEqual(record['exporter']['format'],'harness-project-v3')
        import shutil
        shutil.rmtree(self.root/'objects');shutil.rmtree(self.source)
        proof=relocate(record,self.root/'relocated')
        self.assertEqual(proof['bundleId'],a['id'])
        self.assertEqual(proof['modelCalls'],0)
        self.assertIn('harness.json',read_plugins(record['path'],'.')['files'])
        old={'bundleId':'a','plugins':[], 'executionContract':'harbor-process-v1','project':{'framework':'a'},'candidateSources':'a'}
        new={**old,'bundleId':'b','project':{'framework':'b'},'candidateSources':'b'}
        self.assertEqual([x['kind'] for x in plugin_changes(old,new)],['project','sources'])

    def test_directory_links_executable_modes_and_dependency_free_project(self):
        directory=self.source/'implementation';directory.mkdir();entry=directory/'tool.sh';entry.write_text('#!/bin/sh\nexit 0\n');entry.chmod(0o755)
        (self.source/'alias').symlink_to('implementation',target_is_directory=True)
        self.spec['build']['locks']=[];(self.source/'harness.json').write_text(json.dumps(self.spec))
        files,_=snapshot(self.source);self.assertEqual(files['alias/tool.sh'],files['implementation/tool.sh'])
        with tarfile.open(fileobj=io.BytesIO(source_tar(files))) as archive:self.assertEqual(archive.getmember('alias/tool.sh').mode,0o755)
        (directory/'cycle').symlink_to('..',target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'cycle'):snapshot(self.source)
