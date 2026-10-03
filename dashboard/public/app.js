"use strict";
const DEFAULTS = ["AAPL", "NVDA", "MU", "AMD", "VRT", "LRCX", "VOO", "QQQM"];
const STORAGE = "finfeed.watchlist.v1";
const groups = [
  {name:"证券",view:"market",columns:[["market_cap","Market Cap","公司市值","money"]]},
  {name:"价格",view:"market",columns:[["price","Last Price","常规时段","price"],["high_52w","52W High","52 周高点","price"],["low_52w","52W Low","52 周低点","price"]]},
  {name:"每股收益",view:"market",columns:[["eps_q0","Diluted EPS","已披露 Q0","eps"],["eps_q1","Diluted EPS","已披露 Q−1","eps"],["forward_eps_q0","Forward EPS","当前预测 Q0","eps"]]},
  {name:"估值",view:"market",columns:[["pe_ltm","P/E","LTM","ratio"],["pe_ntm","P/E","NTM","ratio"]]},
  {name:"成交参与",view:"market",columns:[["avg_volume_10","Avg Volume","此前 10 交易日","volume"],["relative_volume_10","Volume / Avg","比较日 / 10 日","ratio"]]},
  {name:"营收",view:"financial",columns:[["revenue_q0","Total Revenue","Q0 · 单季","money"],["revenue_yoy_q0","Revenue Growth","Q0 · 同比","growth"],["revenue_yoy_q1","Revenue Growth","Q−1 · 同比","growth"]]},
  {name:"债务",view:"financial",columns:[["debt_q0","Total Debt","Q0 · 季末","money"],["debt_yoy_q0","Debt Growth","Q0 · 同比","growth"],["debt_yoy_q1","Debt Growth","Q−1 · 同比","growth"]]},
  {name:"自由现金流",view:"financial",columns:[["fcf_q0","Free Cash Flow","Q0 · 单季","money"],["fcf_yoy_q0","FCF Growth","Q0 · 同比","growth"],["fcf_yoy_q1","FCF Growth","Q−1 · 同比","growth"]]}
];
const allColumns=groups.flatMap(g=>g.columns);
const records=new Map();
let tickers, view="all",sortKey=null,sortAsc=true,running=0, queue=[];
try{tickers=JSON.parse(localStorage.getItem(STORAGE)) || DEFAULTS; if(!Array.isArray(tickers))tickers=DEFAULTS;}catch{tickers=DEFAULTS;}
tickers=[...new Set(tickers.filter(t=>typeof t==="string" && /^[A-Z0-9][A-Z0-9.^=-]{0,19}$/.test(t)))].slice(0,40);
const el=id=>document.getElementById(id);
const escapeHTML=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const timestamp=s=>s?new Date(s).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai",hour12:false})+" 北京时间":"未提供";
function selectedGroups(){return groups.filter(g=>view==="all"||g.view===view||g.view==="both");}
function feedback(s){el("feedback").textContent=s;el("feedback").hidden=!s;}
function save(){try{localStorage.setItem(STORAGE,JSON.stringify(tickers));}catch{feedback("浏览器未允许保存，自选股仅在本次打开期间保留。");}}
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
  const chosen=selectedGroups();const cols=chosen.flatMap(g=>g.columns);
  el("table-head").innerHTML=`<tr class="group-head"><th class="sticky">公司 / 基金</th>${chosen.map(g=>`<th colspan="${g.columns.length}">${g.name}</th>`).join("")}<th>时间</th></tr><tr class="column-head"><th class="sticky"><button class="th-button" data-sort="ticker">Ticker / Name<span>点击列名排序</span></button></th>${cols.map(([key,name,sub])=>`<th><button class="th-button" data-sort="${key}" ${sortKey===key?'data-sort-active="true"':""}>${name}${sortKey===key?(sortAsc?" ↑":" ↓"):""}<span>${sub}</span></button></th>`).join("")}<th>Quote Date<span style="display:block;font-weight:400">交易所当地日期</span></th></tr>`;
  el("table-body").innerHTML=tickers.length?sortedTickers().map(t=>{
    const record=records.get(t);const m=record?.metrics||{};
    return `<tr data-ticker="${escapeHTML(t)}" tabindex="0" aria-label="查看 ${escapeHTML(t)} 数据详情"><td class="sticky"><div class="security-cell"><div><span class="symbol">${escapeHTML(t)}</span><div class="security-name" title="${escapeHTML(record?.name||"等待数据")}">${escapeHTML(record?.name||"等待数据")}</div></div><button class="remove" data-remove="${escapeHTML(t)}" aria-label="移除 ${escapeHTML(t)}">×</button></div></td>${cols.map(([key,,,type])=>{
      const metric=m[key];if(!record)return `<td><span class="skeleton"></span></td>`;
      const value=format(metric,type);const color=value==="—"?"missing":type==="growth"?(metric.value>=0?"positive":"negative"):"";
      return `<td class="${color}" title="${escapeHTML(metric?.reason||metric?.basis||"")}">${value}${value==="—"?`<span class="missing-label">${shortMissing(metric)}</span>`:metric?.currency?`<span class="currency">${escapeHTML(metric.currency)}</span>`:""}</td>`;
    }).join("")}<td class="status-cell">${escapeHTML(record?.quote_date||"—")}<div class="missing-label">${record?.stale?"旧快照 · 刷新失败":record?.errors?.length?"部分数据未取得":record?record.volume_complete?"完整交易日":"部分数据待确认":"读取中"}</div></td></tr>`;
  }).join(""):`<tr class="empty-row"><td colspan="${cols.length+2}">添加股票或 ETF 的 Ticker，开始查看指标。</td></tr>`;
  const fetched=tickers.filter(t=>records.has(t)).length;
  const withPrice=tickers.filter(t=>records.get(t)?.metrics?.price?.value!=null).length;
  el("count").textContent=`${tickers.length} 个标的`;
  el("load-status").textContent=running||queue.length?`正在读取 ${fetched} / ${tickers.length} 个标的…`:`${withPrice} / ${tickers.length} 个标的取得行情 · 点击详情查看检索时间`;
  el("refresh").disabled=Boolean(running||queue.length);
}
async function getRecord(ticker,refresh=false){
  const response=await fetch(`/api/security/${encodeURIComponent(ticker)}${refresh?"?refresh=1":""}`);
  if(!response.ok)throw new Error(`读取失败 (${response.status})`);
  return response.json();
}
function pump(){
  while(running<2&&queue.length){const task=queue.shift();running++;render();getRecord(task.ticker,task.refresh).then(record=>{if(tickers.includes(task.ticker))records.set(task.ticker,record);}).catch(error=>{if(tickers.includes(task.ticker)){const previous=records.get(task.ticker);records.set(task.ticker,previous?{...previous,stale:true,refresh_error:error.message}:{ticker:task.ticker,name:task.ticker,metrics:{},errors:[error.message],sources:{}});}}).finally(()=>{running--;render();pump();});}
}
function load(tickersToLoad,refresh=false){queue.push(...tickersToLoad.map(ticker=>({ticker,refresh})));pump();}
function refreshWatchlist(){
  if(running||queue.length||!tickers.length)return;
  load([...tickers],true);
}
function addTickers(text){
  const added=[...new Set(text.toUpperCase().split(/[\s,，;；]+/).filter(Boolean))];
  if(!added.length)throw new Error("请输入 Ticker，例如 AAPL。");
  if(added.some(t=>! /^[A-Z0-9][A-Z0-9.^=-]{0,19}$/.test(t)))throw new Error("Ticker 格式不正确，可输入 AAPL、BRK-B 或 000660.KS。");
  const fresh=added.filter(t=>!tickers.includes(t));
  if(tickers.length+fresh.length>40)throw new Error("当前版本最多保存 40 个标的，以控制免费源请求量。");
  tickers.push(...fresh);save();render();load(fresh);return fresh;
}
function detail(ticker){
  const r=records.get(ticker);if(!r){feedback(`${ticker} 正在读取，请稍后查看。`);return;}
  el("detail-title").textContent=`${ticker} · ${r.name}`;
  const sourceNames={quote:"行情来源",financials:"利润表",balance:"资产负债表",cashflow:"现金流",estimates:"分析师预期",sec:"SEC 披露查询"};
  el("detail-content").innerHTML=`<div class="meta-row">最近披露财季：${escapeHTML(r.quarter_0||"未提供")}　上财季：${escapeHTML(r.quarter_1||"未提供")}<br>检索时间：${timestamp(r.fetched_at)}${r.cached?" · 本机缓存":""}${r.stale?" · 刷新失败，保留旧快照":""}<br>报价时间：${timestamp(r.quote_at)}　交易所：${escapeHTML(r.exchange||"未提供")} (${escapeHTML(r.exchange_timezone||"未提供")})<br>报价币种：${escapeHTML(r.currency||"未提供")}　财报币种：${escapeHTML(r.financial_currency||"未提供")}　延迟：${r.delay_minutes==null?"供应商未明确提供":escapeHTML(r.delay_minutes)+" 分钟（供应商标记）"}<br>申报日：未由免费聚合源提供，请到 SEC 核对。${r.errors?.length?`<br>${escapeHTML(r.errors.join("；"))}`:""}</div><nav class="source-links">${Object.entries(r.sources||{}).map(([k,url])=>`<a href="${escapeHTML(url)}" target="_blank" rel="noreferrer">${sourceNames[k]||k}</a>`).join("")}</nav>${allColumns.map(([key,title,sub,type])=>{
    const m=r.metrics?.[key];return `<section class="metric-detail"><h3>${title}<br><span style="font-weight:400;color:#81909c">${sub}</span></h3><div><div class="value">${format(m,type)} ${escapeHTML(m?.currency||"")}</div>${m?.reason?`<p>${escapeHTML(m.reason)}</p>`:""}<p>数据期：${escapeHTML(m?.period||m?.estimate_label||"未提供")}${m?.comparison_period?" · 比较期："+escapeHTML(m.comparison_period):""}</p><p>${escapeHTML(m?.basis||"未提供口径")}</p>${m?.analysts!=null?`<p>覆盖分析师：${m.analysts}</p>`:""}${m?.inputs?`<p>计算输入：${escapeHTML(JSON.stringify(m.inputs))}</p>`:""}${m?.source?`<a href="${escapeHTML(m.source)}" target="_blank" rel="noreferrer">查看来源</a>`:""}</div></section>`;
  }).join("")}`;
  el("detail-dialog").showModal();
}
el("add-form").addEventListener("submit",event=>{event.preventDefault();try{const fresh=addTickers(el("ticker-input").value);el("ticker-input").value="";feedback(fresh.length?"":"这些标的已在自选股中。");}catch(error){feedback(error.message);}});
el("refresh").addEventListener("click",()=>{feedback("");refreshWatchlist();});
el("method-button").addEventListener("click",()=>el("method-dialog").showModal());
document.querySelectorAll("[data-close]").forEach(button=>button.addEventListener("click",()=>button.closest("dialog").close()));
document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{view=button.dataset.view;document.querySelectorAll("[data-view]").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));render();}));
el("watchlist").addEventListener("click",event=>{
  const remove=event.target.closest("[data-remove]");if(remove){const t=remove.dataset.remove;tickers=tickers.filter(x=>x!==t);queue=queue.filter(task=>task.ticker!==t);save();render();return;}
  const sort=event.target.closest("[data-sort]");if(sort){sortAsc=sortKey===sort.dataset.sort?!sortAsc:true;sortKey=sort.dataset.sort;render();return;}
  const row=event.target.closest("tr[data-ticker]");if(row)detail(row.dataset.ticker);
});
el("watchlist").addEventListener("keydown",event=>{if(event.target.matches("tr[data-ticker]")&&(event.key==="Enter"||event.key===" ")){event.preventDefault();detail(event.target.dataset.ticker);}});
// Use identical visible actions when the browser supports the proposed WebMCP API.
if(document.modelContext?.registerTool){
  for(const tool of [
    {name:"read_watchlist",description:"读取当前本机自选股及已有指标快照",inputSchema:{type:"object",properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute:()=>tickers.map(t=>records.get(t)||{ticker:t,loading:true})},
    {name:"add_watchlist_tickers",description:"将 ticker 加入本机自选股并读取指标；与页面添加操作相同",inputSchema:{type:"object",properties:{tickers:{type:"array",items:{type:"string"},minItems:1,maxItems:40}},required:["tickers"],additionalProperties:false},annotations:{readOnlyHint:false},execute:input=>{if(!input||!Array.isArray(input.tickers)||!input.tickers.length||input.tickers.some(t=>typeof t!=="string"))throw new Error("tickers 必须为非空字符串数组");return {added:addTickers(input.tickers.join(","))};}}
  ]){try{Promise.resolve(document.modelContext.registerTool(tool)).catch(()=>{});}catch{}}
}
render();load(tickers);
setInterval(refreshWatchlist,60_000);
