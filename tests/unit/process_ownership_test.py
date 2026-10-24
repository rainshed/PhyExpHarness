import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from src.execution.host.single_run import cleanup

class ProcessOwnershipTests(unittest.TestCase):
    def test_identical_output_basenames_have_distinct_persisted_cleanup_owners(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);owners=[]
            def command(argv,**kwargs):
                if argv[1:3]==['network','ls']:owners.append(argv[-1])
                return SimpleNamespace(returncode=0,stdout='')
            with patch('src.execution.host.single_run.subprocess.run',side_effect=command):
                for name in ('first','second'):
                    output=root/name/'trial';output.mkdir(parents=True)
                    (output/'provenance.json').write_text(json.dumps({'launchId':'standalone-'+name}))
                    cleanup(output)
            self.assertEqual(owners,['label=phyexp.launch=standalone-first','label=phyexp.launch=standalone-second'])
