"""Private email subscriptions, persistent event cursors and leased outbox."""
import hashlib
import json
import secrets
import time

DEFAULTS = {'enabled': False, 'jobs': True, 'pce': True, 'treasury': True,
            'whales': True, 'news': True, 'treasury_threshold': 5.1}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS notification_settings (
 user_id TEXT PRIMARY KEY, email TEXT, pending_email TEXT, code_hash TEXT,
 code_expires DOUBLE PRECISION NOT NULL DEFAULT 0, code_attempts INTEGER NOT NULL DEFAULT 0,
 code_sent DOUBLE PRECISION NOT NULL DEFAULT 0, preferences TEXT NOT NULL,
 enabled_since DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notification_cursors (
 user_id TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(user_id,source)
);
CREATE TABLE IF NOT EXISTS notification_sources (
 source TEXT PRIMARY KEY, due DOUBLE PRECISION NOT NULL DEFAULT 0,
 lease DOUBLE PRECISION NOT NULL DEFAULT 0, token TEXT
);
CREATE TABLE IF NOT EXISTS notification_outbox (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, email TEXT NOT NULL, category TEXT NOT NULL,
 subject TEXT NOT NULL, body TEXT NOT NULL, created DOUBLE PRECISION NOT NULL,
 due DOUBLE PRECISION NOT NULL, lease DOUBLE PRECISION NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', provider_id TEXT
);
CREATE INDEX IF NOT EXISTS notification_outbox_ready ON notification_outbox(status,due,lease);
CREATE INDEX IF NOT EXISTS notification_outbox_user ON notification_outbox(user_id,status);
'''

def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()

class NotificationStore:
    def __init__(self, store):
        self.store = store

    def _row(self, connection, uid):
        self.store.execute(connection, 'INSERT INTO notification_settings(user_id,preferences) VALUES (?,?) ON CONFLICT(user_id) DO NOTHING', (uid, json.dumps(DEFAULTS)))
        suffix = '' if self.store.sqlite_path else ' FOR UPDATE'
        return self.store.execute(connection, 'SELECT * FROM notification_settings WHERE user_id=?'+suffix, (uid,)).fetchone()

    def settings(self, uid):
        with self.store.transaction() as c:
            row = self._row(c, uid)
            return {'email': row['email'], 'pending_email': row['pending_email'],
                    'preferences': json.loads(row['preferences']), 'verified': bool(row['email'])}

    def begin_verification(self, uid, email, now=None):
        now = time.time() if now is None else now
        code = f'{secrets.randbelow(1000000):06d}'
        with self.store.transaction() as c:
            self._row(c, uid)
            # Rate limits and replacement are atomic across processes.
            changed = self.store.execute(c, 'UPDATE notification_settings SET pending_email=?,code_hash=?,code_expires=?,code_attempts=0,code_sent=? WHERE user_id=? AND code_sent<=?',
                (email, fingerprint(uid+':'+code), now+600, now, uid, now-60)).rowcount
            if not changed:
                raise ValueError('请等待 60 秒后再发送验证码')
        return code

    def verify(self, uid, code, now=None):
        now = time.time() if now is None else now
        with self.store.transaction() as c:
            row = self._row(c, uid)
            if not row['code_hash'] or row['code_expires'] < now or row['code_attempts'] >= 5:
                return False
            self.store.execute(c, 'UPDATE notification_settings SET code_attempts=code_attempts+1 WHERE user_id=?', (uid,))
            if not secrets.compare_digest(row['code_hash'], fingerprint(uid+':'+code)):
                return False
            prefs = json.loads(row['preferences']); prefs['enabled'] = False
            # Changing recipient never forwards the previous recipient's queue.
            self.store.execute(c, "UPDATE notification_outbox SET status='cancelled' WHERE user_id=? AND status='pending'", (uid,))
            self.store.execute(c, 'DELETE FROM notification_cursors WHERE user_id=?', (uid,))
            self.store.execute(c, 'UPDATE notification_settings SET email=pending_email,pending_email=NULL,code_hash=NULL,preferences=?,enabled_since=0 WHERE user_id=?', (json.dumps(prefs), uid))
            return True

    def save(self, uid, prefs):
        now = time.time()
        with self.store.transaction() as c:
            row = self._row(c, uid); old = json.loads(row['preferences'])
            if prefs['enabled'] and not row['email']:
                raise ValueError('请先验证收件邮箱')
            for category in ('jobs','pce','treasury','whales','news'):
                if not prefs[category]:
                    self.store.execute(c, "UPDATE notification_outbox SET status='cancelled' WHERE user_id=? AND category=? AND status='pending'", (uid, category))
            # Re-enabling a category establishes a new baseline, no historical flood.
            for category in ('jobs','pce','treasury','whales','news'):
                if (prefs['enabled'] and not old['enabled']) or (prefs[category] and not old[category]) or (category=='treasury' and prefs['treasury_threshold']!=old['treasury_threshold']):
                    self.store.execute(c, 'DELETE FROM notification_cursors WHERE user_id=? AND source LIKE ?', (uid, category+'%'))
            since = now if prefs['enabled'] and not old['enabled'] else row['enabled_since']
            self.store.execute(c, 'UPDATE notification_settings SET preferences=?,enabled_since=? WHERE user_id=?', (json.dumps(prefs), since, uid))
            if not prefs['enabled']:
                self.store.execute(c, "UPDATE notification_outbox SET status='cancelled' WHERE user_id=? AND status='pending'", (uid,))
        return self.settings(uid)

    def unbind(self, uid):
        with self.store.transaction() as c:
            self.store.execute(c, 'DELETE FROM notification_settings WHERE user_id=?', (uid,))
            self.store.execute(c, 'DELETE FROM notification_cursors WHERE user_id=?', (uid,))
            self.store.execute(c, "UPDATE notification_outbox SET status='cancelled' WHERE user_id=? AND status='pending'", (uid,))

    def subscribers(self):
        with self.store.transaction() as c:
            rows = self.store.execute(c, 'SELECT n.*,a.state FROM notification_settings n JOIN accounts a ON a.id=n.user_id WHERE n.email IS NOT NULL AND NOT EXISTS(SELECT 1 FROM disabled_accounts d WHERE d.id=a.id)').fetchall()
            return [{**dict(r), 'preferences': json.loads(r['preferences']), 'state': json.loads(r['state']) if r['state'] else {'watchlist': []}}
                    for r in rows if json.loads(r['preferences']).get('enabled')]

    def observe(self, uid, source, update, expected=None):
        """Atomically advance a cursor and enqueue its derived events."""
        with self.store.transaction() as c:
            settings = self._row(c, uid); prefs = json.loads(settings['preferences'])
            if expected and (settings['email'] != expected['email'] or prefs != expected['preferences']):
                return
            if source.startswith('news:'):
                account = self.store.account(c, uid, lock=False)
                if source.rsplit(':',1)[-1] not in json.loads(account['state'] or '{}').get('watchlist',[]):
                    return
            suffix = '' if self.store.sqlite_path else ' FOR UPDATE'
            self.store.execute(c, 'INSERT INTO notification_cursors VALUES (?,?,?) ON CONFLICT(user_id,source) DO NOTHING', (uid, source, 'null'))
            row = self.store.execute(c, 'SELECT payload FROM notification_cursors WHERE user_id=? AND source=?'+suffix, (uid, source)).fetchone()
            value, events = update(json.loads(row['payload']))
            self.store.execute(c, 'UPDATE notification_cursors SET payload=? WHERE user_id=? AND source=?', (json.dumps(value), uid, source))
            for event in events:
                if not settings['email'] or not prefs.get('enabled') or not prefs.get(event['category']):
                    continue
                key = fingerprint(uid+':'+event['key'])
                self.store.execute(c, 'INSERT INTO notification_outbox(id,user_id,email,category,subject,body,created,due) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                    (key, uid, settings['email'], event['category'], event['subject'], event['body'], time.time(), time.time()))

    def claim_source(self, source, now):
        token = secrets.token_hex(16)
        with self.store.transaction(cache=True) as c:
            self.store.execute(c, 'INSERT INTO notification_sources(source) VALUES (?) ON CONFLICT(source) DO NOTHING', (source,))
            claimed = self.store.execute(c, 'UPDATE notification_sources SET lease=?,token=? WHERE source=? AND due<=? AND lease<=?', (now+600,token,source,now,now)).rowcount
        return token if claimed else None

    def finish_source(self, source, token, due):
        with self.store.transaction(cache=True) as c:
            self.store.execute(c, 'UPDATE notification_sources SET due=?,lease=0,token=NULL WHERE source=? AND token=?', (due,source,token))

    def claim_mail(self, now):
        with self.store.transaction() as c:
            rows = self.store.execute(c, "SELECT * FROM notification_outbox WHERE status='pending' AND due<=? AND lease<=? ORDER BY created LIMIT 10", (now,now)).fetchall()
            for row in rows:
                changed = self.store.execute(c, "UPDATE notification_outbox SET lease=?,attempts=attempts+1 WHERE id=? AND status='pending' AND lease<=?", (now+90,row['id'],now)).rowcount
                if changed:
                    return dict(row)
        return None

    def allowed(self, mail):
        with self.store.transaction() as c:
            row = self.store.execute(c, 'SELECT n.* FROM notification_settings n WHERE user_id=? AND NOT EXISTS(SELECT 1 FROM disabled_accounts d WHERE d.id=n.user_id)', (mail['user_id'],)).fetchone()
            return bool(row and row['email']==mail['email'] and json.loads(row['preferences']).get('enabled') and json.loads(row['preferences']).get(mail['category']))

    def mark_sending(self, mail):
        # Gmail has no idempotency key. A crashed sender must not be reclaimed.
        with self.store.transaction() as c:
            changed = self.store.execute(c, "UPDATE notification_outbox SET status='sending' WHERE id=? AND status='pending' AND attempts=?", (mail['id'], mail['attempts']+1)).rowcount
            if not changed:
                raise RuntimeError('邮件发送任务已变更')

    def mark_uncertain(self, mail):
        with self.store.transaction() as c:
            self.store.execute(c, "UPDATE notification_outbox SET status='uncertain',lease=0 WHERE id=?", (mail['id'],))

    def finish_mail(self, mail, provider_id=None, cancel=False):
        with self.store.transaction() as c:
            status = 'sent' if provider_id else 'cancelled' if cancel else 'pending'
            # Expire old reminders instead of delivering stale alerts.
            if not provider_id and time.time()-mail['created'] >= 23*3600:
                status = 'failed'
            due = time.time()+min(3600,60*2**min(mail['attempts'],6))
            self.store.execute(c, 'UPDATE notification_outbox SET status=?,provider_id=?,due=?,lease=0 WHERE id=?', (status,provider_id,due,mail['id']))

    def delivery_status(self, uid):
        with self.store.transaction() as c:
            rows=self.store.execute(c, 'SELECT status,COUNT(*) AS total FROM notification_outbox WHERE user_id=? GROUP BY status', (uid,)).fetchall()
            return {r['status']:r['total'] for r in rows}
