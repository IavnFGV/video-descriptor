/* Presentation preferences only. Never owns recordings, jobs or editor state. */
(() => {
  if(new URLSearchParams(location.search).get('embedded')==='1')return;
  const KEY='video-descriptor:ui:workspace', root=document.documentElement;
  const defaults=()=>({version:1,layout:'side',panels:{video:true,transcript:true,speakers:true,translation:false,notes:false,article:false,technical:false}});
  function read(){
    const value=defaults();
    try{
      const saved=JSON.parse(localStorage.getItem(KEY));
      if(saved?.version!==1)return value;
      if(['side','stacked'].includes(saved.layout))value.layout=saved.layout;
      for(const key of Object.keys(value.panels))if(typeof saved.panels?.[key]==='boolean')value.panels[key]=saved.panels[key];
    }catch(_error){/* Unavailable storage or invalid JSON: safe in-memory defaults. */}
    return value;
  }
  let state=read(), pendingState=null, menu, content, summary, rail, tablist;
  function selectTab(value,keepTarget=false){
    // Legacy multi-panel requests fall back to the transcript tab.
    if(value==='all')value='transcript';
    if(!keepTarget)delete root.dataset.workspaceTarget;
    root.dataset.workspaceTab=value;
    if(!tablist)return;
    for(const tab of tablist.querySelectorAll('[role="tab"]')){
      const selected=tab.id==='workspace-tab-'+value;
      tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;
    }
    document.getElementById('workspace-tab-panel').setAttribute('aria-labelledby','workspace-tab-'+value);
  }
  function apply(){
    root.dataset.workspaceLayout=state.layout;
    for(const [key,value] of Object.entries(state.panels))root.setAttribute('data-view-'+key,String(value));
    if(menu){
      for(const input of menu.querySelectorAll('[data-panel]'))input.checked=state.panels[input.dataset.panel];
      for(const input of menu.querySelectorAll('[name="workspace-layout"]'))input.checked=input.value===state.layout;
    }
    const expand=document.getElementById('expand-player');
    if(expand){expand.textContent=state.layout==='stacked'?'Вернуть сбоку':'Развернуть наверх';expand.setAttribute('aria-pressed',String(state.layout==='stacked'));}
    const tabs=['notes','article'].map(kind=>document.getElementById('material-tab-'+kind)).filter(Boolean);
    const selected=tabs.find(tab=>tab.getAttribute('aria-selected')==='true');
    const focusable=selected||tabs[0];
    for(const tab of tabs)tab.tabIndex=tab===focusable?0:-1;
  }
  function save(){pendingState=null;try{localStorage.setItem(KEY,JSON.stringify(state));}catch(_error){}apply();}
  function route(params){
    const material=params.get('material'),stage=params.get('stage');
    const current=document.getElementById('material-tab-article')?.getAttribute('aria-selected')==='true'?'article':'notes';
    const target=['notes','article'].includes(material)?material:params.get('report')||stage==='notes'?current:null;
    if(target){root.dataset.workspaceTarget=target;selectTab(target,true);}
    else if(stage==='speech')selectTab('transcript');
    else selectTab('transcript');
    apply();
  }
  function reset(){state.layout='side';state.panels.video=true;state.panels.speakers=true;save();}
  // One controller on all full pages; preferences apply when a recording is opened.
  function place(){
    if(!menu||!menu.open)return;
    const rect=summary.getBoundingClientRect(),railRect=menu.parentElement.getBoundingClientRect();
    const width=content.offsetWidth||320;
    // A narrow vertical rail opens the panel beside it; a wide row opens it below.
    const vertical=menu.parentElement.classList.contains('vd-global-nav')&&railRect.width<=280&&railRect.height>railRect.width;
    let left=vertical?railRect.right+8:rect.left, top=rect.bottom+4;
    const viewportWidth=document.documentElement.clientWidth;
    if(left+width>viewportWidth-8)left=Math.max(8,viewportWidth-width-8);
    content.style.left=left+'px';
    content.style.top=Math.max(8,top)+'px';
    const height=content.offsetHeight;
    if(top+height>window.innerHeight-8)content.style.top=Math.max(8,window.innerHeight-height-8)+'px';
    content.style.visibility='visible';
  }
  function track(){window.addEventListener('resize',place);window.addEventListener('scroll',place,true);}
  function untrack(){window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);}
  function syncOpen(){
    if(menu.open){place();track();}else untrack();
  }
  // Runs in the head, before stylesheet/DOM rendering: no secondary-panel flash.
  apply();
  window.workspaceView={reset,refresh:apply,route,setPanel(key,value){if(key in state.panels&&typeof value==='boolean'){state.panels[key]=value;save();}},setLayout(value){if(['side','stacked'].includes(value)){state.layout=value;save();}}};
  function focusedWorkspace(){return document.getElementById('workspace-tab-panel')?.contains(document.activeElement)&&!tablist?.contains(document.activeElement);}
  window.addEventListener('storage',event=>{if(event.key===KEY||event.key===null){
    const next=read();if(focusedWorkspace()){pendingState=next;return;}pendingState=null;state=next;apply();
  }});
  document.addEventListener('focusout',()=>{if(pendingState)setTimeout(()=>{
    if(pendingState&&!focusedWorkspace()){state=pendingState;pendingState=null;apply();}
  },0);});
  document.addEventListener('DOMContentLoaded',()=>{
    menu=document.createElement('details');menu.id='workspace-view-menu';menu.className='workspace-view-menu';
    summary=document.createElement('summary');summary.textContent='Вид';menu.append(summary);
    content=document.createElement('div');content.className='workspace-view-content';menu.append(content);
    content.style.left='8px';content.style.top='8px';content.style.visibility='hidden';
    const panels=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent='Показывать';panels.append(legend);
    // Retired panel flags remain in v1 storage/API, but materials are always available through tabs.
    const labels={video:'Видео',speakers:'Участники'};
    for(const [key,title] of Object.entries(labels)){
      const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.dataset.panel=key;
      input.addEventListener('change',()=>window.workspaceView.setPanel(key,input.checked));
      label.append(input,document.createTextNode(title));panels.append(label);
    }
    const layouts=document.createElement('fieldset'),layoutLegend=document.createElement('legend');layoutLegend.textContent='Расположение видео';layouts.append(layoutLegend);
    for(const [value,title] of [['side','Слева от материала'],['stacked','Над материалом']]){
      const label=document.createElement('label'),input=document.createElement('input');input.type='radio';input.name='workspace-layout';input.value=value;
      input.addEventListener('change',()=>{if(input.checked)window.workspaceView.setLayout(value);});
      label.append(input,document.createTextNode(title));layouts.append(label);
    }
    const restore=document.createElement('button');restore.type='button';restore.className='vd-button vd-button--quiet';restore.textContent='Восстановить вид по умолчанию';restore.onclick=reset;
    content.append(panels,layouts,restore);
    // Common chrome adopts this entry; the old navigation is a fallback container.
    const navigation=document.querySelector('.vd-global-nav')||document.querySelector('.sidebar nav');
    if(!navigation)return;
    rail=navigation;navigation.append(menu);
    const workspace=document.querySelector('.studio-layout');
    if(workspace){
      tablist=document.getElementById('workspace-tabs');
      if(tablist){
        const tabs=[...tablist.querySelectorAll('[role="tab"]')];
        route(new URLSearchParams(location.search));
        for(const [index,tab] of tabs.entries()){
          tab.addEventListener('click',()=>{
            const value=tab.id.slice('workspace-tab-'.length);
            if(['notes','article'].includes(value)){
              if(!window.recordingUI?.selectMaterial(value))return;
              root.dataset.workspaceTarget=value;selectTab(value,true);
            }else selectTab(value);
            apply();
          });
          tab.addEventListener('keydown',event=>{
            const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:event.key==='ArrowRight'?(index+1)%tabs.length:event.key==='ArrowLeft'?(index+tabs.length-1)%tabs.length:-1;
            if(next<0)return;event.preventDefault();tabs[next].click();if(tabs[next].getAttribute('aria-selected')==='true')tabs[next].focus();
          });
        }
      }
      // Retain legacy runtime IDs without obsolete hide-all or hidden-material hints.
      const empty=document.createElement('p');empty.id='workspace-view-empty';empty.hidden=true;
      workspace.before(empty);
      const hint=document.createElement('p');hint.id='workspace-material-hint';hint.hidden=true;
      document.querySelector('.material-tabs')?.after(hint);
    }
    // The open attribute changes before the details toggle event, so the panel is placed in time.
    new MutationObserver(syncOpen).observe(menu,{attributes:true,attributeFilter:['open']});
    menu.addEventListener('keydown',event=>{if(event.key==='Escape'){menu.open=false;summary.focus();event.stopPropagation();}});
    document.addEventListener('click',event=>{if(menu.open&&!menu.contains(event.target))menu.open=false;});
    apply();
    document.dispatchEvent(new Event('workspace-view-ready'));
  });
})();
