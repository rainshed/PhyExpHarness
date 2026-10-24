import json
import tempfile
import unittest
from pathlib import Path
from src.control.accounting import reconcile_audit
from src.control.store import Store


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'control.sqlite')
        self.file=self.root/'gateway-audit.jsonl'

    def reserve(self,id,lease='lease'):
        self.store.put('usage',{'id':id,'campaignId':'campaign','leaseId':lease,'purpose':'meta',
            'reservedTokens':300000,'confirmedTokens':None,'status':'unknown'})

    def deny(self,id):
        return {'type':'admission_denied','id':id,'failure':{'source':'host-admission','stage':'admission',
            'code':'accounting_unavailable','requestId':id}}

    def reconcile(self,rows):
        self.file.write_text('\n'.join(map(json.dumps,rows))+'\n')
        reconcile_audit(self.store,'campaign','lease',self.file)

    def test_explicit_denial_releases_only_unused_reservation_and_is_idempotent(self):
        self.reserve('unused');self.reserve('uncertain')
        rows=[{'type':'admission_started','id':'unused'},self.deny('unused'),{'type':'admission_started','id':'uncertain'}]
        self.reconcile(rows);self.reconcile(rows)
        row=self.store.get('usage','unused')
        self.assertEqual((row['status'],row['confirmedTokens']),('reported',0))
        self.assertTrue(row['reconciledFromHostAudit'])
        self.assertEqual(self.store.get('usage','uncertain')['status'],'unknown')
        self.assertEqual(len(self.store.events('campaign',0)),1)

    def test_contradictory_provider_activity_and_wrong_lease_are_not_zeroed(self):
        for kind in ['request','admitted','chunk','settled']:
            self.reserve(kind)
            self.reconcile([self.deny(kind),{'type':kind,'id':kind}])
            self.assertEqual(self.store.get('usage',kind)['status'],'unknown')
        self.reserve('other','other-lease');self.reconcile([self.deny('other')])
        self.assertEqual(self.store.get('usage','other')['status'],'unknown')

    def test_real_usage_and_incomplete_receipts_remain_distinct(self):
        for id in ['complete','partial','failed']:self.reserve(id)
        self.reconcile([
            {'type':'settled','id':'complete','usage':{'totalTokens':123},'finish':{'kind':'stop'}},
            {'type':'settled','id':'partial','usage':{'inputTokens':1},'finish':{'kind':'stop'}},
            {'type':'settled','id':'failed','usage':{'totalTokens':0},'finish':{'kind':'error'}}])
        self.assertEqual(self.store.get('usage','complete')['confirmedTokens'],123)
        self.assertEqual(self.store.get('usage','complete')['status'],'reported')
        self.assertEqual(self.store.get('usage','partial')['status'],'unknown')
        self.assertEqual(self.store.get('usage','failed')['status'],'unknown')

    def test_untrusted_or_mismatched_denial_cannot_release_usage(self):
        for change in [{'source':'runner'},{'stage':'model'},{'requestId':'another'}]:
            self.reserve('unused');row=self.deny('unused');row['failure'].update(change)
            self.reconcile([row]);self.assertEqual(self.store.get('usage','unused')['status'],'unknown')
