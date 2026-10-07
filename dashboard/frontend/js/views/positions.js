"use strict";
// Local calculations: quantities and costs are never sent to the market-data API.
(() => {
  const symbolPattern=/^[A-Z0-9][A-Z0-9.^=-]{0,19}$/;
  function validate(position){
    if(!position||!symbolPattern.test(position.ticker))throw new Error("请输入有效 Ticker，如 AAPL、VOO 或 BRK-B。");
    if(!Number.isFinite(position.quantity)||position.quantity<=0||position.quantity>1e12)throw new Error("持仓数量须大于零，可以填写小数。");
    if(!Number.isFinite(position.averageCost)||position.averageCost<0||position.averageCost>1e12)throw new Error("平均成本须为零或正数。");
    if(!/^[A-Z]{3}$/.test(position.currency))throw new Error("成本币种须为三位代码，如 USD、HKD 或 EUR。");
    return position;
  }
  function evaluate(position,record){
    const cost=position.quantity*position.averageCost;
    const value=record?.metrics?.price?.value;
    const price=Number.isFinite(value)&&value>=0?value:null;
    let reason=null;
    if(price===null)reason="行情暂不可用";
    else if(!record?.currency)reason="报价币种未提供";
    else if(record.currency!==position.currency)reason=`报价为 ${record.currency}，成本为 ${position.currency}，未作汇率转换`;
    const marketValue=reason?null:price*position.quantity;
    const pnl=marketValue===null?null:marketValue-cost;
    return {position,record,cost,price,marketValue,pnl,returnRate:pnl===null||cost<=0?null:pnl/cost,reason};
  }
  function summarize(rows){
    const groups=new Map();
    for(const row of rows){
      const currency=row.position.currency;
      if(!groups.has(currency))groups.set(currency,{currency,count:0,pricedCount:0,cost:0,pricedCost:0,marketValue:0,pnl:0,staleCount:0});
      const group=groups.get(currency);group.count++;group.cost+=row.cost;
      if(row.marketValue!==null){group.pricedCount++;group.pricedCost+=row.cost;group.marketValue+=row.marketValue;group.pnl+=row.pnl;if(row.record?.stale)group.staleCount++;}
    }
    return [...groups.values()].map(g=>({...g,marketValue:g.pricedCount?g.marketValue:null,pnl:g.pricedCount?g.pnl:null,returnRate:g.pricedCount&&g.pricedCost>0?g.pnl/g.pricedCost:null}));
  }
  globalThis.FinFeedPositions={validate,evaluate,summarize};
})();
