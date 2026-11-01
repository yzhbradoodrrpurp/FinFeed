"use strict";
// Authenticated, database-only reads. Full OHLCV snapshots use shared IndexedDB caching.
(() => {
  const dialog=document.createElement('dialog');
  dialog.id='candles-dialog';dialog.className='candles-dialog';dialog.setAttribute('aria-labelledby','candles-title');
  dialog.innerHTML=`<div class="dialog-heading"><div><span class="section-kicker">DAILY CHART</span><h2 id="candles-title" tabindex="-1">日 K 线</h2></div><button class="secondary" id="candles-close" aria-label="关闭 K 线图">关闭</button></div><div class="candles-toolbar"><span>日线</span><span id="candles-currency"></span></div><div id="candles-legend" class="candles-legend" aria-live="off"></div><p id="candles-status" role="status" class="macro-note"></p><div id="candles-chart" aria-label="日 K 线和成交量，可拖动和缩放"></div><div class="candles-bottom"><div id="candles-ranges" role="group" aria-label="图表时间范围"><button data-months="1">1个月</button><button data-months="3">3个月</button><button data-months="6">6个月</button><button data-months="12">1年</button><button data-months="36" aria-pressed="true">3年</button></div></div><p class="macro-note candles-footnote">常规交易时段 · 当日日线可能尚未收盘</p>`;
  document.body.append(dialog);
  const node=id=>document.getElementById('candles-'+id);
  let library,chart,price,volume,snapshot,activeSymbol,aborter,timer,requestId=0,byTime=new Map(),fitted=false,opener,resizer,logicalRange=null,keyboardInteraction=false;
  function loadLibrary(){
    if(window.LightweightCharts)return Promise.resolve();
    if(!library)library=new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src='/lightweight-charts.js';
      script.onload=resolve;script.onerror=()=>{script.remove();library=null;reject(new Error('图表组件加载失败'));};
      document.head.append(script);
    });
    return library;
  }
  const fmt=value=>Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2});
  function legend(bar){node('legend').textContent=bar?`${bar.time}　开 ${fmt(bar.open)}　高 ${fmt(bar.high)}　低 ${fmt(bar.low)}　收 ${fmt(bar.close)}　成交量 ${fmt(bar.volume)}`:'';}
  function setRange(value){logicalRange=value;chart.timeScale().setVisibleLogicalRange(value);}
  function makeChart(){
    const L=window.LightweightCharts;
    chart=L.createChart(node('chart'),{width:node('chart').clientWidth,height:node('chart').clientHeight,localization:{locale:'zh-CN'},layout:{background:{type:'solid',color:'#ffffff'},textColor:'#78736d',attributionLogo:true},grid:{vertLines:{color:'#f2f0ec'},horzLines:{color:'#f2f0ec'}},rightPriceScale:{borderColor:'#e8e3dc',minimumWidth:72},timeScale:{borderColor:'#e8e3dc',rightOffset:0,fixLeftEdge:true,fixRightEdge:true,minBarSpacing:0.01,lockVisibleTimeRangeOnResize:true},crosshair:{mode:L.CrosshairMode.Normal}});
    price=chart.addSeries(L.CandlestickSeries,{upColor:'#089981',downColor:'#f23645',borderVisible:false,wickUpColor:'#089981',wickDownColor:'#f23645'});
    volume=chart.addSeries(L.HistogramSeries,{priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false},1);
    chart.panes()[1].setHeight(140);
    // Own resizing explicitly: asynchronous auto-size after fit could introduce
    // blank space at both edges. Preserve the user's logical range on resize.
    chart.timeScale().subscribeVisibleLogicalRangeChange(value=>{if(value)logicalRange=value;});
    resizer=new ResizeObserver(()=>{
      if(!chart||!dialog.open)return;
      const visible=logicalRange||chart.timeScale().getVisibleLogicalRange();
      chart.resize(node('chart').clientWidth,node('chart').clientHeight);
      if(visible)setRange(visible);
    });
    resizer.observe(node('chart'));
    chart.subscribeCrosshairMove(event=>{
      const time=typeof event.time==='string'?event.time:event.time&&`${event.time.year}-${String(event.time.month).padStart(2,'0')}-${String(event.time.day).padStart(2,'0')}`;
      legend(byTime.get(time)||byTime.get([...byTime.keys()].at(-1)));
    });
  }
  function range(months){
    if(!chart||!snapshot?.bars?.length)return;
    const bars=snapshot.bars,last=bars.at(-1).time,end=new Date(last+'T00:00:00Z');end.setUTCMonth(end.getUTCMonth()-months);
    const start=end.toISOString().slice(0,10),index=Math.max(0,bars.findIndex(b=>b.time>=start));
    setRange({from:index-0.5,to:bars.length-0.5});
    node('ranges').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.months)===months)));
  }
  function render(data){
    snapshot=data;
    if(data.unsupported){node('status').textContent=data.note;return;}
    const bars=data.bars;
    if(!Array.isArray(bars)||!bars.length)return;
    if(!chart)makeChart();
    const visible=fitted?(logicalRange||chart.timeScale().getVisibleLogicalRange()):null;
    byTime=new Map(bars.map(b=>[b.time,b]));
    price.setData(bars.map(({volume,...b})=>b));
    volume.setData(bars.map(b=>({time:b.time,value:b.volume,color:b.close>=b.open?'#08998170':'#f2364570'})));
    legend(bars.at(-1));node('title').textContent=`${activeSymbol} · ${data.name||'日 K 线'}`;node('currency').textContent=data.currency||'';
    const time=new Date(data.retrieved_at);
    node('status').textContent=`${data.stale?'更新失败，保留历史数据 · ':data.refreshing?'缓存 · 正在检查更新 · ':''}${bars[0].time} — ${bars.at(-1).time} · 更新于 ${Number.isNaN(time.getTime())?'未知':time.toLocaleString('zh-CN')}`;
    setRange(visible||{from:-0.5,to:bars.length-0.5});fitted=true;
  }
  async function check(id){
    if(aborter||!dialog.open)return;
    const controller=aborter=new AbortController();
    try{
      await window.FinFeedCache.market('/api/candles/'+encodeURIComponent(activeSymbol),data=>{
        if(id!==requestId||!dialog.open)return;
        if(data.bars?.length||data.unsupported)render(data);
        else if(data.errors?.length)node('status').textContent=data.errors.join('；');
      },{signal:controller.signal,ttl:60000,staleTtl:30*86400000,validate:d=>Boolean(d.bars?.length||d.unsupported)});
    }catch(error){if(!controller.signal.aborted&&id===requestId)node('status').textContent=snapshot?.bars?.length?'暂时无法检查更新，保留本地历史曲线':'历史数据尚未就绪，服务器正在按计划准备，稍后自动检查。';}
    finally{if(aborter===controller)aborter=null;}
  }
  window.FinFeedCandles={async open(symbol,source,keyboard=false){
    keyboardInteraction=keyboard;
    opener=source||document.activeElement;requestId++;const id=requestId;
    aborter?.abort();aborter=null;clearInterval(timer);resizer?.disconnect();chart?.remove();chart=null;snapshot=null;fitted=false;logicalRange=null;activeSymbol=symbol;byTime.clear();
    node('title').textContent=symbol+' · 日 K 线';node('legend').textContent='';node('currency').textContent='';node('status').textContent='正在读取历史日线…';
    node('ranges').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.months==='36')));
    if(!dialog.open)dialog.showModal();node('title').focus({preventScroll:true});
    try{
      await Promise.all([loadLibrary(),window.FinFeedCache.ready]);
      if(id!==requestId||!dialog.open)return;
      const saved=window.FinFeedCache.read('request:/api/candles/'+encodeURIComponent(symbol),30*86400000);
      if(saved?.data)render({...saved.data,cached:true,refreshing:true});
      void check(id);timer=setInterval(()=>void check(id),60000);
    }catch(error){if(id===requestId)node('status').textContent=error.message;}
  }};
  node('close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('keydown',()=>{keyboardInteraction=true;});
  dialog.addEventListener('pointerdown',()=>{keyboardInteraction=false;});
  dialog.addEventListener('close',()=>{
    requestId++;aborter?.abort();aborter=null;clearInterval(timer);resizer?.disconnect();chart?.remove();chart=null;
    const target=opener?.isConnected?opener:[...document.querySelectorAll('[data-candles]')].find(button=>button.dataset.candles===activeSymbol);
    if(keyboardInteraction)target?.focus?.({preventScroll:true});
    // Native dialogs restore focus automatically; pointer closes must not leave
    // a focus-visible ring on the ticker (or Safari's focusable parent row).
    else if(document.activeElement===target||document.activeElement?.matches('.candle-trigger,tr[data-ticker]'))document.activeElement?.blur();
  });
  node('ranges').addEventListener('click',event=>{const button=event.target.closest('[data-months]');if(button)range(Number(button.dataset.months));});
})();
