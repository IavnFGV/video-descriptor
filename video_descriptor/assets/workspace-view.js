/* Presentation preferences only. Never owns recordings, jobs or editor state. */
(() => {
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
  let state=read(), menu, content, summary, rail;
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
    const selected=tabs.find(tab=>tab.getAttribute('aria-selected')==='true'&&state.panels[tab.id.slice(13)]);
    const focusable=selected||tabs.find(tab=>state.panels[tab.id.slice(13)]);
    for(const tab of tabs)tab.tabIndex=tab===focusable?0:-1;
  }
  function save(){try{localStorage.setItem(KEY,JSON.stringify(state));}catch(_error){}apply();}
  function reset(){state=defaults();save();}
  // The entry belongs to the left navigation rail; its panel opens beside the rail.
  function place(){
    if(!menu||!menu.open)return;
    const rect=summary.getBoundingClientRect(),railRect=rail.getBoundingClientRect();
    const width=content.offsetWidth||320;
    // A narrow vertical rail opens the panel beside it; a wide row opens it below.
    const vertical=railRect.width<=280&&railRect.height>railRect.width;
    let left=vertical?railRect.right+8:rect.left, top=rect.bottom+4;
    if(left+width>window.innerWidth-8)left=Math.max(8,window.innerWidth-width-8);
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
  window.workspaceView={reset,refresh:apply,setPanel(key,value){if(key in state.panels&&typeof value==='boolean'){state.panels[key]=value;save();}},setLayout(value){if(['side','stacked'].includes(value)){state.layout=value;save();}}};
  window.addEventListener('storage',event=>{if(event.key===KEY||event.key===null){state=read();apply();}});
  document.addEventListener('DOMContentLoaded',()=>{
    menu=document.createElement('details');menu.id='workspace-view-menu';menu.className='workspace-view-menu';
    summary=document.createElement('summary');summary.textContent='Вид';menu.append(summary);
    content=document.createElement('div');content.className='workspace-view-content';menu.append(content);
    content.style.left='8px';content.style.top='8px';content.style.visibility='hidden';
    const panels=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent='Панели записи';panels.append(legend);
    const labels={video:'Видео',transcript:'Расшифровка',speakers:'Участники',translation:'Перевод',notes:'Конспект',article:'Статья / отчёт',technical:'Технические сведения и параметры'};
    for(const [key,title] of Object.entries(labels)){
      const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.dataset.panel=key;
      input.addEventListener('change',()=>{state.panels[key]=input.checked;save();});
      label.append(input,document.createTextNode(title));panels.append(label);
    }
    const layouts=document.createElement('fieldset'),layoutLegend=document.createElement('legend');layoutLegend.textContent='Видео и расшифровка';layouts.append(layoutLegend);
    for(const [value,title] of [['side','Рядом'],['stacked','Друг под другом']]){
      const label=document.createElement('label'),input=document.createElement('input');input.type='radio';input.name='workspace-layout';input.value=value;
      input.addEventListener('change',()=>{if(input.checked)window.workspaceView.setLayout(value);});
      label.append(input,document.createTextNode(title));layouts.append(label);
    }
    const restore=document.createElement('button');restore.type='button';restore.className='vd-button vd-button--quiet';restore.textContent='Восстановить вид по умолчанию';restore.onclick=reset;
    content.append(panels,layouts,restore);
    const help=document.createElement('p');help.className='vd-help';help.textContent='Применяется к рабочему пространству записи.';content.prepend(help);
    // The entry belongs to the left navigation rail of the recording workspace.
    const navigation=document.querySelector('.vd-global-nav');
    if(!navigation)return;
    rail=navigation;navigation.append(menu);
    const workspace=document.querySelector('.studio-layout');
    if(workspace){
      const empty=document.createElement('p');empty.id='workspace-view-empty';empty.className='feedback';empty.setAttribute('role','status');
      empty.append(document.createTextNode('Видео и расшифровка скрыты. '));
      const button=document.createElement('button');button.type='button';button.className='vd-button';button.textContent='Восстановить рабочее пространство';button.onclick=reset;empty.append(button);
      workspace.before(empty);
      const hint=document.createElement('p');hint.id='workspace-material-hint';hint.className='hint';hint.textContent='Выберите открытую вкладку материала. Скрытые материалы и несохранённые правки сохранены; вернуть их можно через «Вид».';
      document.querySelector('.material-tabs').after(hint);
    }
    // The open attribute changes before the details toggle event, so the panel is placed in time.
    new MutationObserver(syncOpen).observe(menu,{attributes:true,attributeFilter:['open']});
    menu.addEventListener('keydown',event=>{if(event.key==='Escape'){menu.open=false;summary.focus();event.stopPropagation();}});
    document.addEventListener('click',event=>{if(menu.open&&!menu.contains(event.target))menu.open=false;});
    apply();
  });
})();
