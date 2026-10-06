"use strict";
window.FinFeedWhales=(()=>{
  const funds=['berkshire','pershing'], good=new Map();
  let started=false, busy=false, checked=0;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=n=>Number(n).toLocaleString('zh-CN');
  const money=n=>Number(n).toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0});
  function target(kind){const card=document.getElementById('whale-'+kind);let body=card.querySelector('.whale-data');
    if(!body){body=document.createElement('div');body.className='whale-data';body.setAttribute('aria-live','polite');card.appendChild(body);}return body;}
  function render(kind,data){
    const body=target(kind), rows=data.holdings||[];
    if(!rows.length){body.innerHTML='<p class="whale-status">'+esc(data.errors?.join('；')||'正在读取 SEC 13F…')+'</p>';return;}
    const time=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(data.retrieved_at));
    body.innerHTML=`<p class="whale-status">报告期末 ${esc(data.report_date)} · 申报日 ${esc(data.filed_at)}<br>${rows.length} 项证券 · 披露市值合计 ${money(data.total_value)}${data.refreshing?'<br>缓存 · 正在检查更新':data.stale?'<br>本次更新失败，保留旧数据':''}</p><div class="whale-table-scroll"><table class="whale-table"><caption>季度末公开持仓，按市值排序</caption><thead><tr><th>证券 / CUSIP</th><th>股数 / 本金数量</th><th>季度末市值（USD）</th><th>披露占比</th></tr></thead><tbody>${rows.map(row=>`<tr><td><strong>${esc(row.name)}</strong><small>${esc(row.class)}${row.put_call?' · '+esc(row.put_call)+' 期权':''}<br>${esc(row.cusip)}</small></td><td>${number(row.shares)}<small>${row.amount_type==='SH'?'股数':esc(row.amount_type)+' 本金数量'}</small></td><td>${money(row.value)}</td><td>${Number(row.weight).toFixed(2)}%</td></tr>`).join('')}</tbody></table></div><div class="macro-sources">${data.sources.map((source,i)=>`<a href="${esc(source.url)}" target="_blank" rel="noreferrer">SEC ${esc(source.form)} 原始文件${data.sources.length>1?' '+(i+1):''} ↗</a>`).join('')}</div><p class="whale-status">检索于 ${esc(time)} 北京 · 每 6 小时检查申报更新</p>`;
  }
  async function refresh(){if(busy)return;busy=true;document.getElementById('whales-refresh').disabled=true;
    await Promise.allSettled(funds.map(async kind=>{try{
      await FinFeedCache.market('/api/whales/'+kind+'?stream=1',data=>{
        if(!data.holdings?.length){if(good.has(kind)){render(kind,{...good.get(kind),stale:true});return;}render(kind,data);return;}
        render(kind,data);if(!data.stale&&!data.refreshing){good.set(kind,data);FinFeedCache.write('whales-'+kind,data);}
      },{ttl:21600000});
    }catch{render(kind,good.has(kind)?{...good.get(kind),stale:true}:{errors:['SEC 请求失败，请稍后检查更新']});}}));
    checked=Date.now();busy=false;document.getElementById('whales-refresh').disabled=false;
  }
  function open(){if(!started){started=true;funds.forEach(kind=>{const saved=FinFeedCache.read('whales-'+kind,90*86400000);if(saved?.data.holdings?.length){good.set(kind,saved.data);render(kind,{...saved.data,refreshing:true});}else render(kind,{});});refresh();}
    else if(Date.now()-checked>=21600000)refresh();}
  document.getElementById('whales-refresh').addEventListener('click',refresh);
  setInterval(()=>{if(started&&!document.hidden&&!document.getElementById('whales-surface').hidden&&Date.now()-checked>=21600000)refresh();},60000);
  return {open};
})();
