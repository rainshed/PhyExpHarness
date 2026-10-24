import hashlib
import json
import unittest
from unittest.mock import patch
import meta_native_test as base
from src.control.meta_contracts import CONTRACTS,binding,version
from src.control.meta_native_composition import freeze
from src.control.store import Refused,encoded
from src.evidence.files import atomic_json

BIG='完整🧪'*180000+'UNIQUE_END'
class ToolBoundaryTests(unittest.TestCase):
    def setUp(self):
        base.NativeMetaTests.setUp(self)
        c=self.store.get('campaigns',self.c)
        with patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64):c['config']['metaComposition']=freeze(base.ROOT,self.data,c['config'])
        self.store.put('campaigns',c)
    def tearDown(self):base.NativeMetaTests.tearDown(self)
    def full(self,result):
        self.assertLessEqual(len(encoded(result).encode()),4096)
        file=result['file'];data=(self.api.files.directory(self.c)/file['path'].lstrip('/')).read_bytes()
        self.assertEqual(len(data),file['bytes']);self.assertEqual(hashlib.sha256(data).hexdigest(),file['sha256'])
        return json.loads(data)
    def test_all_business_operations_and_optional_results_have_one_boundary(self):
        names=set(CONTRACTS['meta-tools-v7'])|{'reference_'+axis+'_'+action for axis in ('model','harness') for action in ('list','status','submit','cancel')}
        for operation in names:
            with self.subTest(operation=operation),patch.object(self.api,'_dispatch',return_value={'state':'completed','diagnostic':BIG}):
                result=self.api.call(self.c,operation,{})
                self.assertEqual(self.full(result)['diagnostic'],BIG)
    def test_validation_read_failure_optional_rejection_and_write_unknown_are_archived(self):
        for operation,error,status in [('batch_status',Refused(BIG),'rejected'),('reference_model_status',RuntimeError(BIG),'failed'),('candidate_check',RuntimeError(BIG),'outcome_unknown')]:
            with self.subTest(operation=operation),patch.object(self.api,'_dispatch',side_effect=error):
                result=self.api.call(self.c,operation,{})
                self.assertEqual(result['status'],status);self.assertEqual(self.full(result)['error'],BIG)
        # Real schema rejection occurs before the write journal, but still has a file.
        result=self.api.call(self.c,'batch_status',{'batchId':{'bad':BIG}})
        self.assertEqual(result['status'],'rejected');self.assertIn('UNIQUE_END',self.full(result)['error'])
    def test_large_operation_recovery_and_saved_replay_stay_compact(self):
        operation='candidate_check';args={'plugins':[],'idempotencyKey':'check'}
        identity=hashlib.sha256(encoded([self.c,operation,'check']).encode()).hexdigest()
        journal=self.data/'campaigns'/self.c/'meta-requests'/(identity+'.json')
        prior={'requestId':identity,'payload':hashlib.sha256(encoded(args).encode()).hexdigest(),'state':'outcome_unknown'}
        atomic_json(journal,prior)
        row={'id':'op-fixture','campaignId':self.c,'kind':'candidate_check','payload':args,'state':'failed','result':{'detail':BIG},'error':BIG}
        self.store.put('operations',row)
        with patch.object(self.api,'_call',side_effect=AssertionError('must not replay a side effect')):
            first=self.api.call(self.c,operation,args);second=self.api.call(self.c,operation,args)
        self.assertEqual(first,second);self.assertEqual(first['status'],'failed');self.assertEqual(first['operationId'],'op-fixture')
        self.assertEqual(self.full(first)['result']['detail'],BIG)
    def test_lost_write_response_publication_failure_then_retry_does_not_repeat(self):
        args={'plugins':[],'idempotencyKey':'publish'}
        with patch.object(self.api.receipts,'run',return_value={'operationId':'operation','state':'running','result':BIG}) as run:
            with patch.object(self.api.files,'publish',side_effect=OSError('disk full')):
                failed=self.api.call(self.c,'candidate_check',args)
            self.assertEqual(failed['status'],'outcome_unknown');self.assertTrue(failed['reconciliationRequired'])
            recovered=self.api.call(self.c,'candidate_check',args)
            self.assertEqual(run.call_count,1)
        self.assertEqual(recovered['status'],'running');self.assertEqual(self.full(recovered)['result'],BIG)
    def test_unresolved_journal_never_copies_its_error_into_receipt(self):
        op='candidate_check';args={'plugins':[],'idempotencyKey':'unknown'}
        identity=hashlib.sha256(encoded([self.c,op,'unknown']).encode()).hexdigest()
        atomic_json(self.data/'campaigns'/self.c/'meta-requests'/(identity+'.json'),{'requestId':identity,'payload':hashlib.sha256(encoded(args).encode()).hexdigest(),'state':'outcome_unknown','error':BIG})
        result=self.api.call(self.c,op,args)
        self.assertEqual(result['status'],'outcome_unknown');self.assertEqual(result['requestId'],identity)
        self.assertEqual(self.full(result)['error'],BIG)
    def test_explicit_read_pages_keep_unicode_tail_and_do_not_copy_metadata(self):
        text='\x00🧪证据'*10000+'TAIL'
        e=self.service.evidence.add(self.c,None,'large',text,{'archive':'large.txt','extra':BIG})
        for operation,key in [('evidence_read',{'id':e['id']}),('materials_read',{'ref':'evidence:'+e['id']})]:
            offset=0;parts=[]
            while offset is not None:
                result=self.api.call(self.c,operation,{**key,'offset':offset,'limit':32000})
                self.assertLessEqual(len(encoded(result).encode()),48*1024);self.assertNotIn('source',result)
                parts.append(result['text']);offset=result['nextOffset']
            self.assertEqual(''.join(parts),text)
    def test_v4_binding_retains_original_source_hashes(self):
        self.assertEqual(version(self.service,self.c),'meta-tools-v9')
        for name,sha in binding('meta-tools-v4')['files'].items():
            file=base.ROOT/'packages/meta-harness/protocols/meta-tools-v4'/name
            self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),sha)
