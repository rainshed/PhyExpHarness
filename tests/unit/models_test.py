import copy
import os
import subprocess
import unittest
from unittest.mock import patch
from src.control.store import validate_config, Refused
from src.execution.host.models import model_catalog
from src.execution.host.network import network_preflight

GPT={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
DS={'provider':'deepseek-official','model':'deepseek-flash','reasoningEffort':'high'}
BASE={'solver':GPT,'meta':{**GPT,'model':'gpt-6-astra'},'tasks':['time_budgeted_hamlearn_10q'],
      'concurrency':1,'wallTimeSeconds':7200}

class ModelsTests(unittest.TestCase):
    def test_both_roles_and_mixed_providers_are_accepted_with_provider_specific_efforts(self):
        for solver, meta in [(GPT,DS),(DS,GPT),(DS,DS)]:
            for effort in ['off','low','high','max']:
                config=copy.deepcopy({**BASE,'solver':solver,'meta':meta})
                for role in ['solver','meta']:
                    if config[role]['provider']=='deepseek-official':config[role]['reasoningEffort']=effort
                accepted=validate_config(config)
                self.assertEqual(accepted['solver']['provider'],solver['provider'])
                self.assertEqual(accepted['meta']['provider'],meta['provider'])
        for role in ['solver','meta']:
            for invalid in [{**DS,'reasoningEffort':'medium'},{**DS,'model':'DeepSeek-V4.1-Flash-1017'},
                            {**DS,'provider':'openai-codex'},{**GPT,'reasoningEffort':'max'}]:
                with self.assertRaises(Refused):validate_config({**BASE,role:invalid})
        self.assertEqual(validate_config(BASE)['solver'],GPT)

    def test_catalog_keeps_existing_gpt_choices_and_declares_rolling_alias(self):
        entries=model_catalog()
        self.assertEqual([m['model'] for m in entries[:3]],['gpt-6-sol','gpt-6-astra','gpt-6-luna'])
        self.assertEqual(entries[-1]['versionPolicy'],'rolling-alias')
        self.assertEqual(entries[-1]['model'],'deepseek-flash')

    def test_preflight_targets_selected_provider_without_credentials_in_request(self):
        for model,endpoint in [(GPT,'chatgpt.com/backend-api/codex/responses'),(DS,'api.deepseek.com/anthropic')]:
            with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'offline-fixture-key'}), patch('subprocess.run') as run:
                run.return_value=subprocess.CompletedProcess([],0,'{"reachable":true,"modelCall":false}', '')
                self.assertFalse(network_preflight(model)['modelCall'])
                script=run.call_args.args[0][2]
                self.assertIn(endpoint,script)
                self.assertNotIn('offline-fixture-key',script)
                self.assertIn('HEAD',script)
        with patch.dict(os.environ,{},clear=True),patch('subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError,'DEEPSEEK_API_KEY'):network_preflight(DS)
            run.assert_not_called()


class ConfigurableProviderTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp=tempfile.TemporaryDirectory()
        self.root=__import__('pathlib').Path(self.temp.name)
        self.route={'adapter':'pi-ai','api':'openai-completions','baseURL':'https://fixture.invalid/v1',
                    'auth':{'type':'api-key','env':'PHYEXP_FIXTURE_KEY'},
                    'models':[{'id':'fixture-model','name':'Fixture Model','contextWindow':16000,'maxTokens':1024,'reasoningEfforts':False}]}
        self.file=self.root/'models.json'
        self.save({'fixture-gateway':self.route})
    def tearDown(self):self.temp.cleanup()
    def save(self,providers):
        import json
        self.file.write_text(json.dumps({'schemaVersion':1,'providers':providers}))
    def test_merge_role_selection_snapshot_and_limits_survive_file_removal(self):
        from src.execution.host.models import load_model_config,provider_route
        from src.control.store import Store
        with patch.dict(os.environ,{'PHYEXP_MODEL_CONFIG':str(self.file)}):
            config=load_model_config()
            self.assertEqual(len(model_catalog(config)),5)
            store=Store(self.root/'control.sqlite')
            custom={'provider':'fixture-gateway','model':'fixture-model'}
            for role in ['solver','meta']:
                accepted=validate_config({**BASE,role:custom,'modelRoutes':{'solver':{'baseURL':'https://injected.invalid'}}},config)
                self.assertNotIn('reasoningEffort',accepted[role])
                self.assertEqual(accepted['modelRoutes'][role],self.route)
            campaign=store.create({**BASE,'solver':custom},'custom')
            self.file.unlink()
            changed=store.control(campaign['id'],'limits','limits',changes={'wallTimeSeconds':7400})
            self.assertEqual(changed['config']['modelRoutes']['solver'],self.route)
            self.assertEqual(store.model_config,config)
            self.assertEqual(provider_route(custom,config),self.route)
    def test_invalid_deployment_configs_fail_without_model_calls(self):
        from src.execution.host.models import load_model_config
        for change in [{'api':'bad-protocol'},{'apiKey':'never-inline'},{'baseURL':'https://secret:pass@fixture.invalid'},
                       {'baseURL':'http://public.example/v1'},{'auth':{'type':'codex'}},
                       {'models':[self.route['models'][0],self.route['models'][0]]},
                       {'models':[{**self.route['models'][0],'reasoningEfforts':{'high':None},'defaultReasoningEffort':'high'}]}]:
            self.save({'fixture-gateway':{**self.route,**change}})
            with self.assertRaises(ValueError):load_model_config(self.file)
        self.save({'openai-codex':{**self.route,'auth':{'type':'api-key','env':'OPENAI_API_KEY'}}})
        with self.assertRaisesRegex(ValueError,'subscription'):load_model_config(self.file)
    def test_model_directory_is_shared_with_user_api_and_reload_requires_restart(self):
        from fastapi.testclient import TestClient
        from src.control.service import ControlService
        from src.control.server import make_app
        from pathlib import Path
        root=Path(__file__).resolve().parents[2]
        with patch.dict(os.environ,{'PHYEXP_MODEL_CONFIG':str(self.file)}):
            service=ControlService(root,self.root/'data',root.parent/'Quantum-Harbor','http://127.0.0.1:1')
        try:
            with TestClient(make_app(service,supervise=False)) as client:
                client.headers['Authorization']='Bearer '+service.user_token
                response=client.get('/models')
                self.assertEqual(response.status_code,200)
                entries=response.json()['models']
                self.assertEqual(entries[-1]['model'],'fixture-model')
                self.assertEqual(entries[-1]['reasoningEfforts'],[])
                self.file.unlink()
                self.assertEqual(client.get('/models').json()['models'],entries)
        finally:service.pool.shutdown(wait=True)
    def test_custom_bundle_freezes_route_and_can_export_after_config_removal(self):
        import json
        from pathlib import Path
        from src.execution.host.models import load_model_config,provider_route
        from src.execution.bundle.freeze import freeze,verify
        from src.exporting.project import export_project
        root=Path(__file__).resolve().parents[2]
        config=load_model_config(self.file)
        recipe=json.loads((root/'recipes/h0-sol.json').read_text())
        recipe.update(provider='fixture-gateway',model='fixture-model',maxTokens=1024)
        recipe.pop('reasoningEffort')
        recipe['providerConfig']=provider_route(recipe,config)
        self.file.unlink()
        bundle=freeze(root,self.root/'store',recipe)
        export=export_project(bundle['path'],self.root/'relocated with spaces')
        project=Path(export['path']);self.assertEqual(verify(project)['id'],bundle['id'])
        self.assertEqual(json.loads((project/'recipe.json').read_text())['providerConfig'],self.route)
        self.assertFalse(list(project.rglob('credentials.json')))

    def test_deepseek_endpoint_override_is_also_used_by_preflight(self):
        from src.execution.host.models import load_model_config,provider_route
        self.save({'deepseek-official':{'adapter':'deepseek','baseURL':'https://deepseek-proxy.invalid/anthropic',
            'auth':{'type':'api-key','env':'PHYEXP_FIXTURE_KEY'},'models':[{'id':'deepseek-flash','reasoningEfforts':{'high':'high'},'defaultReasoningEffort':'high'}]}})
        config=load_model_config(self.file)
        route=provider_route(DS,config)
        with patch.dict(os.environ,{'PHYEXP_FIXTURE_KEY':'offline-fixture'}),patch('subprocess.run') as run:
            run.return_value=subprocess.CompletedProcess([],0,'{"reachable":true,"modelCall":false}','')
            network_preflight(DS,route)
            self.assertIn('https://deepseek-proxy.invalid/anthropic',run.call_args.args[0][2])
