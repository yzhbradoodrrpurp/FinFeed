"use strict";
window.FinFeedNews=(()=>{
  const el=id=>document.getElementById(id), escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let busy=false,kind='all',listError='',states=new Map(),symbols=[],done=0,total=0;
  const sourceLink=(ticker,kind)=>`https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}/${{press:'press-releases',sec:'sec-filings',calls:'earnings-calls'}[kind]}/`;
  const kinds=['press','sec','calls'];
  const label=k=>({press:'新闻稿',sec:'SEC 披露',calls:'财报电话会'}[k]||k);
  function date(s){if(!s)return '日期未提供';if(/^\d{4}-\d{2}-\d{2}$/.test(s))return s+' · 申报日';const value=new Date(s);return Number.isNaN(value.getTime())?'日期未提供':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short',hour12:false}).format(value)+' 北京';}
  function render(){
    const entries=new Map();
    for(const [key,value] of states){for(const item of value.items||[]){if(kind!=='all'&&item.kind!==kind)continue;const id=item.kind+':'+item.url;const entry=entries.get(id)||{...item,tickers:new Set()};entry.tickers.add(value.ticker);entries.set(id,entry);}}
    const items=[...entries.values()].sort((a,b)=>(Date.parse(b.published_at)||0)-(Date.parse(a.published_at)||0));
    el('news-status').textContent=listError?'观察列表读取失败，请重试':busy?`${symbols.length} 个标的 · 正在并发获取 ${done}/${total}`:symbols.length?`${symbols.length} 个标的 · ${items.length} 条${kind==='all'?'公司动态':label(kind)} · 来源缓存 30 分钟`:'自己的观察列表暂无标的，可先在 Watchlist 添加。';
    el('news-feed').innerHTML=items.map(item=>`<article class="news-card"><div class="news-meta"><span class="news-badge">${label(item.kind)}</span><strong>${[...item.tickers].map(escape).join(' · ')}</strong><time>${escape(date(item.published_at))}</time></div><a href="${escape(item.url)}" target="_blank" rel="noopener noreferrer">${escape(item.title)} ↗</a><p>${escape(item.source)}${item.kind==='sec'?' · 索引经 Yahoo 获取':''}</p></article>`).join('')||(!busy&&symbols.length?`<p class="news-empty">${[...states.values()].some(v=>(kind==='all'||kind===v.kind)&&v.errors?.length)?'部分来源获取失败，暂时没有可展示的动态。':'该来源暂无可展示的动态。'}</p>`:'');
    el('news-errors').innerHTML=(listError?`<p class="macro-note">${escape(listError)}</p>`:'')+[...states.values()].filter(value=>value.errors?.length||value.stale).map(value=>`<p class="macro-note">${escape(value.ticker)} · ${label(value.kind)}：${escape(value.errors?.join('；')||'暂显示缓存，等待更新')} · <a href="${escape(sourceLink(value.ticker,value.kind))}" target="_blank" rel="noopener noreferrer">查看来源 ↗</a></p>`).join('');
    el('news-refresh').disabled=busy;
  }
  async function open(force=false){
    if(busy)return;
    busy=true;done=0;listError='';render();
    try{
      // Never use the currently viewed account or the URL's user parameter.
      const response=await FinFeedAuth.request('/api/news');if(!response.ok)throw new Error('自己的观察列表读取失败');
      const data=await response.json();symbols=data.tickers||[];states=new Map();total=symbols.length*kinds.length;render();
      const tasks=symbols.flatMap(ticker=>kinds.map(kind=>({ticker,kind})));let next=0;
      async function worker(){while(next<tasks.length){const task=tasks[next++],key=task.ticker+':'+task.kind;try{
        const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),35000);
        try{const response=await FinFeedAuth.request(`/api/news/${encodeURIComponent(task.ticker)}/${task.kind}?stream=1`,{signal:controller.signal});if(!response.ok)throw new Error('请求失败');
          if(response.headers.get('content-type')?.includes('ndjson')){const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';try{while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});const lines=buffer.split('\n');buffer=lines.pop();for(const line of lines)if(line.trim()){states.set(key,{...task,...JSON.parse(line)});render();}if(done){if(buffer.trim())states.set(key,{...task,...JSON.parse(buffer)});break;}}}finally{reader.releaseLock();}}
          else states.set(key,{...task,...await response.json()});
        }finally{clearTimeout(timeout);}
      }catch{states.set(key,{...task,items:[],errors:['获取失败，可稍后刷新重试']});}finally{done++;render();}}}
      await Promise.allSettled(Array.from({length:Math.min(8,tasks.length)},worker));
    }catch(error){listError=error.message;}
    finally{busy=false;render();}
  }
  document.querySelectorAll('[data-news-kind]').forEach(button=>button.addEventListener('click',()=>{if(kind===button.dataset.newsKind)return;const order=['all',...kinds],direction=order.indexOf(button.dataset.newsKind)>order.indexOf(kind)?1:-1;kind=button.dataset.newsKind;document.querySelectorAll('[data-news-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));render();window.FinFeedMotion?.enter(el('news-feed'),{kind:'tab',direction});}));
  el('news-refresh').addEventListener('click',()=>open(true));
  return {open};
})();
