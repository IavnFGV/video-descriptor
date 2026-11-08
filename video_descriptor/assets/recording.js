/* One recording, one media element; results remain immutable selectable versions. */
(() => {
  const $ = id => document.getElementById(id), player=$('process-video'), layout=document.querySelector('.studio-layout');
  const speech=$('stage-speech'), notes=$('stage-notes'), left=document.createElement('div');
  left.className='recording-left'; layout.prepend(left); left.append($('shared-player'),speech);
  $('record-versions').hidden=true;
  const speechHeading=document.createElement('div');speechHeading.className='recording-speech-heading';
  const label=document.createElement('label'); label.textContent='Расшифровка';
  const speechSelect=document.createElement('select');speechSelect.id='recording-speech';label.append(speechSelect);speechHeading.append(label);speech.prepend(speechHeading);
  const actions=document.createElement('div');actions.className='recording-actions';
  actions.innerHTML='<button id="recording-diarize" type="button" hidden>Разделить по участникам</button><button id="recording-translate" type="button" hidden>Перевести на русский</button><button id="recording-stop" type="button" hidden>Остановить обработку</button>';
  speechHeading.append(actions);
  const translationPanel=$('translation-settings-panel');
  translationPanel.insertBefore($('recording-translate'),$('translation-settings-form'));
  const transcriptSection=$('speech-feed').closest('section');
  const transcriptDisclosure=document.createElement('details');transcriptDisclosure.id='transcript-disclosure';transcriptDisclosure.open=true;
  const transcriptSummary=document.createElement('summary');transcriptSummary.textContent='Текст расшифровки';
  transcriptDisclosure.append(transcriptSummary);
  while(transcriptSection.firstChild)transcriptDisclosure.append(transcriptSection.firstChild);
  transcriptSection.append(transcriptDisclosure);
  const notice=document.createElement('p');notice.id='recording-status';notice.className='hint';notice.setAttribute('role','status');speechHeading.append(notice);
  const actionNotice=document.createElement('p');actionNotice.id='recording-action-status';actionNotice.className='feedback';actionNotice.setAttribute('role','status');actionNotice.setAttribute('aria-live','polite');speechHeading.append(actionNotice);
  let actionPending=false;
  const newNotes=$('notes-settings').closest('section');newNotes.id='recording-notes-settings';
  if(location.search.includes('folder=')||location.search.includes('job='))newNotes.hidden=true;
  const notesMenu=document.createElement('details'),notesSummary=document.createElement('summary');notesSummary.textContent='Действия с конспектом';notesMenu.append(notesSummary,$('delete-notes'));$('stage-notes').append(notesMenu);
  notesMenu.id='recording-notes-actions';
  const originalResponse=document.createElement('button');originalResponse.id='recording-original-response';originalResponse.type='button';originalResponse.textContent='Оригинальный ответ модели';originalResponse.disabled=true;originalResponse.setAttribute('aria-controls','report-editor');
  const notesMenuActions=document.createElement('div');notesMenuActions.className='notes-actions';notesMenuActions.append($('delete-notes'),originalResponse);notesMenu.append(notesMenuActions);
  originalResponse.onclick=()=>{
    const frame=$('report-editor'),button=frame.contentDocument?.querySelector('[data-notes-view="model"]');
    if(!button)return;
    button.click();notesMenu.open=false;frame.scrollIntoView({block:'start'});
    frame.contentDocument.querySelector('[data-notes-view="read"]')?.focus();
  };
  const originalReports=$('notes-variant-label');originalReports.hidden=true;
  $('source-details').append($('record-menu'));
  const detail=document.createElement('details');detail.id='recording-processing';
  const summary=document.createElement('summary');summary.textContent='Подробности обработки';detail.append(summary);
  const workspace=$('workspace'); workspace.append(detail);
  const jobError=document.createElement('p');jobError.id='recording-job-error';jobError.className='feedback vd-error';jobError.setAttribute('role','alert');jobError.hidden=true;workspace.insertBefore(jobError,$('stage-progress'));
  const retryJob=document.createElement('button');retryJob.id='recording-retry';retryJob.type='button';retryJob.className='vd-button';retryJob.textContent='Продолжить с сохранёнными ответами';retryJob.hidden=true;workspace.insertBefore(retryJob,$('stage-progress'));
  const repairNotes=document.createElement('button');repairNotes.type='button';repairNotes.className='vd-button';repairNotes.textContent='Исправить конспект вручную';repairNotes.hidden=true;workspace.insertBefore(repairNotes,$('stage-progress'));
  async function recoveryPost(value){
    const response=await fetch('/api/construction-recovery',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}),data=await response.json();
    if(!response.ok)throw Error(data.error||'Не удалось сохранить конспект');return data;
  }
  repairNotes.onclick=async()=>{
    if(actionPending||!snapshot)return;
    if(window.speechReplyEditing?.()||$('report-editor').contentWindow?.notesEditorDirty?.()){jobError.textContent='Сначала сохраните или отмените текущие правки.';return;}
    const folder=snapshot.folder;repairNotes.disabled=true;
    try{
      const state=await recoveryPost({folder});if(snapshot?.folder!==folder)return;
      const dialog=document.createElement('dialog');dialog.className='vd-dialog construction-recovery';dialog.setAttribute('aria-labelledby','recovery-title');
      dialog.innerHTML='<form><h2 id="recovery-title">Исправить конспект</h2><p>Исправьте метки в оглавлении и конспекте. Используйте начала реплик из списка. Ответ модели сохранится отдельно; новый запрос к модели не нужен.</p><label>Начала реплик<select data-anchors><option value="">Выберите реплику…</option></select></label><p class="hint">Выделите неверную метку в тексте и выберите реплику, чтобы заменить её.</p><label>Текст конспекта<textarea rows="16" required></textarea></label><p role="alert" data-error></p><div class="vd-actions"><button type="submit">Проверить и сохранить</button><button type="button" data-cancel>Отмена</button></div></form>';
      const text=dialog.querySelector('textarea'),anchors=dialog.querySelector('[data-anchors]'),error=dialog.querySelector('[data-error]'),save=dialog.querySelector('[type=submit]');text.value=state.text;
      const clock=t=>[Math.floor(t/3600),Math.floor(t/60)%60,t%60].map(x=>String(x).padStart(2,'0')).join(':');
      for(const anchor of state.anchors){const item=document.createElement('option');item.value=clock(anchor.time);item.textContent=item.value+' · '+anchor.text.slice(0,160);anchors.append(item);}
      anchors.onchange=()=>{if(!anchors.value)return;text.setRangeText(anchors.value,text.selectionStart,text.selectionEnd,'select');text.focus();anchors.value='';};
      let saving=false,saved=false;const dirty=()=>!saved&&text.value!==state.text;
      const close=async()=>{if(saving)return;if(!dirty()||await window.confirmDiscard('Исправленный конспект ещё не сохранён. Закрыть без сохранения?'))dialog.close();};
      dialog.oncancel=e=>{e.preventDefault();close();};dialog.querySelector('[data-cancel]').onclick=close;
      const unload=e=>{if(dirty()){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',unload);
      dialog.onclose=()=>{window.removeEventListener('beforeunload',unload);dialog.remove();repairNotes.focus();};
      dialog.querySelector('form').onsubmit=async e=>{
        e.preventDefault();if(saving)return;saving=true;save.disabled=true;error.textContent='Проверяем и сохраняем…';
        try{const value=await recoveryPost({folder,revision:state.revision,text:text.value});saved=true;dialog.close();document.dispatchEvent(new CustomEvent('construction-started',{detail:value.job}));}
        catch(exc){error.textContent=exc.message;const stamp=exc.message.match(/\[(\d{2,}:\d{2}:\d{2})\]/)?.[1],at=stamp?text.value.indexOf(stamp):-1;if(at>=0){text.focus();text.setSelectionRange(at,at+stamp.length);}}
        finally{saving=false;save.disabled=false;}
      };
      document.body.append(dialog);dialog.showModal();text.focus();text.setSelectionRange(0,0);text.scrollTop=0;
    }catch(error){jobError.textContent=error.message;}finally{repairNotes.disabled=false;}
  };
  retryJob.onclick=async()=>{
    if(!job?.id||actionPending)return;
    if(window.speechReplyEditing?.()||$('report-editor').contentWindow?.notesEditorDirty?.()){jobError.textContent='Сначала сохраните или отмените текущие правки.';return;}
    actionPending=true;retryJob.disabled=true;retryJob.setAttribute('aria-busy','true');
    try{
      const response=await fetch('/api/retry?'+new URLSearchParams({id:job.id}),{method:'POST',headers:{'X-App-Instance':window.recordingUI.instance}}),value=await response.json();
      if(!response.ok)throw Error(value.error||'Не удалось продолжить обработку');
      document.dispatchEvent(new CustomEvent('construction-started',{detail:value}));
    }catch(error){jobError.textContent=error.message;}
    finally{actionPending=false;retryJob.disabled=false;retryJob.removeAttribute('aria-busy');paint();}
  };

  const diarizationProgress=document.createElement('div');diarizationProgress.id='diarization-progress';diarizationProgress.className='diarization-progress';diarizationProgress.hidden=true;
  diarizationProgress.innerHTML='<span class="diarization-ring" role="progressbar" aria-label="Разделение по участникам"><svg viewBox="0 0 32 32" aria-hidden="true"><circle class="diarization-ring-track" cx="16" cy="16" r="13"/><circle class="diarization-ring-value" cx="16" cy="16" r="13" pathLength="100"/></svg></span><div><p class="diarization-progress-label" role="status"></p><p class="diarization-progress-time"></p></div>';
  workspace.insertBefore(diarizationProgress,$('stage-progress'));
  function renderDiarizationProgress(){
    const value=snapshot?.diarization_progress,active=job?.task==='diarize'&&['queued','running'].includes(job.status);
    diarizationProgress.hidden=!active;
    $('stage-progress').hidden=active;
    if(!active)return;
    $('stage-label').textContent='Разделение по участникам';
    const queued=job.status==='queued',label=queued?'Участники: ожидаем запуска':value?.label||'Разделяем реплики по участникам',ring=diarizationProgress.querySelector('.diarization-ring');
    const measured=!queued&&Number.isFinite(value?.completed)&&Number.isFinite(value?.total)&&value.total>0&&value.completed>=0&&value.completed<=value.total;
    const percent=measured?Math.floor(value.completed/value.total*100):null;
    ring.classList.toggle('indeterminate',!measured);ring.setAttribute('aria-label',label);
    ring.setAttribute('aria-valuemin','0');ring.setAttribute('aria-valuemax','100');
    if(measured)ring.setAttribute('aria-valuenow',String(percent));else ring.removeAttribute('aria-valuenow');
    ring.setAttribute('aria-valuetext',measured?percent+'%':'Выполняется, процент недоступен');
    const arc=ring.querySelector('.diarization-ring-value');arc.setAttribute('stroke-dasharray',measured?'100':'24 76');arc.setAttribute('stroke-dashoffset',measured?String(100-percent):'0');
    const title=diarizationProgress.querySelector('.diarization-progress-label'),message=label+(measured?' · '+percent+'%':'');
    if(title.textContent!==message)title.textContent=message;
    const now=Date.now()/1000,elapsed=Number.isFinite(value?.stage_started_at)?Math.max(0,Math.floor(now-value.stage_started_at)):null;
    const age=Number.isFinite(value?.updated_at)?Math.max(0,Math.floor(now-value.updated_at)):null;
    diarizationProgress.querySelector('.diarization-progress-time').textContent=[measured?value.completed+' из '+value.total:null,elapsed!==null?'На этапе: '+Math.floor(elapsed/60)+':'+String(elapsed%60).padStart(2,'0'):null,age>=60?'Новых данных от модели нет '+age+' с':null].filter(Boolean).join(' · ');
  }
  setInterval(renderDiarizationProgress,1000);
  const requestStatus=document.createElement('p');requestStatus.id='recording-request-status';requestStatus.className='hint';requestStatus.setAttribute('role','status');workspace.insertBefore(requestStatus,detail);
  for(const id of ['run-message','translation-summary','translation-blocks-panel'])detail.append($(id));
  let snapshot=null, job=null, data=null, loading=false, requested=false, pendingReport=null,epoch=0;
  let paused=false, currentTimeKey='', libraryKey='', statusKey='';
  const link=$('playback-link'),resume=$('resume-playback-link');
  const saved=localStorage.getItem('vd-recording-player-position');
  function expand(value){layout.classList.toggle('video-expanded',value);$('expand-player').textContent=value?'Вернуть сбоку':'Развернуть наверх';$('expand-player').setAttribute('aria-pressed',String(value));}
  expand(saved==='top');
  $('expand-player').onclick=()=>{const value=!layout.classList.contains('video-expanded');expand(value);localStorage.setItem('vd-recording-player-position',value?'top':'side');};
  function pauseLink(){if(link.checked){paused=true;resume.hidden=false;}}
  $('speech-feed').addEventListener('wheel',pauseLink,{passive:true});
  $('speech-feed').addEventListener('touchmove',pauseLink,{passive:true});
  $('speech-feed').addEventListener('keydown',event=>{if(['PageDown','PageUp','ArrowDown','ArrowUp','Home','End',' '].includes(event.key))pauseLink();});
  link.onchange=()=>{paused=false;resume.hidden=true;localStorage.setItem('vd-recording-link',String(link.checked));currentTimeKey='';sync(true);};
  if(localStorage.getItem('vd-recording-link')==='false')link.checked=false;
  resume.onclick=()=>{paused=false;resume.hidden=true;currentTimeKey='';sync(true);};
  function scrollInside(container,node){const a=container.getBoundingClientRect(),b=node.getBoundingClientRect();container.scrollTop+=b.top-a.top-24;}
  function sync(force=false){
    if(!snapshot)return;
    const time=player.currentTime;
    const index=snapshot.speech.findIndex((row,i)=>row.start<=time&&(row.end>=time||row.end<0&&(snapshot.speech[i+1]?.start??Infinity)>time));
    const frame=$('report-editor'),doc=frame.contentDocument;
    let target=null;
    if(doc){for(const heading of doc.querySelectorAll('#personal-preview [data-note-time]')){if(Number(heading.dataset.noteTime)<=time&&(!target||Number(heading.dataset.noteTime)>=Number(target.dataset.noteTime)))target=heading;}}
    const key=index+'|'+target?.id+'|'+frame.src;
    if(!force&&key===currentTimeKey)return;currentTimeKey=key;
    for(const [i,row] of [...$('speech-feed').children].entries())row.classList.toggle('active',i===index);
    doc?.querySelectorAll('.current-note').forEach(node=>node.classList.remove('current-note'));
    target?.classList.add('current-note');
    if(!link.checked||paused)return;
    const row=$('speech-feed').children[index];if(row)scrollInside($('speech-feed'),row);
    if(target){const fold=target.closest('details');if(fold)fold.open=true;const preview=doc.getElementById('personal-preview');if(preview)scrollInside(preview,target);}
  }
  function seek(time){
    if(!Number.isFinite(time)||time<0)return;
    $('follow').checked=false;paused=false;resume.hidden=true;currentTimeKey='';
    const move=()=>{player.currentTime=Math.min(time,Number.isFinite(player.duration)?player.duration:time);sync(true);};
    if(!player.readyState){player.addEventListener('loadedmetadata',move,{once:true});player.preload='auto';player.load();}else move();
  }
  player.addEventListener('timeupdate',()=>sync());
  let previewObserver=null;
  $('report-editor').addEventListener('load',()=>{
    previewObserver?.disconnect();currentTimeKey='';sync(true);
    const doc=$('report-editor').contentDocument;
    originalResponse.disabled=!doc?.querySelector('[data-notes-view="model"]');
    if(doc){previewObserver=new MutationObserver(()=>{currentTimeKey='';sync(true);});previewObserver.observe(doc.body,{childList:true,subtree:true});}
  });
  function option(value,text){const node=document.createElement('option');node.value=value;node.textContent=text;return node;}
  const when=seconds=>new Date(seconds*1000).toLocaleString('ru-RU');
  function speechName(item){const kind=(item.result_kind==='article'?'Снимок для статьи':null)||{notes:'Снимок для конспекта',translate:'Перевод',diarize:'С участниками'}[item.task]||({'whisper-local':'Локальное распознавание','whisper-npu':'Локальное распознавание','whisper':'Локальное распознавание','gemini':'Google · распознавание'}[item.engine])||item.engine||'Распознавание';return kind+' · '+when(item.created)+(item.status==='running'?' · Обработка':item.status==='queued'?' · В очереди':item.status==='error'?(item.cancelled?' · Остановлено':' · Ошибка'):'');}
  function paint(){
    if(!data)return;
    const key=JSON.stringify([data.speech,data.reports]);
    if(key!==libraryKey){libraryKey=key;speechSelect.replaceChildren(...data.speech.map(item=>option(item.folder,speechName(item))),option('__new__','＋ Создать новую расшифровку…'));
      $('recording-notes').replaceChildren(option('','Результат ещё не создан'),...data.reports.map(item=>option(item.url,(item.result_kind==='article'?'Статья · ':'')+(item.model||item.name||'Конспект')+' · '+when(item.created))),option('__new__','＋ Создать новый конспект…'));
    }
    speechSelect.value=snapshot?.folder||data.folder;
    const own=data.reports.find(item=>item.folder===snapshot?.folder&&item.name===window.studioUI.reportVariant());
    $('recording-notes').value=own?.url||'';
    $('report-editor').title=own?.result_kind==='article'?'Чтение и редактирование статьи':'Чтение и редактирование конспекта';
    $('recording-notes-origin').textContent=own?'По расшифровке: '+speechName(data.speech.find(item=>item.folder===own.speech_folder)||{created:own.created}):'Создайте конспект по выбранной расшифровке.';
    $('recording-stop').hidden=!window.recordingUI.native||!(data.active_job||['queued','running'].includes(job?.status));
    for(const id of ['recording-diarize','recording-translate'])$(id).disabled=actionPending||!snapshot?.has_ready_transcript||Boolean(data.active_job)||['queued','running'].includes(job?.status);
  }
  async function library(){
    if(loading){requested=true;return;}loading=true;
    const version=epoch;
    const query=snapshot?new URLSearchParams({folder:snapshot.folder}):new URLSearchParams(location.search);
    try{
      const response=await fetch('/api/recording?'+query,{cache:'no-store'}),value=await response.json();
      if(!response.ok)throw Error(value.error);
      if(version!==epoch){requested=true;return;}
      if(snapshot&&query.get('folder')!==snapshot.folder){requested=true;return;}
      data=value;paint();
      if(!snapshot){$('stage-source').hidden=true;speech.hidden=false;notes.hidden=false;$('run-title').textContent=value.filename;}
      if(value.active_job){$('recording-stop').hidden=!window.recordingUI.native;notice.textContent='Новый вариант '+(value.active_job.result_kind==='article'?'статьи':({notes:'конспекта',translate:'перевода',diarize:'с участниками'}[value.active_job.task]||'расшифровки'))+(value.active_job.status==='queued'?' в очереди.':' обрабатывается.')+' Готовые варианты доступны в списках.';}
      if(value.video_url&&player.getAttribute('src')!==value.video_url)player.src=value.video_url;
      $('shared-player').hidden=false;
    }catch(error){notice.textContent=error.message;}finally{loading=false;if(requested){requested=false;library();}}
  }
  function showNewNotes(){newNotes.hidden=false;$('notes-settings').open=true;$('construction-model').focus();}
  $('new-notes').addEventListener('click',showNewNotes);
  $('cancel-new-notes').onclick=()=>{newNotes.hidden=true;};
  speechSelect.onchange=()=>{
    if(speechSelect.value==='__new__'){speechSelect.value=snapshot?.folder||'';$('speech-settings').open=true;$('speech-engine').focus();return;}
    window.recordingSelection.select({folder:speechSelect.value});paint();
  };
  $('recording-notes').onchange=async()=>{
    const value=$('recording-notes').value;
    if(!await window.mayLeaveQuickReply()){paint();return;}
    window.closeQuickReplyEdit();
    if(value==='__new__'){paint();showNewNotes();return;}
    const report=data?.reports.find(item=>item.url===value);if(!report)return;
    if($('report-editor').contentWindow?.notesEditorDirty?.()){notice.textContent='Сохраните правки перед выбором другого конспекта.';paint();return;}
    if(report.folder===snapshot?.folder){window.studioUI.chooseReport(report.name);paint();}
    else {pendingReport=report;window.recordingSelection.select({folder:report.speech_folder});}
  };
  document.addEventListener('recording-snapshot',event=>{
    const changed=snapshot?.folder!==event.detail.snapshot.folder;snapshot=event.detail.snapshot;job=event.detail.job;
    jobError.hidden=job?.status!=='error';
    retryJob.hidden=jobError.hidden||!window.recordingUI.native;
    repairNotes.hidden=jobError.hidden||!snapshot.construction_answer_saved||job.cancelled||job.stage!=='notes';
    retryJob.textContent=snapshot.construction_answer_saved?'Продолжить с сохранённым ответом':'Повторить обработку';
    if(!jobError.hidden){const message=(job.cancelled?'Обработка остановлена. ':'Ошибка обработки. ')+((!job.cancelled&&job.stage==='notes'&&snapshot.construction_error)||job.error||snapshot.status?.message||'Откройте подробности обработки.');if(jobError.textContent!==message)jobError.textContent=message;}
    if(changed){newNotes.hidden=true;$('speech-settings').open=false;currentTimeKey='';library();}
    $('construction-cloud-label').hidden=$('construction-provider').value!=='gemini';
    if(pendingReport&&pendingReport.folder===snapshot.folder){const report=pendingReport;pendingReport=null;window.studioUI.chooseReport(report.name);}
    const state=JSON.stringify([snapshot.report_variants,job?.status,snapshot.speech_count]);if(state!==statusKey){statusKey=state;library();}
    if(!snapshot.has_ready_transcript&&!snapshot.running&&!['queued','running'].includes(job?.status))$('speech-settings').open=true;
    if(!snapshot.report_variants?.length)$('notes-feed').querySelector('.empty')?.replaceChildren(document.createTextNode('Конспект ещё не создан. Выберите «Создать новый конспект…» в списке выше.'));
    $('recording-stop').hidden=!window.recordingUI.native||!['queued','running'].includes(job?.status);
    for(const id of ['recording-diarize','recording-translate'])$(id).disabled=actionPending||!snapshot.has_ready_transcript||snapshot.running||['queued','running'].includes(job?.status);
    if(changed)detail.open=job?.status==='error';
    const stateInfo=snapshot.status||{},active=snapshot.running||['queued','running'].includes(job?.status);
    requestStatus.hidden=!active;
    requestStatus.textContent=active?[stateInfo.total>0?'Готово '+(stateInfo.completed||0)+' из '+stateInfo.total:null,stateInfo.request_state,stateInfo.received?'Получено '+stateInfo.received+' символов':null,stateInfo.request_seconds?'Текущий запрос: '+Math.round(stateInfo.request_seconds)+' с':null].filter(Boolean).join(' · '):'';
    renderDiarizationProgress();paint();sync();
  });
  document.addEventListener('recording-selection',()=>{epoch++;snapshot=null;currentTimeKey='';jobError.hidden=true;retryJob.hidden=true;repairNotes.hidden=true;renderDiarizationProgress();library();});
  async function postprocess(task,extra={}){
    const response=await fetch('/api/native/postprocess',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':window.recordingUI.instance},body:JSON.stringify({folder:snapshot?.folder,task,...extra})});
    const value=await response.json();if(!response.ok)throw Error(value.error);return value;
  }
  async function action(task){
    if(actionPending)return;
    const folder=snapshot?.folder,button=$(task==='diarize'?'recording-diarize':'recording-translate'),label=button.textContent;
    actionPending=true;paint();button.setAttribute('aria-busy','true');button.textContent='Запускаем…';
    actionNotice.classList.remove('vd-error');actionNotice.textContent=task==='diarize'?'Запускаем разделение по участникам… Проверяем запись и готовим задание.':'Запускаем перевод…';
    try{
      const value=await postprocess(task);
      actionNotice.textContent='Задание добавлено в очередь. Прогресс появится в новом варианте записи.';
      if(snapshot?.folder===folder)document.dispatchEvent(new CustomEvent('construction-started',{detail:value}));
      await library();
    }catch(error){
      actionNotice.classList.add('vd-error');actionNotice.textContent='Не удалось запустить: '+error.message;
    }finally{actionPending=false;button.removeAttribute('aria-busy');button.textContent=label;paint();}
  }
  $('recording-diarize').onclick=()=>action('diarize');$('recording-translate').onclick=()=>action('translate');
  $('recording-stop').onclick=async()=>{try{const response=await fetch('/api/native/cancel?id='+encodeURIComponent(data?.active_job?.id||job.id),{method:'POST',headers:{'X-App-Instance':window.recordingUI.instance}});const value=await response.json();if(!response.ok)throw Error(value.error);notice.textContent='Останавливаем. Готовые результаты сохранятся.';window.recordingSelection.refresh();library();}catch(error){notice.textContent=error.message;}};
  window.recordingUI={seek,sync,linked:()=>link.checked&&!paused,pauseLink,restoreChoices:paint,postprocess,native:false,instance:null};
  fetch('/health').then(response=>response.json()).then(value=>{
    if(value.app!=='video-descriptor-windows')return;
    window.recordingUI.native=true;window.recordingUI.instance=value.instance;
    document.querySelector('.vd-global-nav a[aria-current="page"]').href='/#records';
    $('construction-input').value='speech';$('construction-input').closest('label').hidden=true;
    const engine=$('speech-engine');engine.replaceChildren(option('whisper-local','Локальное распознавание · устройство из настроек AI'));engine.value='whisper-local';
    $('speech-engine-label').querySelector('small').textContent='Используется подготовленная модель и выбранное устройство из настроек AI. Новый запуск сохраняет предыдущую расшифровку.';
    for(const id of ['recording-diarize','recording-translate'])$(id).hidden=false;
  }).catch(()=>{});
  if(location.search.includes('folder=')||location.search.includes('job='))library();
  setInterval(()=>{if(!document.hidden&&document.body.classList.contains('has-recording'))library();},10000);
})();
