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
  let started=false,busy=false,updated=0;
  const lastGood=new Map();
  function notice(card,message){let node=card.querySelector('.cache-state');if(!node){node=document.createElement('p');node.className='macro-note cache-state';card.append(node);}node.textContent=message;}

  const escape=s=>String(s??"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function time(s,zone){return s?new Intl.DateTimeFormat('zh-CN',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(s)):"暂无日程";}
  function times(s){return s?`${time(s,'Asia/Shanghai')} 北京<br>${time(s,'America/New_York')} 美国东部`:"暂无日程";}
  function number(v){return Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});}
  function chartRows(m){return (m.history||[]).filter(r=>Number.isFinite(r.value)&&Number.isFinite(Date.parse(r.date)));}
  function chart(m,threshold=null){
    const rows=chartRows(m);if(rows.length<2)return '';
    let min=Math.min(...rows.map(r=>r.value)),max=Math.max(...rows.map(r=>r.value));
    if(threshold!==null){min=Math.min(min,threshold);max=Math.max(max,threshold);}
    const padding=(max-min||1)*0.12;min-=padding;max+=padding;
    const span=max-min||1;
    const warningY=threshold===null?null:76-(threshold-min)/span*62;
    const warningLine=warningY===null?'':`<line x1="8" x2="392" y1="${warningY}" y2="${warningY}" stroke="#c94a39" stroke-width="1" stroke-dasharray="5 4" vector-effect="non-scaling-stroke"/>`;
    const firstDate=Date.parse(rows[0].date),dateSpan=Date.parse(rows.at(-1).date)-firstDate||1;
    const points=rows.map(r=>`${8+(Date.parse(r.date)-firstDate)/dateSpan*384},${76-(r.value-min)/span*62}`).join(' ');
    return `<figure class="macro-chart"><svg viewBox="0 0 400 90" role="img" tabindex="0" aria-label="${escape(m.label)}历史走势，可用左右方向键查看每日数值"><path d="M8 78H392" stroke="#eee8de"/>${warningLine}<polyline points="${points}" fill="none" stroke="#ee7523" stroke-width="2.5" vector-effect="non-scaling-stroke"/><g class="macro-crosshair" visibility="hidden" pointer-events="none"><line class="chart-vertical" y1="8" y2="78"/><line class="chart-horizontal" x1="8" x2="392"/><circle r="4"/></g></svg><div class="macro-chart-tooltip" hidden></div><figcaption><span>${escape(rows[0].date)}</span><span>${escape(rows.at(-1).date)}</span></figcaption></figure>`;
  }
  function bindChart(card,m){
    const figure=card.querySelector('.macro-chart');
    const svg=figure?.querySelector?.('svg');
    const rows=chartRows(m);if(!svg||rows.length<2)return;
    const points=svg.querySelector('polyline').points;
    const crosshair=svg.querySelector('.macro-crosshair');
    const vertical=crosshair.querySelector('.chart-vertical'),horizontal=crosshair.querySelector('.chart-horizontal'),dot=crosshair.querySelector('circle');
    const tooltip=figure.querySelector('.macro-chart-tooltip');
    const first=Date.parse(rows[0].date),span=Date.parse(rows.at(-1).date)-first||1;
    let selected=rows.length-1;
    function show(index,pointer=null){
      selected=Math.max(0,Math.min(rows.length-1,index));
      const row=rows[selected],point=points.getItem(selected);
      vertical.setAttribute('x1',point.x);vertical.setAttribute('x2',point.x);
      horizontal.setAttribute('y1',point.y);horizontal.setAttribute('y2',point.y);
      dot.setAttribute('cx',point.x);dot.setAttribute('cy',point.y);
      crosshair.setAttribute('visibility','visible');
      tooltip.textContent=`${row.date} · ${number(row.value)}${m.unit||''}`;
      tooltip.hidden=false;
      const bounds=figure.getBoundingClientRect();
      let screen=pointer;
      if(!screen){
        const matrix=svg.getScreenCTM();if(!matrix)return;
        const position=svg.createSVGPoint();position.x=point.x;position.y=point.y;
        screen=position.matrixTransform(matrix);
      }
      const x=(pointer?screen.clientX:screen.x)-bounds.left;
      const y=(pointer?screen.clientY:screen.y)-bounds.top;
      tooltip.style.left=`${Math.max(0,Math.min(bounds.width-tooltip.offsetWidth,x+10))}px`;
      tooltip.style.top=`${Math.max(0,y-tooltip.offsetHeight-10)}px`;
    }
    function hide(){crosshair.setAttribute('visibility','hidden');tooltip.hidden=true;}
    svg.addEventListener('pointermove',event=>{
      const matrix=svg.getScreenCTM();if(!matrix)return;
      const position=svg.createSVGPoint();position.x=event.clientX;position.y=event.clientY;
      const local=position.matrixTransform(matrix.inverse());
      const date=first+Math.max(0,Math.min(1,(local.x-8)/384))*span;
      // Snap to a real observation; weekends and missing dates are never interpolated.
      let low=0,high=rows.length-1;
      while(low<high){const middle=(low+high)>>1;if(Date.parse(rows[middle].date)<date)low=middle+1;else high=middle;}
      if(low>0&&date-Date.parse(rows[low-1].date)<=Date.parse(rows[low].date)-date)low--;
      show(low,event);
    });
    svg.addEventListener('pointerleave',hide);
    svg.addEventListener('pointercancel',hide);
    svg.addEventListener('blur',hide);
    svg.addEventListener('focus',()=>show(selected));
    svg.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key))return;
      event.preventDefault();
      if(event.key==='Escape'){hide();return;}
      show(event.key==='Home'?0:event.key==='End'?rows.length-1:selected+(event.key==='ArrowRight'?1:-1));
    });
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
    if(metrics[0]&&(id==='dxy'||id==='treasury'))bindChart(card,metrics[0]);
  }
  let fedBusy=false,fedUpdated=0,fedData=null;
  const fedColors=['#83baff','#416bff','#ee7523','#e5b500','#9871cc'];
  function fedPoints(series,end){
    const rows=(series.history||[]).filter(r=>Number.isFinite(r.t)&&Number.isFinite(r.p)).map(r=>({t:r.t,p:r.p}));
    if(rows.length&&Number.isFinite(series.price))rows.push({t:end,p:series.price});
    return rows.sort((a,b)=>a.t-b.t);
  }
  function nearestPoint(rows,target){
    let low=0,high=rows.length-1;
    while(low<high){const middle=(low+high)>>1;if(rows[middle].t<target)low=middle+1;else high=middle;}
    if(low>0&&target-rows[low-1].t<=rows[low].t-target)low--;
    return rows[low];
  }
  function bindFedChart(card,series,end,first){
    const figure=card.querySelector('.fed-chart'),svg=figure?.querySelector?.('svg');if(!svg)return;
    const datasets=series.map(s=>fedPoints(s,end));
    const timeline=[...new Set(datasets.flatMap(rows=>rows.map(r=>r.t)))].sort((a,b)=>a-b).map(t=>({t}));
    if(!timeline.length)return;
    const overlay=svg.querySelector('.fed-crosshair'),line=overlay.querySelector('line');
    const dots=overlay.querySelectorAll('circle'),tooltip=figure.querySelector('.fed-chart-tooltip');
    const x=t=>12+(t-first)/(end-first||1)*896,y=p=>242-p*220;
    let selected=timeline.at(-1).t;
    function show(target,pointer=null){
      selected=nearestPoint(timeline,target).t;
      line.setAttribute('x1',x(selected));line.setAttribute('x2',x(selected));
      const content=datasets.map((rows,i)=>{
        if(!rows.length){dots[i].setAttribute('visibility','hidden');return `<div>${escape(series[i].label)}：暂无历史数据</div>`;}
        const row=nearestPoint(rows,selected);
        dots[i].setAttribute('cx',x(row.t));dots[i].setAttribute('cy',y(row.p));dots[i].setAttribute('visibility','visible');
        return `<div><i style="background:${fedColors[i%5]}"></i>${escape(series[i].label)} <strong>${number(row.p*100)}%</strong></div>`;
      }).join('');
      tooltip.innerHTML=`${content}<small class="fed-tooltip-time">${time(new Date(selected*1000).toISOString(),'Asia/Shanghai')} 北京</small>`;
      overlay.setAttribute('visibility','visible');tooltip.hidden=false;
      const bounds=figure.getBoundingClientRect();
      let screen=pointer;
      if(!screen){const matrix=svg.getScreenCTM();if(!matrix)return;const point=svg.createSVGPoint();point.x=x(selected);point.y=22;screen=point.matrixTransform(matrix);}
      const left=(pointer?screen.clientX:screen.x)-bounds.left,top=(pointer?screen.clientY:screen.y)-bounds.top;
      tooltip.style.left=`${Math.max(0,Math.min(bounds.width-tooltip.offsetWidth,left+12))}px`;
      tooltip.style.top=`${Math.max(0,Math.min(bounds.height-tooltip.offsetHeight,top-tooltip.offsetHeight-12))}px`;
    }
    function hide(){overlay.setAttribute('visibility','hidden');dots.forEach(dot=>dot.setAttribute('visibility','hidden'));tooltip.hidden=true;}
    svg.addEventListener('pointermove',event=>{
      const matrix=svg.getScreenCTM();if(!matrix)return;
      const point=svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;
      const local=point.matrixTransform(matrix.inverse());
      show(first+Math.max(0,Math.min(1,(local.x-12)/896))*(end-first),event);
    });
    svg.addEventListener('pointerleave',hide);svg.addEventListener('pointercancel',hide);svg.addEventListener('blur',hide);
    svg.addEventListener('focus',()=>show(selected));
    svg.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key))return;
      event.preventDefault();if(event.key==='Escape'){hide();return;}
      const index=timeline.findIndex(r=>r.t===selected);
      show(timeline[event.key==='Home'?0:event.key==='End'?timeline.length-1:Math.max(0,Math.min(timeline.length-1,index+(event.key==='ArrowRight'?1:-1)))].t);
    });
  }
  function renderFed(data){
    const card=document.getElementById('macro-fed');fedData=data;
    const series=data.series||[];
      const end=Date.parse(data.retrieved_at)/1000,rows=series.flatMap(s=>fedPoints(s,end));
      const first=rows.length?Math.min(...rows.map(r=>r.t)):end;
      const x=t=>12+(t-first)/(end-first||1)*896,y=p=>242-p*220;
      const lines=series.map((s,i)=>fedPoints(s,end).length?`<polyline points="${fedPoints(s,end).map(r=>`${x(r.t)},${y(r.p)}`).join(' ')}" fill="none" stroke="${fedColors[i%5]}" stroke-width="2" vector-effect="non-scaling-stroke"/>`:'').join('');
      const ticks=[0,.25,.5,.75,1].map(p=>`<line x1="12" x2="908" y1="${y(p)}" y2="${y(p)}" stroke="#e8e4df" stroke-dasharray="3 4"/><text x="920" y="${y(p)+4}" fill="#8a8177" font-size="12">${p*100}%</text>`).join('');
      const meeting=data.meeting;
      const title=meeting?`美联储 ${Number(meeting.end.slice(5,7))} 月利率决议`:(data.title||'美联储利率决议');
      const period=meeting?`${meeting.start} 至 ${meeting.end} FOMC 会议`:'会议日期见原始市场';
      card.innerHTML=`<div class="macro-card-heading"><div><span class="eyebrow">POLYMARKET · 市场隐含预期</span><h2>${escape(title)}</h2></div><span class="macro-badge">${data.closed?'已结束':'每小时更新'}</span></div>
        <p class="macro-note">${escape(period)} · 联邦基金利率目标区间上限的变化</p>
        <div class="fed-legend">${series.map((s,i)=>`<span><i style="background:${fedColors[i%5]}"></i>${escape(s.label)} <strong>${number(s.price*100)}%</strong></span>`).join('')}</div>
        ${rows.length?`<figure class="fed-chart"><svg viewBox="0 0 970 270" role="img" tabindex="0" aria-label="${escape(title)}各结果的Polymarket历史市场定价，可用左右方向键查看采样数值">${ticks}${lines}<g class="fed-crosshair" visibility="hidden" pointer-events="none"><line y1="22" y2="242"/>${series.map((s,i)=>`<circle r="4" fill="${fedColors[i%5]}"/>`).join('')}</g></svg><div class="fed-chart-tooltip" hidden></div><figcaption><span>${time(new Date(first*1000).toISOString(),'Asia/Shanghai')}</span><span>${time(data.retrieved_at,'Asia/Shanghai')} 北京</span></figcaption></figure>`:''}
        ${series.filter(s=>s.history_error).map(s=>`<p class="macro-error">${escape(s.label)}：${s.history?.length?'历史更新失败，保留上次曲线':'历史曲线暂不可用'}${s.history_retrieved_at?' · 历史检索于 '+time(s.history_retrieved_at,'Asia/Shanghai')+' 北京':''}</p>`).join('')}
        ${(data.errors||[]).map(e=>`<p class="macro-error">${escape(e)}</p>`).join('')}
        <p class="macro-note">市场价格近似反映隐含概率，受价差、费用和流动性影响；不是美联储承诺。报价每小时检查，历史曲线按约 6 小时采样、每小时补全；最新端点随报价更新。</p>
        <p class="macro-note">累计成交额 $${data.volume==null?'—':number(data.volume)} · 流动性 $${data.liquidity==null?'—':number(data.liquidity)}</p>
        <div class="macro-sources"><a href="${escape(data.source)}" target="_blank" rel="noreferrer">Polymarket 原始市场 ↗</a><a href="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm" target="_blank" rel="noreferrer">FOMC 官方日历 ↗</a></div>
        ${data.rules?`<details class="fed-rules"><summary>结算规则（原文）</summary><p>${escape(data.rules)}</p></details>`:''}
        <p class="macro-retrieved">检索于 ${time(data.retrieved_at,'Asia/Shanghai')} 北京</p>`;
    bindFedChart(card,series,end,first);
  }
  async function refreshFed(force=false){
    if(fedBusy)return;fedBusy=true;
    const card=document.getElementById('macro-fed');
    if(!fedData){const saved=FinFeedCache.read('macro-fed',7*86400000);if(saved)renderFed(saved.data);}
    if(!force&&fedData?.series?.length&&Date.now()-Date.parse(fedData.retrieved_at)<60000){fedUpdated=Date.parse(fedData.retrieved_at);fedBusy=false;return;}
    if(fedData)notice(card,'缓存 · 正在更新，数据时间见下方');
    if(!fedData)card.innerHTML='<span class="eyebrow">POLYMARKET</span><h2>美联储利率决议</h2><p class="macro-note">正在获取市场定价…</p>';
    try{
      await FinFeedCache.market('/api/macro/fed?stream=1'+(force?'&refresh=1':''),data=>{
        if(!data.series?.length)return;
        renderFed(data);FinFeedCache.write('macro-fed',data);
        if(data.refreshing)notice(card,'缓存 · 正在更新，数据时间见下方');
      },{ttl:60000,staleTtl:7*86400000,refresh:force,validate:data=>!!data.series?.length&&!data.stale});
      fedUpdated=Date.now();
    }catch{if(fedData)notice(card,'旧数据 · 本次更新失败，数据时间见下方');else card.innerHTML='<span class="eyebrow">POLYMARKET</span><h2>美联储利率决议</h2><p class="macro-error">数据暂不可用，等待自动重试</p>';}
    finally{fedBusy=false;}
  }
  async function refresh(force=false){
    if(busy)return;busy=true;
    const grid=document.getElementById('macro-grid');
    if(!document.getElementById('macro-jobs'))grid.innerHTML=Object.keys(names).map(id=>`<article id="macro-${id}" class="macro-card" aria-busy="true"><span class="eyebrow">${names[id][0]}</span><h2>${names[id][1]}</h2><div class="macro-skeleton"><span></span><span></span><span></span></div><p class="macro-note">正在获取数据…</p></article>`).join('');
    await Promise.allSettled(Object.keys(names).map(async id=>{
      const card=document.getElementById('macro-'+id);
      if(!lastGood.has(id)){const saved=FinFeedCache.read('macro-'+id);if(saved){lastGood.set(id,saved.data);render(id,saved.data);}}
      if(lastGood.has(id))notice(card,'缓存 · 正在更新，数据时间见下方');
      try{await FinFeedCache.market('/api/macro/'+id+'?stream=1'+(force?'&refresh=1':''),data=>{
        if(!data.metrics?.some(m=>m.latest))throw new Error();
        const previous=lastGood.get(id);
        if(previous&&Date.parse(data.retrieved_at)<Date.parse(previous.retrieved_at))return;
        render(id,data);if(!data.errors?.length&&!data.stale&&!data.partial&&!data.refreshing)lastGood.set(id,data);FinFeedCache.write('macro-'+id,data);
        if(data.refreshing)notice(card,'缓存 · 正在更新，数据时间见下方');
        else if(data.stale)notice(card,'旧数据 · 本次更新失败，数据时间见下方');
        },{ttl:3600000,staleTtl:7*86400000,refresh:force});
      }catch{if(lastGood.has(id))notice(card,'旧数据 · 本次更新失败，数据时间见下方');else render(id,{metrics:[],errors:['数据暂不可用，等待自动重试'],retrieved_at:new Date().toISOString()});}
    }));updated=Date.now();busy=false;
  }
  setInterval(()=>{if(started)refresh(true);},3600000);
  setInterval(()=>{if(started&&!document.hidden)refreshFed(true);},3600000);
  document.addEventListener('visibilitychange',()=>{if(started){if(Date.now()-updated>=3600000)refresh(true);if(Date.now()-fedUpdated>=60000)refreshFed(true);}});
  return {chart,bindChart,open(){if(!started){started=true;refresh();}else if(Date.now()-updated>=3600000)refresh(true);if(Date.now()-fedUpdated>=60000)refreshFed(true);}};
})();
