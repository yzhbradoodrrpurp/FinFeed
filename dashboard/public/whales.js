"use strict";
window.FinFeedWhales=(()=>{
  const funds={berkshire:'伯克希尔',pershing:'潘兴广场',appaloosa:'阿帕卢萨管理',ark:'方舟投资',coatue:'蔻图资本',altimeter:'阿尔蒂米特资本',tiger:'老虎环球基金',polar:'北极星资本',alkeon:'阿尔基昂资本',westfield:'韦斯特菲尔德资本',lightstreet:'光街资本',hmi:'HMI 资本',atika:'阿提卡资本',dorsey:'多西资产管理',altarock:'阿尔塔洛克资本',broadrun:'布罗德朗投资管理'};
  const states=new Map(),good=new Map();
  let started=false,busy=false,checked=0,selected=null,tab='latest';
  const el=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=n=>Number(n).toLocaleString('zh-CN');
  const money=n=>Number(n).toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0});
  const signed=n=>(n>0?'+':'')+number(n);
  const labels={new:'新建仓',exit:'退出',increase:'增持',decrease:'减持',unchanged:'不变'};
  const security=row=>`<strong>${esc(row.name)}</strong><small>${esc(row.class)}${row.put_call?' · '+esc(row.put_call)+' 期权':''}<br>${esc(row.cusip)}</small>`;
  const sources=data=>`<div class="macro-sources">${(data.sources||[]).map((source,i)=>`<a href="${esc(source.url)}" target="_blank" rel="noreferrer">SEC ${esc(source.form)} 原始文件${data.sources.length>1?' '+(i+1):''} ↗</a>`).join('')}</div>`;
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
    if(data.schema_version!==3||data.totals_verified!==true||!data.holdings?.length){data=good.has(kind)?{...good.get(kind),stale:true}:{...data,holdings:[],errors:data.errors||['数据格式待更新，请稍后检查更新']};}
    else if(!data.partial&&!data.stale&&!data.refreshing){good.set(kind,data);FinFeedCache.write('whales-v3-'+kind,data);}
    states.set(kind,data);el('whale-summary-'+kind).textContent=summary(data);if(kind===selected)renderDetail();
  }
  async function refresh(){if(busy)return;busy=true;el('whales-refresh').disabled=true;
    await Promise.allSettled(Object.keys(funds).map(async kind=>{try{
      await FinFeedCache.market('/api/whales/'+kind+'?version=10&stream=1',data=>accept(kind,data),{ttl:21600000,validate:data=>data.schema_version===3&&data.totals_verified===true&&!!data.holdings?.length});
    }catch{accept(kind,good.has(kind)?{...good.get(kind),stale:true}:{errors:['SEC 请求失败，请稍后检查更新']});}}));
    checked=Date.now();busy=false;el('whales-refresh').disabled=false;
  }
  function open(){if(!started){started=true;Object.keys(funds).forEach(kind=>{const saved=FinFeedCache.read('whales-v3-'+kind,90*86400000);if(saved?.data.schema_version===3&&saved.data.totals_verified===true){good.set(kind,saved.data);accept(kind,{...saved.data,refreshing:true});}});refresh();}
    show(new URL(location.href).searchParams.get('fund'),false);
    if(Date.now()-checked>=21600000&&!busy)refresh();}
  document.querySelectorAll('[data-whale]').forEach(button=>button.addEventListener('click',()=>show(button.dataset.whale)));
  document.querySelectorAll('[data-whale-tab]').forEach(button=>button.addEventListener('click',()=>{if(tab===button.dataset.whaleTab)return;const order=['latest','previous','changes'];const direction=order.indexOf(button.dataset.whaleTab)>order.indexOf(tab)?1:-1;tab=button.dataset.whaleTab;renderDetail();window.FinFeedMotion?.enter(el('whale-detail-content'),{kind:'tab',direction});}));
  el('whale-category-select')?.addEventListener('change',event=>{
    const category=event.target.value;
    if(selected)show(null,true,false);
    document.querySelectorAll('.whale-group').forEach(group=>{group.hidden=category!=='all'&&group.getAttribute('aria-labelledby')!=='whale-group-'+category;});
    window.FinFeedMotion?.enter(document.querySelector('.whales-groups'),{kind:'filter'});
  });
  el('whale-back').addEventListener('click',()=>{const old=selected;show(null);document.querySelector('[data-whale="'+old+'"]').focus();});
  el('whales-refresh').addEventListener('click',refresh);
  setInterval(()=>{if(started&&!document.hidden&&!el('whales-surface').hidden&&Date.now()-checked>=21600000)refresh();},60000);
  return {open};
})();
