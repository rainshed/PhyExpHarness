"""Benchmark phase clocks survive scheduling, setup and native Harbor launch."""
import json
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from harbor.models.trial.config import TrialConfig
from src.control.store import Store, Refused, PUBLIC_TASKS
from src.control.resource_planning import POLICY as RESOURCE_POLICY
from src.execution.host.task_time import LEGACY_POLICY as POLICY, POLICY as LATE_POLICY, read_task_time, verify_task_time, start_solver_clock, ActivityDeadlineError, execution_timing
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

    def activity(self,wall=20000,policy=POLICY,**options):
        c=self.store.create({'solver':MODEL,'meta':MODEL,'tasks':self.tasks,'concurrency':2,'wallTimeSeconds':wall,
            'resourcePolicy':RESOURCE_POLICY,'executionTimePolicy':{'version':policy},'taskTimeLimits':self.times,**options},'new')['id']
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

    def test_late_start_admits_short_window_and_preserves_native_ceiling(self):
        c,h=self.activity(wall=1800,policy=LATE_POLICY)
        self.store.submit(c,h,self.tasks,1,'batch')
        view=self.store.status(c)['resourcePlanning']['pendingTrials'][0]
        self.assertEqual(view['state'],'waiting_resources')
        self.assertTrue(view['interruptionRisk']);self.assertIsNone(view['requiredSeconds'])
        self.now+=120
        trial=self.store.claim(c)
        self.assertEqual(trial['deadline'],2800)
        self.assertEqual(trial['effectiveConditions']['availableTimeSeconds'],1680)
        self.assertTrue(trial['effectiveConditions']['interruptionRiskAtLaunch'])
        phase=start_solver_clock(self.times[trial['task']],trial['deadline'],self.now+60,LATE_POLICY)
        self.assertEqual(phase['availableTimeAtSolverStartSeconds'],1620)
        self.assertEqual(phase['solverDeadline'],2800)
        self.assertEqual(phase['solverTimeSeconds'],1800)
        self.assertEqual(phase['benchmarkSolverDeadline'],2980)
        self.assertEqual(phase['deadlineCause'],'campaign_deadline')
        with self.assertRaises(ActivityDeadlineError):start_solver_clock(self.times[trial['task']],2800,2800,LATE_POLICY)

    def test_late_start_still_obeys_pause_concurrency_reserve_and_deadline(self):
        c,h=self.activity(wall=1800,policy=LATE_POLICY)
        self.store.submit(c,h,self.tasks,2,'batch')
        self.store.control(c,'pause','pause');self.assertIsNone(self.store.claim(c))
        self.store.control(c,'resume','resume')
        self.assertIsNotNone(self.store.claim(c));self.assertIsNotNone(self.store.claim(c))
        self.assertIsNone(self.store.claim(c))
        for t in self.store.list('trials',c):
            if t['startedAt'] is not None:self.store.trial_update(t['id'],state='finished',finishedAt=self.now)
        self.store.update_plan(c,{'parallelism':2,'closeoutReserveSeconds':600,'closeoutReserveTokens':0},'reserve','reserve',1)
        self.now=2300;self.assertIsNone(self.store.claim(c))
        self.store.update_plan(c,{'parallelism':2,'closeoutReserveSeconds':0,'closeoutReserveTokens':0},'release','release',2)
        self.assertIsNotNone(self.store.claim(c))
        self.now=2800;self.assertIsNone(self.store.claim(c))
        with self.assertRaises(Refused):self.store.submit(c,h,self.tasks,1,'expired')

    def test_late_start_drain_only_extends_started_trials(self):
        c,h=self.activity(wall=1800,policy=LATE_POLICY,stopMode='drain',drainGraceSeconds=300)
        self.store.submit(c,h,self.tasks,1,'batch');self.now=2700
        trial=self.store.claim(c);self.assertEqual(trial['deadline'],3100)
        self.assertEqual(trial['effectiveConditions']['availableTimeSeconds'],400)
        self.now=2800;self.assertIsNone(self.store.claim(c))

    def test_late_start_unbounded_solver_uses_activity_deadline(self):
        timing={**self.times[self.tasks[0]],'solverTimeSeconds':None,'requiredTimeSeconds':None}
        phase=start_solver_clock(timing,2800,1500,LATE_POLICY)
        self.assertIsNone(phase['solverTimeSeconds']);self.assertIsNone(phase['benchmarkSolverDeadline'])
        self.assertEqual(phase['solverDeadline'],2800)
        full=start_solver_clock(self.times[self.tasks[0]],10000,1000,LATE_POLICY)
        self.assertEqual(full['deadlineCause'],'trial_deadline')
        self.assertEqual(full['effectiveSolverTimeSeconds'],1800)

    def test_late_supervisor_starts_short_window_and_enforces_deadline(self):
        bundle=self.root/'bundle';bundle.mkdir()
        (bundle/'recipe.json').write_text(json.dumps({**MODEL,'timePolicy':LATE_POLICY}))
        manifest={'id':'test','runnerImage':'test','agentEntry':'src.execution.adapters.quantum_harbor.agent:DeepSeekHarborAgent'}
        clock=[1000]
        process=Mock(pid=123,returncode=None)
        def poll():
            clock[0]=2800
            return process.returncode
        process.poll.side_effect=poll
        def wait(**kwargs):process.returncode=-15
        process.wait.side_effect=wait
        output=self.root/'short-launch'
        with patch.object(single_run,'verify',return_value=manifest),patch.object(single_run,'provider_environment',return_value={}), \
             patch.object(single_run.subprocess,'run',return_value=Mock(stdout='sha256:fixture')), \
             patch.object(single_run.shutil,'which',return_value='harbor'),patch.object(single_run,'cleanup',return_value=[]), \
             patch.object(single_run.subprocess,'Popen',return_value=process) as launch, \
             patch.object(single_run.time,'time',side_effect=lambda:clock[0]),patch.object(single_run.os,'killpg') as kill:
            result=single_run.run(bundle,self.root/'quantum',self.tasks[1],output,2800)
        launch.assert_called_once();kill.assert_called_once_with(123,signal.SIGTERM)
        self.assertEqual(result['stopReason'],'campaign_deadline')
        self.assertIsNone(result['officialReward'])
        config=json.loads((output/'harbor-config.json').read_text())
        self.assertNotIn('override_timeout_sec',config['agents'][0])
        self.assertEqual(config['agents'][0]['kwargs']['benchmark_time']['solverTimeSeconds'],10800)
        self.assertEqual(result['timing']['availableTimeSeconds'],1800)
        self.assertEqual(result['timing']['executionTimeSeconds'],1800)
        self.assertIsNone(result['timing']['solverSeconds'])

    def test_timing_reports_observed_phase_durations_and_unknown_gaps(self):
        provenance={'recipe':{'timePolicy':LATE_POLICY},'benchmarkTime':{'solverTimeSeconds':9000},
            'availableTimeSeconds':1800,'executionStartedAt':1000,'executionFinishedAt':2200,
            'solverTiming':start_solver_clock({'solverTimeSeconds':9000},2800,1060,LATE_POLICY)}
        native={'agent_execution':{'started_at':'2026-10-26T00:01:00','finished_at':'2026-10-26T00:18:00'},
                'verifier':{'started_at':'2026-10-26T00:18:00','finished_at':'2026-10-26T00:20:00'}}
        record=execution_timing(provenance,native)
        self.assertEqual(record['solverTimeSeconds'],9000);self.assertEqual(record['executionTimeSeconds'],1200)
        self.assertEqual(record['preparationSeconds'],60);self.assertEqual(record['solverSeconds'],1020)
        self.assertEqual(record['verifierSeconds'],120);self.assertIsNone(record['setupSeconds'])

    def test_late_supervisor_completes_before_cutoff_and_refuses_expired_launch(self):
        bundle=self.root/'bundle';bundle.mkdir()
        (bundle/'recipe.json').write_text(json.dumps({**MODEL,'timePolicy':LATE_POLICY}))
        manifest={'id':'test','runnerImage':'test','agentEntry':'src.execution.adapters.quantum_harbor.agent:DeepSeekHarborAgent'}
        clock=[1000];process=Mock(pid=123,returncode=0)
        def poll():clock[0]=2200;return 0
        process.poll.side_effect=poll
        with patch.object(single_run,'verify',return_value=manifest),patch.object(single_run,'provider_environment',return_value={}), \
             patch.object(single_run.subprocess,'run',return_value=Mock(stdout='sha256:fixture')), \
             patch.object(single_run.shutil,'which',return_value='harbor'),patch.object(single_run,'cleanup',return_value=[]), \
             patch.object(single_run.subprocess,'Popen',return_value=process) as launch, \
             patch.object(single_run.time,'time',side_effect=lambda:clock[0]),patch.object(single_run.os,'killpg') as kill, \
             patch.object(single_run,'collect',return_value={'status':'completed','pipelineStatus':'completed','officialReward':1}):
            result=single_run.run(bundle,self.root/'quantum',self.tasks[1],self.root/'completed',2800)
            self.assertEqual(result['officialReward'],1)
            self.assertEqual(result['timing']['executionTimeSeconds'],1200)
            kill.assert_not_called();launch.assert_called_once()
            launch.reset_mock();clock[0]=2800
            result=single_run.run(bundle,self.root/'quantum',self.tasks[1],self.root/'expired',2800)
            self.assertEqual(result['stopReason'],'campaign_deadline');launch.assert_not_called()

    def test_host_rechecks_deadline_after_preflight_before_launch(self):
        bundle=self.root/'bundle';bundle.mkdir()
        (bundle/'recipe.json').write_text(json.dumps({**MODEL,'timePolicy':LATE_POLICY}))
        manifest={'id':'test','runnerImage':'test','agentEntry':'fixture'}
        clock=[1000]
        def slow_preflight(*args,**kwargs):clock[0]=2800;return Mock(stdout='sha256:fixture')
        with patch.object(single_run,'verify',return_value=manifest),patch.object(single_run,'provider_environment',return_value={}), \
             patch.object(single_run.subprocess,'run',side_effect=slow_preflight),patch.object(single_run.shutil,'which',return_value='harbor'), \
             patch.object(single_run,'cleanup',return_value=[]),patch.object(single_run.subprocess,'Popen') as launch, \
             patch.object(single_run.time,'time',side_effect=lambda:clock[0]):
            result=single_run.run(bundle,self.root/'quantum',self.tasks[1],self.root/'expired-preflight',2800)
        launch.assert_not_called();self.assertEqual(result['stopReason'],'campaign_deadline')


if __name__=='__main__':unittest.main()
