"use strict";
window.FinFeedNotifications=(()=>{
  const el=id=>document.getElementById(id);
  const categories=['jobs','pce','treasury','whales','news'];
  let resendUntil=0,resendTimer=null,sendingCode=false,verifying=false;
  let loadVersion=0,bindingAnimation=null;
  let saving=false,savedPreferences=null,saveAnimation=null;
  function preferencesFromForm(){
    const preferences={treasury_threshold:Number(el('notification-threshold').value)};
    categories.forEach(k=>preferences[k]=el('notification-'+k).checked);
    preferences.enabled=categories.some(k=>preferences[k]);
    return preferences;
  }
  const preferenceKey=preferences=>JSON.stringify([preferences.treasury_threshold,...categories.map(k=>Boolean(preferences.enabled&&preferences[k]))]);
  function updateSave(animate=true){
    const button=el('notification-save');
    const saved=savedPreferences!==null&&savedPreferences===preferenceKey(preferencesFromForm());
    const label=saving?'保存中…':saved?'提醒已设置':'保存提醒设置';
    button.disabled=saving||saved;
    if(button.textContent===label)return;
    button.textContent=label;
    saveAnimation?.cancel();
    if(animate&&button.animate&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
      saveAnimation=button.animate([{opacity:.45,transform:'translateY(3px)'},{opacity:1,transform:'none'}],{duration:280,easing:'cubic-bezier(.22,1,.36,1)'});
    }
  }
  categories.forEach(k=>el('notification-'+k).addEventListener('change',()=>updateSave()));
  el('notification-threshold').addEventListener('input',()=>updateSave());
  function updateResend(){
    const seconds=Math.max(0,Math.ceil((resendUntil-Date.now())/1000));
    const button=el('notification-send-code');
    button.disabled=sendingCode||seconds>0||!el('notification-email').value.trim();
    button.textContent=seconds>0?`${seconds}s`:'发送验证码';
    if(!seconds&&resendTimer){clearInterval(resendTimer);resendTimer=null;}
  }
  function updateVerify(){el('notification-verify').disabled=verifying||!el('notification-code').value.trim();}
  function feedbackMotion(id){window.FinFeedMotion?.enter(el(id));}
  el('notification-email').addEventListener('input',updateResend);
  el('notification-code').addEventListener('input',updateVerify);
  function cooldown(seconds){
    resendUntil=Date.now()+Math.max(0,Number(seconds)||0)*1000;
    if(resendTimer)clearInterval(resendTimer);
    resendTimer=setInterval(updateResend,250);updateResend();
  }
  const status=message=>{el('notification-status').textContent=message;};
  async function request(path,method='GET',body){
    const response=await FinFeedAuth.request(path,{method,...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:method==='DELETE'?{headers:{'Content-Type':'application/json'},body:'{}'}:{})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'邮件设置读取失败');return data;
  }
  function render(data){
    cooldown(data.verification_retry_after||0);
    el('notification-email-current').textContent=data.verified?'已验证邮箱：'+data.email:'尚未绑定收件邮箱';
    el('notification-email').value=data.pending_email||data.email||'';
    el('notification-binding-fields').hidden=Boolean(data.verified);
    updateResend();updateVerify();
    categories.forEach(k=>el('notification-'+k).checked=Boolean(data.preferences.enabled&&data.preferences[k]));
    el('notification-threshold').value=data.preferences.treasury_threshold;
    el('notification-unbind').hidden=!data.verified&&!data.pending_email;
    savedPreferences=null;updateSave(false);
    if(data.configured===false)status('邮件服务尚未配置。配置后即可验证邮箱并启用提醒。');
    else if((data.deliveries?.uncertain||0)+(data.deliveries?.sending||0)>0)status('部分邮件发送状态待核实，已暂停这些邮件的自动重发。');
    else if(data.scheduler_configured===false)status('后台定时调度尚未配置，网页关闭后的提醒需要完成服务器配置。');
  }
  function cancelBindingMotion(){
    bindingAnimation?.cancel();bindingAnimation=null;
    el('notification-binding-fields').inert=false;
  }
  // Animate layout height as well as opacity so the controls below move smoothly.
  async function renderBindingChange(data){
    cancelBindingMotion();
    const fields=el('notification-binding-fields'),wasHidden=fields.hidden;
    const before=fields.getBoundingClientRect().height;
    render(data);
    const hide=fields.hidden;
    if(wasHidden===hide||!fields.animate||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    fields.hidden=false;
    const after=hide?0:fields.getBoundingClientRect().height;
    fields.inert=true;
    const animation=fields.animate([
      {height:before+'px',opacity:wasHidden?0:1},
      {height:after+'px',opacity:hide?0:1}
    ],{duration:520,easing:'cubic-bezier(.4,0,.2,1)',fill:'both'});
    bindingAnimation=animation;
    await animation.finished.catch(()=>{});
    if(bindingAnimation!==animation)return;
    fields.hidden=hide;fields.inert=false;animation.cancel();bindingAnimation=null;
  }
  async function open(){
    const version=++loadVersion;
    cancelBindingMotion();status('');
    el('notification-content').hidden=true;
    el('notification-loading').hidden=false;
    el('notification-retry').hidden=true;
    try{
      const data=await request('/api/notifications');
      if(version!==loadVersion)return;
      render(data);el('notification-content').hidden=false;
      window.FinFeedMotion?.enter(el('notification-content'),{kind:'account'});
    }catch(e){
      if(version!==loadVersion)return;
      status(e.message);el('notification-retry').hidden=false;
    }finally{if(version===loadVersion)el('notification-loading').hidden=true;}
  }
  el('notification-retry').addEventListener('click',open);
  async function action(button,work){button.disabled=true;try{await work();}catch(e){status(e.message);}finally{button.disabled=false;}}
  el('notification-send-code').addEventListener('click',async()=>{
    if(sendingCode||Date.now()<resendUntil||!el('notification-email').value.trim())return;
    sendingCode=true;updateResend();
    try{
      await request('/api/notifications/email','POST',{email:el('notification-email').value.trim()});
      cooldown(60);status('验证码已发送，10 分钟内有效。');
    }catch(e){
      status(e.message);
      try{const data=await request('/api/notifications');cooldown(data.verification_retry_after||0);}catch{}
    }finally{sendingCode=false;updateResend();}
  });
  el('notification-verify').addEventListener('click',async()=>{
    if(verifying||!el('notification-code').value.trim())return;
    verifying=true;updateVerify();
    try{
      await renderBindingChange(await request('/api/notifications/verify','POST',{code:el('notification-code').value.trim()}));
      el('notification-code').value='';status('邮箱验证成功。选择提醒后点击保存设置。');feedbackMotion('notification-email-current');feedbackMotion('notification-status');
    }catch(e){status(e.message);}finally{verifying=false;updateVerify();}
  });
  el('notification-save').addEventListener('click',async()=>{
    if(saving||el('notification-save').disabled)return;
    const version=loadVersion,preferences=preferencesFromForm();
    saving=true;updateSave();
    try{
      const data=await request('/api/notifications','PUT',preferences);
      if(version!==loadVersion)return;
      // Preserve edits made while the request was in flight; only acknowledge
      // the preferences actually accepted by the server.
      savedPreferences=preferenceKey(data.preferences);
      status('提醒设置已保存。首次检查建立基线，后续新事件才发送。');feedbackMotion('notification-status');
    }catch(e){if(version===loadVersion)status(e.message);}
    finally{saving=false;updateSave();}
  });
  el('notification-unbind').addEventListener('click',event=>action(event.currentTarget,async()=>{
    await request('/api/notifications/email','DELETE');await renderBindingChange(await request('/api/notifications'));el('notification-code').value='';updateVerify();status('邮箱已解绑，待发提醒已取消。');feedbackMotion('notification-status');
  }));
  updateResend();updateVerify();
  return {open};
})();
