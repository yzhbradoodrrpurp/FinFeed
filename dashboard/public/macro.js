"use strict";
window.FinFeedMacro=(()=>{
  const names={jobs:["EMPLOYMENT","非农就业"],pce:["INFLATION","PCE 通胀"],dxy:["US DOLLAR","美元指数"],treasury:["TREASURY","十年期美债"]};
  const metricLinks={
    jobs:[
      ['非农新增就业','https://tradingeconomics.com/united-states/non-farm-payrolls'],
      ['失业率','https://tradingeconomics.com/united-states/unemployment-rate'],
      ['平均时薪同比','https://tradingeconomics.com/united-states/average-hourly-earnings-yoy']
    ],
    pce:[
      ['总体PCE同比','https://tradingeconomics.com/united-states/pce-price-index-annual-change'],
      ['总体PCE环比','https://tradingeconomics.com/united-states/pce-price-index-monthly-change'],
      ['核心PCE同比','https://tradingeconomics.com/united-states/core-pce-price-index-annual-change'],
      ['核心PCE环比','https://tradingeconomics.com/united-states/core-pce-price-index-mom']
    ]
  };
  let started=false,busy=false;
  const lastGood=new Map();
  function notice(card,message){let node=card.querySelector('.cache-state');if(!node){node=document.createElement('p');node.className='macro-note cache-state';card.append(node);}node.textContent=message;}

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
    const firstDate=Date.parse(rows[0].date),dateSpan=Date.parse(rows.at(-1).date)-firstDate||1;
    const points=rows.map(r=>`${8+(Date.parse(r.date)-firstDate)/dateSpan*384},${76-(r.value-min)/span*62}`).join(' ');
    return `<figure class="macro-chart"><svg viewBox="0 0 400 90" role="img" aria-label="${escape(m.label)}历史走势"><path d="M8 78H392" stroke="#eee8de"/>${warningLine}<polyline points="${points}" fill="none" stroke="#ee7523" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg><figcaption><span>${escape(rows[0].date)}</span><span>${escape(rows.at(-1).date)}</span></figcaption></figure>`;
  }
  function metricValue(id,m){
    const value=`<strong>${m.latest?number(m.latest.value):'—'}<small>${escape(m.unit)}</small></strong>`;
    const link=(metricLinks[id]||[]).find(([label])=>label.replace(/\s/g,'')===m.label.replace(/\s/g,''));
    return link?`<a class="macro-value-link" href="${escape(link[1])}" target="_blank" rel="noreferrer" aria-label="${escape(m.label)}：在 Trading Economics 查看" title="在 Trading Economics 查看">${value}</a>`:value;
  }
  function render(id,data){
    const card=document.getElementById(`macro-${id}`);card.setAttribute('aria-busy','false');
    const metrics=data.metrics||[];
    card.innerHTML=`<div class="macro-card-heading"><div><span class="eyebrow">${names[id][0]}</span><h2>${names[id][1]}</h2></div><span class="macro-badge">${id==='jobs'||id==='pce'?'月度发布':'日度数据'}</span></div>
      <div class="macro-metrics">${metrics.map(m=>`<div><span>${escape(m.label)}</span>${metricValue(id,m)}${id==='treasury'?`<span class="macro-warning ${m.latest&&m.latest.value>=5.1?'is-triggered':''}">${m.latest&&m.latest.value>=5.1?'已达到 5.1% 预警线':'预警线 5.1%'}</span>`:''}<p>前值 ${m.previous?number(m.previous.value):'—'}${escape(m.unit)} · ${escape(m.latest?.date||'暂无数据')}</p></div>`).join('')||'<p class="macro-empty">— 暂无数据</p>'}</div>
      ${metrics[0]&&(id==='dxy'||id==='treasury')?chart(metrics[0],id==='treasury'?5.1:null):''}
      ${id==='jobs'||id==='pce'?`<div class="macro-release"><div><span>本次发布时间</span><p>${times(data.last_release)}</p></div><div><span>下次发布时间</span><p>${times(data.next_release)}</p></div></div>`:''}
      <p class="macro-note">${escape((data.note||'').replace('5.05%','5.1%'))}</p>
      ${(data.errors||[]).map(e=>`<p class="macro-error">${escape(e)}</p>`).join('')}
      <div class="macro-sources">${metrics.map(m=>`<a href="${escape(m.source)}" target="_blank" rel="noreferrer">${escape(m.label)}来源 ↗</a>`).join('')}${data.calendar_source?`<a href="${escape(data.calendar_source)}" target="_blank" rel="noreferrer">官方日历 ↗</a>`:''}${id==='jobs'?'<a href="https://www.bls.gov/news.release/empsit.htm" target="_blank" rel="noreferrer">本次就业报告 ↗</a>':''}${id==='pce'?'<a href="https://www.bea.gov/data/income-saving/personal-income" target="_blank" rel="noreferrer">BEA 发布内容 ↗</a>':''}</div><p class="macro-retrieved">检索于 ${time(data.retrieved_at,'Asia/Shanghai')} 北京</p>`;
  }
  let fedBusy=false,fedUpdated=0,fedData=null;
  const fedColors=['#83baff','#416bff','#ee7523','#e5b500','#9871cc'];
  function renderFed(data){
    const card=document.getElementById('macro-fed');fedData=data;
    const series=data.series||[];
      const rows=series.flatMap(s=>s.history),end=Date.parse(data.retrieved_at)/1000;
      const first=rows.length?Math.min(...rows.map(r=>r.t)):end;
      const x=t=>12+(t-first)/(end-first||1)*896,y=p=>242-p*220;
      const lines=series.map((s,i)=>s.history.length?`<polyline points="${[...s.history,{t:end,p:s.price}].map(r=>`${x(r.t)},${y(r.p)}`).join(' ')}" fill="none" stroke="${fedColors[i%5]}" stroke-width="2" vector-effect="non-scaling-stroke"/>`:'').join('');
      const ticks=[0,.25,.5,.75,1].map(p=>`<line x1="12" x2="908" y1="${y(p)}" y2="${y(p)}" stroke="#e8e4df" stroke-dasharray="3 4"/><text x="920" y="${y(p)+4}" fill="#8a8177" font-size="12">${p*100}%</text>`).join('');
      card.innerHTML=`<div class="macro-card-heading"><div><span class="eyebrow">POLYMARKET · 市场隐含预期</span><h2>美联储 10 月利率决议</h2></div><span class="macro-badge">${data.closed?'已结束':'每分钟更新'}</span></div>
        <p class="macro-note">2026 年 10 月 27–28 日 FOMC 会议 · 联邦基金利率目标区间上限的变化</p>
        <div class="fed-legend">${series.map((s,i)=>`<span><i style="background:${fedColors[i%5]}"></i>${escape(s.label)} <strong>${number(s.price*100)}%</strong></span>`).join('')}</div>
        ${rows.length?`<figure class="fed-chart"><svg viewBox="0 0 970 270" role="img" aria-label="美联储10月利率决议各结果的Polymarket历史市场定价">${ticks}${lines}</svg><figcaption><span>${time(new Date(first*1000).toISOString(),'Asia/Shanghai')}</span><span>${time(data.retrieved_at,'Asia/Shanghai')} 北京</span></figcaption></figure>`:''}
        ${series.some(s=>s.history_error)?'<p class="macro-error">部分历史曲线暂不可用</p>':''}
        ${(data.errors||[]).map(e=>`<p class="macro-error">${escape(e)}</p>`).join('')}
        <p class="macro-note">市场价格近似反映隐含概率，受价差、费用和流动性影响；不是美联储承诺。报价每分钟检查，历史曲线按约 6 小时采样、每小时补全；最新端点随报价更新。</p>
        <p class="macro-note">累计成交额 $${data.volume==null?'—':number(data.volume)} · 流动性 $${data.liquidity==null?'—':number(data.liquidity)}</p>
        <div class="macro-sources"><a href="${escape(data.source)}" target="_blank" rel="noreferrer">Polymarket 原始市场 ↗</a><a href="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm" target="_blank" rel="noreferrer">FOMC 官方日历 ↗</a></div>
        ${data.rules?`<details class="fed-rules"><summary>结算规则（原文）</summary><p>${escape(data.rules)}</p></details>`:''}
        <p class="macro-retrieved">检索于 ${time(data.retrieved_at,'Asia/Shanghai')} 北京</p>`;
  }
  async function refreshFed(){
    if(fedBusy)return;fedBusy=true;
    const card=document.getElementById('macro-fed');
    if(!fedData){const saved=FinFeedCache.read('macro-fed',86400000);if(saved)renderFed(saved.data);}
    if(fedData)notice(card,'缓存 · 正在更新，数据时间见下方');
    if(!fedData)card.innerHTML='<span class="eyebrow">POLYMARKET</span><h2>美联储 10 月利率决议</h2><p class="macro-note">正在获取市场定价…</p>';
    try{
      const response=await FinFeedAuth.request('/api/macro/fed');if(!response.ok)throw new Error();
      const data=await response.json();
      if(!data.series?.length)throw new Error();
      renderFed(data);FinFeedCache.write('macro-fed',data);
      fedUpdated=Date.now();
    }catch{if(fedData)notice(card,'旧数据 · 本次更新失败，数据时间见下方');else card.innerHTML='<span class="eyebrow">POLYMARKET</span><h2>美联储 10 月利率决议</h2><p class="macro-error">数据暂不可用，请稍后刷新</p>';}
    finally{fedBusy=false;}
  }
  async function refresh(){
    if(busy)return;busy=true;document.getElementById('macro-refresh').disabled=true;
    const grid=document.getElementById('macro-grid');
    if(!document.getElementById('macro-jobs'))grid.innerHTML=Object.keys(names).map(id=>`<article id="macro-${id}" class="macro-card" aria-busy="true"><span class="eyebrow">${names[id][0]}</span><h2>${names[id][1]}</h2><div class="macro-skeleton"><span></span><span></span><span></span></div><p class="macro-note">正在获取数据…</p></article>`).join('');
    await Promise.allSettled(Object.keys(names).map(async id=>{
      const card=document.getElementById('macro-'+id);
      if(!lastGood.has(id)){const saved=FinFeedCache.read('macro-'+id);if(saved){lastGood.set(id,saved.data);render(id,saved.data);}}
      if(lastGood.has(id))notice(card,'缓存 · 正在更新，数据时间见下方');
      try{const r=await FinFeedAuth.request('/api/macro/'+id);if(!r.ok)throw new Error();const data=await r.json();
        if(!data.metrics?.some(m=>m.latest))throw new Error();
        render(id,data);lastGood.set(id,data);FinFeedCache.write('macro-'+id,data);
      }catch{if(lastGood.has(id))notice(card,'旧数据 · 本次更新失败，数据时间见下方');else render(id,{metrics:[],errors:['数据暂不可用，请稍后刷新'],retrieved_at:new Date().toISOString()});}
    }));busy=false;document.getElementById('macro-refresh').disabled=false;
  }
  document.getElementById('macro-refresh').addEventListener('click',()=>{refresh();refreshFed();});
  setInterval(()=>{if(started&&!document.hidden&&!document.getElementById('macro-surface').hidden)refresh();},3600000);
  setInterval(()=>{if(started&&!document.hidden&&!document.getElementById('macro-surface').hidden)refreshFed();},60000);
  document.addEventListener('visibilitychange',()=>{if(started&&!document.hidden&&!document.getElementById('macro-surface').hidden&&Date.now()-fedUpdated>=60000)refreshFed();});
  return {open(){if(!started){started=true;refresh();}if(Date.now()-fedUpdated>=60000)refreshFed();}};
})();
