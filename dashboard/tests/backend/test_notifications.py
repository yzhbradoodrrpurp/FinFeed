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

    def test_personalized_alert_envelope(self):
        self.enabled();self.enqueue()
        with self.store.transaction() as c:
            self.store.execute(c, 'UPDATE accounts SET name=? WHERE id=?', ('Liam',self.uid))
        NotificationWorker(self.n,self.mailer,self.store).deliver()
        body=self.mailer.send.call_args.args[2]
        self.assertTrue(body.startswith('Dear Liam,\n\n'))
        self.assertIn('body',body)
        self.assertIn('管理邮件提醒',body)
        self.assertTrue(body.endswith('Best regards,\nFinFeed Team'))

    def test_verification_envelope(self):
        from backend.infrastructure.mailer import format_email
        body=format_email('Liam\n', '邮箱绑定验证码：123456', verification=True)
        self.assertTrue(body.startswith('Dear Liam,\n\n'))
        self.assertIn('绑定收件邮箱',body)
        self.assertIn('123456',body)
        self.assertEqual(body.count('Best regards,'),1)

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

    def test_gmail_uncertain_or_crashed_send_is_not_reclaimed(self):
        from backend.infrastructure.mailer import DeliveryUncertain
        self.enabled();self.enqueue();self.mailer.provider='gmail'
        def send(*args, before_send):
            before_send()
            raise DeliveryUncertain('unknown')
        self.mailer.send.side_effect=send
        worker=NotificationWorker(self.n,self.mailer,self.store)
        worker.deliver();worker.deliver()
        self.assertEqual(self.mailer.send.call_count,1)
        self.assertEqual(self.n.delivery_status(self.uid),{'uncertain':1})
        with self.store.transaction() as c:
            self.store.execute(c,"UPDATE notification_outbox SET status='sending',lease=0")
        self.assertIsNone(self.n.claim_mail(time.time()+1000))

    def test_gmail_accepted_then_db_failure_does_not_requeue(self):
        self.enabled();self.enqueue();self.mailer.provider='gmail'
        def send(*args, before_send):
            before_send()
            return 'gmail-id'
        self.mailer.send.side_effect=send
        with patch.object(self.n,'finish_mail',side_effect=RuntimeError('db unavailable')):
            with self.assertRaises(RuntimeError):
                NotificationWorker(self.n,self.mailer,self.store).deliver()
        self.assertEqual(self.n.delivery_status(self.uid),{'sending':1})
        self.assertIsNone(self.n.claim_mail(time.time()+1000))

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
        stamp=instant('2026-10-08T12:00:00Z')
        baseline,events=item_events('news','AAPL',[item],None,'AAPL',now=stamp);self.assertEqual(events,[])
        _,events=item_events('news','AAPL',[item],baseline,'AAPL',now=stamp);self.assertEqual(events,[])
        _,events=item_events('news','AAPL',[{**item,'id':'two'}],baseline,'AAPL',now=stamp);self.assertEqual(len(events),1)
        def data(day,value):return {'metrics':[{'latest':{'date':day,'value':value}}]}
        base,events=treasury_events(data('2026-10-07',5),None,5.1);self.assertEqual(events,[])
        above,events=treasury_events(data('2026-10-08',5.1),base,5.1);self.assertEqual(len(events),1)
        _,events=treasury_events(data('2026-10-06',4),above,5.1);self.assertEqual(events,[])
        _,events=treasury_events(data('2026-10-09',5),above,5.1);self.assertEqual(len(events),1)
        with self.assertRaises(ValueError):treasury_events(data('2026-10-09',float('nan')),above,5.1)

    def test_sec_accession_dedup_backfill_and_outage_recovery(self):
        source='news:sec:MU'
        stamp=instant('2026-10-11T12:00:00Z')
        def item(accession, date, document='main.htm'):
            url=f'https://www.sec.gov/Archives/edgar/data/723125/{accession}/{document}'
            return {'id':url,'url':url,'title':'10-Q','date':date}
        old=item('000072312526000015','2026-06-25')
        # Upgrade legacy URL cursors and suppress changes of exhibit URL.
        baseline,events=item_events('news',source,[{**old,'id':old['id'].replace('main.htm','exhibit.htm')}],{'ids':[old['id']]},'MU',now=stamp)
        self.assertEqual(events,[]);self.assertEqual(len(baseline['ids']),1)
        historical=item('000072312526000014','2026-05-01')
        current=item('000072312526000025','2026-10-11')
        value,events=item_events('news',source,[historical,current],baseline,'MU',now=stamp)
        self.assertEqual(len(events),1);self.assertNotIn(historical['url'],events[0]['body'])
        self.assertIn(current['url'],events[0]['body'])
        self.assertEqual(item_events('news',source,[current],value,'MU',now=stamp)[1],[])
        # Successful empty reads and legacy empty cursors cannot replay old rows.
        empty,_=item_events('news',source,[],None,'MU',now=stamp)
        self.assertEqual(item_events('news',source,[historical],empty,'MU',now=stamp)[1],[])
        self.assertEqual(item_events('news',source,[historical],{'ids':[]},'MU',now=stamp)[1],[])
        # Actual filings published during an outage remain eligible on recovery.
        recovered,events=item_events('news',source,[item('000072312526000026','2026-10-12')],value,'MU',now=stamp+3*86400)
        self.assertEqual(len(events),1)
        # Subscription start also fences old events; invalid/future dates stay quiet.
        for date in ['2026-10-10','2026-10-15','', '2026-02-30']:
            self.assertEqual(item_events('news',source,[item('000072312526000027',date)],{'ids':[],'observed_at':stamp-86400},'MU',now=stamp,since=stamp)[1],[])

    def test_late_provider_index_does_not_move_notification_start(self):
        start=instant('2026-10-11T12:00:00Z')
        source='news:sec:MU'
        baseline,_=item_events('news',source,[],None,'MU',now=start,since=start)
        # Several successful empty polls must not advance the eligibility boundary.
        later,_=item_events('news',source,[],baseline,'MU',now=start+4*86400,since=start)
        url='https://www.sec.gov/Archives/edgar/data/723125/000072312526000030/main.htm'
        filing={'id':url,'url':url,'title':'10-Q','date':'2026-10-12'}
        value,events=item_events('news',source,[filing],later,'MU',now=start+5*86400,since=start)
        self.assertEqual(len(events),1)
        self.assertEqual(value['baseline_at'],start)
        self.assertEqual(item_events('news',source,[filing],value,'MU',now=start+6*86400,since=start)[1],[])
        # Changing the document also remains deduplicated after a restart.
        changed={**filing,'id':url.replace('main.htm','exhibit.htm')}
        self.assertEqual(item_events('news',source,[changed],value,'MU',now=start+6*86400,since=start)[1],[])

    def test_future_and_unknown_dates_can_become_publishable(self):
        start=instant('2026-10-11T12:00:00Z')
        base,_=item_events('news','news:calls:MU',[],None,'MU',now=start)
        for initial in ['', '2026-10-12T12:00:00Z']:
            item={'id':'call','url':'https://example.com/call','title':'call','date':initial}
            waiting,events=item_events('news','news:calls:MU',[item],base,'MU',now=start)
            self.assertEqual(events,[]);self.assertNotIn('call',waiting['ids'])
            item['date']='2026-10-12T12:00:00Z'
            value,events=item_events('news','news:calls:MU',[item],waiting,'MU',now=start+2*86400)
            self.assertEqual(len(events),1)
            self.assertEqual(item_events('news','news:calls:MU',[item],value,'MU',now=start+3*86400)[1],[])

    def test_call_timestamp_watermark(self):
        stamp=instant('2026-10-11T12:00:00Z')
        base={'ids':[],'observed_at':stamp}
        item={'id':'call','url':'https://example.com/call','title':'call','date':'2026-10-11T11:00:00Z'}
        self.assertEqual(item_events('news','news:calls:MU',[item],base,'MU',now=stamp+3600)[1],[])
        item['date']='2026-10-11T12:30:00Z'
        self.assertEqual(len(item_events('news','news:calls:MU',[item],base,'MU',now=stamp+3600)[1]),1)

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
