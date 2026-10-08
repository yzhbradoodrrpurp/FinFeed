"""Server-side reminder detection, bounded polling and durable email delivery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
import threading
import time
from backend.infrastructure.failure_log import failure
from backend.storage.notifications import fingerprint


def instant(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError,TypeError,AttributeError):
        return None


def times(stamp):
    return ' / '.join(datetime.fromtimestamp(stamp,ZoneInfo(zone)).strftime('%Y-%m-%d %H:%M')+' '+label
                    for zone,label in [('Asia/Shanghai','北京'),('America/New_York','美国东部')])


def event(category, key, title, body):
    return {'category':category,'key':key,'subject':'FinFeed · '+title,
            'body':body+'\n\n管理邮件提醒：登录 FinFeed → 我的账户 → 邮件提醒，可关闭提醒或解绑邮箱。'}


def macro_events(kind, data, previous, now, since):
    releases = {v for v in (data.get('last_release'),data.get('next_release')) if instant(v) is not None}
    releases.update(v for v in (previous or {}).get('releases',[]) if (instant(v) or 0)>now-86400)
    name = '非农就业报告 NFP' if kind=='jobs' else 'PCE 价格指数'
    events=[]
    source=data.get('calendar_source','')
    for release in sorted(releases):
        stamp=instant(release)
        body=f'{name}\n官方计划发布时间：{times(stamp)}\n官方日历：{source}\n'
        if stamp-86400<=now<stamp and since<=now:
            events.append(event(kind,f'{kind}:before:{release}',name+' 将于 24 小时内发布',body+'提醒以官方日历为准，发布时间可能调整。'))
        if stamp<=now<stamp+21600 and since<=stamp:
            events.append(event(kind,f'{kind}:release:{release}',name+' 已到计划发布时刻',body+'已到官方计划发布时刻；如原始机构临时延迟，以原始公告为准。FRED 数值可能稍后更新。'))
    latest=[m.get('latest') for m in data.get('metrics',[]) if m.get('latest')]
    period=min((m['date'] for m in latest),default='')
    old_period=(previous or {}).get('period','')
    if old_period and period>old_period:
        lines=[f"{m['label']}：{m['latest']['value']:.4g}{m.get('unit','')}，对应期 {m['latest']['date']}" for m in data['metrics'] if m.get('latest')]
        events.append(event(kind,f'{kind}:data:{period}',name+' 数据已更新','\n'.join(lines)+f"\n检索时间：{data.get('retrieved_at','')}\n数据经 FRED 获取，前值可能修订。\n"+source))
    return {'releases':sorted(releases),'period':max(period,old_period)},events


def treasury_events(data, previous, threshold):
    latest=data['metrics'][0]['latest']; day=latest['date']; value=latest['value']
    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
        raise ValueError('Invalid yield')
    if previous and day<previous['date']:
        return previous,[]
    above=value>=threshold
    next_value={'date':day,'value':value,'above':above,'threshold':threshold}
    if not previous or previous.get('threshold')!=threshold or previous['above']==above:
        return next_value,[]
    direction='达到' if above else '回落至下方'
    return next_value,[event('treasury',f'treasury:{threshold}:{day}:{above}',f'十年美债收益率{direction} {threshold:g}% 预警线',
        f"H.15 十年恒定期限收益率：{value:g}%\n数据日期：{day}\n此前记录：{previous['value']:g}%（{previous['date']}）\n检索时间：{data.get('retrieved_at','')}\n这是日度统计穿越提醒，不能代表盘中首次触线。预警线为个人观察设置。\nhttps://www.federalreserve.gov/releases/h15/\nhttps://fred.stlouisfed.org/series/DGS10")]


def item_events(category, source, items, previous, heading):
    # Existing items become the first baseline; no flood of historical emails.
    ids={str(item['id']) for item in items}; old=set((previous or {}).get('ids',[]))
    new=[item for item in items if str(item['id']) not in old] if previous is not None else []
    # Keep previously seen identifiers even as the two-quarter window rolls.
    value={'ids':sorted(old|ids)}
    if not new:
        return value,[]
    body='\n\n'.join(f"{item['title']}\n发布/申报时间：{item.get('date','未提供')}\n{item['url']}" for item in new)
    key=fingerprint(source+':'+':'.join(sorted(str(item['id']) for item in new)))
    return value,[event(category,category+':'+key,heading+f'（{len(new)} 条）',body)]


class NotificationWorker:
    def __init__(self, storage, mailer, market_store):
        self.storage=storage;self.mailer=mailer;self.market_store=market_store
        self.guard=threading.Lock();self.delivery_guard=threading.Lock();self.running=False;self.macro_running=False

    def trigger(self):
        if not self.mailer.ready:
            return False
        # Independent macro lane remains responsive during slow company retrieval.
        for lane in ('macro','companies'):
            attribute='macro_running' if lane=='macro' else 'running'
            with self.guard:
                if getattr(self,attribute):continue
                setattr(self,attribute,True)
            def run(lane=lane, attribute=attribute):
                try:self.cycle(lane)
                except Exception as exc:failure('notifications','cycle',error=exc)
                finally:
                    with self.guard:setattr(self,attribute,False)
            threading.Thread(target=run,daemon=True,name='notification-'+lane).start()
        return True

    def deliver(self):
        if not self.mailer.ready or not self.delivery_guard.acquire(blocking=False):return
        try:self._deliver()
        finally:self.delivery_guard.release()

    def _deliver(self):
        for _ in range(5):
            mail=self.storage.claim_mail(time.time())
            if not mail:break
            if time.time()-mail['created']>=23*3600:
                self.storage.finish_mail(mail);continue
            if not self.storage.allowed(mail):
                self.storage.finish_mail(mail,cancel=True);continue
            try:
                provider=self.mailer.send(mail['email'],mail['subject'],mail['body'],'finfeed-'+mail['id'])
                self.storage.finish_mail(mail,provider_id=provider)
            except Exception as exc:
                failure('email','delivery',error=exc)
                self.storage.finish_mail(mail)

    def cycle(self, lane=None):
        self.deliver()
        subscribers=self.storage.subscribers()
        if not subscribers:
            self.deliver();return
        from backend.services.whales import FUNDS
        tasks={}
        for user in subscribers:
            prefs=user['preferences']
            for kind in ('jobs','pce','treasury'):
                if prefs[kind]:tasks.setdefault('macro:'+kind,[]).append(user)
            if prefs['whales']:
                for kind in FUNDS:tasks.setdefault('whales:'+kind,[]).append(user)
            if prefs['news']:
                for symbol in user['state'].get('watchlist',[]):
                    for kind in ('calls','sec'):tasks.setdefault('news:'+kind+':'+symbol,[]).append(user)
        # Heavy provider retrieval never runs inside a login/page response.
        # Claims happen in the worker, so queued work cannot lease-expire early.
        tasks={key:value for key,value in tasks.items() if lane is None or (key.startswith('macro:') == (lane=='macro'))}
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix='notification-source') as pool:
            list(pool.map(lambda item:self.poll(*item),tasks.items()))
        self.deliver()

    def poll(self, source, users):
        now=time.time();token=self.storage.claim_source(source,now)
        if not token:return
        interval=3600
        try:
            parts=source.split(':');category=parts[0]
            if category=='macro':
                from backend.services.macro import snapshot
                kind=parts[1]
                data=self.cached('market:v1:macro:'+kind,3600,lambda:snapshot(kind,force=True))
                if data.get('errors') or not data.get('metrics') or not all(m.get('latest') for m in data['metrics']):raise ValueError('Incomplete macro data')
                if kind in ('jobs','pce'):
                    release=instant(data.get('next_release'));last=instant(data.get('last_release'))
                    near=any(stamp is not None and -21600<=stamp-now<=86400 for stamp in (release,last))
                    interval=60 if near else 3600
                    # Release-day data may lag the calendar. Bypass the hour cache.
                    approaching=any(stamp is not None and -1800<=stamp-now<=300 for stamp in (release,last))
                    age=now-(instant(data.get('retrieved_at')) or 0)
                    if approaching and age>=60:
                        data=snapshot(kind,force=True)
                        if not data.get('errors'):self.market_store.publish_cache('market:v1:macro:'+kind,data)
                    if data.get('errors'):raise ValueError('Incomplete release data')
                for user in users:
                    update=(lambda old,u=user:macro_events(kind,data,old,now,u['enabled_since'])) if kind!='treasury' else (lambda old,u=user:treasury_events(data,old,u['preferences']['treasury_threshold']))
                    self.storage.observe(user['user_id'],kind,update,expected=user)
            elif category=='whales':
                from backend.services.whales import snapshot
                kind=parts[1];data=self.cached('market:v1:whales:v5:'+kind,3600,lambda:snapshot(kind))
                if not data.get('totals_verified') or not data.get('report_date') or not data.get('sources'):raise ValueError('Incomplete current holdings')
                items=[{'id':r['accession'],'title':f"{data['name']} · {r['form']} · 持仓季度 {data['report_date']}",
                        'date':r.get('accepted_at') or r['filed_at'],'url':r['url']} for r in data['sources']]
                for user in users:self.storage.observe(user['user_id'],source,lambda old:item_events('whales',source,items,old,data['name']+' 新持仓披露'))
            else:
                from backend.services.news import snapshot
                kind,symbol=parts[1:];data=self.cached('market:v1:news:v1:'+kind+':'+symbol,3600,lambda:snapshot(symbol,kind))
                if data.get('errors') or not isinstance(data.get('items'),list):raise ValueError('Incomplete news data')
                items=[{'id':r['url'],'title':r['title'],'date':r['published_at'],'url':r['url']} for r in data['items']]
                for user in users:self.storage.observe(user['user_id'],source,lambda old:item_events('news',source,items,old,symbol+' 新'+('财报电话会' if kind=='calls' else 'SEC 披露')),expected=user)
            self.storage.finish_source(source,token,time.time()+interval)
            self.deliver()
        except Exception as exc:
            failure('notifications','source_poll',error=exc)
            self.storage.finish_source(source,token,time.time()+300)

    def cached(self, key, ttl, loader):
        saved=self.market_store.get_cache(key)
        if saved and time.time()-saved[1]<ttl and not any(saved[0].get(k) for k in ('stale','partial','errors')):
            return saved[0]
        data=loader()
        if not any(data.get(k) for k in ('stale','partial','errors')):
            self.market_store.publish_cache(key,data)
        return data
