"use strict";
window.FinFeedMacro=(()=>{
  const names={jobs:["EMPLOYMENT","非农就业"],pce:["INFLATION","PCE 通胀"],dxy:["US DOLLAR","美元指数"],treasury:["TREASURY","十年期美债"]};
  const calendarLinks={
    jobs:[['非农就业 · Trading Economics','https://tradingeconomics.com/united-states/non-farm-payrolls']],
    pce:[
      ['总体 PCE 同比 · Trading Economics','https://tradingeconomics.com/united-states/pce-price-index-annual-change'],
      ['总体 PCE 环比 · Trading Economics','https://tradingeconomics.com/united-states/pce-price-index-monthly-change']
    ]
  };
  let started=false,busy=false;
  const escape=s=>String(s??"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function time(s,zone){return s?new Intl.DateTimeFormat('zh-CN',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(s)):"暂无日程";}
  function times(s){return s?`${time(s,'Asia/Shanghai')} 北京<br>${time(s,'America/New_York')} 美国东部`:"暂无日程";}
  function number(v){return Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});}
  function chart(m,threshold=null){
    const rows=m.history||[];if(rows.length<2)return '';
    let min=Math.min(...rows.map(r=>r.value)),max=Math.max(...rows.map(r=>r.value));
    if(threshold!==null){min=Math.min(min,threshold);max=Math.max(max,threshold);}
    const padding=(max-min||1)*0.12;min-=padding;max+=padding;
    const span=max-min||1;
    const warningY=threshold===null?null:76-(threshold-min)/span*62;
    const warningLine=warningY===null?'':`<line x1="8" x2="392" y1="${warningY}" y2="${warningY}" stroke="#c94a39" stroke-width="1" stroke-dasharray="5 4" vector-effect="non-scaling-stroke"/>`;
    const points=rows.map((r,i)=>`${8+i/(rows.length-1)*384},${76-(r.value-min)/span*62}`).join(' ');
    return `<figure class="macro-chart"><svg viewBox="0 0 400 90" role="img" aria-label="${escape(m.label)}历史走势"><path d="M8 78H392" stroke="#eee8de"/>${warningLine}<polyline points="${points}" fill="none" stroke="#ee7523" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg><figcaption><span>${escape(rows[0].date)}</span><span>${escape(rows.at(-1).date)}</span></figcaption></figure>`;
  }
  function render(id,data){
    const card=document.getElementById(`macro-${id}`);card.setAttribute('aria-busy','false');
    const metrics=data.metrics||[];
    card.innerHTML=`<div class="macro-card-heading"><div><span class="eyebrow">${names[id][0]}</span><h2>${names[id][1]}</h2></div><span class="macro-badge">${id==='jobs'||id==='pce'?'月度发布':'日度数据'}</span></div>
      <div class="macro-metrics">${metrics.map(m=>`<div><span>${escape(m.label)}</span><strong>${m.latest?number(m.latest.value):'—'}<small>${escape(m.unit)}</small></strong>${id==='treasury'?`<span class="macro-warning ${m.latest&&m.latest.value>=5.1?'is-triggered':''}">${m.latest&&m.latest.value>=5.1?'已达到 5.1% 预警线':'预警线 5.1%'}</span>`:''}<p>前值 ${m.previous?number(m.previous.value):'—'}${escape(m.unit)} · ${escape(m.latest?.date||'暂无数据')}</p></div>`).join('')||'<p class="macro-empty">— 暂无数据</p>'}</div>
      ${metrics[0]&&(id==='dxy'||id==='treasury')?chart(metrics[0],id==='treasury'?5.1:null):''}
      ${id==='jobs'||id==='pce'?`<div class="macro-release"><div><span>本次发布时间</span><p>${times(data.last_release)}</p></div><div><span>下次发布时间</span><p>${times(data.next_release)}</p></div></div>`:''}
      <p class="macro-note">${escape((data.note||'').replace('5.05%','5.1%'))}</p>
      ${(data.errors||[]).map(e=>`<p class="macro-error">${escape(e)}</p>`).join('')}
      <div class="macro-sources">${metrics.map(m=>`<a href="${escape(m.source)}" target="_blank" rel="noreferrer">${escape(m.label)}来源 ↗</a>`).join('')}${data.calendar_source?`<a href="${escape(data.calendar_source)}" target="_blank" rel="noreferrer">官方日历 ↗</a>`:''}${id==='jobs'?'<a href="https://www.bls.gov/news.release/empsit.htm" target="_blank" rel="noreferrer">本次就业报告 ↗</a>':''}${id==='pce'?'<a href="https://www.bea.gov/data/income-saving/personal-income" target="_blank" rel="noreferrer">BEA 发布内容 ↗</a>':''}${(calendarLinks[id]||[]).map(([label,url])=>`<a href="${escape(url)}" target="_blank" rel="noreferrer">${escape(label)} ↗</a>`).join('')}</div><p class="macro-retrieved">检索于 ${time(data.retrieved_at,'Asia/Shanghai')} 北京</p>`;
  }
  async function refresh(){
    if(busy)return;busy=true;document.getElementById('macro-refresh').disabled=true;
    const grid=document.getElementById('macro-grid');
    grid.innerHTML=Object.keys(names).map(id=>`<article id="macro-${id}" class="macro-card" aria-busy="true"><span class="eyebrow">${names[id][0]}</span><h2>${names[id][1]}</h2><div class="macro-skeleton"><span></span><span></span><span></span></div><p class="macro-note">正在获取数据…</p></article>`).join('');
    await Promise.all(Object.keys(names).map(async id=>{
      try{const r=await FinFeedAuth.request('/api/macro/'+id);if(!r.ok)throw new Error();render(id,await r.json());}
      catch{render(id,{metrics:[],errors:['数据暂不可用，请稍后刷新'],retrieved_at:new Date().toISOString()});}
    }));busy=false;document.getElementById('macro-refresh').disabled=false;
  }
  document.getElementById('macro-refresh').addEventListener('click',refresh);
  setInterval(()=>{if(started&&!document.hidden&&!document.getElementById('macro-surface').hidden)refresh();},3600000);
  return {open(){if(!started){started=true;refresh();}}};
})();
