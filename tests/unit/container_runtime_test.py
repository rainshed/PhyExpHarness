import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from src.execution.host import container_runtime as runtime

spec = importlib.util.spec_from_file_location('podman_build', Path(__file__).resolve().parents[2]/'scripts/podman-single-uid.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class ContainerRuntimeTest(unittest.TestCase):
    def test_unknown_policy_and_unsupported_tasks_fail_closed(self):
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME='unknown'):
            with self.assertRaises(ValueError): runtime.policy()
        with patch.dict(os.environ, PHYEXP_CONTAINER_RUNTIME=runtime.PODMAN_SINGLE_UID):
            runtime.require_tasks(['time_budgeted_hamlearn_10q'])
            for tasks in [[], ['logical_cnot_decoder_calibration'], ['time_budgeted_hamlearn_10q', 'other']]:
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


if __name__ == '__main__': unittest.main()
