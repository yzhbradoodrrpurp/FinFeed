"use strict";
window.FinFeedNews=(()=>{
  const el=id=>document.getElementById(id), escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let busy=false,kind="all",selectedTicker="all",listError='',states=new Map(),symbols=[],done=0,total=0;
  const sourceLink=(ticker,kind)=>kind==='sec'?`https://www.sec.gov/edgar/search/#/q=${encodeURIComponent(ticker)}`:`https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}/earnings-calls/`;
  const kinds=['calls','sec'];
  const refreshInterval=60*60*1000;
  let lastCheck=null,owner=null,pendingRender=false,retryAt=null;
  function scheduleRender(){
    if(pendingRender)return;pendingRender=true;
    const frame=window.requestAnimationFrame|| (callback=>Promise.resolve().then(callback));
    frame(()=>{pendingRender=false;render();});
  }
  const cacheAge=7*86400000;
  const matches=value=>(selectedTicker==='all'||value.ticker===selectedTicker)&&(kind==='all'||value.kind===kind);
  function tickers(){el('news-tickers').innerHTML=['all',...symbols].map(ticker=>`<button class="secondary" data-news-ticker="${escape(ticker)}" aria-pressed="${ticker===selectedTicker}">${ticker==='all'?'全部':escape(ticker)}</button>`).join('');}
  function seed(){for(const ticker of symbols)for(const kind of kinds){const saved=FinFeedCache.read('news:'+ticker+':'+kind,cacheAge);if(saved)accept({ticker,kind},saved.data,false);}}
  function setWatchlist(values){
    if(JSON.stringify(symbols)!==JSON.stringify(values))lastCheck=null;
    symbols=[...new Set(values.filter(value=>typeof value==='string'))];
    if(selectedTicker!=='all'&&!symbols.includes(selectedTicker))selectedTicker='all';
    states=new Map([...states].filter(([,value])=>symbols.includes(value.ticker)&&kinds.includes(value.kind)));
    if(owner)try{sessionStorage.setItem('finfeed-news-list:'+owner,JSON.stringify({symbols,savedAt:Date.now()}));}catch{}
    tickers();seed();render();
  }
  function initialize(user){
    owner=user.id;
    try{const saved=JSON.parse(sessionStorage.getItem('finfeed-news-list:'+owner));if(saved&&Array.isArray(saved.symbols)&&Date.now()-saved.savedAt<=cacheAge)setWatchlist(saved.symbols);}catch{}
    tickers();render();return open();
  }
  function accept(task,value,persist=true){
    if(!symbols.includes(task.ticker)||!kinds.includes(task.kind))return;
    if(task.kind==='sec'&&value.provider!=='sec_edgar'&&!value.errors?.length)return;
    const key=task.ticker+':'+task.kind,previous=states.get(key);
    if(previous&&Date.parse(previous.retrieved_at)>Date.parse(value.retrieved_at))return;
    if((value.errors?.length||value.stale)&&previous?.items?.length&& !value.items?.length)value={...value,items:previous.items,retrieved_at:previous.retrieved_at};
    states.set(key,{...task,...value});
    if(persist&&Array.isArray(value.items)&&!value.errors?.length&&!value.stale&&!value.refreshing&&!value.partial)FinFeedCache.write('news:'+key,value);
  }
  const label=k=>({sec:'SEC 披露',calls:'财报电话会'}[k]||k);
  function date(s){if(!s)return '日期未提供';if(/^\d{4}-\d{2}-\d{2}$/.test(s))return s+' · 申报日';const value=new Date(s);return Number.isNaN(value.getTime())?'日期未提供':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short',hour12:false}).format(value)+' 北京';}
  function recentItems(value){
    const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(Date.now()));
    const part=name=>parts.find(value=>value.type===name).value;
    const today=`${part('year')}-${part('month')}-${part('day')}`;
    const items=(value.items||[]).filter(item=>value.kind==='calls'?Date.parse(item.published_at)<=Date.now():String(item.published_at||'').slice(0,10)<=today);
    const fiscal=item=>{
      if(Number.isInteger(item.fiscal_period))return item.fiscal_period;
      const match=String(item.title||'').match(/\bQ([1-4])\s+(?:FY\s*)?(20\d{2})\b/i);
      return match?Number(match[2])*4+Number(match[1])-1:null;
    };
    if(value.kind==='calls'){
      const periods=items.map(fiscal).filter(period=>period!==null);
      if(periods.length){const latest=Math.max(...periods);return items.filter(item=>[latest,latest-1].includes(fiscal(item)));}
    }
    if(value.kind==='calls')return [];
    const anchors=[...new Set(items.filter(item=>/^(?:10-[QK]|20-F|40-F)(?:\s|$)/.test(item.title||'')).map(item=>String(item.published_at||'').slice(0,10)).filter(date=>/^\d{4}-\d{2}-\d{2}$/.test(date)&&date<=today))].sort().reverse().slice(0,2);
    if(!anchors.length)return [];
    const start=anchors.at(-1);
    return items.filter(item=>{const date=String(item.published_at||'').slice(0,10);return date>=start&&date<=today;});
  }

  function render(){
    el('news-types').hidden=false;
    document.querySelectorAll('[data-news-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.newsKind===kind)));
    el('news-tickers').querySelectorAll('[data-news-ticker]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.newsTicker===selectedTicker)));
    const entries=new Map();
    for(const [key,value] of states){if(!kinds.includes(value.kind)||(selectedTicker!=='all'&&value.ticker!==selectedTicker))continue;for(const item of recentItems(value)){if(kind!=='all'&&item.kind!==kind)continue;const id=item.kind+':'+item.url;const entry=entries.get(id)||{...item,tickers:new Set()};entry.tickers.add(value.ticker);entries.set(id,entry);}}
    const items=[...entries.values()].sort((a,b)=>(Date.parse(b.published_at)||0)-(Date.parse(a.published_at)||0));
    el('news-status').textContent=!symbols.length?(busy?'正在读取自己的观察列表…':listError?'观察列表暂时无法读取，可稍后重试。':'自己的观察列表暂无标的，可先在 Watchlist 添加。'):`${selectedTicker==='all'?'全部 Ticker':selectedTicker} · ${kind==='all'?'全部类型':label(kind)} · ${items.length} 条${busy?` · 正在并发更新 ${done}/${total}`:' · 最近两次财季披露 · 每小时自动检查'}${listError?' · 暂用缓存列表':''}`;
    el('news-feed').innerHTML=items.map(item=>`<article class="news-card"><div class="news-meta"><span class="news-badge">${label(item.kind)}</span><strong>${[...item.tickers].map(escape).join(' · ')}</strong><time>${escape(date(item.published_at))}</time></div><a href="${escape(item.url)}" target="_blank" rel="noopener noreferrer">${escape(item.title)} ↗</a><p>${escape(item.source)}${item.kind==='sec'?' · 最近两次季报／年报申报以来 · SEC 官方 API':''}</p></article>`).join('')||(!busy&&symbols.length?`<p class="news-empty">${[...states.values()].some(v=>matches(v)&&v.errors?.length)?'部分来源获取失败，暂时没有可展示的动态。':'该来源暂无可展示的动态。'}</p>`:'');
    el('news-errors').innerHTML=(listError?`<p class="macro-note">${escape(listError)}</p>`:'')+[...states.values()].filter(value=>matches(value)&&(value.errors?.length||value.stale)).map(value=>`<p class="macro-note">${escape(value.ticker)} · ${label(value.kind)}：${escape(value.errors?.join('；')||'暂显示缓存，等待更新')} · <a href="${escape(sourceLink(value.ticker,value.kind))}" target="_blank" rel="noopener noreferrer">查看来源 ↗</a></p>`).join('');
    el('news-refresh').disabled=busy;
  }
  async function open(force=false,retryOnly=false){
    if(busy||(!force&&lastCheck!==null&&Date.now()-lastCheck<refreshInterval)){render();return;}
    busy=true;done=0;total=symbols.length*kinds.length;seed();render();
    try{
      // Read only the authenticated owner's list, regardless of the viewed account.
      if(!retryOnly||listError)try{
        const data=FinFeedAuth.read?await FinFeedAuth.read('/api/news'):await (await FinFeedAuth.request('/api/news')).json();setWatchlist(data.tickers||[]);listError='';
        for(const value of Object.values(data.snapshots||{}))if(symbols.includes(value.ticker)&&kinds.includes(value.kind))accept(value,value);
        render();
      }catch(error){listError=error.message;render();}
      total=symbols.length*kinds.length;
      const tasks=symbols.flatMap(ticker=>kinds.map(kind=>({ticker,kind}))).filter(task=>!retryOnly||states.get(task.ticker+':'+task.kind)?.errors?.length);total=tasks.length;let next=0;
      async function worker(){while(next<tasks.length){const task=tasks[next++];try{
        await FinFeedCache.market(`/api/news/${encodeURIComponent(task.ticker)}/${task.kind}?stream=1&window=${task.kind==='sec'?'sec-edgar-v1':'reported-v2'}${force?'&refresh=1':''}`,value=>{accept(task,value);scheduleRender();},{ttl:refreshInterval,staleTtl:cacheAge,refresh:force,validate:value=>Array.isArray(value.items)&&!value.errors?.length&&(task.kind!=='sec'||value.provider==='sec_edgar')});
      }catch{const saved=states.get(task.ticker+':'+task.kind)?.items?.length;accept(task,{items:[],errors:[saved?'本次更新失败，暂显示上次成功结果':'暂时无法取得数据，将自动重试'],stale:true});}finally{done++;scheduleRender();}}}
      await Promise.allSettled(Array.from({length:Math.min(4,tasks.length)},worker));
    }finally{busy=false;if(!retryOnly){lastCheck=Date.now();retryAt=listError||[...states.values()].some(value=>value.errors?.length)?lastCheck+60000:null;}else retryAt=listError?Date.now()+60000:null;render();}
  }
  document.querySelectorAll('[data-news-kind]').forEach(button=>button.addEventListener('click',()=>{if(kind===button.dataset.newsKind)return;const order=['all',...kinds],direction=order.indexOf(button.dataset.newsKind)>order.indexOf(kind)?1:-1;kind=button.dataset.newsKind;document.querySelectorAll('[data-news-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));render();window.FinFeedMotion?.enter(el('news-feed'),{kind:'tab',direction});}));
  el('news-tickers').addEventListener('wheel',event=>{
    if(event.ctrlKey||Math.abs(event.deltaX)>=Math.abs(event.deltaY))return;
    const strip=el('news-tickers');
    const scale=event.deltaMode===1?16:event.deltaMode===2?strip.clientWidth:1;
    const next=Math.max(0,Math.min(strip.scrollWidth-strip.clientWidth,strip.scrollLeft+event.deltaY*scale));
    if(next===strip.scrollLeft)return;
    event.preventDefault();strip.scrollLeft=next;
  },{passive:false});
  el('news-tickers').addEventListener('click',event=>{
    const button=event.target.closest('[data-news-ticker]');
    if(!button||button.dataset.newsTicker===selectedTicker)return;
    selectedTicker=button.dataset.newsTicker;render();
    window.FinFeedMotion?.enter(el('news-types'),{kind:'account'});
    window.FinFeedMotion?.enter(el('news-feed'),{kind:'filter'});
  });
  el('news-refresh').addEventListener('click',()=>open(true));
  function checkDue(){
    if(lastCheck!==null&&Date.now()-lastCheck>=refreshInterval)open(true);
    else if(retryAt!==null&&Date.now()>=retryAt)open(true,true);
  }
  setInterval(checkDue,60000);
  document.addEventListener('visibilitychange',checkDue);
  window.addEventListener('focus',checkDue);
  return {open,initialize,setWatchlist};
})();
