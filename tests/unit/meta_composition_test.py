import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.control.meta_composition import freeze,verify,validate
from src.control.store import Refused
ROOT=Path(__file__).resolve().parents[2]
class CompositionTests(unittest.TestCase):
    def test_missing_dependency_rejects_but_optional_removal_is_real(self):
        manifest=json.loads((ROOT/'packages/meta-harness/composition.json').read_text())
        manifest['plugins'][2]['enabled']=False
        with self.assertRaises(Refused):validate(manifest,ROOT/'packages/meta-harness')
        manifest['plugins'][4]['enabled']=False
        validate(manifest,ROOT/'packages/meta-harness')
    def test_snapshot_is_recoverable_unchanged_and_checks_every_byte(self):
        with tempfile.TemporaryDirectory() as temp:
            config={'objective':'literal {{unknown}}','solver':{'model':'fixture'},'metaCompositionConfig':json.loads((ROOT/'packages/meta-harness/composition.json').read_text())}
            with patch('src.control.meta_composition.subprocess.run') as docker:
                docker.return_value.returncode=0;docker.return_value.stdout='sha256:'+'a'*64
                ref=freeze(ROOT,Path(temp),config);again=freeze(ROOT,Path(temp),config)
            self.assertEqual(ref,again)
            folder,doc=verify(temp,ref,ROOT);self.assertIn('literal {{unknown}}',doc['systemPrompt']['text'])
            file=folder/'packages/meta-harness/stop-review.mjs';file.write_text(file.read_text()+'\n// changed')
            with self.assertRaisesRegex(Refused,'source changed'):verify(temp,ref,ROOT)
    def test_configuration_changes_have_distinct_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            config={'objective':'objective','solver':{'model':'fixture'},'metaCompositionConfig':json.loads((ROOT/'packages/meta-harness/composition.json').read_text())}
            with patch('src.control.meta_composition.subprocess.run') as docker:
                docker.return_value.returncode=0;docker.return_value.stdout='sha256:'+'a'*64
                first=freeze(ROOT,temp,config)
                manifest=json.loads((ROOT/'packages/meta-harness/composition.json').read_text());manifest['plugins'][5]['enabled']=False
                second=freeze(ROOT,temp,{**config,'metaCompositionConfig':manifest})
            self.assertNotEqual(first['id'],second['id']);verify(temp,first,ROOT);verify(temp,second,ROOT)
    def test_cannot_mount_outside_frozen_package(self):
        manifest=json.loads((ROOT/'packages/meta-harness/composition.json').read_text());manifest['plugins'][0]['module']='../escape.mjs'
        with self.assertRaises(Refused):validate(manifest,ROOT/'packages/meta-harness')
