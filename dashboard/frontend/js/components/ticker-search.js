"use strict";
// One lazy static download per page; keystrokes never request market data.
(()=>{
  const input=document.getElementById('ticker-input'),list=document.getElementById('ticker-suggestions');
  let directory=null,loading=null,items=[],active=-1,composing=false;
  const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function close(){list.hidden=true;active=-1;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');}
  function choose(index){if(!items[index])return;input.value=items[index][0];close();input.focus({preventScroll:true});}
  async function render(){
    const query=input.value.trim().toUpperCase();
    if(!query||/[\s,，;；]/.test(query)||input.disabled){close();return;}
    if(!directory){
      loading ||= fetch('/symbol-directory.json',{cache:'force-cache'}).then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>directory=data.securities).catch(()=>{loading=null;return null;});
      await loading;
      if(!directory||input.value.trim().toUpperCase()!==query||document.activeElement!==input)return;
    }
    const rank=row=>row[0]===query?0:row[0].startsWith(query)?1:2;
    items=directory.filter(row=>row[0].startsWith(query)||row[1].toUpperCase().includes(query)).sort((a,b)=>rank(a)-rank(b)||a[0].localeCompare(b[0])).slice(0,8);
    active=-1;input.removeAttribute('aria-activedescendant');
    list.innerHTML=items.map((row,i)=>`<button type="button" role="option" aria-selected="false" tabindex="-1" id="ticker-option-${i}" data-index="${i}"><strong>${escape(row[0])}${row[2]?' · ETF':''}</strong><span>${escape(row[1])}</span></button>`).join('');
    list.hidden=!items.length;input.setAttribute('aria-expanded',String(!!items.length));
  }
  input.addEventListener('input',()=>{if(!composing)void render();});
  input.addEventListener('focus',()=>{void render();});
  input.addEventListener('compositionstart',()=>{composing=true;});
  input.addEventListener('compositionend',()=>{composing=false;void render();});
  input.addEventListener('keydown',event=>{
    if(event.isComposing)return;
    if(event.key==='Escape'){close();return;}
    if(list.hidden)return;
    if(event.key==='Enter'&&active>=0){event.preventDefault();choose(active);return;}
    if(!['ArrowDown','ArrowUp'].includes(event.key))return;
    event.preventDefault();active=(active+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;
    list.querySelectorAll('button').forEach((button,i)=>button.setAttribute('aria-selected',String(i===active)));
    input.setAttribute('aria-activedescendant','ticker-option-'+active);
    document.getElementById('ticker-option-'+active).scrollIntoView({block:'nearest'});
  });
  list.addEventListener('pointerdown',event=>{if(event.button===0)event.preventDefault();});
  list.addEventListener('click',event=>{const button=event.target.closest('[data-index]');if(button)choose(Number(button.dataset.index));});
  input.addEventListener('blur',close);
  document.getElementById('add-form').addEventListener('submit',close);
})();
