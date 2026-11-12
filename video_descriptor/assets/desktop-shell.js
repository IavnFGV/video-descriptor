/* Shared desktop chrome. Moves existing controls; never owns jobs, media or editors. */
(() => {
  if(new URLSearchParams(location.search).get('embedded')==='1')return;
  function start(){
    const $=id=>document.getElementById(id), native=!!$('app-shell');
    const navigation=native?document.querySelector('.sidebar nav'):document.querySelector('.vd-global-nav');
    if(!navigation)return;
    document.body.classList.add('vd-desktop');
    const brand=document.querySelector('.brand>span:last-child');if(brand)brand.textContent='Video Descriptor';
    const header=native?document.querySelector('.topbar'):document.createElement('header');
    header.classList.add('desktop-header');
    if(!native)document.body.prepend(header);
    // Retain legacy IDs for their existing handlers, but no second navigation surface.
    if($('sidebar-toggle'))$('sidebar-toggle').hidden=true;
    const bar=document.createElement('div');bar.className='desktop-menu-bar';bar.setAttribute('aria-label','Команды приложения');header.append(bar);
    function menu(id,title){
      const details=document.createElement('details'),summary=document.createElement('summary'),body=document.createElement('div');
      details.id=id;details.className='desktop-menu';summary.textContent=title;body.className='desktop-menu-content';details.append(summary,body);bar.append(details);return {details,body};
    }
    function link(body,title,href){const a=document.createElement('a');a.textContent=title;a.href=href;a.dataset.desktopNavigation='';body.append(a);return a;}
    function command(body,title,run){const b=document.createElement('button');b.type='button';b.textContent=title;b.onclick=run;body.append(b);return b;}
    const file=menu('desktop-file-menu','Файл');
    link(file.body,'Новая запись…',native?'#new':'/#new');
    function navigationItem(body,id,title,href){
      const item=native?$(id):null;
      if(item){item.textContent=title;body.append(item);return item;}
      return link(body,title,href);
    }
    navigationItem(file.body,'records-open','Записи',native?'#records':'/output/');
    const oldMenu=document.querySelector('.app-menu');
    if($('stop'))file.body.append($('stop'));
    const view=menu('desktop-view-menu','Вид');
    const tools=menu('desktop-tools-menu','Инструменты');
    navigationItem(tools.body,'setup-open','Настройки AI и подключения…',native?'#settings':'/#settings');
    navigationItem(tools.body,'diagnostics-open','Диагностика…',native?'#diagnostics':'/#diagnostics');
    // The old recording-only dialog omits Ollama. All entry points use the shared form.
    if($('open-connections'))$('open-connections').hidden=true;
    const help=menu('desktop-help-menu','Справка');
    if($('updates-check'))help.body.append($('updates-check'));
    const about=document.createElement('dialog');about.id='desktop-help-dialog';about.className='vd-dialog';about.setAttribute('aria-labelledby','desktop-help-heading');
    about.innerHTML='<h2 id="desktop-help-heading">Video Descriptor</h2><p>Рабочее пространство записи</p><ol><li>Откройте или добавьте видео или аудио.</li><li>Расшифруйте речь и при необходимости разделите её по участникам.</li><li>Проверьте текст по видео. Нажмите на время для перехода, на карандаш — для правки.</li><li>Скопируйте нужный текст или скачайте TXT, SRT либо VTT рядом с расшифровкой.</li></ol><p>В меню «Вид» включаются перевод, конспект, статья и технические сведения. Скрытие не останавливает обработку и не удаляет материалы.</p><p>В редакторе: Ctrl+S — сохранить, Ctrl+Z — отменить. Несохранённые изменения защищены при переходах.</p><p class="desktop-help-version vd-help"></p><div class="vd-actions"><button type="button" class="vd-button">Закрыть</button></div>';
    const aboutButton=command(help.body,'О приложении и работе с записью',()=>{about.querySelector('.desktop-help-version').textContent=$('build-label')?.textContent||'Локальное рабочее пространство';about.showModal();});
    link(help.body,'Подключение Ollama','/help/ollama');
    link(help.body,'Подключение LM Studio','/help/lmstudio');
    about.querySelector('button').onclick=()=>about.close();about.addEventListener('close',()=>help.details.querySelector('summary').focus());document.body.append(about);
    // Native dialogs cannot restore focus into a command menu that just closed.
    const returns=new Map();
    bar.addEventListener('click',event=>{
      const id=event.target.closest('button')?.id;
      if(id==='open-connections')returns.set($('connections-dialog'),tools.details.querySelector('summary'));
      if(id==='updates-check')returns.set($('updates-dialog'),help.details.querySelector('summary'));
    },true);
    for(const id of ['connections-dialog','updates-dialog'])$(id)?.addEventListener('close',()=>{const target=returns.get($(id));if(target){returns.delete($(id));target.focus();}});
    if(oldMenu)oldMenu.hidden=true;
    const caption=document.createElement('span');caption.className='desktop-app-caption';caption.textContent='Video Descriptor';header.append(caption);
    if($('updates-badge'))header.append($('updates-badge'));
    // One View controller and one persisted preference structure, not a second menu.
    function adoptView(){
      const existing=$('workspace-view-menu');if(!existing)return;
      view.details.replaceWith(existing);existing.classList.add('desktop-menu');
    }
    adoptView();document.addEventListener('workspace-view-ready',adoptView);
    function closeMenus(except){for(const item of bar.querySelectorAll('details'))if(item!==except)item.open=false;}
    bar.addEventListener('toggle',event=>{if(event.target.open)closeMenus(event.target);},true);
    bar.addEventListener('keydown',event=>{
      if(event.key==='Escape'){const active=event.target.closest('details');if(active){active.open=false;active.querySelector('summary').focus();event.preventDefault();}}
      if(['ArrowLeft','ArrowRight'].includes(event.key)&&event.target.tagName==='SUMMARY'){
        const entries=[...bar.querySelectorAll(':scope>details>summary')],i=entries.indexOf(event.target),next=entries[(i+(event.key==='ArrowRight'?1:entries.length-1))%entries.length];
        closeMenus();next.focus();event.preventDefault();
      }
    });
    document.addEventListener('click',event=>{if(!bar.contains(event.target))closeMenus();else if(event.target.closest('a,button')&&!event.target.closest('#workspace-view-menu'))closeMenus();});
    // New menu links and shared navigation retain the existing dirty owners.
    document.addEventListener('click',async event=>{
      const a=event.target.closest('a[data-desktop-navigation],.vd-global-nav a');
      if(!a||event.button||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
      event.preventDefault();
      const frame=$('report-editor');
      if(frame?.contentWindow?.notesEditorDirty?.()||window.notesEditorDirty?.()){
        const status=$('recording-status')||$('editor-status');if(status)status.textContent='Сохраните правки материала перед переходом.';return;
      }
      if(window.mayLeaveQuickReply&&!await window.mayLeaveQuickReply())return;
      location.assign(a.href);
    },true);
    // Library action next to the library heading, not a miscellaneous sidebar item.
    if(native&&$('new-record-open')){
      const row=$('jobs-panel')?.querySelector('.card-title');if(row){$('new-record-open').className='vd-button vd-button--primary';row.insertBefore($('new-record-open'),$('refresh'));}
    }
    if(!native){
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
      const index=document.createElement('nav');index.className='desktop-settings-index';index.setAttribute('aria-label','Разделы настроек');
      for(const [i,section] of [...wizard.querySelectorAll(':scope>details')].entries()){
        if(!section.id)section.id='desktop-settings-'+i;
        const button=command(index,section.querySelector('summary').textContent,()=>{section.open=true;section.scrollIntoView({block:'start'});section.querySelector('summary').focus({preventScroll:true});});button.setAttribute('aria-controls',section.id);
      }
      wizard.prepend(index);
      const card=wizard.querySelector(':scope>section'),preparation=$('desktop-preparation');
      preparation.hidden=false;preparation.open=true;
      const preserve=new Set([preparation,card.querySelector('h2'),$('ai-summary'),$('preparation-status'),card.querySelector('a[href="#diagnostics"]')]);
      for(const node of [...card.children])if(!preserve.has(node))preparation.append(node);
      card.querySelector('h2').textContent='Распознавание и участники';card.append(preparation);card.insertBefore($('prepare-selected-stop'),preparation);
      card.insertBefore($('ai-summary'),card.querySelector('h2').nextSibling);
      preparation.open=$('setup-callout').dataset.complete!=='true';
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
      const observer=new ResizeObserver(fit);
      for(const node of [$('workspace'),feed.closest('section')?.querySelector('.subtitle-tools')])if(node)observer.observe(node);
      window.addEventListener('resize',fit);document.addEventListener('recording-snapshot',()=>requestAnimationFrame(fit));fit();
    }
    document.dispatchEvent(new Event('desktop-shell-ready'));
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
