"""Benchmark phase clocks survive scheduling, setup and native Harbor launch."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from harbor.models.trial.config import TrialConfig
from src.control.store import Store, Refused, PUBLIC_TASKS
from src.control.resource_planning import POLICY as RESOURCE_POLICY
from src.execution.host.task_time import POLICY, read_task_time, verify_task_time, start_solver_clock
from src.execution.host import single_run

MODEL={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}


class BenchmarkTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=1000
        self.tasks=list(PUBLIC_TASKS)[:2]
        for task,seconds in zip(self.tasks,[1800,10800]):
            p=self.root/'quantum/harbor_tasks'/task;p.mkdir(parents=True)
            (p/'task.toml').write_text(f'[agent]\ntimeout_sec = {seconds}\nsetup_timeout_sec = 1\n[verifier]\ntimeout_sec = 1200\nenvironment_mode = "separate"\n[environment]\nbuild_timeout_sec = 600\n')
        self.times={t:read_task_time(self.root/'quantum',t) for t in self.tasks}
        self.store=Store(self.root/'ledger',clock=lambda:self.now)

    def activity(self,wall=20000):
        c=self.store.create({'solver':MODEL,'meta':MODEL,'tasks':self.tasks,'concurrency':2,'wallTimeSeconds':wall,
            'resourcePolicy':RESOURCE_POLICY,'executionTimePolicy':{'version':POLICY},'taskTimeLimits':self.times},'new')['id']
        self.store.control(c,'start','start')
        self.store.update_plan(c,{'parallelism':2,'closeoutReserveSeconds':0,'closeoutReserveTokens':0},'Full benchmark runs','plan',0)
        h=self.store.candidate(c,{'id':'bundle','path':str(self.root/'bundle'),'plugins':[]},'H0',check={'status':'passed'})['id']
        return c,h

    def test_native_config_and_separate_verifier_reservation(self):
        t=self.times[self.tasks[0]]
        self.assertEqual(t['solverTimeSeconds'],1800)
        # Harbor 0.18 ignores task agent.setup_timeout_sec; its native default is 360.
        self.assertEqual(t['setupTimeSeconds'],360)
        self.assertEqual(t['requiredTimeSeconds'],1800+360+600+1200+600)
        self.assertEqual(verify_task_time(self.root/'quantum',self.tasks[0],t),t)
        p=self.root/'quantum'/t['source'];p.write_text(p.read_text().replace('1800','1801'))
        with self.assertRaisesRegex(ValueError,'changed'):verify_task_time(self.root/'quantum',self.tasks[0],t)

    def test_missing_limit_is_not_replaced_with_platform_default(self):
        p=self.root/'quantum'/self.times[self.tasks[0]]['source'];p.write_text('')
        t=read_task_time(self.root/'quantum',self.tasks[0])
        self.assertIsNone(t['solverTimeSeconds']);self.assertIsNone(t['requiredTimeSeconds'])
        with self.assertRaisesRegex(RuntimeError,'refusing shortened'):start_solver_clock(t,100000,1000)

    def test_configuration_cannot_escape_benchmark(self):
        with self.assertRaises(ValueError):read_task_time(self.root/'quantum','../outside')
        p=self.root/'quantum'/self.times[self.tasks[0]]['source'];p.unlink()
        outside=self.root/'external.toml';outside.write_text('[agent]\ntimeout_sec=1\n');p.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'inside'):read_task_time(self.root/'quantum',self.tasks[0])

    def test_setup_does_not_consume_solver_window(self):
        t=self.times[self.tasks[0]]
        phase=start_solver_clock(t,10000,1700)
        self.assertEqual(phase['solverDeadline']-phase['solverStartedAt'],1800)
        self.assertEqual(phase['solverDeadline'],3500)
        with self.assertRaisesRegex(RuntimeError,'refusing shortened'):start_solver_clock(t,5299,1700)

    def test_each_task_gets_its_full_limit_and_no_precomputed_solver_deadline(self):
        c,h=self.activity();self.store.submit(c,h,self.tasks,1,'batch')
        a=self.store.claim(c);b=self.store.claim(c)
        self.assertEqual({a['task']:a['taskTimeLimitSeconds'],b['task']:b['taskTimeLimitSeconds']},
                         {t:v['solverTimeSeconds'] for t,v in self.times.items()})
        for trial in [a,b]:
            self.assertIsNone(trial['effectiveConditions']['solverDeadline'])
            self.assertNotIn('trialCloseoutReserveSeconds',trial['effectiveConditions'])
            self.assertEqual(trial['deadline'],21000)

    def test_insufficient_activity_time_waits_then_extension_admits_full_task(self):
        c,h=self.activity(wall=4000);self.store.submit(c,h,self.tasks,1,'batch')
        self.assertIsNone(self.store.claim(c))
        rows=self.store.list('trials',c)
        self.assertTrue(all(t['conditionsRequired']['canShorten'] is False for t in rows))
        with self.assertRaisesRegex(Refused,'cannot be shortened'):
            self.store.accept_trial_conditions(c,rows[0]['id'],100,'shrink','diagnostic')
        self.store.control(c,'limits','extend',changes={'wallTimeSeconds':20000})
        trial=self.store.claim(c)
        self.assertEqual(trial['taskTimeLimitSeconds'],self.times[trial['task']]['solverTimeSeconds'])
        self.assertNotIn('conditionsRequired',trial)

    def test_platform_and_meta_cannot_override_task_time(self):
        c,h=self.activity()
        for execution in [{'trialTimeSeconds':1200},{'allowShortened':True}]:
            with self.assertRaisesRegex(Refused,'Benchmark owns'):self.store.submit(c,h,self.tasks,1,'bad',execution=execution)
        with self.assertRaisesRegex(Refused,'exactly'):
            self.store.update_plan(c,{'parallelism':2,'defaultTrialTimeSeconds':1200,'closeoutReserveSeconds':0,'closeoutReserveTokens':0},'shrink','bad',1)
        with self.assertRaisesRegex(Refused,'Benchmark owns'):
            self.store.control(c,'limits','bad',changes={'trialTimeSeconds':1200})

    def test_supervisor_leaves_native_harbor_phase_limits_unmodified(self):
        bundle=self.root/'bundle';bundle.mkdir()
        (bundle/'recipe.json').write_text(json.dumps({**MODEL,'timePolicy':POLICY}))
        output=self.root/'launch'
        manifest={'id':'test','runnerImage':'test','agentEntry':'src.execution.adapters.quantum_harbor.agent:DeepSeekHarborAgent'}
        with patch.object(single_run,'verify',return_value=manifest),patch.object(single_run,'provider_environment',return_value={}),\
             patch.object(single_run.subprocess,'run',return_value=Mock(stdout='sha256:fixture')),\
             patch.object(single_run.shutil,'which',return_value=None),patch.object(single_run,'cleanup',return_value=[]):
            single_run.run(bundle,self.root/'quantum',self.tasks[0],output,10**10,soft_token_limit=None)
        config=json.loads((output/'harbor-config.json').read_text())
        agent=config['agents'][0]
        self.assertNotIn('override_timeout_sec',agent)
        self.assertIsNone(TrialConfig.model_validate({'agent':agent,'task':config['tasks'][0]}).agent.override_timeout_sec)
        self.assertEqual(agent['kwargs']['benchmark_time']['solverTimeSeconds'],1800)
        self.assertEqual(config['verifier'],{'disable':False})
        provenance=json.loads((output/'provenance.json').read_text())
        self.assertNotIn('solverDeadline',provenance)
        self.assertNotIn('trialCloseoutReserveSeconds',provenance)


if __name__=='__main__':unittest.main()
