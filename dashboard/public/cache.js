"use strict";
// Public market snapshots only. Account records and credentials are never stored here.
window.FinFeedCache={
  read(key,maxAge=7*86400000){
    try{const value=JSON.parse(localStorage.getItem('finfeed-market:v1:'+key));
      return value&&value.data&&Number.isFinite(value.savedAt)&&Date.now()-value.savedAt>=0&&Date.now()-value.savedAt<=maxAge?value:null;
    }catch{return null;}
  },
  write(key,data){try{localStorage.setItem('finfeed-market:v1:'+key,JSON.stringify({data,savedAt:Date.now()}));}catch{}}
};

// Locks coordinate public market fetches across tabs. No account IDs or lists.
(() => {
  const FinFeedCache=window.FinFeedCache;
  const pending=new Map();
  FinFeedCache.market=async function(url,consume,{signal,ttl=60000}={}){
    const key='request:'+url.replace(/[?&]stream=1/g,'').replace(/[?&]refresh=1/g,'');
    const controller=new AbortController();
    const abort=()=>controller.abort(signal?.reason);
    if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
    const timeout=setTimeout(()=>controller.abort(new DOMException('数据请求超过 30 秒','TimeoutError')),30000);
    const run=async()=>{
      const shared=FinFeedCache.read(key,ttl);
      const sourceTime=shared&&Date.parse(shared.data.retrieved_at||shared.data.fetched_at||'');
      if(shared&&!shared.data.stale&&(!Number.isFinite(sourceTime)||Date.now()-sourceTime<ttl)){consume(shared.data);return shared.data;}
      let latest=shared?.data;
      if(latest)consume(latest);
      const response=await FinFeedAuth.request(url,{signal:controller.signal});
      if(!response.ok)throw new Error(`读取失败 (${response.status})`);
      const accept=value=>{latest=value;consume(value);if(!value.partial&&!value.refreshing&&!value.stale)FinFeedCache.write(key,value);};
      if(!response.headers?.get('content-type')?.includes('ndjson')){accept(await response.json());return latest;}
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      try{while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});
        const lines=buffer.split('\n');buffer=lines.pop();for(const line of lines)if(line.trim())accept(JSON.parse(line));
        if(done){if(buffer.trim())accept(JSON.parse(buffer));break;}
      }}finally{reader.releaseLock();}
      return latest;
    };
    try{
      const work=()=>navigator.locks?navigator.locks.request('finfeed-market:'+key,{signal:controller.signal},run):run();
      if(signal)return await work();
      if(!pending.has(key))pending.set(key,work().finally(()=>pending.delete(key)));
      const value=await pending.get(key);if(!controller.signal.aborted&&value)consume(value);return value;
    }finally{clearTimeout(timeout);signal?.removeEventListener('abort',abort);}
  };
})();
