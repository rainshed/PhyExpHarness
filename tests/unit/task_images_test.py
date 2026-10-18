import hashlib
import json
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
