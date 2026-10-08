"use strict";
window.FinFeedNotifications=(()=>{
  const el=id=>document.getElementById(id);
  const categories=['jobs','pce','treasury','whales','news'];
  const status=message=>{el('notification-status').textContent=message;};
  async function request(path,method='GET',body){
    const response=await FinFeedAuth.request(path,{method,...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:method==='DELETE'?{headers:{'Content-Type':'application/json'},body:'{}'}:{})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'邮件设置读取失败');return data;
  }
  function render(data){
    el('notification-email-current').textContent=data.verified?'已验证邮箱：'+data.email:'尚未绑定收件邮箱';
    el('notification-email').value=data.pending_email||data.email||'';
    el('notification-enabled').checked=data.preferences.enabled;
    categories.forEach(k=>el('notification-'+k).checked=data.preferences[k]);
    el('notification-threshold').value=data.preferences.treasury_threshold;
    el('notification-unbind').hidden=!data.verified&&!data.pending_email;
    if(data.configured===false)status('邮件服务尚未配置。配置后即可验证邮箱并启用提醒。');
    else if(data.scheduler_configured===false)status('后台定时调度尚未配置，网页关闭后的提醒需要完成服务器配置。');
  }
  async function open(){try{render(await request('/api/notifications'));}catch(e){status(e.message);}}
  async function action(button,work){button.disabled=true;try{await work();}catch(e){status(e.message);}finally{button.disabled=false;}}
  el('notification-send-code').addEventListener('click',event=>action(event.currentTarget,async()=>{
    await request('/api/notifications/email','POST',{email:el('notification-email').value.trim()});status('验证码已发送，10 分钟内有效。');
  }));
  el('notification-verify').addEventListener('click',event=>action(event.currentTarget,async()=>{
    render(await request('/api/notifications/verify','POST',{code:el('notification-code').value.trim()}));el('notification-code').value='';status('邮箱验证成功。选择提醒后点击保存设置。');
  }));
  el('notification-save').addEventListener('click',event=>action(event.currentTarget,async()=>{
    const preferences={enabled:el('notification-enabled').checked,treasury_threshold:Number(el('notification-threshold').value)};
    categories.forEach(k=>preferences[k]=el('notification-'+k).checked);
    render(await request('/api/notifications','PUT',preferences));status('提醒设置已保存。首次检查建立基线，后续新事件才发送。');
  }));
  el('notification-unbind').addEventListener('click',event=>action(event.currentTarget,async()=>{
    await request('/api/notifications/email','DELETE');await open();status('邮箱已解绑，待发提醒已取消。');
  }));
  return {open};
})();
