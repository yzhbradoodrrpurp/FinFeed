"""One project-owned timer; clients read snapshots, never own refresh cadence."""
import json
import os
from pathlib import Path
import threading
import time
from backend.infrastructure.failure_log import failure


def symbols(store):
    # Do not export identities or account state into public market caches/logs.
    with store.transaction() as connection:
        rows = store.execute(connection, 'SELECT state FROM accounts a WHERE NOT EXISTS (SELECT 1 FROM disabled_accounts d WHERE d.id=a.id)').fetchall()
    watch, holdings = set(), set()
    for row in rows:
        state = json.loads(row['state']) if row['state'] else {}
        watch.update(state.get('watchlist', []))
        holdings.update(item['ticker'] for item in state.get('positions', []) if item.get('ticker'))
    return sorted(watch | holdings), sorted(watch)


def cycle(store, jobs, market_symbols, news_symbols):
    from backend.services.securities import security, SCHEMA_VERSION
    from backend.providers.longbridge_financial import snapshot as financial
    from backend.services.home import index_snapshot, SECTORS
    from backend.services.sectors import snapshot as sector
    from backend.services.macro import snapshot as macro
    from backend.providers.polymarket import snapshot as fed
    from backend.services.whales import FUNDS, snapshot as whales
    from backend.services.news import snapshot as news
    from backend.paths import DASHBOARD_ROOT
    directory = json.loads((DASHBOARD_ROOT/'frontend/assets/symbol-directory.json').read_text())
    etfs = {row[0] for row in directory['securities'] if row[2]}
    for symbol in market_symbols:
        us_equity = symbol not in etfs and not symbol.endswith('-USD') and ('.' not in symbol or symbol.rsplit('.',1)[1] in ('A','B'))
        if us_equity:
            jobs.kick('financial:'+symbol, lambda publish, s=symbol: financial(s, store), 3600,
                      lambda v: bool(v.get('series', {}).get('revenue')) and not v.get('errors'))
        jobs.kick('security:'+symbol, lambda publish, s=symbol: security(
            s, True, store=store, financial_refresh=False, quarterly_cache_only=True), 60,
            lambda v: v.get('schema_version') == SCHEMA_VERSION and v.get('metrics',{}).get('price',{}).get('value') is not None, persist=False)
    for symbol in ('^GSPC','^IXIC','^DJI'):
        jobs.kick('home:'+symbol, lambda publish, s=symbol: index_snapshot(s), 3600,
                  lambda v: v.get('index',{}).get('price') is not None)
    for item in SECTORS:
        jobs.kick('sector:3y:'+item[0], lambda publish, s=item[0]: sector(s,store), 3600,
                  lambda v: v.get('sector',{}).get('price') is not None and not v.get('sector',{}).get('error'))
    for kind in ('jobs','pce','dxy','treasury'):
        jobs.kick('macro:'+kind, lambda publish, k=kind: macro(k,force=True), 3600,
                  lambda v: any(m.get('latest') for m in v.get('metrics',[])))
    jobs.kick('macro:fed',lambda publish: fed(store),3600,lambda v:bool(v.get('series')) and not v.get('stale'))
    for kind in FUNDS:
        jobs.kick('whales:v5:'+kind, lambda publish, k=kind: whales(k),3600,
                  lambda v:v.get('totals_verified') is True and bool(v.get('holdings')) and v.get('previous_status') != 'failed')
    for symbol in news_symbols:
        for kind in ('sec','calls'):
            key=('news:sec-edgar:v1:' if kind=='sec' else 'news:v1:calls:')+symbol
            jobs.kick(key,lambda publish,s=symbol,k=kind:news(s,k),3600,
                      lambda v:isinstance(v.get('items'),list) and not v.get('errors'))


def start(store, jobs, root):
    import fcntl
    runtime = Path(root)/'.runtime'
    runtime.mkdir(parents=True,exist_ok=True)
    lock = (runtime/'market-refresh.lock').open('a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError('Another FinFeed market scheduler owns the lock')
    def run():
        held_lock = lock  # Keep process lock for the full thread lifetime.
        known, news, scanned = [], [], 0
        while True:
            try:
                if time.monotonic()-scanned >= 60:
                    known, news = symbols(store)
                    scanned = time.monotonic()
                cycle(store,jobs,known,news)
                payload={'pid':os.getpid(),'checked_at':time.time(),'symbols':len(known),
                         'news_symbols':len(news),'quote_interval':60,'financial_interval':3600,'other_interval':3600}
                temp=runtime/'market-refresh.tmp'
                temp.write_text(json.dumps(payload));os.replace(temp,runtime/'market-refresh.json')
            except Exception as exc:
                failure('backend','market_scheduler',error=exc)
            time.sleep(5)
    threading.Thread(target=run,daemon=True,name='finfeed-market-refresh').start()
