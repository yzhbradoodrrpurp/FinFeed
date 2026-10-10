"use strict";
window.FinFeedPreferences=(()=>{
  let ready=false,loading=null,values={},writes=Promise.resolve(),pending=0,version=0;
  const listeners=new Set();
  const copy=value=>JSON.parse(JSON.stringify(value));
  function emit(){listeners.forEach(listener=>listener(copy(values),ready));}
  async function request(method,patch){
    const response=await FinFeedAuth.request('/api/preferences',{method,...(patch?{headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)}:{})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'展示顺序保存失败');return data.preferences;
  }
  function initialize(){
    if(loading)return loading;
    loading=request('GET').then(data=>{values=data;ready=true;emit();}).catch(error=>{
      loading=null;ready=false;emit();
      const feedback=document.getElementById('feedback');feedback.hidden=false;feedback.textContent=`展示顺序读取失败：${error.message}。请刷新重试。`;
    });
    return loading;
  }
  function save(patch){
    if(!ready)return Promise.reject(new Error('展示设置尚未读取完成'));
    const snapshot=copy(patch);
    pending++;version++;
    const work=writes.then(()=>request('PUT',snapshot)).then(data=>{values={...values,...snapshot};return data;}).finally(()=>pending--);
    // Do not replace newer optimistic changes with an older write response.
    writes=work.catch(()=>{});return work;
  }
  async function refresh(){
    if(!ready||pending)return;
    const started=version;try{const data=await request('GET');if(!pending&&started===version){values=data;emit();}}catch{}
  }
  window.addEventListener('focus',refresh);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  return {initialize,save,get ready(){return ready;},subscribe(listener){listeners.add(listener);listener(copy(values),ready);}};
})();
