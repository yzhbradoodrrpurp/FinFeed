"use strict";
// Public market snapshots only. Account records and credentials are never stored here.
const finfeedSnapshotMemory=new Map();
let finfeedSnapshotDB=null;
// IndexedDB avoids localStorage's small quota for full Watchlist explanations.
const finfeedSnapshotsReady=new Promise(resolve=>{
  if(typeof indexedDB==='undefined'){resolve();return;}
  const timer=setTimeout(resolve,1500);
  try{
    const request=indexedDB.open('finfeed-public-market',1);
    request.onupgradeneeded=()=>request.result.createObjectStore('snapshots');
    request.onerror=()=>{clearTimeout(timer);resolve();};
    request.onsuccess=()=>{
      finfeedSnapshotDB=request.result;
      const tx=finfeedSnapshotDB.transaction('snapshots','readonly');
      const cursor=tx.objectStore('snapshots').openCursor();
      cursor.onsuccess=()=>{const row=cursor.result;if(row){
        const current=finfeedSnapshotMemory.get(row.key);
        if(!current||row.value.savedAt>current.savedAt)finfeedSnapshotMemory.set(row.key,row.value);
        row.continue();
      }};
      tx.oncomplete=tx.onerror=()=>{clearTimeout(timer);resolve();};
    };
  }catch{clearTimeout(timer);resolve();}
});
window.FinFeedCache={
  ready:finfeedSnapshotsReady,
  read(key,maxAge=7*86400000){
    try{const value=finfeedSnapshotMemory.get(key)||JSON.parse(localStorage.getItem('finfeed-market:v1:'+key));
      return value&&value.data&&Number.isFinite(value.savedAt)&&Date.now()-value.savedAt>=0&&Date.now()-value.savedAt<=maxAge?value:null;
    }catch{return null;}
  },
  write(key,data){
    // Never replace a completed snapshot with an in-progress or failed response.
    if(!data||data.stale||data.partial||data.refreshing||(data.errors?.length&&data.metrics?.price?.value==null))return false;
    try{
      const storageKey='finfeed-market:v1:'+key;
      let previous=finfeedSnapshotMemory.get(key)?.data;
      if(!previous){try{previous=JSON.parse(localStorage.getItem(storageKey)||'null')?.data;}catch{}}
      const before=Date.parse(previous?.fetched_at||previous?.retrieved_at||'');
      const incoming=Date.parse(data.fetched_at||data.retrieved_at||'');
      if(Number.isFinite(before)&&Number.isFinite(incoming)&&incoming<before)return false;
      const entry={data,savedAt:Date.now()};finfeedSnapshotMemory.set(key,entry);
      const persist=()=>{if(finfeedSnapshotDB){try{
        const tx=finfeedSnapshotDB.transaction('snapshots','readwrite');
        tx.objectStore('snapshots').put(entry,key);
        tx.onerror=()=>{window.FinFeedCache.storageWarning=true;};
      }catch{window.FinFeedCache.storageWarning=true;}}};
      if(finfeedSnapshotDB)persist();else finfeedSnapshotsReady.then(persist);
      try{localStorage.setItem(storageKey,JSON.stringify(entry));}
      catch{window.FinFeedCache.storageWarning=true;}
      return true;
    }catch{return false;}
  }
};

// Locks coordinate public market fetches across tabs. No account IDs or lists.
(() => {
  const FinFeedCache=window.FinFeedCache;
  const pending=new Map();
  FinFeedCache.market=async function(url,consume,{signal,ttl=60000,staleTtl=ttl,refresh=false,validate=()=>true}={}){
    const key='request:'+url.replace(/[?&]stream=1/g,'').replace(/[?&]refresh=1/g,'');
    const controller=new AbortController();
    const abort=()=>controller.abort(signal?.reason);
    if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
    const timeout=setTimeout(()=>controller.abort(new DOMException('后台更新暂未完成，保留已取得的数据','TimeoutError')),125000);
    const run=async()=>{
      const cached=FinFeedCache.read(key,staleTtl);
      const shared=cached&&validate(cached.data)?cached:null;
      const sourceTime=shared&&(shared.data.client_checked_at||Date.parse(shared.data.retrieved_at||shared.data.fetched_at||''));
      if(!refresh&&shared&&!shared.data.cache_version&&Date.now()-shared.savedAt<ttl&&!shared.data.stale&&(!Number.isFinite(sourceTime)||Date.now()-sourceTime<ttl)){consume(shared.data);return shared.data;}
      let latest=shared?.data;
      if(latest)consume({...latest,cached:true,refreshing:true});
      const accept=value=>{
        const previousTime=Date.parse(latest?.fetched_at||latest?.retrieved_at||'');
        const incomingTime=Date.parse(value?.fetched_at||value?.retrieved_at||'');
        if(Number.isFinite(previousTime)&&Number.isFinite(incomingTime)&&incomingTime<previousTime)return;
        latest=value;consume(value);if(validate(value))FinFeedCache.write(key,value);
      };
      let pollURL=url;
      do{
      let requestURL=pollURL;
      if(shared?.data.cache_version)requestURL+=(requestURL.includes('?')?'&':'?')+'version='+encodeURIComponent(shared.data.cache_version);
      const response=await FinFeedAuth.request(requestURL,{signal:controller.signal});
      if(response.status===304){
        if(!shared)throw new Error('服务器版本响应缺少本地快照');
        const value={...shared.data,client_checked_at:Date.now(),cached:true};
        const checked=Number(response.headers?.get('X-FinFeed-Checked-At'));
        if(checked>0)value.server_checked_at=checked;
        consume(value);FinFeedCache.write(key,value);return value;
      }
      if(!response.ok)throw new Error(`读取失败 (${response.status})`);
      if(!response.headers?.get('content-type')?.includes('ndjson')){
        const data=await response.json();
        if(!data.pending){accept({...data,client_checked_at:Date.now()});return latest;}
        // A cold server cache warms independently; keep local content visible.
        latest={...(latest||{}),pending:true};
      }else{
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      try{while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});
        const lines=buffer.split('\n');buffer=lines.pop();for(const line of lines)if(line.trim())accept(JSON.parse(line));
        if(done){if(buffer.trim())accept(JSON.parse(buffer));break;}
      }}finally{reader.releaseLock();}
      }
      if(!latest?.pending)return latest;
      // A queued/running server job is not a provider failure. Rejoin that job
      // without forcing a second refresh, releasing its HTTP thread meanwhile.
      await new Promise((resolve,reject)=>{
        const abortWait=()=>{clearTimeout(timer);reject(controller.signal.reason);};
        const timer=setTimeout(()=>{controller.signal.removeEventListener('abort',abortWait);resolve();},1000);
        if(controller.signal.aborted)abortWait();else controller.signal.addEventListener('abort',abortWait,{once:true});
      });
      pollURL=url.replace(/([?&])refresh=1(&|$)/,'$1').replace(/[?&]$/,'');
      }while(!controller.signal.aborted);
      throw controller.signal.reason;
    };
    try{
      // Show old public snapshots before waiting for another tab's refresh lock.
      const preview=FinFeedCache.read(key,staleTtl);
      if(preview&&validate(preview.data))consume({...preview.data,cached:true,refreshing:true});
      const work=()=>navigator.locks?navigator.locks.request('finfeed-market:'+key,{signal:controller.signal},run):run();
      if(signal)return await work();
      if(!pending.has(key))pending.set(key,work().finally(()=>pending.delete(key)));
      const value=await pending.get(key);if(!controller.signal.aborted&&value)consume(value);return value;
    }finally{clearTimeout(timeout);signal?.removeEventListener('abort',abort);}
  };
})();
