"use strict";
// Authenticated, database-only reads. Full OHLCV snapshots use shared IndexedDB caching.
(() => {
  const vegasGroups=[{periods:[144,169],color:'#f23645'},{periods:[288,338],color:'#f59e0b'},{periods:[576,676],color:'#4caf50'}];
  const dialog=document.createElement('dialog');
  dialog.id='candles-dialog';dialog.className='candles-dialog';dialog.setAttribute('aria-labelledby','candles-title');
  dialog.innerHTML=`<div class="dialog-heading"><div><span class="section-kicker">DAILY CHART</span><h2 id="candles-title" tabindex="-1">日 K 线</h2></div><button class="secondary" id="candles-close" aria-label="关闭 K 线图">关闭</button></div><div class="candles-toolbar"><span>日线</span><span id="candles-currency"></span><span class="candles-vegas" title="EMA 使用前复权收盘价，按交易日计算；以缓存历史首日收盘价初始化，早期数值可能受历史长度影响。">${vegasGroups.map(group=>`<span style="color:${group.color}">EMA ${group.periods.join('/')}</span>`).join('')}</span></div><div id="candles-legend" class="candles-legend" aria-live="off"></div><p id="candles-status" role="status" class="macro-note"></p><div class="candles-workspace"><div id="candles-tools" role="toolbar" aria-label="图表工具"><button data-tool="cursor" aria-label="光标" title="光标：选择图形、拖动和缩放图表" aria-pressed="true"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M5 3l14 10-7 1-3 7z"/><path d="M12 14l5 7"/></svg></button><button data-tool="measure" aria-label="测量" title="测量：选择两点或拖动" aria-pressed="false"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3 16L16 3l5 5L8 21z"/><path d="M13 6l2 2M10 9l3 3M7 12l2 2M4 15l3 3"/></svg></button><button data-tool="trend" aria-label="趋势线" title="趋势线：选择两点，保存到我的账户" aria-pressed="false" disabled><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M14 5l5 5M4 20l5-1L21 7a2.1 2.1 0 0 0-4-4L5 15z"/></svg></button></div><div id="candles-chart" aria-label="日 K 线和成交量，可拖动和缩放"></div></div><div class="candles-tool-feedback"><span id="candles-tool-status" role="status"></span><button id="candles-retry" class="secondary" hidden>重试</button><button id="candles-discard" class="secondary" hidden>放弃本次更改</button></div><div class="candles-bottom"><div id="candles-ranges" role="group" aria-label="图表时间范围"><button data-months="1">1个月</button><button data-months="3">3个月</button><button data-months="6">6个月</button><button data-months="12">1年</button><button data-months="36" aria-pressed="true">3年</button></div></div><p class="macro-note candles-footnote">常规交易时段 · 当日日线可能尚未收盘</p>`;
  document.body.append(dialog);
  const node=id=>document.getElementById('candles-'+id);
  let library,chart,price,volume,vegas=[],snapshot,activeSymbol,aborter,timer,requestId=0,byTime=new Map(),fitted=false,opener,resizer,logicalRange=null,keyboardInteraction=false;
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
  function ema(bars,period){
    const alpha=2/(period+1);let value=bars[0].close;
    return bars.map(bar=>{value+=alpha*(bar.close-value);return {time:bar.time,value};});
  }
  function setRange(value){logicalRange=value;chart.timeScale().setVisibleLogicalRange(value);}
  // Private annotations never enter the shared market snapshot/IndexedDB cache.
  let tool='cursor',anchor=null,preview=null,measure=null,drawState=null,dragOrigin=null,overlay,deleteButton,selection=null,redrawFrame=0;
  const svgNS='http://www.w3.org/2000/svg';
  function toolStatus(message=''){node('tool-status').textContent=message;}
  function setTool(value){
    if(value==='trend'&&(!drawState?.loaded||drawState.pending)){toolStatus('请先完成划线读取或保存');return;}
    tool=value;anchor=preview=null;selection=null;
    node('tools').querySelectorAll('[data-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tool===value)));
    if(overlay)overlay.style.pointerEvents=value==='cursor'?'none':'auto';
    toolStatus(value==='cursor'?'':value==='measure'?'选择两点测量，或按住拖动；Esc 取消':'选择不同日期的两点划线；完成后自动保存');redraw();
  }
  function project(point){
    const index=snapshot?.bars?.findIndex(b=>b.time===point.time);
    if(index==null||index<0)return null;
    const x=chart.timeScale().logicalToCoordinate(index),y=price.priceToCoordinate(point.price);
    return x==null||y==null?null:{x,y,index};
  }
  function redraw(){
    if(!overlay||!chart||!snapshot?.bars?.length)return;
    const width=chart.timeScale().width(),height=chart.panes()[0].getHeight();
    overlay.setAttribute('width',width);overlay.setAttribute('height',height);overlay.replaceChildren();
    const add=(name,attributes,text)=>{const n=document.createElementNS(svgNS,name);Object.entries(attributes).forEach(([k,v])=>n.setAttribute(k,String(v)));if(text)n.textContent=text;overlay.append(n);return n;};
    const hit=(element,kind,id='')=>{if(tool==='cursor'){element.dataset.drawing=kind;element.dataset.drawingId=id;element.style.pointerEvents='all';element.style.cursor='pointer';}};
    const segment=(points,color,dash=false,item=null)=>{
      const a=project(points[0]),b=project(points[1]);if(!a||!b)return;
      if(item){const target=add('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'transparent','stroke-width':16});hit(target,item.kind,item.id);}
      add('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:color,'stroke-width':2,...(dash?{'stroke-dasharray':'5 4'}:{})});
      [a,b].forEach(p=>add('circle',{cx:p.x,cy:p.y,r:3,fill:'white',stroke:color,'stroke-width':2}));return [a,b];
    };
    (drawState?.lines||[]).forEach(line=>segment(line.points,selection?.id===line.id?'#c6530c':'#ee7523',false,{kind:'line',id:line.id}));
    if(tool==='trend'&&anchor&&preview)segment([anchor,preview],'#ee7523',true);
    const ruler=tool==='measure'&&anchor&&preview?[anchor,preview]:measure;
    if(ruler){const pair=segment(ruler,'#ee7523',true,{kind:'measure'});if(pair){
      const [a,b]=pair,delta=ruler[1].price-ruler[0].price,percent=delta/ruler[0].price*100;
      hit(add('rect',{x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.max(2,Math.abs(a.x-b.x)),height:Math.max(2,Math.abs(a.y-b.y)),fill:'#ee752315',stroke:'#ee752350'}),'measure');
      const label=`${delta>=0?'+':''}${fmt(delta)} (${percent>=0?'+':''}${fmt(percent)}%) · ${Math.abs(a.index-b.index)+1} 根日 K`;
      const boxWidth=Math.min(width,Math.max(200,label.length*8)),x=Math.max(0,Math.min(width-boxWidth,(a.x+b.x)/2-boxWidth/2)),y=Math.max(2,Math.min(height-30,Math.min(a.y,b.y)-34));
      hit(add('rect',{x,y,width:boxWidth,height:28,rx:5,fill:'#fff5eb',stroke:'#ee7523'}),'measure');
      hit(add('text',{x:x+8,y:y+18,fill:'#a8490c','font-size':12},label),'measure');
    }}
    if(deleteButton){
      const points=selection?.kind==='measure'?measure:drawState?.lines.find(line=>line.id===selection?.id)?.points;
      const pair=points?.map(project);
      deleteButton.hidden=!pair?.every(Boolean)||tool!=='cursor';
      deleteButton.disabled=!!drawState?.pending;
      if(!deleteButton.hidden){const [a,b]=pair;deleteButton.style.left=Math.max(2,Math.min(width-72,(a.x+b.x)/2-32))+'px';deleteButton.style.top=Math.max(2,Math.min(height-36,Math.min(a.y,b.y)+12))+'px';deleteButton.setAttribute('aria-label',selection.kind==='measure'?'删除选中测量':'删除选中划线');}
    }
  }
  function scheduleRedraw(){if(!redrawFrame)redrawFrame=requestAnimationFrame(()=>{redrawFrame=0;redraw();});}
  function pointAt(event){
    if(!snapshot?.bars?.length)return null;
    const rect=overlay.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;
    if(x<0||x>rect.width||y<0||y>rect.height)return null;
    const logical=chart.timeScale().coordinateToLogical(x),value=price.coordinateToPrice(y);
    if(logical==null||!Number.isFinite(value)||value<=0)return null;
    const index=Math.max(0,Math.min(snapshot.bars.length-1,Math.round(logical)));
    return {time:snapshot.bars[index].time,price:value};
  }
  async function readDrawings(state=drawState){
    if(!state||state.pending||state.loading)return;
    state.loading=true;
    try{
      const response=await FinFeedAuth.request('/api/chart-drawings/'+encodeURIComponent(state.symbol));
      const data=await response.json();if(!response.ok)throw Error(data.error||'划线读取失败');
      if(drawState!==state||!dialog.open||state.pending||data.revision<state.revision)return;
      state.revision=data.revision;state.lines=data.lines;state.loaded=true;state.error=null;toolStatus('');redraw();
    }catch(error){if(drawState===state&&dialog.open){state.error='read';toolStatus('划线读取失败，请重试；测量仍可使用');}}
    finally{state.loading=false;if(drawState===state)updateToolButtons();}
  }
  function updateToolButtons(){
    node('retry').hidden=!drawState?.error;
    node('discard').hidden=!drawState?.pending||!drawState?.error;
    node('tools').querySelector('[data-tool="trend"]').disabled=!drawState?.loaded||!!drawState?.pending;
    if(deleteButton)deleteButton.disabled=!!drawState?.pending;
  }
  async function saveDrawing(operation=drawState?.pending){
    const state=drawState;if(!state||!operation||state.saving)return;
    state.pending=operation;state.saving=true;state.error=null;updateToolButtons();toolStatus('正在保存划线…');
    try{
      const response=await FinFeedAuth.request('/api/chart-drawings/'+encodeURIComponent(state.symbol),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(operation)});
      const data=await response.json();if(!response.ok)throw Error(data.error||'保存失败');
      if(drawState!==state)return;
      state.revision=data.revision;state.lines=data.lines;state.pending=null;toolStatus('划线已保存');redraw();
    }catch(error){if(drawState===state){state.error='save';toolStatus(`划线保存未确认：${error.message}。请重试，或放弃本次更改。`);}}
    finally{state.saving=false;if(drawState===state)updateToolButtons();}
  }
  function completePoint(point){
    if(!point||!anchor)return;
    if(tool==='trend'){
      if(point.time===anchor.time){toolStatus('请选择不同日期的终点');return;}
      const line={id:Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join(''),points:[anchor,point]};
      drawState.lines.push(line);setTool('cursor');void saveDrawing({operation:'add',line});
    }else{measure=[anchor,point];setTool('cursor');updateToolButtons();redraw();}
  }
  function mountTools(){
    overlay=document.createElementNS(svgNS,'svg');overlay.classList.add('candles-drawing-overlay');overlay.setAttribute('aria-label','在价格图上选择起点和终点');node('chart').append(overlay);
    deleteButton=document.createElement('button');deleteButton.type='button';deleteButton.textContent='删除';deleteButton.className='candles-object-delete';deleteButton.hidden=true;deleteButton.addEventListener('click',deleteSelection);node('chart').append(deleteButton);
    overlay.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;
      if(tool==='cursor'){
        const target=event.target.closest('[data-drawing]');if(!target)return;
        event.preventDefault();event.stopPropagation();selection={kind:target.dataset.drawing,id:target.dataset.drawingId};toolStatus('已选中，可点击删除或按 Delete / Backspace');redraw();return;
      }
      event.preventDefault();event.stopPropagation();
      const point=pointAt(event);if(!point)return;
      if(anchor)completePoint(point);else{anchor=preview=point;dragOrigin={x:event.clientX,y:event.clientY};overlay.setPointerCapture(event.pointerId);redraw();}
    });
    overlay.addEventListener('pointermove',event=>{if(anchor){preview=pointAt(event)||preview;redraw();}});
    overlay.addEventListener('pointerup',event=>{if(anchor&&dragOrigin&&Math.hypot(event.clientX-dragOrigin.x,event.clientY-dragOrigin.y)>6)completePoint(pointAt(event));dragOrigin=null;});
    overlay.addEventListener('pointercancel',()=>{anchor=preview=dragOrigin=null;redraw();});
    setTool('cursor');redraw();
  }
  function closeChart(){
    if(drawState?.pending){toolStatus('划线尚未保存，请重试或放弃本次更改后关闭');return;}
    dialog.close();
  }
  node('tools').addEventListener('click',event=>{
    const button=event.target.closest('[data-tool]');if(button)setTool(button.dataset.tool);
  });
  function deleteSelection(){
    if(!selection||drawState?.pending)return;
    const selected=selection;selection=null;
    if(selected.kind==='measure'){measure=null;toolStatus('');redraw();}
    else{redraw();void saveDrawing({operation:'delete',ids:[selected.id]});}
  }
  dialog.addEventListener('keydown',event=>{
    if(selection&&['Delete','Backspace'].includes(event.key)&&!event.target.closest('input,textarea,select,[contenteditable]')){event.preventDefault();deleteSelection();}
  });
  node('chart').addEventListener('pointerdown',event=>{if(tool==='cursor'&&!event.target.closest('[data-drawing],.candles-object-delete')){selection=null;toolStatus('');redraw();}},true);
  node('retry').addEventListener('click',()=>drawState?.pending?void saveDrawing():void readDrawings());
  node('discard').addEventListener('click',()=>{if(drawState?.saving)return;drawState.pending=null;drawState.loaded=false;void readDrawings();});
  dialog.addEventListener('cancel',event=>{if(tool!=='cursor'||anchor||selection){event.preventDefault();setTool('cursor');}else if(drawState?.pending){event.preventDefault();closeChart();}});
  node('chart').addEventListener('pointermove',scheduleRedraw);node('chart').addEventListener('wheel',scheduleRedraw,{passive:true});
  window.addEventListener('focus',()=>{if(dialog.open)void readDrawings();});

  function makeChart(){
    const L=window.LightweightCharts;
    chart=L.createChart(node('chart'),{width:node('chart').clientWidth,height:node('chart').clientHeight,localization:{locale:'zh-CN'},layout:{background:{type:'solid',color:'#ffffff'},textColor:'#78736d',attributionLogo:true},grid:{vertLines:{color:'#f2f0ec'},horzLines:{color:'#f2f0ec'}},rightPriceScale:{borderColor:'#e8e3dc',minimumWidth:72},timeScale:{borderColor:'#e8e3dc',rightOffset:0,fixLeftEdge:true,fixRightEdge:true,minBarSpacing:0.01,lockVisibleTimeRangeOnResize:true},crosshair:{mode:L.CrosshairMode.Normal}});
    price=chart.addSeries(L.CandlestickSeries,{upColor:'#089981',downColor:'#f23645',borderVisible:false,wickUpColor:'#089981',wickDownColor:'#f23645'});
    vegas=vegasGroups.flatMap(group=>group.periods.map(period=>({period,series:chart.addSeries(L.LineSeries,{color:group.color,lineWidth:2,lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false})})));
    volume=chart.addSeries(L.HistogramSeries,{priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false},1);
    chart.panes()[1].setHeight(140);
    // Own resizing explicitly: asynchronous auto-size after fit could introduce
    // blank space at both edges. Preserve the user's logical range on resize.
    chart.timeScale().subscribeVisibleLogicalRangeChange(value=>{if(value)logicalRange=value;scheduleRedraw();});
    resizer=new ResizeObserver(()=>{
      if(!chart||!dialog.open)return;
      const visible=logicalRange||chart.timeScale().getVisibleLogicalRange();
      chart.resize(node('chart').clientWidth,node('chart').clientHeight);
      if(visible)setRange(visible);scheduleRedraw();
    });
    resizer.observe(node('chart'));
    mountTools();
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
    vegas.forEach(({period,series})=>series.setData(ema(bars,period)));
    legend(bars.at(-1));node('title').textContent=`${activeSymbol} · ${data.name||'日 K 线'}`;node('currency').textContent=data.currency||'';
    const time=new Date(data.retrieved_at);
    node('status').textContent=`${data.stale?'更新失败，保留历史数据 · ':data.refreshing?'缓存 · 正在检查更新 · ':''}${bars[0].time} — ${bars.at(-1).time} · 更新于 ${Number.isNaN(time.getTime())?'未知':time.toLocaleString('zh-CN')}`;
    setRange(visible||{from:-0.5,to:bars.length-0.5});fitted=true;redraw();
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
  async function readDrawingsAfterOpen(){await Promise.resolve();if(dialog.open)await readDrawings();}
  window.FinFeedCandles={async open(symbol,source,keyboard=false){
    keyboardInteraction=keyboard;drawState={symbol,revision:0,lines:[],loaded:false,pending:null,loading:false};measure=null;anchor=preview=null;tool='cursor';selection=null;overlay?.remove();deleteButton?.remove();deleteButton=null;overlay=null;toolStatus('正在读取我的划线…');updateToolButtons();void readDrawingsAfterOpen();
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
      void check(id);timer=setInterval(()=>{void check(id);void readDrawings();},60000);
    }catch(error){if(id===requestId)node('status').textContent=error.message;}
  }};
  node('close').addEventListener('click',closeChart);
  dialog.addEventListener('keydown',()=>{keyboardInteraction=true;});
  dialog.addEventListener('pointerdown',()=>{keyboardInteraction=false;});
  dialog.addEventListener('close',()=>{
    requestId++;aborter?.abort();aborter=null;clearInterval(timer);resizer?.disconnect();chart?.remove();chart=null;overlay?.remove();deleteButton?.remove();deleteButton=null;selection=null;overlay=null;cancelAnimationFrame(redrawFrame);redrawFrame=0;drawState=null;
    const target=opener?.isConnected?opener:[...document.querySelectorAll('[data-candles]')].find(button=>button.dataset.candles===activeSymbol);
    if(keyboardInteraction)target?.focus?.({preventScroll:true});
    // Native dialogs restore focus automatically; pointer closes must not leave
    // a focus-visible ring on the ticker (or Safari's focusable parent row).
    else if(document.activeElement===target||document.activeElement?.matches('.candle-trigger,tr[data-ticker]'))document.activeElement?.blur();
  });
  node('ranges').addEventListener('click',event=>{const button=event.target.closest('[data-months]');if(button)range(Number(button.dataset.months));});
})();
