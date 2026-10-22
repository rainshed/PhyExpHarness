import hashlib
import json
import subprocess
import unittest
from src.execution.host.single_run import validate_task_image_lock

class TaskImageLockTests(unittest.TestCase):
    def test_lock_rejects_source_changes_task_substitution_and_mutable_tags(self):
        sources={'src/a.py':'original'}
        lock={'task':'task','taskSourcesDigest':hashlib.sha256(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
              'images':{role:'sha256:'+'a'*64 for role in ['main','qsim','verifier']}}
        self.assertEqual(validate_task_image_lock(lock,'task',sources),lock['images'])
        for task,source in [('other',sources),('task',{'src/a.py':'changed'})]:
            self.assertRaises(ValueError,validate_task_image_lock,lock,task,source)
        lock['images']['qsim']='qiqcbench-qsim:latest'
        self.assertRaises(ValueError,validate_task_image_lock,lock,'task',sources)


# No daemon or models: emulate Docker identities while exercising real cache/files.
import tempfile
from pathlib import Path
from unittest.mock import patch
from src.control.task_images import POLICY, prepare_task_images, verify_locks, sources_digest, image_id
from src.control.store import PUBLIC_TASKS, Refused
from src.control.service import ControlService
from src.execution.host.single_run import task_image_sources

ROOT = Path(__file__).resolve().parents[2]


class ImageAvailabilityTests(unittest.TestCase):
    def test_existing_image_needs_no_extra_engine_probe(self):
        image = 'sha256:'+'a'*64
        with patch('src.control.task_images.subprocess.run', return_value=subprocess.CompletedProcess([], 0, image+'\n', '')) as run:
            self.assertEqual(image_id(image), image)
            self.assertEqual(run.call_count, 1)

    def test_stopped_engine_is_not_reported_as_missing_image(self):
        failure = subprocess.CompletedProcess([], 1, '', 'Cannot connect to the Docker daemon')
        with patch('src.control.task_images.subprocess.run', side_effect=[failure, failure]):
            with self.assertRaisesRegex(ValueError, '无法连接 Docker 引擎') as caught:
                image_id('sha256:'+'a'*64)
        self.assertNotIn('install', str(caught.exception))

    def test_missing_frozen_image_requires_the_exact_identity(self):
        failure = subprocess.CompletedProcess([], 1, '', 'Error response from daemon: No such image: fixture')
        engine = subprocess.CompletedProcess([], 0, '28.0\n', '')
        for reference, message in [('official:latest', 'install the official'), ('sha256:'+'a'*64, 'restore this exact frozen image')]:
            with self.subTest(reference=reference), patch('src.control.task_images.subprocess.run', side_effect=[failure, engine]):
                self.assertRaisesRegex(ValueError, message, image_id, reference)

    def test_other_inspect_failure_is_not_reported_as_missing_image(self):
        failure = subprocess.CompletedProcess([], 1, '', 'authorization denied')
        engine = subprocess.CompletedProcess([], 0, '28.0\n', '')
        with patch('src.control.task_images.subprocess.run', side_effect=[failure, engine]):
            self.assertRaisesRegex(ValueError, '无法检查任务镜像', image_id, 'official:latest')

    def test_missing_cli_and_timeouts_have_actionable_errors(self):
        for failure, message in [(FileNotFoundError(), '未找到 Docker 命令'),
                                 (subprocess.TimeoutExpired('docker', 30), '检查超时')]:
            with self.subTest(message=message), patch('src.control.task_images.subprocess.run', side_effect=failure):
                self.assertRaisesRegex(ValueError, message, image_id, 'official:latest')
        with patch('src.control.task_images.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 1, '', 'connection failed'),
                subprocess.TimeoutExpired('docker info', 10)]):
            self.assertRaisesRegex(ValueError, '检查超时', image_id, 'official:latest')


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.quantum = self.root/'quantum'
        self.images = {}
        self.commands = []
        self.add_image('qiqcbench-agent:latest')
        for task in PUBLIC_TASKS:
            folder = self.quantum/'harbor_tasks'/task
            (folder/'environment').mkdir(parents=True)
            (folder/'environment'/'Dockerfile').write_text('ARG AGENT_IMAGE\nFROM ${AGENT_IMAGE}\n')
            (folder/'task.toml').write_text('[verifier.environment]\ndocker_image="'+task+':latest"\n')
            (folder/'instruction.md').write_text(task)
            self.add_image(task+':latest')
        (self.quantum/'pyproject.toml').write_text('original build input')
        self.cache = self.root/'cache'
        self.log = self.root/'build.log'
        self.inspect = patch('src.control.task_images.image_id', side_effect=self.image_id).start()
        self.run = patch('src.control.task_images.subprocess.run', side_effect=self.command).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.tmp.cleanup)

    def add_image(self, name):
        value = 'sha256:'+hashlib.sha256((name+str(len(self.images))).encode()).hexdigest()
        self.images[name] = value
        self.images[value] = value
        return value

    def image_id(self, name):
        if name not in self.images: raise ValueError('Task image unavailable: '+name)
        return self.images[name]

    def command(self, args, **kwargs):
        self.commands.append(args)
        if args[1]=='build': self.add_image(args[args.index('-t')+1])
        elif args[1]=='tag': self.images[args[3]] = self.images[args[2]]
        else: raise AssertionError(args)

    def prepare(self, tasks=PUBLIC_TASKS, **kwargs):
        return prepare_task_images(self.quantum, tasks, self.cache, self.log, **kwargs)

    def builds(self):
        return [c for c in self.commands if c[1]=='build']

    def test_all_five_are_prepared_once_with_one_shared_qsim_and_reused(self):
        first = self.prepare()
        self.assertEqual(set(first), set(PUBLIC_TASKS))
        self.assertEqual(len(self.builds()), 6)
        self.assertEqual(len({v['images']['qsim'] for v in first.values()}), 1)
        self.assertEqual(len({c[c.index('-t')+1] for c in self.builds()}), 6)
        self.assertEqual(self.prepare(), first)
        self.assertEqual(len(self.builds()), 6)
        # A moved official verifier tag affects new preparations, never old locks.
        task = PUBLIC_TASKS[3]
        self.add_image(task+':latest')
        second = self.prepare()
        self.assertNotEqual(first[task]['images']['verifier'], second[task]['images']['verifier'])
        verify_locks(self.quantum, PUBLIC_TASKS, first)
        self.assertEqual(len(self.builds()), 6)

    def test_preflight_refuses_partial_missing_or_changed_locks_without_building(self):
        locks = self.prepare()
        count = len(self.builds())
        self.assertRaisesRegex(ValueError, 'not prepared', verify_locks, self.quantum, PUBLIC_TASKS, {})
        missing = locks[PUBLIC_TASKS[3]]['images']['qsim']
        del self.images[missing]
        self.assertRaisesRegex(ValueError, 'unavailable', verify_locks, self.quantum, PUBLIC_TASKS, locks)
        self.images[missing] = missing
        (self.quantum/'pyproject.toml').write_text('changed')
        self.assertRaisesRegex(ValueError, 'sources', verify_locks, self.quantum, PUBLIC_TASKS, locks)
        self.assertEqual(len(self.builds()), count)

    def test_sources_changing_during_build_never_publish_locks(self):
        digest = sources_digest(task_image_sources(self.quantum))
        def changing(args, **kwargs):
            self.command(args, **kwargs)
            if args[1]=='build': (self.quantum/'pyproject.toml').write_text('changed')
        self.run.side_effect = changing
        self.assertRaisesRegex(ValueError, 'sources', self.prepare, expected_sources_digest=digest)
        self.assertEqual(list(self.cache.glob('*.json')), [])
        self.assertRaisesRegex(ValueError, 'sources changed', self.prepare, expected_sources_digest=digest)

    def test_missing_verifier_fails_before_builds(self):
        del self.images[PUBLIC_TASKS[-1]+':latest']
        self.assertRaisesRegex(ValueError, 'unavailable', self.prepare)
        self.assertEqual(self.builds(), [])


class CampaignPreparationTests(unittest.TestCase):
    def setUp(self):
        self.meta=patch('src.control.service.freeze_meta',return_value={});self.meta.start();self.addCleanup(self.meta.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.service = ControlService(ROOT, self.data, ROOT.parent/'Quantum-Harbor', 'http://127.0.0.1:1')
        model = {'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
        self.config = {'solver':model,'meta':model,'tasks':list(PUBLIC_TASKS),'wallTimeSeconds':7200,'concurrency':1}
        digest = sources_digest(task_image_sources(self.service.quantum))
        self.locks = {task:{'schemaVersion':2,'task':task,'taskSourcesDigest':digest,
                           'images':{role:'sha256:'+'a'*64 for role in ['main','qsim','verifier']}}
                      for task in PUBLIC_TASKS}

    def tearDown(self):
        self.service.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def finish_operations(self):
        for future in list(self.service.operations.values()): future.result(timeout=10)

    def test_create_freezes_all_locks_before_h0_and_idempotent_replay_does_not_prepare_again(self):
        order = []
        def prepare(*args, **kwargs):
            order.append('images')
            self.assertEqual(list(args[1]), list(PUBLIC_TASKS))
            return self.locks
        def build(campaign, *args):
            order.append('h0')
            self.assertEqual(self.service.store.get('campaigns',campaign)['config']['taskImageLocks'], self.locks)
            return {'id':'fixture'}
        with patch('src.control.service.prepare_task_images',side_effect=prepare), patch.object(self.service,'build_candidate',side_effect=build):
            c = self.service.create(self.config, 'new')['id']
            self.finish_operations()
            replay = self.service.create(self.config, 'new')
        self.assertEqual(order, ['images','h0'])
        self.assertEqual(replay['id'], c)
        self.assertEqual(replay['config']['taskImagePolicy'], POLICY)
        self.assertEqual(replay['config']['taskImageLocks'], self.locks)
        self.assertEqual(self.service.store.list('operations', c)[0]['state'], 'finished')
        self.assertEqual(self.service.store.list('trials', c), [])

    def test_failed_preparation_never_builds_baseline_or_allows_start(self):
        with patch('src.control.service.prepare_task_images',side_effect=ValueError('missing verifier')), patch.object(self.service,'build_candidate') as build:
            c = self.service.create(self.config, 'failed')['id']
            self.finish_operations()
            build.assert_not_called()
        op = self.service.store.list('operations',c)[0]
        self.assertEqual(op['state'], 'failed')
        self.assertIn('missing verifier', op['error'])
        self.assertEqual(self.service.store.get('campaigns',c)['config']['taskImageLocks'], {})
        self.assertRaisesRegex(Refused,'H0',self.service.control,c,'start','start')
        self.assertEqual(self.service.store.list('trials',c), [])

    def test_start_rejects_missing_image_before_network_or_trial_admission(self):
        c = self.service.store.create(self.config,'fixture',defaults={'taskImagePolicy':POLICY,'taskImageLocks':self.locks})['id']
        self.service.store.candidate(c,{'id':'fixture','path':'/fixture','plugins':[]},'H0',check={'status':'passed'})
        with patch('src.control.task_images.image_id', side_effect=ValueError('image unavailable')), patch('src.control.service.network_preflight') as network:
            self.assertRaisesRegex(Refused,'unavailable',self.service.control,c,'start','start')
            network.assert_not_called()
        self.assertEqual(self.service.store.get('campaigns',c)['state'],'draft')
        self.assertEqual(self.service.store.list('trials',c), [])

    def test_legacy_campaign_is_not_migrated_by_preflight(self):
        c = self.service.store.create(self.config,'legacy')
        with patch('src.control.service.verify_locks') as verify:
            self.service._verify_task_images(c['config'])
            verify.assert_not_called()
        self.assertNotIn('taskImagePolicy',self.service.store.get('campaigns',c['id'])['config'])
