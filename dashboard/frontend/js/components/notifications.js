"use strict";
window.FinFeedNotifications=(()=>{
  const el=id=>document.getElementById(id);
  const categories=['jobs','pce','treasury','whales','news'];
  let resendUntil=0,resendTimer=null,sendingCode=false,verifying=false;
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
    if(data.configured===false)status('邮件服务尚未配置。配置后即可验证邮箱并启用提醒。');
    else if((data.deliveries?.uncertain||0)+(data.deliveries?.sending||0)>0)status('部分邮件发送状态待核实，已暂停这些邮件的自动重发。');
    else if(data.scheduler_configured===false)status('后台定时调度尚未配置，网页关闭后的提醒需要完成服务器配置。');
  }
  async function open(){try{render(await request('/api/notifications'));}catch(e){status(e.message);}}
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
      render(await request('/api/notifications/verify','POST',{code:el('notification-code').value.trim()}));
      el('notification-code').value='';status('邮箱验证成功。选择提醒后点击保存设置。');feedbackMotion('notification-email-current');feedbackMotion('notification-status');
    }catch(e){status(e.message);}finally{verifying=false;updateVerify();}
  });
  el('notification-save').addEventListener('click',event=>action(event.currentTarget,async()=>{
    const preferences={treasury_threshold:Number(el('notification-threshold').value)};
    categories.forEach(k=>preferences[k]=el('notification-'+k).checked);
    preferences.enabled=categories.some(k=>preferences[k]);
    render(await request('/api/notifications','PUT',preferences));status('提醒设置已保存。首次检查建立基线，后续新事件才发送。');feedbackMotion('notification-status');feedbackMotion('notification-save');
  }));
  el('notification-unbind').addEventListener('click',event=>action(event.currentTarget,async()=>{
    await request('/api/notifications/email','DELETE');render(await request('/api/notifications'));el('notification-code').value='';updateVerify();status('邮箱已解绑，待发提醒已取消。');feedbackMotion('notification-binding-fields');feedbackMotion('notification-status');
  }));
  updateResend();updateVerify();
  return {open};
})();
