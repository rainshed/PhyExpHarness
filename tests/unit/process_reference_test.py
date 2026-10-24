import json,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from tests.unit.process_candidates_test import ProcessCandidatesTests
from src.control.reference.process import bind_model,model_route
from src.execution.bundle.manifest import resolve

class ProcessReferenceTests(ProcessCandidatesTests):
    def test_reference_model_preserves_complete_candidate_and_primary_recipe(self):
        candidate=self.service.build_candidate(self.cid,[],'H0')
        original=resolve(candidate['bundlePath']);original_recipe=original.asset('recipe.json').read_bytes()
        catalog=self.root/'native';(catalog/'credentials').mkdir(parents=True)
        (catalog/'credentials/approved.json').write_text(json.dumps({'ref':'REF_KEY','value':'private-fixture-key'}))
        self.service.references.catalog.root=catalog
        snapshot={'adapter':'pi-ai','credentialRef':'REF_KEY','call':{'provider':'reference','model':'another-model','reasoningEffort':'high'},
                  'config':{'providers':{'reference':{'api':'openai-completions','baseURL':'https://fixture.invalid/v1','apiKeyEnv':'REF_KEY'}}}}
        selected,env=bind_model(self.service,self.cid,candidate,snapshot,'approved')
        frozen=resolve(selected['bundlePath']);recipe=json.loads(frozen.asset('recipe.json').read_text())
        self.assertEqual(recipe['model'],'another-model');self.assertEqual(env['PHYEXP_REFERENCE_NATIVE_KEY'],'private-fixture-key')
        for key in ('sources','artifact','adapter','project'):self.assertEqual(original.manifest[key],frozen.manifest[key])
        self.assertEqual(original.asset('recipe.json').read_bytes(),original_recipe)
        self.assertNotIn('private-fixture-key',json.dumps(frozen.manifest)+json.dumps(recipe))

    def test_reference_route_does_not_substitute_an_unsupported_protocol(self):
        from src.control.store import Refused
        with self.assertRaises(Refused):model_route({'adapter':'pi-ai','call':{'provider':'native','model':'model'},'config':{}})
