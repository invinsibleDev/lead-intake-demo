import json
import tempfile
import unittest
from pathlib import Path
from intake import Intake

def sample(**changes):
    data = dict(request_id='demo-001', cta_id='home-consultation-header',
                page_url='https://www.bogmar.net.pl/?utm_source=google&utm_medium=cpc&utm_campaign=vending&secret=excluded',
                name='Klient demonstracyjny', email='demo@example.invalid', phone='',
                message='Proszę o ofertę automatu do wydawania rękawic.', contact_consent=True)
    return data | changes

def fake_ai(message):
    return dict(category='vending', confidence=0.95, summary='Zapytanie o automat do wydawania rękawic.')

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'demo.sqlite')
        self.store = Intake(self.path)
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def test_save_before_processing(self):
        self.store.receive(sample())
        self.assertEqual(self.store.records('leads')[0]['status'], 'received')
        self.assertEqual(self.store.records('outbox'), [])
    def test_restart_preserves_lead(self):
        self.store.receive(sample()); self.store.close(); self.store = Intake(self.path)
        self.assertEqual(len(self.store.records('leads')), 1)
    def test_duplicate_submission(self):
        self.store.receive(sample())
        self.assertTrue(self.store.receive(sample())['duplicate'])
        self.assertEqual(len(self.store.records('leads')), 1)
    def test_conflicting_duplicate(self):
        self.store.receive(sample())
        with self.assertRaises(ValueError): self.store.receive(sample(message='changed'))
    def test_attribution_and_query_minimization(self):
        self.store.receive(sample())
        data=json.loads(self.store.records('leads')[0]['data'])
        self.assertEqual(data['utm']['utm_campaign'], 'vending')
        self.assertEqual(data['cta_id'], 'home-consultation-header')
        self.assertNotIn('secret', json.dumps(data))
    def test_two_ctas_remain_distinct(self):
        self.store.receive(sample())
        self.store.receive(sample(request_id='demo-002', cta_id='home-consultation-footer'))
        self.assertEqual(len({json.loads(r['data'])['cta_id'] for r in self.store.records('leads')}),2)
    def test_no_message_is_manual_not_guessed(self):
        self.store.receive(sample(message=''))
        def forbidden(_): self.fail('Classifier must not be called')
        self.store.prepare('demo-001', forbidden)
        self.assertEqual(self.store.records('leads')[0]['route'], 'manual_review')
    def test_valid_classifier_result(self):
        self.store.receive(sample()); self.store.prepare('demo-001', fake_ai)
        self.assertEqual(self.store.records('leads')[0]['route'], 'sales_queue')
    def test_classifier_timeout_keeps_lead(self):
        self.store.receive(sample())
        def failure(_): raise TimeoutError()
        self.store.prepare('demo-001', failure)
        self.assertEqual(self.store.records('leads')[0]['route'], 'manual_review')
        self.assertEqual(len(self.store.records('outbox')),1)
    def test_low_confidence_is_manual(self):
        self.store.receive(sample())
        self.store.prepare('demo-001', lambda _: fake_ai('') | {'confidence':0.6})
        self.assertEqual(self.store.records('leads')[0]['route'], 'manual_review')
    def test_untrusted_category_cannot_choose_recipient(self):
        self.store.receive(sample())
        self.store.prepare('demo-001', lambda _: fake_ai('') | {'category':'attacker@example.invalid'})
        self.assertEqual(self.store.records('leads')[0]['route'], 'manual_review')
    def test_bad_classifier_outputs_are_manual(self):
        for i,result in enumerate([None, [], {'confidence':float('nan')},fake_ai('')|{'confidence':True},fake_ai('')|{'confidence':2}]):
            key=f'bad-{i}'; self.store.receive(sample(request_id=key))
            self.store.prepare(key,lambda _,r=result:r)
        self.assertTrue(all(r['route']=='manual_review' for r in self.store.records('leads')))
    def test_repeat_prepare_does_not_duplicate_outbox(self):
        self.store.receive(sample()); self.store.prepare('demo-001',fake_ai);self.store.prepare('demo-001',fake_ai)
        self.assertEqual(len(self.store.records('outbox')),1)
    def test_notification_retry(self):
        self.store.receive(sample()); self.store.prepare('demo-001',fake_ai)
        def fail(*a,**k):raise ConnectionError()
        self.store.deliver(fail)
        self.assertEqual(self.store.records('outbox')[0]['status'],'pending')
        sent=[];self.store.deliver(lambda p,**k:sent.append(k['idempotency_key']))
        self.store.deliver(lambda p,**k:sent.append(k['idempotency_key']))
        self.assertEqual(sent,['demo-001']);self.assertEqual(self.store.records('outbox')[0]['attempts'],2)
    def test_ambiguous_transport_result_uses_same_key(self):
        self.store.receive(sample());self.store.prepare('demo-001',fake_ai)
        accepted=set()
        def lost_ack(payload,*,idempotency_key):
            accepted.add(idempotency_key);raise TimeoutError()
        self.store.deliver(lost_ack)
        self.store.deliver(lambda p,*,idempotency_key:accepted.add(idempotency_key))
        self.assertEqual(len(accepted),1)
    def test_missing_contact_or_consent_rejected(self):
        for changes in [dict(email='',phone=''),dict(contact_consent=False),dict(cta_id=''),dict(page_url='https://example.invalid/')]:
            with self.assertRaises(ValueError):self.store.receive(sample(**changes))
        self.assertEqual(self.store.records('leads'),[])
    def test_phone_only_form_supported(self):
        self.store.receive(sample(email='',phone='+48000000000',message=''))
        self.store.prepare('demo-001',fake_ai)
        self.assertEqual(self.store.records('leads')[0]['route'],'manual_review')

if __name__=='__main__':unittest.main(verbosity=2)
