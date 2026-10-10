"use strict";
window.FinFeedWatchlistOrder=(()=>{
  const easing='cubic-bezier(.22,1,.36,1)';
  let cancelDrag=()=>{};
  function bind({getOrder,reorder,save,canReorder=()=>true}){
    const table=document.getElementById('watchlist'),shell=table.closest('.table-shell');
    let drag=null,hold=null,frame=0;
    const animations=new Map();
    const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const key=cell=>`${cell.closest('tr').dataset.ticker||cell.closest('tr').className}:${cell.dataset.column||cell.dataset.group}`;
    function capture(){return new Map([...table.querySelectorAll('[data-group]')].map(cell=>[key(cell),cell.getBoundingClientRect()]));}
    function shift(order){
      const before=capture();animations.forEach(animation=>animation.cancel());animations.clear();reorder(order);
      table.querySelectorAll('[data-group]').forEach(cell=>{
        const old=before.get(key(cell)),rect=cell.getBoundingClientRect();
        const dx=old?old.left-rect.left:0;
        if(!dx||reduced()||!cell.animate)return;
        const animation=cell.animate([{transform:`translateX(${dx}px)`},{transform:'none'}],{duration:380,easing});
        animations.set(key(cell),animation);
      });
    }
    function report(error){const feedback=document.getElementById('feedback');feedback.hidden=false;feedback.textContent=`指标顺序尚未保存：${error.message}。请重试。`;}
    function persist(order,previous){save(order).catch(error=>{
      if(canReorder()&&JSON.stringify(getOrder())===JSON.stringify(order))shift(previous);report(error);
    });}
    function start(){
      hold=null;if(!drag||!window.FinFeedPreferences.ready||!canReorder())return;
      drag.active=true;document.body.classList.add('group-order-dragging');
      const header=table.querySelector(`.group-head [data-group="${drag.id}"]`),bounds=header.getBoundingClientRect();
      const preview=document.createElement('div'),copy=table.cloneNode(true);
      copy.removeAttribute('id');copy.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
      preview.className='group-drag-preview';preview.setAttribute('aria-hidden','true');preview.inert=true;
      copy.querySelectorAll('tr').forEach((row,index)=>{
        [...row.cells].forEach(cell=>{if(cell.dataset.group!==drag.id)cell.remove();else{
          const original=table.rows[index].querySelector(`[data-column="${cell.dataset.column}"]`)||header;
          const width=original.getBoundingClientRect().width;
          Object.assign(cell.style,{position:'static',width:width+'px',minWidth:width+'px',maxWidth:width+'px'});
        }});
        if(index>7)row.remove();
      });
      preview.append(copy);document.body.append(preview);
      drag.preview=preview;drag.offset=drag.x-bounds.left;drag.top=bounds.top;drag.width=bounds.width;
      Object.assign(preview.style,{top:bounds.top+'px',left:'0',width:bounds.width+'px',maxHeight:Math.min(360,shell.getBoundingClientRect().height)+'px'});
      tick();
    }
    function tick(){
      if(!drag?.active)return;
      drag.preview.style.transform=`translate3d(${drag.x-drag.offset}px,${drag.y-drag.startY}px,0)`;
      const bounds=shell.getBoundingClientRect(),edge=48;
      const speed=drag.x<bounds.left+edge?-Math.min(1,(bounds.left+edge-drag.x)/edge):drag.x>bounds.right-edge?Math.min(1,(drag.x-bounds.right+edge)/edge):0;
      shell.scrollLeft+=speed*12;
      table.querySelectorAll('[data-group]').forEach(cell=>cell.classList.toggle('group-moving',cell.dataset.group===drag.id));
      const headers=[...table.querySelectorAll('.group-head [data-group]')];
      const layoutRect=cell=>{const rect=cell.getBoundingClientRect(),transform=getComputedStyle(cell).transform;return {left:rect.left-(transform==='none'?0:new DOMMatrixReadOnly(transform).m41),width:rect.width};};
      const target=headers.find(cell=>{const rect=layoutRect(cell);return drag.x>=rect.left&&drag.x<=rect.left+rect.width;});
      if(target&&target.dataset.group!==drag.id){
        const order=getOrder(),from=order.indexOf(drag.id),to=order.indexOf(target.dataset.group);
        // Use layout offset rather than an in-flight visual transform for the swap threshold.
        const rect=layoutRect(target);
        const crossed=to>from?drag.x>rect.left+rect.width/2:drag.x<rect.left+rect.width/2;
        if(crossed){order.splice(from,1);order.splice(to,0,drag.id);shift(order);}
      }
      frame=requestAnimationFrame(tick);
    }
    function finish(cancel=false){
      clearTimeout(hold);hold=null;cancelAnimationFrame(frame);frame=0;
      const previous=drag;drag=null;if(!previous)return;
      document.body.classList.remove('group-order-dragging');table.querySelectorAll('.group-moving').forEach(cell=>cell.classList.remove('group-moving'));
      if(!previous.active)return;
      if(cancel){previous.preview.remove();shift(previous.original);return;}
      const order=getOrder(),header=table.querySelector(`.group-head [data-group="${previous.id}"]`),rect=header?.getBoundingClientRect();
      const preview=previous.preview;
      if(rect&&preview.animate&&!reduced()){
        const animation=preview.animate([{transform:preview.style.transform,opacity:.96},{transform:`translate3d(${rect.left}px,0,0)`,opacity:0}],{duration:320,easing,fill:'forwards'});
        animation.finished.catch(()=>{}).then(()=>preview.remove());
      }else preview.remove();
      if(JSON.stringify(order)!==JSON.stringify(previous.original))persist(order,previous.original);
    }
    cancelDrag=()=>finish(true);
    shell.addEventListener('pointerdown',event=>{
      const handle=event.target.closest('[data-group-handle]');if(!canReorder()||!handle||handle.disabled||event.button!==0||drag)return;
      event.preventDefault();drag={id:handle.dataset.groupHandle,pointer:event.pointerId,x:event.clientX,y:event.clientY,startX:event.clientX,startY:event.clientY,original:getOrder(),active:false};
      shell.setPointerCapture?.(event.pointerId);hold=setTimeout(start,300);
    });
    shell.addEventListener('pointermove',event=>{
      if(!drag||event.pointerId!==drag.pointer)return;
      drag.x=event.clientX;drag.y=event.clientY;
      if(!drag.active&&Math.hypot(drag.x-drag.startX,drag.y-drag.startY)>8)finish(true);
      else if(drag.active)event.preventDefault();
    });
    shell.addEventListener('pointerup',()=>finish());
    shell.addEventListener('pointercancel',()=>finish(true));
    shell.addEventListener('lostpointercapture',()=>finish(true));
    window.addEventListener('blur',()=>finish(true));
    shell.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&drag){event.preventDefault();finish(true);return;}
      const handle=event.target.closest('[data-group-handle]');if(!canReorder()||!handle||handle.disabled||!['ArrowLeft','ArrowRight'].includes(event.key))return;
      event.preventDefault();const original=getOrder(),order=[...original],from=order.indexOf(handle.dataset.groupHandle);
      const visible=[...table.querySelectorAll('.group-head [data-group]')].map(cell=>cell.dataset.group),index=visible.indexOf(handle.dataset.groupHandle),neighbor=visible[index+(event.key==='ArrowLeft'?-1:1)],to=order.indexOf(neighbor);
      if(to<0)return;order.splice(from,1);order.splice(to,0,handle.dataset.groupHandle);shift(order);persist(order,original);
      table.querySelector(`[data-group-handle="${handle.dataset.groupHandle}"]`)?.focus({preventScroll:true});
    });
  }
  return {bind,cancel:()=>cancelDrag()};
})();
