import importlib.util
import json
import io
import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stderr
from src.execution.host import container_runtime as runtime

spec = importlib.util.spec_from_file_location('podman_build', Path(__file__).resolve().parents[2]/'scripts/podman-single-uid.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class ContainerRuntimeTest(unittest.TestCase):
    def test_unknown_policy_and_unsupported_tasks_fail_closed(self):
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME='unknown'):
            with self.assertRaises(ValueError): runtime.policy()
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME=runtime.PODMAN_SINGLE_UID):
            from src.control.store import PUBLIC_TASKS
            runtime.require_tasks(PUBLIC_TASKS)
            for task in PUBLIC_TASKS:
                runtime.require_tasks([task])
            for tasks in [[], ['syndrome_feedback_control'], ['time_budgeted_hamlearn_10q', 'other']]:
                with self.assertRaises(ValueError): runtime.require_tasks(tasks)
            with self.assertRaises(ValueError): runtime.verify_lock({}, 'time_budgeted_hamlearn_10q')

    def test_rootful_engine_and_unadapted_image_are_rejected(self):
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME=runtime.PODMAN_SINGLE_UID):
            with patch.object(runtime.subprocess, 'check_output', return_value='{"host":{"security":{"rootless":false}}}'):
                with self.assertRaises(ValueError): runtime.preflight(['time_budgeted_hamlearn_10q'])
            with patch.object(runtime.subprocess, 'check_output', side_effect=[json.dumps({'host':{'security':{'rootless':True}},'store':{'graphRoot':'/expected'}}), '/different']):
                with self.assertRaises(ValueError): runtime.preflight(['time_budgeted_hamlearn_10q'])
            with patch.object(runtime.subprocess, 'check_output', return_value='null'):
                with self.assertRaises(ValueError): runtime.verify_image('sha256:fixture')
            with patch.object(runtime.subprocess, 'check_output', return_value=json.dumps({'org.phyexp.container-runtime':runtime.PODMAN_SINGLE_UID})):
                runtime.verify_image('sha256:fixture')

    def test_default_docker_behavior_is_unchanged(self):
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME='docker'):
            runtime.preflight(['logical_cnot_decoder_calibration'])
            runtime.verify_lock({}, 'logical_cnot_decoder_calibration')
            self.assertEqual(runtime.compose_security('main'), {})
            self.assertEqual(runtime.compose_security('qsim'), {})

    def test_build_adaptation_keeps_scoring_and_removes_helpers_at_runtime(self):
        source = 'FROM python:3.11\nRUN apt-get update && echo original\nCOPY --chown=verifier:verifier --chmod=0400 private/answer /verifier/answer\nUSER verifier\nENTRYPOINT ["python"]\n'
        value = builder.adapt(source)
        self.assertIn('COPY --chown=0:0 --chmod=0400 private/answer /verifier/answer', value)
        self.assertIn('ENTRYPOINT ["python"]', value)
        self.assertIn('FAKEROOTDONTTRYCHOWN=1', value)
        self.assertIn('RUN rm -rf /.phyexp-build-helpers', value)
        self.assertNotIn('USER verifier', value)
        with self.assertRaises(ValueError): builder.adapt('FROM alpine\nONBUILD RUN echo no\n')

    def test_pilot_runtime_drops_capabilities_for_every_role(self):
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME=runtime.PODMAN_SINGLE_UID):
            for role in ['main', 'qsim', 'verifier']:
                config = runtime.compose_security(role)
                self.assertEqual(config['cap_drop'], ['ALL'])
                self.assertEqual(config['security_opt'], ['no-new-privileges:true'])
                self.assertNotIn('privileged', config)
                self.assertNotIn('network_mode', config)

    def test_task_resource_requirements_survive_the_security_overlay(self):
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME=runtime.PODMAN_SINGLE_UID):
            shadow = runtime.compose_security('main', cpus=4, memory_mb=4096)
            cnot = runtime.compose_security('main', cpus=2, memory_mb=6144)
            qsim = runtime.compose_security('qsim', cpus=2, memory_mb=4096)
            self.assertEqual((shadow['cpus'], shadow['mem_limit']), (4, '4096m'))
            self.assertEqual((cnot['cpus'], cnot['mem_limit']), (2, '6144m'))
            self.assertEqual((qsim['cpus'], qsim['mem_limit']), (4, '8g'))
            self.assertEqual(qsim['environment'], {'OPENBLAS_NUM_THREADS':'4', 'OMP_NUM_THREADS':'4', 'MKL_NUM_THREADS':'4'})
            self.assertNotIn('environment', shadow)
            self.assertNotIn('environment', runtime.compose_security('verifier'))

    def test_offline_build_policy_cannot_silently_gain_network(self):
        source='FROM node\nRUN --network=none npm ci --offline\nRUN --network=none echo done\n'
        self.assertEqual(builder.build_network(source), ['--network=none'])
        self.assertNotIn('RUN --network=none', builder.adapt(source))
        for other in ['FROM node\nRUN --network=host echo no\n', source+'RUN curl example.com\n']:
            with self.assertRaises(ValueError): builder.adapt(other)

    def test_pilot_internal_network_disables_dns_forwarding(self):
        from src.execution.host import task_network
        configs=[{'NetworkSettings':{'Networks':{'old':{}}}},
                 {'NetworkSettings':{'Networks':{'phyexp-trial-fixture':{}}}},
                 {'NetworkSettings':{'Networks':{'phyexp-trial-fixture':{'IPAddress':'10.90.0.2'}}}}]
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME=runtime.PODMAN_SINGLE_UID), \
             patch.object(task_network.uuid, 'uuid4', return_value='fixture'), \
             patch.object(task_network.subprocess, 'check_output') as native, \
             patch.object(task_network, 'docker') as docker:
            def command(*args):
                return json.dumps([configs.pop(0)]) if args[0]=='inspect' else ''
            docker.side_effect=command
            self.assertEqual(task_network.restrict_main('main','qsim'), 'phyexp-trial-fixture')
            self.assertIn('--disable-dns', native.call_args.args[0])
            commands=[call.args for call in docker.call_args_list]
            self.assertTrue(any(cmd[:3]==('network','disconnect','old') for cmd in commands))
            self.assertIn('10.90.0.2 qsim', commands[-1][-1])

    def test_compose_wait_handles_disabled_health_without_accepting_failed_checks(self):
        container={'State':{'Status':'running','Running':True,'Health':{'Status':''}},
                   'Config':{'Healthcheck':{'Test':['NONE']}}}
        self.assertTrue(builder.startup_ready(container))
        container['Config']['Healthcheck']['Test']=['CMD','/app/healthcheck.sh']
        self.assertFalse(builder.startup_ready(container))
        container['State']['Health']['Status']='unhealthy'
        with self.assertRaises(RuntimeError): builder.startup_ready(container)
        container['State']['Health']['Status']='healthy'
        self.assertTrue(builder.startup_ready(container))
        container['State']['Status']='exited'
        with self.assertRaises(RuntimeError): builder.startup_ready(container)

    def test_compose_budget_covers_creation_discovery_and_health(self):
        clock = [0]
        calls = []
        def create(*args, **kwargs):
            calls.append(kwargs['timeout']); clock[0] += 200
            return Mock(returncode=0)
        def output(argv, **kwargs):
            calls.append(kwargs['timeout'])
            if 'ps' in argv:
                clock[0] += 10; return 'container'
            clock[0] += 1
            return json.dumps([{'State': {'Running': True, 'Status': 'running'}}])
        with patch.object(builder.time, 'monotonic', side_effect=lambda:clock[0]), \
             patch.object(builder.subprocess, 'run', side_effect=create), \
             patch.object(builder.subprocess, 'check_output', side_effect=output):
            self.assertEqual(builder.compose_wait(['compose','up','-d','--wait','--wait-timeout','600'],
                                                 {'dockerClient':'docker','podman':'podman'}, {}), 0)
        self.assertEqual(calls, [600, 400, 390])

    def test_empty_podman_health_log_is_valid_before_first_check(self):
        self.assertEqual(builder.startup_snapshot([{'State':{'Health':{'Status':'starting','Log':None}}}])[0]['healthLog'], [])

    def test_compose_timeout_saves_last_health_without_environment_secrets(self):
        clock = [0]
        container = {'Id':'fixture', 'State':{'Running':True, 'Status':'running',
            'Health':{'Status':'starting','Log':[{'ExitCode':1,'Output':'not ready'}]}},
            'Config':{'Healthcheck':{'Test':['CMD','check']}, 'Env':['SECRET=private']}}
        def output(argv, **kwargs):
            return 'fixture' if 'ps' in argv else json.dumps([container])
        def sleep(seconds): clock[0] += seconds
        stream = io.StringIO()
        with patch.object(builder.time, 'monotonic', side_effect=lambda:clock[0]), \
             patch.object(builder.time, 'sleep', side_effect=sleep), \
             patch.object(builder.subprocess, 'run', return_value=Mock(returncode=0)), \
             patch.object(builder.subprocess, 'check_output', side_effect=output), redirect_stderr(stream):
            with self.assertRaises(TimeoutError):
                builder.compose_wait(['compose','up','-d','--wait','--wait-timeout','2'],
                                     {'dockerClient':'docker','podman':'podman'}, {})
        receipt = json.loads(stream.getvalue().splitlines()[-1].split('=',1)[1])
        self.assertEqual(receipt['code'], 'environment_start_timeout')
        self.assertEqual(receipt['containers'][0]['health'], 'starting')
        self.assertNotIn('SECRET', stream.getvalue())
        self.assertEqual(clock[0], 2)

    def test_later_failed_service_is_not_hidden_by_starting_service(self):
        containers = [{'State':{'Running':False}}, {'Name':'qsim','State':{'Status':'exited','ExitCode':1}}]
        stream = io.StringIO()
        with patch.object(builder.subprocess, 'run', return_value=Mock(returncode=0)), \
             patch.object(builder.subprocess, 'check_output', side_effect=['main qsim', json.dumps(containers)]), \
             patch.object(builder.time, 'sleep') as sleep, redirect_stderr(stream):
            with self.assertRaises(RuntimeError):
                builder.compose_wait(['compose','up','-d','--wait'], {'dockerClient':'docker','podman':'podman'}, {})
        self.assertEqual(json.loads(stream.getvalue().splitlines()[-1].split('=',1)[1])['code'], 'environment_container_exited')
        sleep.assert_not_called()

    def test_compose_creation_timeout_has_specific_diagnostic(self):
        stream = io.StringIO()
        with patch.object(builder.subprocess, 'run', side_effect=subprocess.TimeoutExpired('compose', 600)), \
             redirect_stderr(stream):
            with self.assertRaises(subprocess.TimeoutExpired):
                builder.compose_wait(['compose','up','-d','--wait','--wait-timeout','600'],
                                     {'dockerClient':'docker','podman':'podman'}, {})
        receipt = json.loads(stream.getvalue().splitlines()[-1].split('=',1)[1])
        self.assertEqual((receipt['code'], receipt['phase']), ('environment_start_timeout', 'compose-up'))


if __name__ == '__main__': unittest.main()
