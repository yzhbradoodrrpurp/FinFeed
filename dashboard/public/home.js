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
  function renderIndex(index,slot){
    document.getElementById('home-index-'+slot).innerHTML=`<span class="eyebrow">${esc(index.name)}</span><h2>${esc(index.label)}</h2><strong class="home-index-price">${format(index.price)}</strong><p class="${index.change>0?'positive':index.change<0?'negative':''}">${index.change>0?'+':''}${format(index.change)} / ${index.change_percent>0?'+':''}${format(index.change_percent)}%</p><p class="home-quote-time">${index.quoted_at?'报价于 '+date(index.quoted_at,'America/New_York')+' 美国东部':esc(index.error||'暂无报价')}</p><a class="home-source" href="${esc(index.source)}" target="_blank" rel="noreferrer">Yahoo Finance ↗</a>`;
  }
  async function fetchData(url){
    const response=await FinFeedAuth.request(url);if(!response.ok)throw new Error();return response.json();
  }
  async function refresh(){
    if(busy)return;busy=true;document.getElementById('home-refresh').disabled=true;
    if(!document.getElementById('home-index-0'))document.getElementById('home-indices').innerHTML=indices.map((index,slot)=>`<article class="home-index" id="home-index-${slot}"><span class="eyebrow">${esc(index[1])}</span><h2>${esc(index[2])}</h2><strong class="home-index-price">—</strong><p class="home-quote-time">正在加载…</p></article>`).join('');
    const calendar=fetchData('/api/home').then(data=>{market=data;serverNow=Date.parse(data.server_time);syncedAt=performance.now();clock();}).catch(()=>{
      market=null;document.getElementById('home-market-status').textContent='状态暂不可用';document.getElementById('home-countdown').textContent='—';document.getElementById('home-session-time').textContent='';
    });
    const quotes=indices.map(async(index,slot)=>{
      try{
        const data=await fetchData('/api/home?symbol='+encodeURIComponent(index[0]));renderIndex(data.index,slot);
        document.getElementById('home-update-status').textContent=`检索于 ${date(data.retrieved_at,'Asia/Shanghai')} 北京 · 每分钟检查更新，行情可能延迟；涨跌相对前收盘价。`;
      }catch{
        renderIndex({name:index[1],label:index[2],source:'https://finance.yahoo.com/quote/'+encodeURIComponent(index[0])+'/',error:'行情请求失败，请稍后刷新'},slot);
      }
    });
    await Promise.allSettled([calendar,...quotes]);
    updated=Date.now();busy=false;document.getElementById('home-refresh').disabled=false;
  }
  document.getElementById('home-refresh').addEventListener('click',refresh);
  setInterval(clock,1000);
  setInterval(()=>{if(started&&!document.hidden&&!document.getElementById('home-surface').hidden)refresh();},60000);
  document.addEventListener('visibilitychange',()=>{if(started&&!document.hidden&&!document.getElementById('home-surface').hidden&&Date.now()-updated>=60000)refresh();});
  return {open(user){if(user)document.getElementById('page-title').textContent='Hi '+user.name;if(!started){started=true;refresh();}else if(Date.now()-updated>=60000)refresh();}};
})();
