"""Notification isolation, event baselines, durable dedup and delivery boundaries."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from backend.app import create_app
from backend.storage.store import Store
from backend.storage.notifications import NotificationStore, DEFAULTS
from backend.services.notifications import NotificationWorker, item_events, treasury_events, macro_events, instant, event

class NotificationCases(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(sqlite_path=str(Path(self.tmp.name)/'test.db'))
        self.n=NotificationStore(self.store)
        with self.store.transaction() as c:
            self.uid=self.store.owner(c)['user_handle'];self.token=self.store.new_session(c,self.uid)
        self.mailer=Mock(ready=True);self.mailer.send.return_value='provider-id'

    def enabled(self):
        code=self.n.begin_verification(self.uid,'user@example.com')
        self.assertTrue(self.n.verify(self.uid,code))
        self.n.save(self.uid,{**DEFAULTS,'enabled':True})

    def enqueue(self):
        self.n.observe(self.uid,'jobs',lambda old:({},[event('jobs','release:one','NFP','body')]))

    def test_verification_attempts_expiry_rate_limit_and_recipient_reset(self):
        code=self.n.begin_verification(self.uid,'user@example.com',now=1000)
        with self.assertRaises(ValueError):self.n.begin_verification(self.uid,'other@example.com',now=1020)
        for _ in range(5):self.assertFalse(self.n.verify(self.uid,'wrong',now=1001))
        self.assertFalse(self.n.verify(self.uid,code,now=1001))
        code=self.n.begin_verification(self.uid,'user@example.com',now=1100)
        self.assertFalse(self.n.verify(self.uid,code,now=1701))
        self.enabled();self.enqueue()
        code=self.n.begin_verification(self.uid,'new@example.com',now=time.time()+61)
        self.assertTrue(self.n.verify(self.uid,code,now=time.time()+62))
        self.assertFalse(self.n.settings(self.uid)['preferences']['enabled'])
        self.assertEqual(self.n.delivery_status(self.uid),{'cancelled':1})

    def test_dedup_persists_and_disabled_delivery_is_cancelled(self):
        self.enabled();self.enqueue();NotificationStore(self.store).observe(self.uid,'jobs',lambda old:({},[event('jobs','release:one','NFP','body')]))
        self.assertEqual(self.n.delivery_status(self.uid),{'pending':1})
        self.n.save(self.uid,{**DEFAULTS,'enabled':True,'jobs':False})
        NotificationWorker(self.n,self.mailer,self.store).deliver()
        self.mailer.send.assert_not_called()

    def test_delivery_retry_uses_same_id_and_stops_before_dedup_expires(self):
        self.enabled();self.enqueue();worker=NotificationWorker(self.n,self.mailer,self.store)
        self.mailer.send.side_effect=RuntimeError('temporary')
        worker.deliver();first=self.mailer.send.call_args.args[-1]
        with self.store.transaction() as c:self.store.execute(c,'UPDATE notification_outbox SET due=0')
        self.mailer.send.side_effect=None;worker.deliver()
        self.assertEqual(self.mailer.send.call_args.args[-1],first)
        self.assertEqual(self.n.delivery_status(self.uid),{'sent':1})
        with self.store.transaction() as c:self.store.execute(c,"UPDATE notification_outbox SET status='pending',due=0,created=?",(time.time()-86400,))
        self.mailer.send.reset_mock();worker.deliver();self.mailer.send.assert_not_called()
        self.assertEqual(self.n.delivery_status(self.uid),{'failed':1})

    def test_old_settings_and_removed_ticker_do_not_enqueue(self):
        self.enabled()
        original=self.n.subscribers()[0]
        self.n.save(self.uid,{**DEFAULTS,'enabled':True,'treasury_threshold':6})
        self.n.observe(self.uid,'treasury',lambda old:({},[event('treasury','late','late','late')]),expected=original)
        self.n.observe(self.uid,'news:calls:NOTINLIST',lambda old:({},[event('news','removed','removed','removed')]))
        self.assertEqual(self.n.delivery_status(self.uid),{})

    def test_other_account_settings_are_isolated(self):
        self.enabled()
        self.assertIsNone(self.n.settings('another-account')['email'])
        self.n.save('another-account',DEFAULTS)
        self.assertEqual(self.n.settings(self.uid)['email'],'user@example.com')
        self.assertTrue(self.n.settings(self.uid)['preferences']['enabled'])

    def test_source_lease_ownership(self):
        token=self.n.claim_source('jobs',1000)
        self.assertIsNotNone(token);self.assertIsNone(self.n.claim_source('jobs',1001))
        self.n.finish_source('jobs','wrong',0);self.assertIsNone(self.n.claim_source('jobs',1002))
        self.n.finish_source('jobs',token,2000);self.assertIsNone(self.n.claim_source('jobs',1999))
        self.assertIsNotNone(self.n.claim_source('jobs',2000))

    def test_baseline_and_crossings(self):
        item={'id':'one','title':'one','url':'https://example.com/one','date':'2026-10-08'}
        baseline,events=item_events('news','AAPL',[item],None,'AAPL');self.assertEqual(events,[])
        _,events=item_events('news','AAPL',[item],baseline,'AAPL');self.assertEqual(events,[])
        _,events=item_events('news','AAPL',[{**item,'id':'two'}],baseline,'AAPL');self.assertEqual(len(events),1)
        def data(day,value):return {'metrics':[{'latest':{'date':day,'value':value}}]}
        base,events=treasury_events(data('2026-10-07',5),None,5.1);self.assertEqual(events,[])
        above,events=treasury_events(data('2026-10-08',5.1),base,5.1);self.assertEqual(len(events),1)
        _,events=treasury_events(data('2026-10-06',4),above,5.1);self.assertEqual(events,[])
        _,events=treasury_events(data('2026-10-09',5),above,5.1);self.assertEqual(len(events),1)
        with self.assertRaises(ValueError):treasury_events(data('2026-10-09',float('nan')),above,5.1)

    def test_macro_calendar_and_new_period(self):
        release='2026-10-09T08:30:00-04:00';stamp=instant(release)
        data={'next_release':release,'metrics':[{'label':'NFP','latest':{'date':'2026-08-01','value':100}}]}
        base,events=macro_events('jobs',data,None,stamp-86399,stamp-90000)
        self.assertIn('before:',events[0]['key'])
        _,events=macro_events('jobs',data,base,stamp,stamp-90000)
        self.assertIn('release:',events[0]['key'])
        data['metrics'][0]['latest']['date']='2026-09-01'
        _,events=macro_events('jobs',data,base,stamp+1,stamp-90000)
        self.assertTrue(any(':data:' in e['key'] for e in events))

    def test_routes_auth_csrf_and_protected_tick(self):
        with patch('backend.infrastructure.mailer.Mailer',return_value=self.mailer):
            app=create_app({'TESTING':True,'PUBLIC_ORIGIN':'http://localhost','FINFEED_NOTIFICATION_CRON_TOKEN':'t'*40},self.store)
        client=app.test_client();self.assertEqual(client.get('/api/notifications').status_code,401)
        client.set_cookie('finfeed_test_session',self.token)
        self.assertEqual(client.get('/api/notifications').status_code,200)
        self.assertEqual(client.put('/api/notifications',json=DEFAULTS).status_code,403)
        self.assertEqual(client.post('/api/notifications/tick',json={}).status_code,403)
        with patch.object(app.extensions['finfeed_notification_worker'],'trigger') as trigger:
            self.assertEqual(client.post('/api/notifications/tick',json={},headers={'Authorization':'Bearer '+'t'*40}).status_code,202)
            trigger.assert_called_once()
        self.mailer.ready=False
        response=client.post('/api/notifications/email',json={'email':'user@example.com'},headers={'Origin':'http://localhost','X-FinFeed-Client':'1'})
        self.assertEqual(response.status_code,503)
        self.assertFalse(self.n.settings(self.uid)['verified'])
