"use strict";
window.FinFeedWhales=(()=>{
  const funds={berkshire:'伯克希尔',pershing:'潘兴广场',appaloosa:'阿帕卢萨管理',ark:'方舟投资',coatue:'蔻图资本',altimeter:'阿尔蒂米特资本',tiger:'老虎环球基金',polar:'北极星资本',alkeon:'阿尔基昂资本',westfield:'韦斯特菲尔德资本',lightstreet:'光街资本',hmi:'HMI 资本',atika:'阿提卡资本',dorsey:'多西资产管理',altarock:'阿尔塔洛克资本',broadrun:'布罗德朗投资管理',mubadala:'穆巴达拉投资',bridgewater:'桥水基金',trian:'特里安基金'};
  const states=new Map(),good=new Map();
  let started=false,busy=false,checked=0,selected=null,tab='latest';
  let mode='funds',stockCusip=null,searchActive=true,analysisFrame=null;
  const el=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=n=>Number(n).toLocaleString('zh-CN');
  const money=n=>Number(n).toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0});
  const signed=n=>(n>0?'+':'')+number(n);
  const labels={new:'新建仓',exit:'退出',increase:'增持',decrease:'减持',unchanged:'不变'};
  const security=row=>`<strong>${esc(row.name)}</strong><small>${esc(row.class)}${row.put_call?' · '+esc(row.put_call)+' 期权':''}<br>${esc(row.cusip)}</small>`;
  const sources=data=>`<div class="macro-sources">${(data.sources||[]).map((source,i)=>`<a href="${esc(source.url)}" target="_blank" rel="noreferrer">SEC ${esc(source.form)} 原始文件${data.sources.length>1?' '+(i+1):''} ↗</a>`).join('')}</div>`;
  function setMode(next){
    mode=next;document.querySelector('.whales-groups').hidden=mode!=='funds';el('whale-stock-analysis').hidden=mode!=='stock';
    el('whale-category-control').hidden=el('whales-surface').hidden;
    document.querySelectorAll('[data-whale-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.whaleMode===mode)));
    if(mode==='stock')renderStockAnalysis();
  }
  function filteredFunds(){
    const category=el('whale-category-select').value;
    if(category==='all')return funds;
    const group=document.querySelector('[aria-labelledby="whale-group-'+category+'"]');
    return Object.fromEntries([...group.querySelectorAll('[data-whale]')].map(button=>[button.dataset.whale,funds[button.dataset.whale]]));
  }
  function renderStockAnalysis(){
    if(mode!=='stock')return;
    const scopedFunds=filteredFunds(),scopedStates=new Map([...states].filter(([fund])=>Object.hasOwn(scopedFunds,fund)));
    const list=FinFeedWhaleAnalysis.securities(scopedStates),query=el('whale-stock-search').value.trim().toUpperCase();
    const ranking=FinFeedWhaleAnalysis.topHeld(scopedStates);
    const matches=query?list.filter(row=>row.name.toUpperCase().includes(query)||row.cusip.includes(query)):ranking.rows;
    el('whale-stock-ranking').hidden=!!query||!searchActive||!ranking.report_date;
    el('whale-stock-ranking').textContent=`${ranking.report_date} · ${ranking.covered}/${Object.keys(scopedFunds).length} 家机构已取得该季度持仓 · 持有机构数量最多的 12 只股票`;
    el('whale-stock-results').hidden=!searchActive;
    if(searchActive)el('whale-stock-results').innerHTML=matches.slice(0,12).map(row=>`<button class="whale-stock-choice" data-stock-cusip="${esc(row.cusip)}"><strong>${esc(row.name)}</strong><small>${esc(row.class)} · ${esc(row.cusip)}${!query?' · '+row.count+' 家机构持有':''}</small></button>`).join('')||`<p class="whale-status">${list.length?'未找到匹配证券，可尝试 SEC 公司名或 CUSIP。':'正在读取机构持仓，取得数据后会逐步显示证券。'}</p>`;
    const body=el('whale-stock-content'),stock=list.find(row=>row.cusip===stockCusip);
    if(!stock){body.innerHTML='';return;}
    const result=FinFeedWhaleAnalysis.analyze(scopedStates,scopedFunds,stockCusip);
    const count=Object.values(result.groups).reduce((n,rows)=>n+rows.length,0);
    body.innerHTML=`<h3>${esc(stock.name)}</h3><p class="whale-status">${esc(stock.class)} · CUSIP ${esc(stock.cusip)} · ${count} 家机构有持仓记录 · ${result.absent.length} 家两季均未披露持有 · ${result.unavailable.length} 家待比较</p>`+Object.entries(result.groups).map(([status,rows])=>`<section class="whale-stock-group"><h3><span class="whale-change ${status}">${labels[status]}</span><span class="count">${rows.length} 家机构</span></h3>${rows.length?`<div class="whale-table-scroll"><table class="whale-table"><caption>${esc(stock.name)} · ${labels[status]}机构</caption><thead><tr><th>机构 / 比较季度</th><th>上季度股数</th><th>最新季度股数</th><th>股数变化</th><th>变化率</th><th>最新披露占比</th></tr></thead><tbody>${rows.map(row=>`<tr><td><button class="whale-fund-link" data-stock-fund="${esc(row.fund)}">${esc(row.name)} →</button><small>${esc(row.previous_date)} → ${esc(row.report_date)}<br>申报日 ${esc(row.previous_filed_at)} → ${esc(row.filed_at)}${row.stale?' · 缓存旧数据':row.refreshing?' · 正在检查更新':''}</small></td><td>${number(row.previous.shares)}</td><td>${number(row.current.shares)}</td><td>${signed(row.delta)}</td><td>${row.percent==null?'—':`${row.percent>0?'+':''}${row.percent.toFixed(2)}%`}</td><td>${row.current.weight.toFixed(2)}%</td></tr>`).join('')}</tbody></table></div>`:'<p class="whale-status">暂无机构。</p>'}</section>`).join('')+
      (result.unavailable.length?`<p class="whale-status">待比较：${result.unavailable.map(row=>esc(row.name)).join('、')}。尚未取得并核验相邻两季度持仓。</p>`:'')+
      (result.absent.length?`<p class="whale-status">两季均未披露持有：${result.absent.map(row=>esc(row.name)).join('、')}。不计入“不变”。</p>`:'');
  }
  function scheduleAnalysis(){if(mode!=='stock'||analysisFrame!==null)return;analysisFrame=requestAnimationFrame(()=>{analysisFrame=null;renderStockAnalysis();});}
  function summary(data){return data?.holdings?.length?`报告期末 ${data.report_date} · ${data.holdings.length} 项证券${data.refreshing?' · 正在检查更新':data.stale?' · 使用旧数据':''}`:data?.errors?.join('；')||'正在读取 SEC 13F…';}
  function table(data,label){return `<p class="whale-status">${esc(label)}：${esc(data.report_date)} · 申报日 ${esc(data.filed_at)} · 披露市值合计 ${money(data.total_value)} · 封面与明细合计已严格核对</p><div class="whale-table-scroll"><table class="whale-table"><caption>${esc(label)}，按季度末市值排序</caption><thead><tr><th>证券 / CUSIP</th><th>股数 / 本金数量</th><th>季度末市值（USD）</th><th>披露占比</th></tr></thead><tbody>${data.holdings.map(row=>`<tr><td>${security(row)}</td><td>${number(row.shares)}<small>${row.amount_type==='SH'?'股数':esc(row.amount_type)+' 本金数量'}</small></td><td>${money(row.value)}</td><td>${Number(row.weight).toFixed(2)}%</td></tr>`).join('')}</tbody></table></div>${sources(data)}${(data.warnings||[]).map(w=>'<p class="whale-status">'+esc(w)+'</p>').join('')}`;}
  function changes(data){
    const rows=data.changes||[],counts={};rows.forEach(row=>counts[row.status]=(counts[row.status]||0)+1);
    return `<p class="whale-status">${esc(data.previous.report_date)} → ${esc(data.report_date)} · ${Object.entries(labels).map(([key,label])=>label+' '+(counts[key]||0)).join(' / ')}</p><div class="whale-table-scroll"><table class="whale-table"><caption>两个季度的证券数量与披露市值变化</caption><thead><tr><th>证券 / CUSIP</th><th>变化</th><th>上季度数量</th><th>最新季度数量</th><th>数量变化</th><th>数量变化率</th><th>上季度市值</th><th>最新季度市值</th><th>仓位变化（百分点）</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${security(row)}</td><td><span class="whale-change ${row.status}">${labels[row.status]}</span></td><td>${number(row.previous_shares)}</td><td>${number(row.current_shares)}</td><td>${signed(row.shares_change)}</td><td>${row.shares_change_percent==null?'—':(row.shares_change_percent>0?'+':'')+row.shares_change_percent.toFixed(2)+'%'}</td><td>${money(row.previous_value)}</td><td>${money(row.current_value)}</td><td>${row.weight_change>0?'+':''}${row.weight_change.toFixed(2)}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function renderDetail(){
    if(!selected)return;const data=states.get(selected);
    el('whale-detail-title').textContent=funds[selected];
    el('whale-detail-summary').textContent=summary(data);
    document.querySelectorAll('[data-whale-tab]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.whaleTab===tab)));
    const body=el('whale-detail-content');
    if(!data?.holdings?.length){body.innerHTML='<p class="whale-status">'+esc(summary(data))+'</p>';return;}
    if(tab==='latest')body.innerHTML=table(data,'最新披露季度');
    else if(data.previous)body.innerHTML=tab==='previous'?table(data.previous,'上季度持仓'):changes(data);
    else body.innerHTML='<p class="whale-status">'+esc(data.previous_status==='loading'?'正在读取上季度持仓…':data.previous_status==='failed'?'上季度读取失败，暂不计算变化':'未找到相邻上季度的 13F 报告，暂不计算变化')+'</p>';
    if(data.reporting_warning)body.insertAdjacentHTML('beforeend',`<p class="whale-status">${esc(data.reporting_warning)} <a href="${esc(data.reporting_notice.url)}" target="_blank" rel="noreferrer">SEC 申报主体变更通知 ↗</a></p>`);
    const time=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(data.retrieved_at));
    body.insertAdjacentHTML('beforeend',`<p class="whale-status whale-retrieved">检索于 ${esc(time)} 北京 · 每 6 小时检查申报更新</p>`);
  }
  function show(kind,writeURL=true,animate=true){
    selected=Object.hasOwn(funds,kind)?kind:null;tab='latest';
    el('whales-list').hidden=!!selected;el('whale-detail').hidden=!selected;
    if(writeURL){const url=new URL(location.href);if(selected)url.searchParams.set('fund',selected);else url.searchParams.delete('fund');history.replaceState(history.state,'',url);}
    if(selected){renderDetail();el('whale-detail-title').focus();}
    if(writeURL&&animate)window.FinFeedMotion?.enter(el(selected?'whale-detail':'whales-list'),{kind:'detail',direction:selected?1:-1});
  }
  function accept(kind,data){
    const previous=states.get(kind);
    if(previous&&Date.parse(data.retrieved_at)<Date.parse(previous.retrieved_at))return;
    if(data.schema_version!==3||data.totals_verified!==true||!data.holdings?.length){data=good.has(kind)?{...good.get(kind),stale:true}:{...data,holdings:[],errors:data.errors||['数据格式待更新，请稍后检查更新']};}
    else if(!data.partial&&!data.stale&&!data.refreshing){good.set(kind,data);FinFeedCache.write('whales-v3-'+kind,data);}
    states.set(kind,data);el('whale-summary-'+kind).textContent=summary(data);if(kind===selected)renderDetail();
    scheduleAnalysis();
  }
  async function refresh(force=false){if(busy)return;busy=true;el('whales-refresh').disabled=true;
    const tasks=Object.keys(funds);let next=0;
    async function worker(){while(next<tasks.length){const kind=tasks[next++];try{
      await FinFeedCache.market('/api/whales/'+kind+'?version=10&stream=1'+(force?'&refresh=1':''),data=>accept(kind,data),{ttl:3600000,staleTtl:90*86400000,refresh:force,validate:data=>data.schema_version===3&&data.totals_verified===true&&!!data.holdings?.length});
    }catch{accept(kind,good.has(kind)?{...good.get(kind),stale:true}:{errors:['SEC 请求失败，请稍后检查更新']});}}}
    await Promise.allSettled([worker(),worker()]);
    checked=Date.now();busy=false;el('whales-refresh').disabled=false;
  }
  function open(){if(!started){started=true;Object.keys(funds).forEach(kind=>{const saved=FinFeedCache.read('whales-v3-'+kind,90*86400000);if(saved?.data.schema_version===3&&saved.data.totals_verified===true){good.set(kind,saved.data);accept(kind,{...saved.data,refreshing:true});}});refresh();}
    show(new URL(location.href).searchParams.get('fund'),false);
    if(Date.now()-checked>=3600000&&!busy)refresh(true);}
  document.querySelectorAll('[data-whale]').forEach(button=>button.addEventListener('click',()=>show(button.dataset.whale)));
  document.querySelectorAll('[data-whale-mode]').forEach(button=>button.addEventListener('click',()=>{if(mode===button.dataset.whaleMode)return;const direction=button.dataset.whaleMode==='stock'?1:-1;setMode(button.dataset.whaleMode);window.FinFeedMotion?.enter(mode==='stock'?el('whale-stock-analysis'):document.querySelector('.whales-groups'),{kind:'tab',direction});}));
  el('whale-stock-search').addEventListener('input',()=>{searchActive=true;if(!el('whale-stock-search').value.trim())stockCusip=null;renderStockAnalysis();window.FinFeedMotion?.enter(el('whale-stock-results'),{kind:'search'});});
  el('whale-stock-results').addEventListener('click',event=>{
    const button=event.target.closest('[data-stock-cusip]');if(!button)return;
    stockCusip=button.dataset.stockCusip;searchActive=false;
    const stock=FinFeedWhaleAnalysis.securities(states).find(row=>row.cusip===stockCusip);el('whale-stock-search').value=stock.name;
    renderStockAnalysis();window.FinFeedMotion?.enter(el('whale-stock-content'),{kind:'filter'});
  });
  el('whale-stock-content').addEventListener('click',event=>{const button=event.target.closest('[data-stock-fund]');if(button)show(button.dataset.stockFund);});
  document.querySelectorAll('[data-whale-tab]').forEach(button=>button.addEventListener('click',()=>{
    if(tab===button.dataset.whaleTab)return;
    const order=Array.from(document.querySelectorAll('[data-whale-tab]'),item=>item.dataset.whaleTab);
    const direction=order.indexOf(button.dataset.whaleTab)>order.indexOf(tab)?1:-1;
    tab=button.dataset.whaleTab;renderDetail();
    window.FinFeedMotion?.enter(el('whale-detail-content'),{kind:'tab',direction});
  }));
  el('whale-category-select')?.addEventListener('change',event=>{
    const category=event.target.value;
    if(mode==='stock'){
      if(selected)show(null,true,false);
      renderStockAnalysis();
      window.FinFeedMotion?.enter(el('whale-stock-analysis'),{kind:'filter'});
    }
    const before=window.FinFeedMotion?.capture(document.querySelectorAll('.whale-group-heading,.whale-card'));
    if(selected)show(null,true,false);
    document.querySelectorAll('.whale-group').forEach(group=>{group.hidden=category!=='all'&&group.getAttribute('aria-labelledby')!=='whale-group-'+category;});
    if(before)window.FinFeedMotion.settle(before,document.querySelectorAll('.whale-group-heading,.whale-card'));
  });
  el('whale-back').addEventListener('click',()=>{const old=selected;show(null);document.querySelector('[data-whale="'+old+'"]').focus();});
  el('whales-refresh').addEventListener('click',()=>refresh(true));
  function checkDue(){if(started&&Date.now()-checked>=3600000)refresh(true);}
  setInterval(checkDue,60000);
  document.addEventListener('visibilitychange',checkDue);
  window.addEventListener('focus',checkDue);
  return {open,isStockAnalysis:()=>mode==='stock'};
})();
