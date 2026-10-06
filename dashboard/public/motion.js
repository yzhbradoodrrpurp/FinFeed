"use strict";
// Only user navigation animates; background data updates never restart motion.
window.FinFeedMotion=(()=>{
  const running=new WeakMap();
  const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const easing='cubic-bezier(.22,1,.36,1)';
  function play(element,frames,duration=300,curve=easing){
    running.get(element)?.cancel();
    if(reduced()||!element.animate)return;
    const animation=element.animate(frames,{duration,easing:curve});
    running.set(element,animation);
    animation.onfinish=()=>{if(running.get(element)===animation)running.delete(element);};
    return animation;
  }
  function capture(elements){
    return new Map(Array.from(elements).filter(e=>e.getClientRects().length).map(e=>{running.get(e)?.cancel();return [e,e.getBoundingClientRect()];}).filter(([,rect])=>rect.bottom>=0&&rect.top<=window.innerHeight));
  }
  function settle(before,elements){
    Array.from(elements).filter(e=>e.getClientRects().length).forEach(element=>{
      const rect=element.getBoundingClientRect(),old=before.get(element);
      if(rect.bottom<0||rect.top>window.innerHeight)return;
      if(old){const x=old.left-rect.left,y=old.top-rect.top;if(x||y)play(element,[{transform:`translate(${x}px,${y}px)`},{transform:'none'}],360);}
      else play(element,[{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],320);
    });
  }
  const closing=new WeakSet();
  function finishClose(dialog){
    dialog.close();
    // Safari restores focus to a mouse-clicked row and can draw a keyboard ring.
    if(dialog.dataset.pointerOpened==='true'&&document.activeElement?.matches('tr[data-ticker],tr[data-holding-ticker]'))document.activeElement.blur();
  }
  function close(dialog){
    if(!dialog?.open||closing.has(dialog))return;
    if(reduced()||!dialog.animate){finishClose(dialog);return;}
    closing.add(dialog);
    // Preserve the current entrance frame even if Close is clicked mid-animation.
    const style=getComputedStyle(dialog),opacity=style.opacity,transform=style.transform;
    dialog.style.setProperty('--exit-backdrop-opacity',getComputedStyle(dialog,'::backdrop').opacity);
    dialog.classList.add('motion-closing');
    const animation=play(dialog,[{opacity,transform},{opacity:0,transform}],240,'cubic-bezier(.4,0,.2,1)');
    // Keep the final transparent frame until the native dialog leaves the top layer.
    animation.effect.updateTiming({fill:'forwards'});
    animation.finished.catch(()=>{}).then(()=>{finishClose(dialog);animation.cancel();dialog.classList.remove('motion-closing');dialog.style.removeProperty('--exit-backdrop-opacity');closing.delete(dialog);});
  }
  // A visual copy exits while the real row and saved state update immediately.
  function removeRow(row){
    if(!row||reduced())return;
    const rect=row.getBoundingClientRect();if(rect.bottom<0||rect.top>window.innerHeight)return;
    const shell=document.createElement('div'),table=document.createElement('table'),body=document.createElement('tbody'),copy=row.cloneNode(true);
    shell.className='motion-row-exit';shell.setAttribute('aria-hidden','true');shell.inert=true;
    Object.assign(shell.style,{top:rect.top+'px',left:rect.left+'px',width:rect.width+'px',height:rect.height+'px'});
    Array.from(copy.cells).forEach((cell,i)=>{const width=row.cells[i].getBoundingClientRect().width;Object.assign(cell.style,{width:width+'px',minWidth:width+'px',maxWidth:width+'px',position:'static'});});
    body.append(copy);table.append(body);shell.append(table);document.body.append(shell);
    const animation=play(shell,[{opacity:1,transform:'none'},{opacity:0,transform:'translateX(-16px)'}],180);
    if(animation)animation.finished.catch(()=>{}).then(()=>shell.remove());else shell.remove();
  }
  function enter(element,{kind='surface',direction=1}={}){
    if(!element||element.hidden||!element.animate)return;
    running.get(element)?.cancel();
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    // Direction follows navigation order; filters/accounts stay spatially neutral.
    const presets={
      surface:{transform:`translateX(${direction*24}px)`,duration:340},
      detail:{transform:`translateX(${direction*32}px)`,duration:360},
      tab:{transform:`translateX(${direction*48}px)`,duration:320},
      account:{transform:'translateY(6px)',duration:240},
      filter:{transform:'none',duration:220}
    };
    const preset=presets[kind]||presets.surface;
    const animation=element.animate([
      {opacity:0,transform:preset.transform},
      {opacity:1,transform:'translateY(0)'}
    ],{duration:preset.duration,easing:'cubic-bezier(.22,1,.36,1)'});
    running.set(element,animation);
    animation.onfinish=()=>{if(running.get(element)===animation)running.delete(element);};
  }
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('cancel',event=>{event.preventDefault();close(dialog);}));
  return {enter,capture,settle,close,removeRow};
})();
