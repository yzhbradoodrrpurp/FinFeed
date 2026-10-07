"use strict";
let initialLoading=true;
const fetchingTickers=new Set();
let readOnly=true,currentUser=null;
const surfaceNames=["home","watchlist","portfolio","macro","whales"];
const initialSurface=new URLSearchParams(location.search).get("surface");
let holdings=[],surface=surfaceNames.includes(initialSurface)?initialSurface:"home",editingPosition=null;
let viewedUserId=null,accountStateVersion=0,accountRequest=null;
let recordGeneration=0;
const recordRequests=new Set();
const surfaceAccounts={watchlist:null,portfolio:null};
function rememberSurfaceAccount(name,id){
  surfaceAccounts[name]=id;
  try{sessionStorage.setItem(`finfeed-view:${currentUser.id}:${name}`,id);}catch{}
}
function accountViewURL(name,id){
  const params=new URLSearchParams();
  if(id!==currentUser.id)params.set("user",id);
  if(name!=="home")params.set("surface",name);
  return "/"+(params.size?"?"+params.toString():"");
}
const groups = [
  {name:"证券",view:"market",columns:[["market_cap","Market Cap","公司市值","money"]]},
  {name:"价格",view:"market",columns:[["price","Last Price","常规时段","price"],["high_52w","52W High","52 周高点","price"],["low_52w","52W Low","52 周低点","price"]]},
  {name:"每股收益",view:"market",columns:[["eps_q0","Diluted EPS","已披露 Q0","eps"],["eps_q1","Diluted EPS","已披露 Q−1","eps"],["forward_eps_next","Forward EPS","下一财季预测","eps"]]},
  {name:"估值",view:"market",columns:[["pe_quarter","P/E","已披露季 · 年化","ratio"],["pe_forward_quarter","Forward P/E","下一季 · 年化","ratio"]]},
  {name:"成交参与",view:"market",columns:[["avg_volume_10","Avg Volume","此前 10 交易日","volume"],["relative_volume_10","Volume / Avg","比较日 / 10 日","ratio"]]},
  {name:"营收",view:"financial",columns:[["revenue_q0","Total Revenue","Q0 · 单季","money"],["revenue_yoy_q0","Revenue Growth","Q0 · 季度同比","growth"],["revenue_qoq_q0","Revenue Growth","Q0 · 季度环比","growth"],["revenue_qoq_q1","Revenue Growth","Q−1 · 季度环比","growth"]]},
  {name:"债务",view:"financial",columns:[["debt_q0","Total Debt","Q0 · 季末","money"],["debt_yoy_q0","Debt Growth","Q0 · 季度同比","growth"],["debt_qoq_q0","Debt Growth","Q0 · 季度环比","growth"],["debt_qoq_q1","Debt Growth","Q−1 · 季度环比","growth"]]},
  {name:"自由现金流",view:"financial",columns:[["fcf_q0","Free Cash Flow","Q0 · 单季","money"],["fcf_yoy_q0","FCF Growth","Q0 · 季度同比","growth"],["fcf_qoq_q0","FCF Growth","Q0 · 季度环比","growth"],["fcf_qoq_q1","FCF Growth","Q−1 · 季度环比","growth"]]}
];
const allColumns=groups.flatMap(g=>g.columns);
const records=new Map();
let tickers=[], view="all",sortKey=null,sortAsc=true,running=0, queue=[];
const el=id=>document.getElementById(id);
let sidebarWidth=184,sidebarCollapsed=false;
try{const saved=JSON.parse(localStorage.getItem("finfeed-sidebar")||"null");if(saved){sidebarWidth=Math.max(154,Math.min(320,Number(saved.width)||184));sidebarCollapsed=!!saved.collapsed;}}catch{}
function applySidebar(){
  document.body.style.setProperty("--sidebar",`${matchMedia("(max-width:640px)").matches?64:sidebarWidth}px`);
  document.body.classList.toggle("sidebar-collapsed",sidebarCollapsed);
  el("sidebar-toggle").textContent=sidebarCollapsed?"›":"‹";
  el("sidebar-toggle").setAttribute("aria-label",sidebarCollapsed?"展开侧栏":"折叠侧栏");
  el("sidebar-toggle").setAttribute("aria-expanded",String(!sidebarCollapsed));
  el("sidebar-resize").setAttribute("aria-valuenow",String(sidebarWidth));
}
function saveSidebar(){try{localStorage.setItem("finfeed-sidebar",JSON.stringify({width:sidebarWidth,collapsed:sidebarCollapsed}));}catch{}}
applySidebar();
window.addEventListener("resize",applySidebar);
el("sidebar-toggle").addEventListener("click",()=>{sidebarCollapsed=!sidebarCollapsed;applySidebar();saveSidebar();});
const sidebarHandle=el("sidebar-resize");
sidebarHandle.addEventListener("pointerdown",event=>{if(event.button!==0)return;sidebarHandle.focus();sidebarHandle.setPointerCapture(event.pointerId);document.body.classList.add("sidebar-resizing");event.preventDefault();});
sidebarHandle.addEventListener("pointermove",event=>{if(!sidebarHandle.hasPointerCapture(event.pointerId))return;sidebarWidth=Math.max(154,Math.min(320,event.clientX));applySidebar();});
function finishSidebarResize(){document.body.classList.remove("sidebar-resizing");saveSidebar();}
sidebarHandle.addEventListener("pointerup",finishSidebarResize);
sidebarHandle.addEventListener("lostpointercapture",finishSidebarResize);
sidebarHandle.addEventListener("keydown",event=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;event.preventDefault();sidebarWidth=event.key==="Home"?154:event.key==="End"?320:Math.max(154,Math.min(320,sidebarWidth+(event.key==="ArrowRight"?10:-10)));applySidebar();saveSidebar();});
const escapeHTML=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const timestamp=s=>s?new Date(s).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai",hour12:false})+" 北京时间":"未提供";
function selectedGroups(){return groups.filter(g=>view==="all"||g.view===view||g.view==="both");}
function trackedTickers(){return [...new Set([...tickers,...holdings.map(p=>p.ticker)])];}
const holdingNumber=n=>n==null?"—":n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const holdingUnitPrice=n=>n==null?"—":n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:6});
const holdingPercent=n=>n==null?"—":`${n>0?"+":""}${(n*100).toFixed(2)}%`;
const pnlClass=n=>n==null?"missing":n>0?"positive":n<0?"negative":"";
// Preserve flash progress across table rerenders during a refresh batch.
const cellValues=new Map(),cellFlashes=new Map();
const FLASH_MS=900;
function changeAttributes(key,value){
  return Number.isFinite(value)?`data-change-key="${escapeHTML(key)}" data-change-value="${value}"`:"";
}
function flashChangedCells(){
  const now=performance.now();
  document.querySelectorAll("[data-change-key]").forEach(cell=>{
    const key=cell.dataset.changeKey,value=Number(cell.dataset.changeValue),previous=cellValues.get(key);
    if(previous!==undefined&&previous!==value)cellFlashes.set(key,{direction:value>previous?"up":"down",started:now});
    cellValues.set(key,value);
    const flash=cellFlashes.get(key);
    if(flash&&now-flash.started<FLASH_MS){
      cell.classList.add(`value-flash-${flash.direction}`);
      cell.style.animationDelay=`-${now-flash.started}ms`;
    }else cellFlashes.delete(key);
  });
  // Missing values break the comparison chain; their next valid value is an initial load.
  const present=new Set([...document.querySelectorAll("[data-change-key]")].map(c=>c.dataset.changeKey));
  for(const key of cellValues.keys())if(!present.has(key)){cellValues.delete(key);cellFlashes.delete(key);}
}
// Keep existing rows/cells, focus and scroll position while quotes arrive.
function patchRows(body,html,key){
  const template=document.createElement("template");template.innerHTML=`<table><tbody>${html}</tbody></table>`;
  const next=[...template.content.querySelector("tbody").children];
  const existing=new Map([...body.children].filter(row=>row.dataset[key]).map(row=>[row.dataset[key],row]));
  const keep=new Set();
  next.forEach((fresh,index)=>{
    let row=existing.get(fresh.dataset[key]);
    if(!row||row.cells.length!==fresh.cells.length)row=fresh;
    else {
      [...fresh.cells].forEach((cell,i)=>{
        const current=row.cells[i];
        if(current.innerHTML!==cell.innerHTML)current.innerHTML=cell.innerHTML;
        // Flash metadata is recomputed below; don't replay animations on unchanged cells.
        for(const attr of [...current.attributes])if(!cell.hasAttribute(attr.name)&&!['class','style'].includes(attr.name))current.removeAttribute(attr.name);
        for(const attr of cell.attributes)if(current.getAttribute(attr.name)!==attr.value)current.setAttribute(attr.name,attr.value);
      });
    }
    keep.add(row);
    if(body.children[index]!==row)body.insertBefore(row,body.children[index]||null);
  });
  for(const row of [...body.children])if(!keep.has(row))row.remove();
}
let scheduledRender=false;
function scheduleRender(){
  if(scheduledRender)return;
  scheduledRender=true;
  requestAnimationFrame(()=>{scheduledRender=false;render();});
}
function renderHoldings(){
  if(surface!=="portfolio")return;
  if(initialLoading){
    el("holdings-count").textContent="正在加载持仓…";
    el("holdings-summary").innerHTML=`<section class="currency-summary" aria-busy="true"><div class="summary-heading"><span class="skeleton"></span></div><div class="summary-metrics">${["成本总额 · 全部持仓","当前市值","未实现盈亏","持仓收益率"].map(label=>`<div><small>${label}</small><strong><span class="skeleton"></span></strong></div>`).join("")}</div></section>`;
    patchRows(el("holdings-body"),Array.from({length:4},()=>`<tr class="initial-loading">${Array.from({length:11},(_,i)=>`<td${i===0?' class="sticky"':""}><span class="skeleton"></span></td>`).join("")}</tr>`).join(""),"holdingTicker");
    el("holdings-status").textContent="正在加载持仓…";
    return;
  }
  const rows=holdings.map(p=>FinFeedPositions.evaluate(p,records.get(p.ticker)));
  const summaries=FinFeedPositions.summarize(rows);
  el("holdings-count").textContent=`${holdings.length} 项持仓`;
  el("holdings-summary").innerHTML=summaries.map(g=>`<section class="currency-summary"><div class="summary-heading"><strong>${escapeHTML(g.currency)}</strong><span>${g.pricedCount} / ${g.count} 项已估值${g.staleCount?` · ${g.staleCount} 项使用旧报价`:""}${g.pricedCount<g.count?" · 市值和盈亏仅统计已估值部分":""}</span></div><div class="summary-metrics"><div><small>成本总额 · 全部持仓</small><strong>${holdingNumber(g.cost)}</strong></div><div><small>当前市值${g.pricedCount<g.count?" · 已估值部分":""}</small><strong>${holdingNumber(g.marketValue)}</strong></div><div><small>未实现盈亏${g.pricedCount<g.count?" · 已估值部分":""}</small><strong class="${pnlClass(g.pnl)}">${g.pnl>0?"+":""}${holdingNumber(g.pnl)}</strong></div><div><small>持仓收益率${g.pricedCount<g.count?" · 已估值部分":""}</small><strong class="${pnlClass(g.returnRate)}">${holdingPercent(g.returnRate)}</strong></div></div></section>`).join("");
  const holdingHTML=rows.length?rows.map(r=>{
    const p=r.position,g=summaries.find(g=>g.currency===p.currency),weight=r.marketValue!==null&&g.marketValue>0?r.marketValue/g.marketValue:null;
    const currency=`<span class="currency">${escapeHTML(p.currency)}</span>`;
    const quoteCurrency=`<span class="currency">${escapeHTML(r.record?.currency||"")}</span>`;
    return `<tr data-holding-ticker="${escapeHTML(p.ticker)}" tabindex="0" aria-label="查看 ${escapeHTML(p.ticker)} 持仓数据来源"><td class="sticky"><span class="symbol">${escapeHTML(p.ticker)}</span><div class="security-name">${escapeHTML(r.record?.name||p.ticker)}</div></td><td>${p.quantity.toLocaleString("en-US",{maximumSignificantDigits:15})}</td><td>${holdingUnitPrice(p.averageCost)} ${currency}</td><td>${holdingNumber(r.cost)} ${currency}</td><td>${holdingUnitPrice(r.price)} ${quoteCurrency}</td><td title="${escapeHTML(r.reason||"")}">${holdingNumber(r.marketValue)} ${currency}${r.reason?`<div class="portfolio-missing">${escapeHTML(r.reason)}</div>`:""}</td><td class="${pnlClass(r.pnl)}">${r.pnl>0?"+":""}${holdingNumber(r.pnl)} ${currency}</td><td class="${pnlClass(r.returnRate)}" title="${r.cost===0?"成本为零，收益率不适用":""}">${holdingPercent(r.returnRate)}</td><td>${weight==null?"—":(weight*100).toFixed(1)+"%"}${g.pricedCount<g.count?'<div class="missing-label">已估值持仓内占比</div>':""}</td><td class="status-cell">${escapeHTML(r.record?.quote_date||"—")}${r.record?.refreshing?'<div class="missing-label">缓存 · 正在更新</div>':r.record?.stale?'<div class="missing-label">旧报价 · 刷新失败</div>':""}</td><td><div class="holding-actions"><button class="secondary" data-edit-position="${escapeHTML(p.ticker)}">编辑</button><button class="secondary holding-delete" data-delete-position="${escapeHTML(p.ticker)}">删除记录</button></div></td></tr>`;
  }).join(""):'<tr class="holdings-empty"><td colspan="11">还没有持仓记录。<br>点击“添加持仓”，填写 Ticker、持仓数量、平均成本和币种。</td></tr>';
  patchRows(el("holdings-body"),holdingHTML,"holdingTicker");
  rows.forEach(r=>{
    const row=[...el("holdings-body").rows].find(row=>row.dataset.holdingTicker===r.position.ticker);
    const pending=fetchingTickers.has(r.position.ticker);
    for(let i=4;i<=9;i++){
      row.cells[i].classList.toggle("cell-fetching",pending);
      if(pending&&!r.record)row.cells[i].innerHTML='<span class="skeleton"></span>';
    }
    row.setAttribute("aria-busy",String(pending));
    const g=summaries.find(g=>g.currency===r.position.currency);
    const values=[r.position.quantity,r.position.averageCost,r.cost,r.price,r.marketValue,r.pnl,r.returnRate,r.marketValue!==null&&g.marketValue>0?r.marketValue/g.marketValue:null];
    values.forEach((value,i)=>{if(Number.isFinite(value)){row.cells[i+1].dataset.changeKey=`holding:${r.position.ticker}:${r.position.currency}:${i}`;row.cells[i+1].dataset.changeValue=value;}});
  });
  summaries.forEach((g,i)=>{
    const cells=el("holdings-summary").children[i].querySelectorAll(".summary-metrics>div");
    const pending=rows.some(r=>r.position.currency===g.currency&&fetchingTickers.has(r.position.ticker));
    el("holdings-summary").children[i].setAttribute("aria-busy",String(pending));
    cells.forEach((cell,j)=>{if(j>0){cell.classList.toggle("cell-fetching",pending);if(pending&&!g.pricedCount)cell.querySelector("strong").innerHTML='<span class="skeleton"></span>';}});
    [g.cost,g.marketValue,g.pnl,g.returnRate].forEach((value,j)=>{if(Number.isFinite(value)){cells[j].dataset.changeKey=`summary:${g.currency}:${j}`;cells[j].dataset.changeValue=value;}});
  });
  flashChangedCells();
  el("holdings-status").textContent=running||queue.length?"正在更新行情…":holdings.length?"使用最近常规时段报价估值，点击持仓行查看报价时间和来源。":"按平均成本记录持仓，支持小数数量。";
}
function openPosition(ticker=null){
  if(readOnly)return;
  editingPosition=ticker;
  const p=holdings.find(p=>p.ticker===ticker);
  el("position-form").reset();el("position-error").hidden=true;
  el("position-title").textContent=p?`编辑 ${p.ticker} 持仓`:"添加持仓";
  el("position-ticker").value=p?.ticker||"";el("position-ticker").readOnly=Boolean(p);
  el("position-quantity").value=p?.quantity??"";el("position-cost").value=p?.averageCost??"";
  el("position-currency").value=p?.currency||"USD";
  el("position-dialog").showModal();
}
let stateWrites=Promise.resolve();
function persistState(patch){
  if(readOnly)return Promise.reject(new Error("当前账户仅供查看，请切换回我的账户后修改"));
  const payload=JSON.stringify(patch);
  const write=stateWrites.then(async()=>{
    const response=await FinFeedAuth.request("/api/state",{method:"PUT",headers:{"Content-Type":"application/json"},body:payload});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||"记录保存失败");
    return data.state;
  });
  stateWrites=write.catch(()=>{});return write;
}
async function storeHoldings(next){
  await persistState({positions:next});holdings=next;
}
function cancelRecordLoads(){
  recordGeneration++;
  queue=[];fetchingTickers.clear();
  for(const controller of recordRequests)controller.abort();
}
async function changeViewedAccount(name,id){
  const version=++accountStateVersion;
  accountRequest?.abort();accountRequest=new AbortController();
  const controller=accountRequest;
  viewedUserId=id;rememberSurfaceAccount(name,id);
  if(surface===name){el("view-account").value=id;window.FinFeedDropdowns?.sync();}
  readOnly=true;document.body.classList.toggle("read-only",true);
  cancelRecordLoads();tickers=[];holdings=[];initialLoading=true;
  sortKey=null;cellValues.clear();cellFlashes.clear();feedback("");render();
  if(surface===name)window.FinFeedMotion?.enter(el(`${name}-surface`),{kind:'account'});
  if(surface===name)history.replaceState(history.state,"",accountViewURL(name,id));
  try{
    await stateWrites;
    if(version!==accountStateVersion)return false;
    const response=await FinFeedAuth.request("/api/state?user="+encodeURIComponent(id),{signal:controller.signal});
    const data=await response.json();
    if(version!==accountStateVersion)return false;
    if(!response.ok)throw new Error(data.error||"记录读取失败");
    const state=data.state||{watchlist:[],positions:[]};
    readOnly=data.readOnly;document.body.classList.toggle("read-only",readOnly);
    tickers=state.watchlist;holdings=state.positions;initialLoading=false;
    for(const ticker of trackedTickers()){if(data.quotes?.[ticker])records.set(ticker,data.quotes[ticker]);}
    feedback("");render();load(trackedTickers());
    if(surface===name)window.FinFeedMotion?.enter(el(`${name}-surface`),{kind:'account'});
    return true;
  }catch(error){
    if(version!==accountStateVersion||error.name==="AbortError")return false;
    viewedUserId=null;initialLoading=false;render();
    feedback(`账户加载失败：${error.message}`);return false;
  }
}
async function switchSurface(next){
  if(!surfaceNames.includes(next))return;
  const changed=surface!==next;
  const direction=surfaceNames.indexOf(next)>surfaceNames.indexOf(surface)?1:-1;
  surface=next;
  const viewURL=new URL(location.href);
  if(next==="home")viewURL.searchParams.delete("surface");
  else viewURL.searchParams.set("surface",next);
  history.replaceState(history.state,"",viewURL);
  if(next==="macro"&&currentUser)FinFeedMacro.open();
  if(next==="whales"&&currentUser)FinFeedWhales.open();
  for(const name of surfaceNames)el(`${name}-surface`).hidden=surface!==name;
  el("page-title").textContent={home:currentUser?"Hi "+currentUser.name:"Hi",watchlist:"关注列表",portfolio:"持仓",macro:"宏观动向",whales:"巨鲸持仓"}[surface];
  el("page-eyebrow").textContent={home:"HOME",watchlist:"MY WATCHLIST",portfolio:"MY PORTFOLIO",macro:"MACRO OUTLOOK",whales:"WHALE HOLDINGS"}[surface];
  document.querySelector(".account-browser").hidden=!["watchlist","portfolio"].includes(surface);
  if(el("whale-category-control"))el("whale-category-control").hidden=surface!=="whales"||!!FinFeedWhales.isStockAnalysis?.();
  document.querySelector(".title-actions").hidden=!["watchlist","portfolio"].includes(surface);
  document.querySelector(".source-footer").hidden=!["watchlist","portfolio"].includes(surface);
  document.querySelectorAll("[data-surface]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.surface===surface)));
  if(next==="home"&&currentUser)FinFeedHome.open(currentUser);
  render();
  if(changed)window.FinFeedMotion?.enter(el(`${next}-surface`),{kind:'surface',direction});
  if(currentUser&&surfaceAccounts[next]&&surfaceAccounts[next]!==viewedUserId){
    changeViewedAccount(next,surfaceAccounts[next]);
  }
}
function feedback(s){el("feedback").textContent=s;el("feedback").hidden=!s;}
function save(){persistState({watchlist:tickers}).catch(error=>feedback(`关注列表尚未保存：${error.message}。请重试操作。`));}
function renderOrder(){
  el("order-list").innerHTML=tickers.map((ticker,index)=>`<li draggable="true" data-order-ticker="${escapeHTML(ticker)}"><span class="drag-handle" aria-hidden="true">⠿</span><span class="order-security"><strong>${escapeHTML(ticker)}</strong><span>${escapeHTML(records.get(ticker)?.name||ticker)}</span></span><span class="order-actions"><button class="secondary" data-move="up" data-order-symbol="${escapeHTML(ticker)}" aria-label="上移 ${escapeHTML(ticker)}" ${index===0?"disabled":""}>上移</button><button class="secondary" data-move="down" data-order-symbol="${escapeHTML(ticker)}" aria-label="下移 ${escapeHTML(ticker)}" ${index===tickers.length-1?"disabled":""}>下移</button></span></li>`).join("")||'<li class="order-empty">尚未添加标的。</li>';
}
function moveTicker(ticker,targetIndex){
  if(readOnly)return false;
  const from=tickers.indexOf(ticker);
  if(from<0||targetIndex<0||targetIndex>=tickers.length||from===targetIndex)return false;
  tickers.splice(from,1);tickers.splice(targetIndex,0,ticker);
  sortKey=null;save();render();renderOrder();
  el("order-status").textContent=`${ticker} 已移至第 ${targetIndex+1} 位，顺序已保存。`;
  return true;
}
function format(metric,type){
  const n=metric?.value;if(n===null||n===undefined||!Number.isFinite(n))return "—";
  if(type==="money"){const abs=Math.abs(n);return abs>=1e12?(n/1e12).toFixed(2)+"T":abs>=1e9?(n/1e9).toFixed(2)+"B":abs>=1e6?(n/1e6).toFixed(2)+"M":n.toLocaleString("en-US",{maximumFractionDigits:0});}
  if(type==="volume")return n.toLocaleString("en-US",{maximumFractionDigits:0});
  if(type==="growth")return (n>0?"+":"")+(n*100).toFixed(1)+"%";
  if(type==="ratio")return n.toFixed(1)+"×";
  return n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
}
function shortMissing(metric){const reason=metric?.reason||"数据缺失";return reason.includes("不适用")?"不适用":reason.includes("收盘")?"待收盘":reason.includes("负值")?"基期非正":reason.includes("连续 4")?"预期不完整":"缺失";}
function sortedTickers(){
  return [...tickers].sort((a,b)=>{
    if(!sortKey)return 0;
    if(sortKey==="ticker")return (sortAsc?1:-1)*a.localeCompare(b);
    let va=records.get(a)?.metrics?.[sortKey]?.value,vb=records.get(b)?.metrics?.[sortKey]?.value;
    if(va==null)return vb==null?0:1;if(vb==null)return -1;
    const ma=records.get(a)?.metrics?.[sortKey],mb=records.get(b)?.metrics?.[sortKey];
    // Monetary comparisons stay within currency rather than pretending FX conversion.
    if(ma?.currency && mb?.currency && ma.currency!==mb.currency)return ma.currency.localeCompare(mb.currency);
    return (sortAsc?1:-1)*(va-vb);
  });
}
function render(){
  if(surface==="watchlist"){
  const chosen=selectedGroups();const cols=chosen.flatMap(g=>g.columns);
  const headerHTML=`<tr class="group-head"><th class="sticky">公司 / 基金</th>${chosen.map(g=>`<th colspan="${g.columns.length}">${g.name}</th>`).join("")}<th>时间</th></tr><tr class="column-head"><th class="sticky"><button class="th-button" data-sort="ticker">Ticker / Name<span>点击列名排序</span></button></th>${cols.map(([key,name,sub])=>`<th><button class="th-button" data-sort="${key}" ${sortKey===key?'data-sort-active="true"':""}>${name}${sortKey===key?(sortAsc?" ↑":" ↓"):""}<span>${sub}</span></button></th>`).join("")}<th>Quote Date<span style="display:block;font-weight:400">交易所当地日期</span></th></tr>`;
  if(el("table-head").innerHTML!==headerHTML)el("table-head").innerHTML=headerHTML;
  const watchHTML=tickers.length?sortedTickers().map(t=>{
    const record=records.get(t);const m=record?.metrics||{};
    return `<tr data-ticker="${escapeHTML(t)}" tabindex="0" aria-label="查看 ${escapeHTML(t)} 数据详情"><td class="sticky"><div class="security-cell"><div><span class="symbol">${escapeHTML(t)}</span><div class="security-name" title="${escapeHTML(record?.name||"等待数据")}">${escapeHTML(record?.name||"等待数据")}</div></div><button class="remove" data-remove="${escapeHTML(t)}" aria-label="移除 ${escapeHTML(t)}">×</button></div></td>${cols.map(([key,,,type])=>{
      const metric=m[key];if(!record)return `<td><span class="skeleton"></span></td>`;
      const value=format(metric,type);const color=value==="—"?"missing":type==="growth"?(metric.value>=0?"positive":"negative"):"";
      return `<td ${changeAttributes(`watch:${t}:${key}:${metric?.currency||record.currency||""}`,metric?.value)} class="${color}${fetchingTickers.has(t)?" cell-fetching":""}" title="${escapeHTML(metric?.reason||metric?.basis||"")}">${value}${value==="—"?`<span class="missing-label">${shortMissing(metric)}</span>`:metric?.currency?`<span class="currency">${escapeHTML(metric.currency)}</span>`:""}</td>`;
    }).join("")}<td class="status-cell">${escapeHTML(record?.quote_date||"—")}<div class="missing-label">${record?.partial?"行情已取得 · 正在补充数据":record?.refreshing?"缓存 · 正在更新":record?.stale?"旧快照 · 刷新失败":record?.errors?.length?"部分数据未取得":record?record.volume_complete?"完整交易日":"部分数据待确认":"读取中"}</div></td></tr>`;
  }).join(""):initialLoading?Array.from({length:8},()=>`<tr class="initial-loading"><td class="sticky"><span class="skeleton"></span></td>${cols.map(()=>`<td><span class="skeleton"></span></td>`).join("")}<td><span class="skeleton"></span></td></tr>`).join(""):`<tr class="empty-row"><td colspan="${cols.length+2}">添加股票或 ETF 的 Ticker，开始查看指标。</td></tr>`;
  patchRows(el("table-body"),watchHTML,"ticker");
  }
  const fetched=tickers.filter(t=>records.has(t)).length;
  const withPrice=tickers.filter(t=>records.get(t)?.metrics?.price?.value!=null).length;
  el("count").textContent=`${tickers.length} 个标的`;
  el("load-status").textContent=running||queue.length?`正在读取 ${fetched} / ${tickers.length} 个标的…`:`${withPrice} / ${tickers.length} 个标的取得行情 · 点击详情查看检索时间`;
  el("refresh").disabled=Boolean(running||queue.length);
  renderHoldings();
  if(surface==="watchlist")flashChangedCells();
}
async function getRecord(ticker,refresh=false,signal,onUpdate=()=>{}){
  return FinFeedCache.market(`/api/security/${encodeURIComponent(ticker)}?stream=1${refresh?"&refresh=1":""}`,onUpdate,{signal});
}
function acceptRecord(ticker,incoming){
  const saved=records.get(ticker);
  if(incoming?.metrics?.price?.value==null&&saved?.metrics?.price?.value!=null){
    records.set(ticker,{...saved,stale:true,refresh_checked_at:new Date().toISOString(),
      errors:[...new Set([...(saved.errors||[]),...(incoming.errors||[]),'行情刷新失败，保留上次成功快照'])]});
  }else records.set(ticker,incoming.partial&&saved?{...saved,...incoming,metrics:{...saved.metrics,...incoming.metrics}}:incoming);
}
function pump(){
  while(running<128&&queue.length){
    const task=queue.shift(),controller=new AbortController();running++;recordRequests.add(controller);
    getRecord(task.ticker,task.refresh,controller.signal,record=>{
      if(task.generation===recordGeneration&&trackedTickers().includes(task.ticker)){acceptRecord(task.ticker,record);scheduleRender();}
    }).then(record=>{
      if(task.generation===recordGeneration&&trackedTickers().includes(task.ticker))acceptRecord(task.ticker,record);
    }).catch(error=>{
      if(task.generation===recordGeneration&&error.name!=="AbortError"&&trackedTickers().includes(task.ticker))acceptRecord(task.ticker,{ticker:task.ticker,name:records.get(task.ticker)?.name||task.ticker,metrics:{},errors:[error.message],sources:{}});
    }).finally(()=>{
      recordRequests.delete(controller);
      if(task.generation===recordGeneration)fetchingTickers.delete(task.ticker);
      running--;scheduleRender();pump();
    });
  }
}
function load(tickersToLoad,refresh=false){tickersToLoad.forEach(t=>fetchingTickers.add(t));scheduleRender();queue.push(...tickersToLoad.map(ticker=>({ticker,refresh,generation:recordGeneration})));el("refresh").disabled=true;pump();}

function refreshWatchlist(){
  const tracked=trackedTickers();
  if(running||queue.length||!tracked.length)return;
  load(tracked,true);
}
function addTickers(text){
  if(readOnly)throw new Error("其他账户仅供查看");
  const added=[...new Set(text.toUpperCase().split(/[\s,，;；]+/).filter(Boolean))];
  if(!added.length)throw new Error("请输入 Ticker，例如 AAPL。");
  if(added.some(t=>! /^[A-Z0-9][A-Z0-9.^=-]{0,19}$/.test(t)))throw new Error("Ticker 格式不正确，可输入 AAPL、BRK-B 或 000660.KS。");
  const fresh=added.filter(t=>!tickers.includes(t));
  if(new Set([...trackedTickers(),...fresh]).size>128)throw new Error("关注列表和持仓合计最多 128 个不同标的，以控制免费源请求量。");
  const before=window.FinFeedMotion?.capture(el("watchlist").querySelectorAll("tbody tr[data-ticker]"));
  tickers.push(...fresh);save();render();load(fresh);
  if(before)window.FinFeedMotion.settle(before,el("watchlist").querySelectorAll("tbody tr[data-ticker]"));return fresh;
}
function detail(ticker,keyboard=false){
  const r=records.get(ticker);if(!r){feedback(`${ticker} 正在读取，请稍后查看。`);return;}
  el("detail-title").textContent=`${ticker} · ${r.name}`;
  const sourceNames={quote:"行情来源",financials:"利润表",balance:"资产负债表",cashflow:"现金流",estimates:"Yahoo 分析师预期",estimates_alpha:"Alpha Vantage 盈利预测",sec:"SEC 披露查询"};
  el("detail-content").innerHTML=`<div class="meta-row">最近披露财季：${escapeHTML(r.quarter_0||"未提供")}　上财季：${escapeHTML(r.quarter_1||"未提供")}<br>行情检索：${timestamp(r.fetched_at)}${r.cached?" · 缓存":""}${r.refreshing?" · 正在更新":r.stale?" · 刷新失败，保留旧快照":""}${r.refresh_checked_at?`<br>本次刷新检查：${timestamp(r.refresh_checked_at)}`:""}<br>财务与预测检索：${timestamp(r.financial_fetched_at)}${r.financial_stale?" · 日度更新失败，使用旧财务数据":""}<br>Alpha Vantage 预测检索：${timestamp(r.estimates_fetched_at)}<br>财务日度检查：${timestamp(r.financial_checked_at)}<br>报价时间：${timestamp(r.quote_at)}　交易所：${escapeHTML(r.exchange||"未提供")} (${escapeHTML(r.exchange_timezone||"未提供")})<br>报价币种：${escapeHTML(r.currency||"未提供")}　财报币种：${escapeHTML(r.financial_currency||"未提供")}　延迟：${r.delay_minutes==null?"供应商未明确提供":escapeHTML(r.delay_minutes)+" 分钟（供应商标记）"}<br>申报日：未由免费聚合源提供，请到 SEC 核对。${r.errors?.length?`<br>${escapeHTML(r.errors.join("；"))}`:""}</div><nav class="source-links">${Object.entries(r.sources||{}).map(([k,url])=>`<a href="${escapeHTML(url)}" target="_blank" rel="noreferrer">${sourceNames[k]||k}</a>`).join("")}</nav>${allColumns.map(([key,title,sub,type])=>{
    const m=r.metrics?.[key];return `<section class="metric-detail"><h3>${title}<br><span style="font-weight:400;color:#81909c">${sub}</span></h3><div><div class="value">${format(m,type)} ${escapeHTML(m?.currency||"")}</div>${m?.reason?`<p>${escapeHTML(m.reason)}</p>`:""}${m?.estimate_stale?"<p>预测更新失败，使用旧预测。</p>":""}${m?.historical_cache?`<p>包含历史缓存：Yahoo 本次未返回部分财季；缓存原始检索时间 ${timestamp(m.cache_fetched_at||m.fetched_at)}。后续修订尚待数据源核验。</p>`:""}<p>数据期：${escapeHTML(m?.period||m?.estimate_label||"未提供")}${m?.comparison_period?" · 比较期："+escapeHTML(m.comparison_period):""}</p><p>${escapeHTML(m?.basis||"未提供口径")}</p>${m?.analysts!=null?`<p>覆盖分析师：${m.analysts}</p>`:""}${m?.inputs?`<p>计算输入：${escapeHTML(JSON.stringify(m.inputs))}</p>`:""}${m?.source?`<a href="${escapeHTML(m.source)}" target="_blank" rel="noreferrer">查看来源</a>`:""}</div></section>`;
  }).join("")}`;
  el("detail-dialog").dataset.pointerOpened=String(!keyboard);
  el("detail-dialog").showModal();el("detail-title").focus({preventScroll:true});
}
el("add-form").addEventListener("submit",event=>{event.preventDefault();try{const fresh=addTickers(el("ticker-input").value);el("ticker-input").value="";feedback(fresh.length?"":"这些标的已在关注列表中。");}catch(error){feedback(error.message);}});
el("refresh").addEventListener("click",()=>{feedback("");refreshWatchlist();});
el("method-button").addEventListener("click",()=>el("method-dialog").showModal());
document.querySelectorAll("[data-surface]").forEach(b=>b.addEventListener("click",()=>switchSurface(b.dataset.surface)));
el("add-position").addEventListener("click",()=>openPosition());
el("position-ticker").addEventListener("change",()=>{if(!editingPosition){const record=records.get(el("position-ticker").value.trim().toUpperCase());if(record?.currency&&/^[A-Z]{3}$/.test(record.currency))el("position-currency").value=record.currency;}});
el("position-form").addEventListener("submit",async event=>{
  event.preventDefault();
  try{
    const p=FinFeedPositions.validate({ticker:el("position-ticker").value.trim().toUpperCase(),quantity:Number(el("position-quantity").value),averageCost:Number(el("position-cost").value),currency:el("position-currency").value.trim().toUpperCase(),updatedAt:new Date().toISOString()});
    if(!editingPosition&&holdings.some(h=>h.ticker===p.ticker))throw new Error("该 Ticker 已有持仓，请点击对应行的编辑按钮。");
    if(new Set([...trackedTickers(),p.ticker]).size>128)throw new Error("关注列表和持仓合计最多 128 个不同标的。");
    const next=editingPosition?holdings.map(h=>h.ticker===editingPosition?p:h):[...holdings,p];
    await storeHoldings(next);el("position-dialog").close();renderHoldings();
    if(!records.has(p.ticker)&&!queue.some(t=>t.ticker===p.ticker))load([p.ticker]);
  }catch(error){el("position-error").textContent=error.name==="QuotaExceededError"||error.name==="SecurityError"?"浏览器未允许保存，记录尚未保存，请保留输入并检查浏览器存储设置。":error.message;el("position-error").hidden=false;}
});
el("holdings-body").addEventListener("click",async event=>{
  const edit=event.target.closest("[data-edit-position]");if(edit){openPosition(edit.dataset.editPosition);return;}
  const remove=event.target.closest("[data-delete-position]");if(remove){
    if(readOnly)return;
    if(confirm(`删除 ${remove.dataset.deletePosition} 的持仓记录？`)){try{await storeHoldings(holdings.filter(p=>p.ticker!==remove.dataset.deletePosition));renderHoldings();}catch{alert("未能保存删除操作，记录已保留。");}}
    return;
  }
  const row=event.target.closest("[data-holding-ticker]");if(row)detail(row.dataset.holdingTicker);
});
el("holdings-body").addEventListener("keydown",event=>{if(event.target.matches("tr[data-holding-ticker]")&&(event.key==="Enter"||event.key===" ")){event.preventDefault();detail(event.target.dataset.holdingTicker,true);}});
el("order-button").addEventListener("click",()=>{sortKey=null;render();renderOrder();el("order-dialog").showModal();});
el("order-list").addEventListener("click",event=>{
  const button=event.target.closest("[data-move]");if(!button)return;
  const ticker=button.dataset.orderSymbol;
  if(moveTicker(ticker,tickers.indexOf(ticker)+(button.dataset.move==="up"?-1:1))){
    const row=[...el("order-list").children].find(row=>row.dataset.orderTicker===ticker);
    const same=row?.querySelector(`[data-move="${button.dataset.move}"]`);
    (same&&!same.disabled?same:row?.querySelector("button:not(:disabled)"))?.focus();
  }
});
let draggingTicker=null;
function clearDropMarks(){el("order-list").querySelectorAll(".drop-before,.drop-after").forEach(row=>row.classList.remove("drop-before","drop-after"));}
el("order-list").addEventListener("dragstart",event=>{const row=event.target.closest("[data-order-ticker]");if(!row)return;draggingTicker=row.dataset.orderTicker;event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("text/plain",draggingTicker);row.classList.add("dragging");});
el("order-list").addEventListener("dragover",event=>{const row=event.target.closest("[data-order-ticker]");if(!row||!draggingTicker)return;event.preventDefault();event.dataTransfer.dropEffect="move";clearDropMarks();if(row.dataset.orderTicker!==draggingTicker)row.classList.add(tickers.indexOf(draggingTicker)<tickers.indexOf(row.dataset.orderTicker)?"drop-after":"drop-before");});
el("order-list").addEventListener("drop",event=>{const row=event.target.closest("[data-order-ticker]");if(!row||!draggingTicker)return;event.preventDefault();moveTicker(draggingTicker,tickers.indexOf(row.dataset.orderTicker));draggingTicker=null;clearDropMarks();});
el("order-list").addEventListener("dragend",()=>{draggingTicker=null;clearDropMarks();el("order-list").querySelectorAll(".dragging").forEach(row=>row.classList.remove("dragging"));});
document.querySelectorAll("[data-close]").forEach(button=>button.addEventListener("click",()=>window.FinFeedMotion.close(button.closest("dialog"))));
document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{if(view===button.dataset.view)return;view=button.dataset.view;document.querySelectorAll("[data-view]").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));render();window.FinFeedMotion?.enter(el("watchlist"),{kind:"account"});}));
el("watchlist").addEventListener("click",event=>{
  const remove=event.target.closest("[data-remove]");if(remove){if(readOnly)return;const before=window.FinFeedMotion?.capture(el("watchlist").querySelectorAll("tbody tr[data-ticker]"));window.FinFeedMotion?.removeRow(remove.closest("tr"));const t=remove.dataset.remove;tickers=tickers.filter(x=>x!==t);queue=queue.filter(task=>task.ticker!==t||holdings.some(p=>p.ticker===t));save();render();if(before)window.FinFeedMotion.settle(before,el("watchlist").querySelectorAll("tbody tr[data-ticker]"));return;}
  const sort=event.target.closest("[data-sort]");if(sort){sortAsc=sortKey===sort.dataset.sort?!sortAsc:true;sortKey=sort.dataset.sort;render();return;}
  const row=event.target.closest("tr[data-ticker]");if(row)detail(row.dataset.ticker);
});
el("watchlist").addEventListener("keydown",event=>{if(event.target.matches("tr[data-ticker]")&&(event.key==="Enter"||event.key===" ")){event.preventDefault();detail(event.target.dataset.ticker,true);}});
// Use identical visible actions when the browser supports the proposed WebMCP API.
if(document.modelContext?.registerTool){
  for(const tool of [
    {name:"read_watchlist",description:"读取当前私人关注列表及已有指标快照",inputSchema:{type:"object",properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute:()=>tickers.map(t=>records.get(t)||{ticker:t,loading:true})},
    {name:"add_watchlist_tickers",description:"将 ticker 加入私人关注列表并读取指标；与页面添加操作相同",inputSchema:{type:"object",properties:{tickers:{type:"array",items:{type:"string"},minItems:1,maxItems:128}},required:["tickers"],additionalProperties:false},annotations:{readOnlyHint:false},execute:input=>{if(!input||!Array.isArray(input.tickers)||!input.tickers.length||input.tickers.some(t=>typeof t!=="string"))throw new Error("tickers 必须为非空字符串数组");return {added:addTickers(input.tickers.join(","))};}}
  ]){try{Promise.resolve(document.modelContext.registerTool(tool)).catch(()=>{});}catch{}}
}
async function initializeState(){
  if(initializeState.running)return;
  initializeState.running=true;
  switchSurface(surface);
  const main=document.querySelector("main");main.inert=false;
  readOnly=true;document.body.classList.toggle("read-only",true);
  try{
    const auth=await FinFeedAuth.initialize();
    el("startup-status").hidden=true;feedback("");
    currentUser=auth.user;main.inert=false;
    // Shared views start after authentication, without waiting for private records.
    FinFeedHome.prefetch();
    if(surface==="home")FinFeedHome.open(currentUser);
    FinFeedMacro.open();
    FinFeedWhales.open();
    el("domain-passkey").hidden=location.hostname!=="finfeed-research.vercel.app"||auth.frontendPasskeyBound;
    el("profile-name").textContent=currentUser.name;
    el("invite-controls").hidden=!auth.canInvite;
    el("admin-controls").hidden=!auth.isAdmin;
    el("account-button").hidden=false;
    const requestedUser=new URLSearchParams(location.search).get("user")||currentUser.id;
    viewedUserId=requestedUser;
    for(const name of ["watchlist","portfolio"])surfaceAccounts[name]=currentUser.id;
    if(["watchlist","portfolio"].includes(surface))rememberSurfaceAccount(surface,requestedUser);
    el("view-account").disabled=true;
    // Directory and state are independent. Render private records as soon as ready.
    const directoryTask=FinFeedAuth.request("/api/accounts").then(async response=>{
      if(!response.ok)throw new Error("账户列表读取失败");
      const directory=await response.json();
      el("view-account").innerHTML=directory.accounts.map(a=>`<option value="${escapeHTML(a.id)}">${escapeHTML(a.name)}${a.id===currentUser.id?" · 我的账户":""}</option>`).join("");
      for(const name of ["watchlist","portfolio"]){
        if(name===surface)continue;
        let saved=null;try{saved=sessionStorage.getItem(`finfeed-view:${currentUser.id}:${name}`);}catch{}
        surfaceAccounts[name]=directory.accounts.some(a=>a.id===saved)?saved:currentUser.id;
      }
      el("view-account").value=viewedUserId;
      el("view-account").disabled=false;window.FinFeedDropdowns?.sync();
    }).catch(error=>feedback(error.message+"，请稍后刷新。"));
    const stateVersion=++accountStateVersion;
    accountRequest=new AbortController();
    readOnly=true;document.body.classList.toggle("read-only",true);
    const stateTask=FinFeedAuth.request("/api/state"+(requestedUser!==currentUser.id?"?user="+encodeURIComponent(requestedUser):""),{signal:accountRequest.signal}).then(async response=>{
      const data=await response.json();
      if(stateVersion!==accountStateVersion)return;
      if(!response.ok)throw new Error(data.error||"记录读取失败");
      readOnly=data.readOnly;document.body.classList.toggle("read-only",readOnly);
      let state=data.state;
      if(!state&&readOnly)state={watchlist:[],positions:[]};
      if(!state)state=await persistState({initialize:true,watchlist:[],positions:[]});
      if(stateVersion!==accountStateVersion)return;
      initialLoading=false;tickers=state.watchlist;holdings=state.positions;
      for(const ticker of trackedTickers()){if(data.quotes?.[ticker])records.set(ticker,data.quotes[ticker]);}
      render();load(trackedTickers());
    }).catch(error=>{
      if(stateVersion!==accountStateVersion||error.name==="AbortError")return;
      readOnly=true;document.body.classList.toggle("read-only",true);
      viewedUserId=null;initialLoading=false;render();
      feedback(`记录加载失败：${error.message}。请稍后刷新页面。`);
    }).finally(()=>{main.inert=false;});
    setInterval(refreshWatchlist,60_000);
    await Promise.allSettled([directoryTask,stateTask]);
  }catch(error){
    const message=`登录检查失败：${error.message}。15 秒后自动重试。`;
    feedback(message);
    el("startup-status").textContent=message;el("startup-status").hidden=false;
    main.inert=false;
    const controls=Array.from(document.querySelectorAll("main button, main input, main select"));
    const disabled=controls.map(control=>control.disabled);
    controls.forEach(control=>{if(!control.closest(".dropdown"))control.disabled=true;});
    // Retry only startup. No intervals or market requests start before auth succeeds.
    setTimeout(()=>{
      controls.forEach((control,index)=>control.disabled=disabled[index]);
      el("startup-status").textContent="正在重新检查登录状态…";
      void initializeState();
    },15000);
  }finally{
    initializeState.running=false;
  }
}
initializeState();

// Account actions are exposed only by the cloud service.
let pendingImport=null,usersTimer=null,usersLoading=false;
function accountFeedback(message){el("account-error").textContent=message;el("account-error").hidden=!message;}
el("account-button").addEventListener("click",async()=>{
  el("account-dialog").showModal();el("account-title").focus({preventScroll:true});accountFeedback("");
  if(!el("admin-controls").hidden){
    loadAdminAccounts().catch(e=>accountFeedback(e.message));
    clearInterval(usersTimer);usersTimer=setInterval(()=>loadAdminAccounts().catch(e=>accountFeedback(e.message)),60_000);
  }

});
el("account-dialog").addEventListener("close",()=>{clearInterval(usersTimer);usersTimer=null;});
el("bind-domain-passkey").addEventListener("click",async()=>{
  const button=el("bind-domain-passkey");button.disabled=true;accountFeedback("");
  try{await FinFeedAuth.passkey(true,"","FinFeed · 新网址");el("domain-passkey").hidden=true;accountFeedback("已绑定此网址，下次可直接使用新 Passkey 登录。");}
  catch(error){accountFeedback(FinFeedAuth.message(error));if(error.message.includes("重新验证"))el("passkey-reauth").hidden=false;}
  finally{button.disabled=false;}
});
el("account-close").addEventListener("click",()=>window.FinFeedMotion.close(el("account-dialog")));
el("logout").addEventListener("click",async()=>{
  try{await FinFeedAuth.post("/api/auth/logout");location.replace("/login?manual=1");}
  catch(e){accountFeedback(FinFeedAuth.message(e));}
});
el("export-state").addEventListener("click",()=>{
  const blob=new Blob([JSON.stringify({watchlist:tickers,positions:holdings},null,2)],{type:"application/json"});
  const url=URL.createObjectURL(blob),link=document.createElement("a");
  link.href=url;link.download="finfeed-research-records.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
el("choose-import").addEventListener("click",()=>el("import-state").click());
el("import-state").addEventListener("change",async()=>{
  pendingImport=null;el("import-preview").hidden=true;
  try{
    const file=el("import-state").files[0];if(!file)return;
    if(file.size>65536)throw new Error("文件不能超过 64 KB");
    const state=JSON.parse(await file.text());
    if(!Array.isArray(state.watchlist)||!Array.isArray(state.positions)||state.watchlist.length>128||state.positions.length>128||state.watchlist.some(t=>typeof t!=="string"||!/^[A-Z0-9][A-Z0-9.^=-]{0,19}$/.test(t))||new Set(state.watchlist).size!==state.watchlist.length)throw new Error("文件中的关注列表格式不正确");
    state.positions.forEach(p=>FinFeedPositions.validate(p));
    const positionSymbols=state.positions.map(p=>p.ticker);
    if(new Set(positionSymbols).size!==positionSymbols.length||new Set([...state.watchlist,...positionSymbols]).size>128)throw new Error("标的重复或关注列表与持仓合计超过 128 个");
    pendingImport={watchlist:state.watchlist,positions:state.positions};
    el("import-summary").textContent=`将导入 ${state.watchlist.length} 个自选标的与 ${state.positions.length} 项持仓。现有云端记录会被替换，并保留历史备份。`;
    el("import-preview").hidden=false;accountFeedback("");
  }catch(e){accountFeedback(e.message||"无法读取导入文件");}
  finally{el("import-state").value="";}
});
el("confirm-import").addEventListener("click",async()=>{
  if(!pendingImport)return;el("confirm-import").disabled=true;
  try{
    const state=await persistState(pendingImport);
    initialLoading=false;tickers=state.watchlist;holdings=state.positions;pendingImport=null;
    el("import-preview").hidden=true;sortKey=null;queue=[];records.clear();cellValues.clear();cellFlashes.clear();
    render();load(trackedTickers());accountFeedback("关注列表与持仓已保存到云端。");
  }catch(e){accountFeedback(e.message);}
  finally{el("confirm-import").disabled=false;}
});

el("view-account").addEventListener("change",async()=>{
  const selected=el("view-account").value;
  await changeViewedAccount(surface,selected);
});
el("create-invite").addEventListener("click",async()=>{
  el("create-invite").disabled=true;
  try{
    const response=await FinFeedAuth.post("/api/invitations");
    el("invite-result").textContent=`${response.code}（有效至 ${new Date(response.expires*1000).toLocaleString("zh-CN")}）`;
    el("invite-result").hidden=false;
  }catch(error){accountFeedback(error.message);}
  finally{el("create-invite").disabled=false;}
});

async function loadAdminAccounts(){
  if(usersLoading)return;
  usersLoading=true;el("users-loading").hidden=false;el("admin-accounts").setAttribute("aria-busy","true");
  if(!el("admin-accounts").children.length)el("admin-accounts").innerHTML=Array.from({length:3},()=>'<div class="user-placeholder"><span class="skeleton"></span></div>').join("");
  try{
    const response=await FinFeedAuth.request("/api/admin/accounts"),data=await response.json();
    if(!response.ok)throw new Error(data.error);
    const html=data.accounts.filter(a=>!a.disabled).map(a=>`<section class="admin-account"><strong>${escapeHTML(a.name)}${a.admin?" · 管理员":" · 普通用户"}</strong>${a.admin?"":`<button class="secondary" data-admin-action="delete-account" data-admin-id="${escapeHTML(a.id)}">删除账户</button>`}</section>`).join("");
    if(el("admin-accounts").innerHTML!==html)el("admin-accounts").innerHTML=html;
  }catch(error){el("admin-accounts").querySelectorAll(".user-placeholder").forEach(node=>node.remove());throw error;}
  finally{usersLoading=false;el("users-loading").hidden=true;el("admin-accounts").setAttribute("aria-busy","false");}
}
el("admin-accounts").addEventListener("click",async event=>{
  const button=event.target.closest("[data-admin-action]");if(!button)return;
  const action=button.dataset.adminAction,id=encodeURIComponent(button.dataset.adminId),isAccount=action.endsWith("account"),restore=action.startsWith("restore");
  if(!confirm(restore?"恢复此账户或 Passkey 的访问权限？":"确认删除此账户？该账户将无法登录，其所有 Passkey 在本站失效，现有登录会话会退出。"))return;
  button.disabled=true;
  try{
    const url=`/api/admin/${isAccount?"accounts":"passkeys"}/${id}${restore?"/restore":""}`;
    const response=await FinFeedAuth.request(url,{method:restore?"POST":"DELETE",headers:{"Content-Type":"application/json"},body:"{}"});
    const data=await response.json();if(!response.ok)throw new Error(data.error);
    await loadAdminAccounts();accountFeedback(restore?"已恢复。":"已删除并撤销会话。");
  }catch(error){accountFeedback(error.message);button.disabled=false;}
});
