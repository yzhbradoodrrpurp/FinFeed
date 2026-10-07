"use strict";
// Ordinary share quantities only; options and principal amounts are not stocks.
window.FinFeedWhaleAnalysis=(()=>{
  const stock=row=>!row.put_call&&String(row.amount_type).toUpperCase()==='SH';
  const key=row=>String(row.cusip||'').trim().toUpperCase();
  function securities(states){
    const result=new Map();
    for(const data of states.values())for(const row of [...(data.holdings||[]),...(data.previous?.holdings||[])]){
      if(stock(row)&&key(row)&&!result.has(key(row)))result.set(key(row),{...row,cusip:key(row)});
    }
    return [...result.values()].sort((a,b)=>a.name.localeCompare(b.name));
  }
  function previousQuarter(date){
    if(!/^\d{4}-(03-31|06-30|09-30|12-31)$/.test(date||''))return null;
    const year=Number(date.slice(0,4)),ends=['03-31','06-30','09-30','12-31'],index=ends.indexOf(date.slice(5));
    return index===0?`${year-1}-12-31`:`${year}-${ends[index-1]}`;
  }
  function topHeld(states,limit=12){
    const valid=[...states.values()].filter(data=>data?.totals_verified&&previousQuarter(data.report_date)&&Array.isArray(data.holdings));
    const report_date=valid.map(data=>data.report_date).sort().at(-1)||null;
    const reports=valid.filter(data=>data.report_date===report_date),result=new Map();
    for(const data of reports){
      const seen=new Set();
      for(const row of data.holdings){
        const cusip=key(row);
        if(!stock(row)||!cusip||!Number.isFinite(Number(row.shares))||Number(row.shares)<=0||seen.has(cusip))continue;
        seen.add(cusip);
        const item=result.get(cusip)||{...row,cusip,count:0};
        item.count++;result.set(cusip,item);
      }
    }
    return {report_date,covered:reports.length,rows:[...result.values()].sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name)||a.cusip.localeCompare(b.cusip)).slice(0,limit)};
  }
  function position(rows,cusip){
    return rows.filter(row=>stock(row)&&key(row)===cusip).reduce((total,row)=>({shares:total.shares+Number(row.shares),value:total.value+Number(row.value),weight:total.weight+Number(row.weight)}),{shares:0,value:0,weight:0});
  }
  function analyze(states,funds,cusip){
    const groups={increase:[],decrease:[],unchanged:[],new:[],exit:[]},unavailable=[],absent=[];
    for(const [fund,name] of Object.entries(funds)){
      const data=states.get(fund),previous=data?.previous;
      if(!data?.totals_verified||!previous?.totals_verified||!Array.isArray(data.holdings)||!Array.isArray(previous.holdings)||previous.report_date!==previousQuarter(data.report_date)){
        unavailable.push({fund,name});continue;
      }
      const current=position(data.holdings,cusip),old=position(previous.holdings,cusip);
      if(!Number.isFinite(current.shares)||!Number.isFinite(old.shares)){unavailable.push({fund,name});continue;}
      if(!current.shares&&!old.shares){absent.push({fund,name});continue;}
      const delta=current.shares-old.shares;
      const status=!old.shares?'new':!current.shares?'exit':delta>0?'increase':delta<0?'decrease':'unchanged';
      groups[status].push({fund,name,current,previous:old,delta,percent:old.shares?delta/old.shares*100:null,report_date:data.report_date,previous_date:previous.report_date,filed_at:data.filed_at,previous_filed_at:previous.filed_at,stale:!!data.stale,refreshing:!!data.refreshing,sources:[...(data.sources||[]),...(previous.sources||[])]});
    }
    return {groups,unavailable,absent};
  }
  return {securities,analyze,topHeld};
})();
