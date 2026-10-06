"use strict";
// Keep native select values/change events as the shared state; render a stable menu.
window.FinFeedDropdowns = (() => {
  const widgets=[];
  function enhance(select){
    if(!select)return;
    select.classList.add('dropdown-source');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
    const root=document.createElement('div');root.className='dropdown';
    const trigger=document.createElement('button');trigger.type='button';trigger.className='dropdown-trigger';trigger.id=select.id+'-trigger';
    document.querySelector('label[for="'+select.id+'"]')?.setAttribute('for',trigger.id);
    trigger.setAttribute('aria-label',select.getAttribute('aria-label'));trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
    const label=document.createElement('span'),arrow=document.createElement('span');arrow.className='dropdown-arrow';arrow.setAttribute('aria-hidden','true');trigger.append(label,arrow);
    const menu=document.createElement('div');menu.className='dropdown-menu';menu.id=select.id+'-menu';menu.hidden=true;menu.setAttribute('role','listbox');menu.setAttribute('aria-label',select.getAttribute('aria-label'));trigger.setAttribute('aria-controls',menu.id);
    root.append(trigger,menu);select.after(root);
    let signature='';
    function close(){menu.hidden=true;trigger.setAttribute('aria-expanded','false');}
    function sync(){
      const options=Array.from(select.options);
      label.textContent=options.find(option=>option.value===select.value)?.textContent||'正在读取账户…';
      const next=JSON.stringify(options.map(option=>[option.value,option.textContent,option.disabled]));
      if(next!==signature){
        const focusedValue=document.activeElement?.dataset?.value;
        signature=next;menu.replaceChildren();
        options.forEach(option=>{
          const button=document.createElement('button');button.type='button';button.className='dropdown-option';button.dataset.value=option.value;button.textContent=option.textContent;button.disabled=option.disabled;button.setAttribute('role','option');
          // Safari can blur a focused option to the page before dispatching click.
          // Keep focus inside the menu until the selection has been committed.
          button.addEventListener('pointerdown',event=>{if(event.button===0)event.preventDefault();});
          button.addEventListener('click',()=>{select.value=option.value;sync();close();trigger.focus();select.dispatchEvent(new Event('change',{bubbles:true}));});menu.append(button);
        });
        if(!options.length){const empty=document.createElement('p');empty.className='dropdown-empty';empty.textContent='正在读取账户…';menu.append(empty);}
        if(!menu.hidden&&focusedValue)Array.from(menu.children).find(item=>item.dataset.value===focusedValue)?.focus();
      }
      menu.querySelectorAll('[role="option"]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.value===select.value)));
    }
    function open(){widgets.forEach(widget=>widget.close());sync();menu.hidden=false;trigger.setAttribute('aria-expanded','true');(menu.querySelector('[aria-selected="true"]')||menu.querySelector('button'))?.focus();}
    trigger.addEventListener('click',()=>menu.hidden?open():close());
    trigger.addEventListener('keydown',event=>{if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();open();}});
    root.addEventListener('keydown',event=>{
      if(event.key==='Tab')setTimeout(()=>{if(!root.contains(document.activeElement))close();},0);
      if(event.key==='Escape'){event.preventDefault();close();trigger.focus();}
      if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&!menu.hidden){
        event.preventDefault();const items=Array.from(menu.querySelectorAll('button:not(:disabled)'));if(!items.length)return;
        const index=items.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;items[next].focus();
      }
    });
    root.addEventListener('focusout',event=>{if(event.relatedTarget&&!root.contains(event.relatedTarget))close();});
    document.addEventListener('pointerdown',event=>{if(!root.contains(event.target))close();});
    select.addEventListener('change',sync);
    new MutationObserver(sync).observe(select,{childList:true,subtree:true,characterData:true,attributes:true});
    const widget={sync,close};widgets.push(widget);sync();return widget;
  }
  return {enhance,sync:()=>widgets.forEach(widget=>widget.sync())};
})();
FinFeedDropdowns.enhance(document.getElementById('view-account'));
FinFeedDropdowns.enhance(document.getElementById('whale-category-select'));
