"use strict";
window.FinFeedHome=(()=>{
  let started=false,busy=false,updated=0,market=null,syncedAt=0,serverNow=0;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const format=n=>n==null?'—':Number(n).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  const date=(s,zone)=>new Intl.DateTimeFormat('zh-CN',{timeZone:zone,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(s));
  function clock(){
    if(!market)return;
    const now=serverNow+(performance.now()-syncedAt),sessions=market.sessions||[];
    const current=sessions.find(s=>Date.parse(s.open)<=now&&now<Date.parse(s.close));
    const next=sessions.find(s=>Date.parse(s.open)>now);
    const status=document.getElementById('home-market-status');
    status.textContent=market.calendar_error?'状态暂不可用':current?'美股已开盘':'美股休市';
    status.classList.toggle('is-open',!!current);
    const target=current?.close||next?.open;
    const seconds=target?Math.max(0,Math.ceil((Date.parse(target)-now)/1000)):null;
    const countdown=document.getElementById('home-countdown');
    if(seconds===null){countdown.textContent='—';document.getElementById('home-countdown-label').textContent='暂无交易日历';return;}
    const days=Math.floor(seconds/86400),hours=Math.floor(seconds%86400/3600),minutes=Math.floor(seconds%3600/60),sec=seconds%60;
    countdown.textContent=(days?days+' 天 ':'')+[hours,minutes,sec].map(n=>String(n).padStart(2,'0')).join(':');
    document.getElementById('home-countdown-label').textContent=current?'距离收盘':'距离下次开盘';
    document.getElementById('home-session-time').textContent=`${current?'本次收盘':'下次开盘'}：${date(target,'Asia/Shanghai')} 北京 / ${date(target,'America/New_York')} 美国东部`;
  }
  const indices=[['^GSPC','S&P 500','标普 500'],['^IXIC','Nasdaq Composite','纳斯达克综合指数'],['^DJI','Dow Jones Industrial Average','道琼斯工业指数']];
  const lastGood=new Map();
  function renderIndex(index,slot,state=""){
    document.getElementById('home-index-'+slot).innerHTML=`<span class="eyebrow">${esc(index.name)}</span><h2>${esc(index.label)}</h2><strong class="home-index-price">${format(index.price)}</strong><p class="${index.change>0?'positive':index.change<0?'negative':''}">${index.change>0?'+':''}${format(index.change)} / ${index.change_percent>0?'+':''}${format(index.change_percent)}%</p><p class="home-quote-time">${state?esc(state)+' · ':''}${index.quoted_at?'报价于 '+date(index.quoted_at,'America/New_York')+' 美国东部':esc(index.error||'暂无报价')}</p><a class="home-source" href="${esc(index.source)}" target="_blank" rel="noreferrer">Yahoo Finance ↗</a>`;
  }
  const sectors=[['XLC','通信服务'],['XLY','可选消费'],['XLP','必需消费'],['XLE','能源'],['XLF','金融'],['XLV','医疗保健'],['XLI','工业'],['XLB','原材料'],['XLRE','房地产'],['XLK','信息技术'],['XLU','公用事业']];
  const sectorGood=new Map(),sectorBusy=new Set();
  let sectorDragging=null,sectorScroll=null;
  const sectorOrderKey='finfeed-home-sector-order:v1';
  function saveSectorOrder(){try{localStorage.setItem(sectorOrderKey,JSON.stringify([...document.getElementById('home-sectors').children].map(card=>card.id.replace('home-sector-',''))));}catch{}}
  function moveSector(symbol,target){
    const grid=document.getElementById('home-sectors'),cards=[...grid.children],card=document.getElementById('home-sector-'+symbol);
    const from=cards.indexOf(card);if(from<0||target<0||target>=cards.length||target===from)return;
    const before=window.FinFeedMotion.capture(cards);
    grid.insertBefore(card,target>from?cards[target].nextSibling:cards[target]);
    window.FinFeedMotion.settle(before,grid.children);saveSectorOrder();
  }
  function finishSectorDrag(){sectorDragging=null;sectorScroll?.stop();document.querySelectorAll('.sector-dragging,.sector-drop').forEach(card=>card.classList.remove('sector-dragging','sector-drop'));}
  function bindSectorOrder(){
    const grid=document.getElementById('home-sectors');
    grid.addEventListener('dragstart',event=>{
      const handle=event.target.closest('.sector-handle');if(!handle)return;
      const card=handle.closest('.home-sector');sectorDragging=card.id.replace('home-sector-','');
      event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',sectorDragging);
      const bounds=card.getBoundingClientRect();
      // Anchor the preview to the point grabbed, including its position after scrolling.
      event.dataTransfer.setDragImage(card,event.clientX-bounds.left,event.clientY-bounds.top);
      card.classList.add('sector-dragging');
    });
    grid.addEventListener('dragover',event=>{
      if(!sectorDragging)return;event.preventDefault();event.dataTransfer.dropEffect='move';
      sectorScroll ||= window.FinFeedMotion.edgeScroll(document.scrollingElement);sectorScroll.move(event.clientY);
      grid.querySelectorAll('.sector-drop').forEach(card=>card.classList.remove('sector-drop'));
      const card=event.target.closest('.home-sector');if(card&&card.id!=='home-sector-'+sectorDragging)card.classList.add('sector-drop');
    });
    grid.addEventListener('drop',event=>{
      if(!sectorDragging)return;event.preventDefault();const card=event.target.closest('.home-sector');
      if(card)moveSector(sectorDragging,[...grid.children].indexOf(card));finishSectorDrag();
    });
    grid.addEventListener('dragleave',event=>{if(!grid.contains(event.relatedTarget))sectorScroll?.stop();});
    grid.addEventListener('dragend',finishSectorDrag);window.addEventListener('blur',finishSectorDrag);
    grid.addEventListener('keydown',event=>{
      const handle=event.target.closest('.sector-handle');if(!handle||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
      event.preventDefault();const card=handle.closest('.home-sector'),index=[...grid.children].indexOf(card);
      moveSector(card.id.replace('home-sector-',''),index+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1));handle.focus({preventScroll:true});
    });
  }
  function renderSector(data,state=''){
    const card=document.getElementById('home-sector-'+data.symbol);if(!card)return;
    const chart=window.FinFeedMacro.chart(data);
    if(sectorDragging===data.symbol)return; // Keep the native drag source attached during refresh.
    card.innerHTML=`<button class="sector-handle" draggable="true" type="button" aria-label="拖动排序 ${esc(data.symbol)}，也可用方向键移动" title="按住拖动排序">⠿</button><span class="eyebrow">${esc(data.symbol)}</span><h3>${esc(data.label)}</h3><strong class="home-index-price">${format(data.price)}<small>USD</small></strong><p class="${data.change>0?'positive':data.change<0?'negative':''}">${data.change>0?'+':''}${format(data.change)} / ${data.change_percent>0?'+':''}${format(data.change_percent)}%</p>${chart||'<div class="home-sector-chart-empty">日线数据暂不可用</div>'}<p class="home-quote-time">${esc(state)}${state?'<br>':''}${data.quoted_at?'报价于 '+date(data.quoted_at,'America/New_York')+' 美国东部':'等待报价'}</p><a class="home-source" href="https://finance.yahoo.com/quote/${esc(data.symbol)}/" target="_blank" rel="noreferrer">Yahoo Finance ↗</a>`;
    window.FinFeedMacro.bindChart(card,data);
  }
  async function refreshSector([symbol,label]){
    if(sectorBusy.has(symbol))return;sectorBusy.add(symbol);
    try{
      await FinFeedCache.market('/api/home/sectors/'+symbol+'?stream=1&refresh=1&range=3y',data=>{
        const old=sectorGood.get(symbol),item=data.sector;
        if(!item||item.price==null||item.error||!item.history?.length){
          if(data.pending)return;
          throw new Error('Sector unavailable');
        }
        // A delayed response must never replace a newer quote already displayed.
        if(old&&Date.parse(item.quoted_at)<Date.parse(old.sector.quoted_at))return;
        if(old&&Date.parse(data.retrieved_at)<Date.parse(old.retrieved_at))return;
        sectorGood.set(symbol,data);
        renderSector(item,data.refreshing?'缓存 · 正在更新':data.stale?'旧数据 · 更新失败':'每分钟检查更新');
        FinFeedCache.write('sector-3y-v2-'+symbol,data);
      },{refresh:true,staleTtl:7*86400000,validate:data=>!!data.sector?.history?.length&&data.sector.price!=null&&!data.sector.error});
    }catch{
      renderSector(sectorGood.get(symbol)?.sector||{symbol,label},'更新失败，稍后自动重试');
    }finally{sectorBusy.delete(symbol);}
  }
  function refreshSectors(){sectors.forEach(item=>refreshSector(item));}
  function startSectors(){
    document.getElementById('home-sectors').innerHTML=sectors.map(([symbol])=>`<article class="home-sector" id="home-sector-${symbol}"></article>`).join('');
    try{
      const order=JSON.parse(localStorage.getItem(sectorOrderKey)||'[]');
      if(Array.isArray(order))for(const symbol of [...new Set([...order,...sectors.map(item=>item[0])])]){
        if(!sectors.some(item=>item[0]===symbol))continue;
        document.getElementById('home-sectors').append(document.getElementById('home-sector-'+symbol));
      }
    }catch{}
    bindSectorOrder();
    sectors.forEach(([symbol,label])=>{
      const saved=FinFeedCache.read('sector-3y-v2-'+symbol,7*86400000);
      if(saved?.data?.sector?.price!=null){sectorGood.set(symbol,saved.data);renderSector(saved.data.sector,'缓存 · 正在更新');}
      else renderSector({symbol,label},'正在加载…');
    });
    refreshSectors();
  }
  async function fetchData(url){
    const response=await FinFeedAuth.request(url);if(!response.ok)throw new Error();return response.json();
  }
  async function refresh(){
    if(busy)return;busy=true;document.getElementById('home-refresh').disabled=true;
    if(!document.getElementById('home-index-0'))document.getElementById('home-indices').innerHTML=indices.map((index,slot)=>`<article class="home-index" id="home-index-${slot}"><span class="eyebrow">${esc(index[1])}</span><h2>${esc(index[2])}</h2><strong class="home-index-price">—</strong><p class="home-quote-time">正在加载…</p></article>`).join('');
    const calendar=fetchData('/api/home').then(data=>{market=data;serverNow=Date.parse(data.server_time);syncedAt=performance.now();clock();FinFeedCache.write('home-calendar',data);}).catch(()=>{
      if(market)return;document.getElementById('home-market-status').textContent='状态暂不可用';document.getElementById('home-countdown').textContent='—';document.getElementById('home-session-time').textContent='';
    });
    const quotes=indices.map(async(index,slot)=>{
      try{
        await FinFeedCache.market('/api/home?symbol='+encodeURIComponent(index[0])+'&stream=1',data=>{
        if(data.index.price==null&&lastGood.has(slot))throw new Error();
        renderIndex(data.index,slot,data.refreshing?'缓存 · 正在更新':data.stale?'旧数据 · 更新失败':'');
        if(data.index.price!=null){lastGood.set(slot,data.index);FinFeedCache.write('home-'+index[0],data);}
        document.getElementById('home-update-status').textContent=`检索于 ${date(data.retrieved_at,'Asia/Shanghai')} 北京 · 每分钟检查更新，行情可能延迟；涨跌相对前收盘价。`;
        });
      }catch{
        if(lastGood.has(slot)){renderIndex(lastGood.get(slot),slot,'旧数据 · 更新失败');return;}
        renderIndex({name:index[1],label:index[2],source:'https://finance.yahoo.com/quote/'+encodeURIComponent(index[0])+'/',error:'行情请求失败，请稍后刷新'},slot);
      }
    });
    await Promise.allSettled([calendar,...quotes]);
    updated=Date.now();busy=false;document.getElementById('home-refresh').disabled=false;
  }
  document.getElementById('home-refresh').addEventListener('click',()=>{refresh();refreshSectors();});
  setInterval(clock,1000);
  setInterval(()=>{if(started){refresh();refreshSectors();}},60000);
  document.addEventListener('visibilitychange',()=>{if(started&&Date.now()-updated>=60000){refresh();refreshSectors();}});
  function start(){if(!started){started=true;startSectors();
    document.getElementById('home-indices').innerHTML=indices.map((index,slot)=>`<article class="home-index" id="home-index-${slot}"></article>`).join('');
    indices.forEach((index,slot)=>{const saved=FinFeedCache.read('home-'+index[0],86400000);
      if(saved){lastGood.set(slot,saved.data.index);renderIndex(saved.data.index,slot,'缓存 · 正在更新');}
      else renderIndex({name:index[1],label:index[2],source:'https://finance.yahoo.com/quote/'+encodeURIComponent(index[0])+'/',error:'正在加载…'},slot);
    });
    const calendar=FinFeedCache.read('home-calendar',86400000);
    if(calendar){market=calendar.data;serverNow=Date.parse(market.server_time)+Date.now()-calendar.savedAt;syncedAt=performance.now();clock();}
    document.getElementById('home-update-status').textContent='先显示上次成功缓存，正在逐项更新；报价时间见各指数。';
    refresh();}else if(Date.now()-updated>=60000)refresh();}
  return {prefetch:start,open(user){if(user)document.getElementById('page-title').textContent='Hi '+user.name;start();}};
})();
