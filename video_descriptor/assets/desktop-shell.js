/* Shared application commands and chrome; never owns jobs, media or editors. */
(() => {
  if(new URLSearchParams(location.search).get('embedded')==='1')return;
  if(window.desktopShellEnvironment)return;
  // One health snapshot for the shell and its existing page controllers.
  const listeners=new Set();
  let environment={kind:'pending',health:null}, request=null, confirmedKind=null;
  function notify(listener,value){try{listener(value);}catch(error){console.error('Desktop shell environment listener failed',error);}}
  function publish(value){
    environment=value;
    if(['windows','web','offline'].includes(value.kind))confirmedKind=value.kind;
    for(const listener of listeners)notify(listener,value);
    return value;
  }
  function readEnvironment(retry=false){
    if(request)return request;
    if(!retry&&environment.kind!=='pending')return Promise.resolve(environment);
    if(location.protocol==='file:')return Promise.resolve(publish({kind:'offline',health:null}));
    publish({kind:'pending',health:null});
    const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),10000);
    request=fetch('/health',{cache:'no-store',signal:controller.signal}).then(response=>{
      if(!response.ok)throw Error('health unavailable');
      return response.json();
    }).then(health=>{
      if(health?.app==='video-descriptor-windows'&&typeof health.instance==='string'&&health.instance)
        return publish({kind:'windows',health});
      if(health?.status==='ok'&&!health.app)return publish({kind:'web',health});
      throw Error('unknown health response');
    }).catch(()=>publish({kind:'unavailable',health:null})).finally(()=>{clearTimeout(timeout);request=null;});
    return request;
  }
  const shellEnvironment={read:readEnvironment,subscribe(listener){listeners.add(listener);notify(listener,environment);return()=>listeners.delete(listener);}};
  window.desktopShellEnvironment=shellEnvironment;
  readEnvironment();
  const menuDescriptions={file:'Файл',view:'Вид',tools:'Инструменты',help:'Справка'};
  const routeMaps={
    windows:{new:'/#new',records:'/#records',settings:'/#settings',diagnostics:'/#diagnostics',ollama:'/help/ollama',lmstudio:'/help/lmstudio'},
    web:{new:'/create',records:'/output/'},
    offline:{}
  };
  const route=command=>(routeMaps[confirmedKind]||routeMaps.web)[command];
  let mounted=false;
  function start(){
    if(mounted)return;
    const $=id=>document.getElementById(id), localNavigation=document.querySelector('.sidebar nav');
    const navigation=localNavigation||document.querySelector('.vd-global-nav');
    if(!navigation)return;
    mounted=true;
    document.body.classList.add('vd-desktop');
    const brand=document.querySelector('.brand>span:last-child');if(brand)brand.textContent='Video Descriptor';
    const existingHeader=document.querySelector('.topbar');
    const header=existingHeader||document.createElement('header');
    header.classList.add('desktop-header');
    if(!existingHeader){
      const skip=document.querySelector('body>.vd-skip,body>.skip');
      if(skip)skip.after(header);else document.body.prepend(header);
    }
    // Retain legacy IDs for their existing handlers, but no second navigation surface.
    if($('sidebar-toggle'))$('sidebar-toggle').hidden=true;
    const bar=document.createElement('nav');bar.className='desktop-menu-bar';bar.setAttribute('aria-label','Команды приложения');header.append(bar);
    function menu(id,title){
      const details=document.createElement('details'),summary=document.createElement('summary'),body=document.createElement('div');
      details.id=id;details.className='desktop-menu';summary.textContent=title;body.className='desktop-menu-content';details.append(summary,body);bar.append(details);return {details,body};
    }
    function link(body,title,key,id){
      const a=id&&$(id)||document.createElement('a');a.textContent=title;
      if(id)a.id=id;
      a.dataset.desktopCommand=key;a.dataset.desktopNavigation='';
      body.append(a);return a;
    }
    function command(body,title,run){const b=document.createElement('button');b.type='button';b.className='vd-button vd-button--quiet vd-button--compact';b.textContent=title;b.onclick=run;body.append(b);return b;}
    const file=menu('desktop-file-menu',menuDescriptions.file);
    link(file.body,'Новая запись…','new');
    link(file.body,'Записи','records','records-open');
    const view=menu('desktop-view-menu',menuDescriptions.view);
    view.details.hidden=true;
    const tools=menu('desktop-tools-menu',menuDescriptions.tools);
    link(tools.body,'Настройки AI и подключения…','settings','setup-open');
    link(tools.body,'Диагностика…','diagnostics','diagnostics-open');
    // The old recording-only dialog omits Ollama. All entry points use the shared form.
    if($('open-connections'))$('open-connections').hidden=true;
    const help=menu('desktop-help-menu',menuDescriptions.help);
    const about=document.createElement('dialog');about.id='desktop-help-dialog';about.className='vd-dialog';about.setAttribute('aria-labelledby','desktop-help-heading');
    about.innerHTML='<h2 id="desktop-help-heading">Video Descriptor</h2><p>Рабочее пространство записи</p><ol><li>Откройте или добавьте видео или аудио.</li><li>Расшифруйте речь и при необходимости разделите её по участникам.</li><li>Проверьте текст по видео. Нажмите на время для перехода, на карандаш — для правки.</li><li>Скопируйте нужный текст или скачайте TXT, SRT либо VTT рядом с расшифровкой.</li></ol><p>В меню «Вид» включаются конспект, статья и технические сведения. Скрытие не останавливает обработку и не удаляет материалы.</p><p>В редакторе: Ctrl+S — сохранить, Ctrl+Z — отменить. Несохранённые изменения защищены при переходах.</p><p class="desktop-help-version vd-help"></p><div class="vd-actions"><button type="button" class="vd-button">Закрыть</button></div>';
    function openAbout(){
      about.querySelector('.desktop-help-version').textContent=versionLabel(environment.health)||'Video Descriptor';
      closeMenus();about.showModal();
    }
    command(help.body,'О приложении и работе с записью',openAbout);
    const helpAction=command(bar,'Справка',openAbout);helpAction.hidden=true;
    link(help.body,'Подключение Ollama','ollama');
    link(help.body,'Подключение LM Studio','lmstudio');
    about.querySelector('button').onclick=()=>about.close();about.addEventListener('close',()=>{(helpAction.hidden?help.details.querySelector('summary'):helpAction).focus();});document.body.append(about);
    const caption=document.createElement('span');caption.className='desktop-app-caption';caption.textContent='Video Descriptor';header.append(caption);
    const feedback=document.createElement('p');feedback.className='desktop-command-status';feedback.setAttribute('role','status');header.after(feedback);
    const connection=document.createElement('p');connection.className='desktop-environment-status';connection.hidden=true;header.after(connection);
    const connectionText=document.createElement('span');connectionText.setAttribute('role','status');
    const retry=document.createElement('button');retry.type='button';retry.className='vd-button vd-button--quiet vd-button--compact';retry.textContent='Повторить';
    retry.addEventListener('click',()=>readEnvironment(true));connection.append(connectionText,retry);
    function versionLabel(health){
      return health?.version?'Video Descriptor '+health.version+(health.build==null?'':' · билд '+(health.build>=12?String(health.build).padStart(4,'0'):health.build)):'';
    }
    let updatesLoading=null, commandsMounted=false, stopping=false;
    function loadUpdates(){
      if(window.updatesUI)return Promise.resolve(window.updatesUI);
      if(updatesLoading)return updatesLoading;
      updatesLoading=new Promise((resolve,reject)=>{
        const script=document.createElement('script');script.src='/updates.js';
        script.onload=()=>window.updatesUI?resolve(window.updatesUI):reject(Error('updates controller unavailable'));
        script.onerror=()=>{script.remove();reject(Error('updates controller unavailable'));};
        document.head.append(script);
      }).catch(error=>{updatesLoading=null;throw error;});
      return updatesLoading;
    }
    function mountWindowsCommands(){
      if(commandsMounted)return;
      commandsMounted=true;
      const stop=command(file.body,'Завершить приложение',async()=>{
        if(stopping||environment.kind!=='windows')return;
        stopping=true;
        if(!await mayLeave(stop)||environment.kind!=='windows'){stopping=false;return;}
        stop.disabled=true;stop.setAttribute('aria-busy','true');feedback.textContent='Завершаем приложение…';
        try{
          const response=await fetch('/api/native/stop',{method:'POST',headers:{'X-App-Instance':environment.health.instance}});
          const result=await response.json();
          if(!response.ok)throw Error(result.error||'Не удалось завершить приложение.');
          window.desktopShellStopped=true;window.updatesUI?.suspend();closeMenus();file.details.querySelector('summary').focus();
          feedback.textContent='Приложение завершено. Эту вкладку можно закрыть.';
          window.dispatchEvent(new Event('desktop-application-stopped'));
        }catch(error){feedback.textContent=error.message;stop.disabled=false;restoreFocus(stop);}
        finally{stopping=false;stop.disabled=window.desktopShellStopped===true;stop.setAttribute('aria-busy','false');}
      });stop.id='stop';
      const check=command(help.body,'Проверить обновления',()=>{});check.id='updates-check';check.disabled=true;help.body.prepend(check);
      const badge=command(header,'Обновление',()=>{});badge.id='updates-badge';badge.hidden=true;badge.setAttribute('aria-label','Доступно обновление');
      const dialog=document.createElement('dialog');dialog.id='updates-dialog';dialog.className='vd-dialog';dialog.setAttribute('aria-labelledby','updates-heading');
      dialog.innerHTML='<h2 id="updates-heading">Обновления</h2><p id="updates-status" role="status" aria-live="polite"></p><p id="updates-installed"></p><p id="updates-available"></p><h3 id="updates-title"></h3><p id="updates-notes" class="vd-help"></p><div class="vd-actions"><button id="updates-open" type="button" class="vd-button vd-button--primary" hidden>Открыть релиз</button><button id="updates-later" type="button" class="vd-button">Позже</button></div>';
      document.body.append(dialog);
      let returnTo=help.details.querySelector('summary');
      check.addEventListener('click',()=>{returnTo=help.details.querySelector('summary');closeMenus();});
      badge.addEventListener('click',()=>{returnTo=badge;closeMenus();});
      dialog.addEventListener('close',()=>{(returnTo.checkVisibility()?returnTo:helpAction.hidden?help.details.querySelector('summary'):helpAction).focus();});
    }
    shellEnvironment.subscribe(value=>{
      if(value.kind!=='unavailable'&&connection.contains(document.activeElement))file.details.querySelector('summary').focus();
      connection.hidden=value.kind!=='unavailable';retry.disabled=value.kind==='pending';
      connectionText.textContent=value.kind==='unavailable'?'Приложение недоступно.':'';
      const helpFocused=help.details.contains(document.activeElement)||document.activeElement===helpAction;
      bar.hidden=value.kind==='offline';
      help.details.hidden=confirmedKind!=='windows';helpAction.hidden=confirmedKind==='windows';
      if(helpFocused&&!document.activeElement.checkVisibility())(helpAction.hidden?help.details.querySelector('summary'):helpAction).focus();
      caption.textContent=versionLabel(value.health)||'Video Descriptor';
      for(const a of document.querySelectorAll('[data-desktop-command]')){
        const href=route(a.dataset.desktopCommand);a.hidden=!href;if(href)a.href=href;
      }
      tools.details.hidden=![...tools.body.querySelectorAll('a')].some(a=>!a.hidden);
      if(value.kind==='windows'){
        mountWindowsCommands();$('stop').disabled=stopping||window.desktopShellStopped===true;
        loadUpdates().then(ui=>{
          if(environment.kind==='windows'&&!window.desktopShellStopped){ui.init(environment.health.instance);feedback.textContent='';}
        }).catch(()=>{feedback.textContent='Не удалось загрузить обновления. Повторите проверку подключения.';connection.hidden=false;retry.disabled=false;});
      }else{
        window.updatesUI?.suspend();
        if(commandsMounted){$('stop').disabled=true;$('updates-check').disabled=true;}
      }
      if(commandsMounted){$('stop').hidden=confirmedKind!=='windows';$('updates-check').hidden=confirmedKind!=='windows';}
    });
    window.addEventListener('pageshow',event=>{if(event.persisted)readEnvironment(true);});
    // One View controller and one persisted preference structure, not a second menu.
    let viewAdopted=false;
    function adoptView(){
      if(viewAdopted)return;
      const existing=$('workspace-view-menu');if(!existing)return;
      viewAdopted=true;
      view.details.replaceWith(existing);existing.classList.add('desktop-menu');
      const workspace=$('workspace');
      const sync=()=>{existing.hidden=!workspace||workspace.hidden;if(existing.hidden)existing.open=false;};
      sync();
      if(workspace)new MutationObserver(sync).observe(workspace,{attributes:true,attributeFilter:['hidden']});
    }
    adoptView();document.addEventListener('workspace-view-ready',adoptView);
    function closeMenus(except){for(const item of bar.querySelectorAll('details'))if(item!==except)item.open=false;}
    bar.addEventListener('toggle',event=>{if(event.target.open)closeMenus(event.target);},true);
    bar.addEventListener('keydown',event=>{
      if(event.key==='Escape'){const active=event.target.closest('details');if(active){active.open=false;active.querySelector('summary').focus();event.preventDefault();}}
      if(['ArrowLeft','ArrowRight'].includes(event.key)&&(event.target.tagName==='SUMMARY'||event.target===helpAction)){
        const entries=[...bar.querySelectorAll(':scope>details:not([hidden])>summary,:scope>button:not([hidden])')],i=entries.indexOf(event.target),next=entries[(i+(event.key==='ArrowRight'?1:entries.length-1))%entries.length];
        closeMenus();next.focus();event.preventDefault();
      }
    });
    document.addEventListener('click',event=>{if(!bar.contains(event.target))closeMenus();});
    function restoreFocus(target){
      const menu=target?.closest('details');if(menu)menu.open=true;
      target?.focus();
    }
    async function mayLeave(target){
      try{
        const frame=$('report-editor');
        if(frame?.contentWindow?.notesEditorDirty?.()||window.notesEditorDirty?.()){
          const status=$('recording-status')||$('editor-status');
          feedback.textContent='Сохраните правки материала перед переходом.';
          if(status)status.textContent=feedback.textContent;
          restoreFocus(target);return false;
        }
        if(window.mayLeaveQuickReply&&!await window.mayLeaveQuickReply()){restoreFocus(target);return false;}
        return true;
      }catch(_error){
        feedback.textContent='Не удалось проверить несохранённые правки. Завершите редактирование и повторите.';
        restoreFocus(target);return false;
      }
    }
    // New menu links and shared navigation retain the existing dirty owners.
    let navigating=false;
    async function navigateFromShell(event){
      const a=event.target.closest('a[data-desktop-navigation]');
      if(!a||event.button||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
      event.preventDefault();event.stopImmediatePropagation();
      if(navigating)return;
      navigating=true;
      try{
        if(environment.kind==='pending')await readEnvironment();
        if(a.hidden||!await mayLeave(a))return;
        // Global destinations are canonical and never inherit the previous job.
        feedback.textContent='';window.dispatchEvent(new CustomEvent('desktop-navigation',{detail:{command:a.dataset.desktopCommand}}));
        closeMenus();location.assign(a.href);
      }finally{navigating=false;}
    }
    document.addEventListener('click',navigateFromShell,true);
    if($('new-record-open')){
      const button=$('new-record-open');button.dataset.desktopCommand='new';button.dataset.desktopNavigation='';button.href=route('new')||'/create';
    }
    if(!localNavigation){
      navigation.classList.add('desktop-navigation');
      for(const a of navigation.querySelectorAll('a'))a.classList.add('desktop-nav-item');
    }
    const sourceHeading=document.querySelector('.studio-header h1');
    if(sourceHeading&&!new URLSearchParams(location.search).has('job')&&!new URLSearchParams(location.search).has('folder'))sourceHeading.textContent='Новая запись';
    for(const tab of document.querySelectorAll('.stage-tabs [data-stage]'))tab.addEventListener('click',()=>{
      if(tab.dataset.stage==='notes')window.workspaceView?.setPanel('notes',true);
      if(tab.dataset.stage==='speech')window.workspaceView?.setPanel('transcript',true);
    });
    // A local settings index opens existing disclosures without introducing routes/state.
    const wizard=$('setup-wizard');
    if(wizard){
      const card=wizard.querySelector(':scope>section'),preparation=$('desktop-preparation');
      preparation.hidden=false;preparation.open=true;
      const preserve=new Set([preparation,card.querySelector('h2'),$('ai-summary'),$('preparation-status'),card.querySelector('a[href="#diagnostics"]')]);
      for(const node of [...card.children])if(!preserve.has(node))preparation.append(node);
      card.querySelector('h2').textContent='Функции и подготовка';
      card.append(preparation);card.insertBefore($('prepare-selected-stop'),preparation);
      card.insertBefore($('ai-summary'),card.querySelector('h2').nextSibling);
      preparation.open=$('setup-callout').dataset.complete!=='true';
      // Every settings section is one tab: preparation first, then the existing disclosures.
      const panels=[card,...wizard.querySelectorAll(':scope>details')];
      const index=document.createElement('nav');index.className='desktop-settings-index vd-tabs';index.id='desktop-settings-index';index.setAttribute('role','tablist');index.setAttribute('aria-label','Разделы настроек');
      const tabs=[];
      for(const [i,panel] of panels.entries()){
        if(!panel.id)panel.id='desktop-settings-'+i;
        const label=(panel.querySelector(':scope>summary')||panel.querySelector(':scope>h2'))?.textContent.trim()||'Настройки';
        const button=document.createElement('button');button.type='button';button.id=panel.id+'-tab';
        button.setAttribute('role','tab');button.setAttribute('aria-controls',panel.id);
        button.textContent=label;button.tabIndex=-1;
        button.dataset.settingsTab=panel.id;
        index.append(button);tabs.push(button);
        panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);
      }
      wizard.prepend(index);
      // One section at a time: the tab owns the panel, the panel keeps its own ids.
      let active=-1;
      function activate(next,focus=false){
        if(next<0||next>=panels.length)return;
        active=next;
        panels.forEach((panel,i)=>{
          const selected=i===active;
          tabs[i].setAttribute('aria-selected',String(selected));
          tabs[i].tabIndex=selected?0:-1;
          panel.hidden=!selected;
          if(selected&&panel.tagName==='DETAILS')panel.open=true;
        });
        if(focus)tabs[active].focus();
      }
      tabs.forEach((tab,i)=>tab.addEventListener('click',()=>activate(i)));
      index.addEventListener('keydown',event=>{
        const current=tabs.indexOf(document.activeElement);
        if(current<0)return;
        let next=current;
        if(event.key==='ArrowRight')next=(current+1)%tabs.length;
        else if(event.key==='ArrowLeft')next=(current+tabs.length-1)%tabs.length;
        else if(event.key==='Home')next=0;
        else if(event.key==='End')next=tabs.length-1;
        else return;
        event.preventDefault();
        activate(next,true);
      });
      activate(0);
      // Preparation progress stays visible on its own tab instead of a card above the strip.
      const status=$('preparation-status'),stop=$('prepare-selected-stop');
      if(status&&tabs[0]){
        const badge=document.createElement('span');badge.className='vd-status';badge.hidden=true;
        tabs[0].append(badge);
        const update=()=>{
          const failed=status.dataset.tone==='danger';
          const running=!!stop&&!stop.hidden;
          badge.hidden=!(failed||running);
          badge.textContent=failed?'ошибка':'подготовка';
          badge.dataset.tone=failed?'danger':'info';
          tabs[0].title=(failed||running)?status.textContent.trim():'';
        };
        const observer=new MutationObserver(update);
        observer.observe(status,{childList:true,characterData:true,subtree:true,attributes:true});
        if(stop)observer.observe(stop,{attributes:true,attributeFilter:['hidden']});
        update();
      }
      // A field of a hidden panel becomes visible before it takes the focus.
      window.desktopSettingsShow=target=>{
        if(!target)return false;
        const panel=panels.find(item=>item.contains(target));
        if(!panel)return false;
        activate(panels.indexOf(panel));
        const details=target.closest('details');
        if(details)details.open=true;
        return true;
      };
    }
    const feed=$('speech-feed');
    if(feed){
      const exports=document.querySelector('.transcript-export-tools');
      if(exports){
        const message=document.createElement('span');message.className='vd-help';message.setAttribute('role','status');
        const copy=command(exports,'Копировать',async()=>{
          if(window.speechReplyEditing?.()){message.textContent='Сначала завершите правку реплики.';return;}
          const text=[...feed.querySelectorAll('.utterance .subtitle-original')].map(node=>node.textContent.trim()).filter(Boolean).join('\n\n');
          if(!text){message.textContent='В выбранной версии пока нет текста.';return;}
          try{await navigator.clipboard.writeText(text);message.textContent='Расшифровка скопирована.';}
          catch(_error){message.textContent='Буфер обмена недоступен. Выделите текст или скачайте TXT.';}
        });copy.id='desktop-copy-transcript';copy.className='vd-button vd-button--quiet';exports.append(message);
      }
      // Size the existing scroller, never replace its contents or reset scroll position.
      const fit=()=>{
        if(!feed.checkVisibility())return;
        const top=feed.getBoundingClientRect().top+window.scrollY;
        const value=Math.max(240,window.innerHeight-top-24)+'px';
        if(feed.style.getPropertyValue('--desktop-feed-height')!==value)feed.style.setProperty('--desktop-feed-height',value);
      };
      // Resizing the feed can resize the observed workspace. Write on the next
      // frame, outside ResizeObserver delivery, and coalesce repeated snapshots.
      let fitFrame=null;
      const scheduleFit=()=>{if(fitFrame===null)fitFrame=requestAnimationFrame(()=>{fitFrame=null;fit();});};
      const observer=new ResizeObserver(scheduleFit);
      for(const node of [$('workspace'),feed.closest('section')?.querySelector('.subtitle-tools')])if(node)observer.observe(node);
      window.addEventListener('resize',scheduleFit);document.addEventListener('recording-snapshot',scheduleFit);scheduleFit();
    }
    document.dispatchEvent(new Event('desktop-shell-ready'));
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
