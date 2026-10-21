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
  actions.innerHTML='<button id="recording-diarize" type="button" hidden>Определить говорящих</button><button id="recording-translate" type="button" hidden>Перевести на русский</button><button id="recording-stop" type="button" hidden>Остановить обработку</button>';
  speechHeading.append(actions);
  const notice=document.createElement('p');notice.id='recording-status';notice.className='hint';notice.setAttribute('role','status');speechHeading.append(notice);
  const newNotes=$('notes-settings').closest('section');newNotes.id='recording-notes-settings';
  if(location.search.includes('folder=')||location.search.includes('job='))newNotes.hidden=true;
  const notesMenu=document.createElement('details'),notesSummary=document.createElement('summary');notesSummary.textContent='Действия с конспектом';notesMenu.append(notesSummary,$('delete-notes'));$('stage-notes').append(notesMenu);
  const originalReports=$('notes-variant-label');originalReports.hidden=true;
  $('source-details').append($('record-menu'));
  const detail=document.createElement('details');detail.id='recording-processing';
  const summary=document.createElement('summary');summary.textContent='Подробности обработки';detail.append(summary);
  const workspace=$('workspace'); workspace.append(detail);
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
    if(doc){previewObserver=new MutationObserver(()=>{currentTimeKey='';sync(true);});previewObserver.observe(doc.body,{childList:true,subtree:true});}
  });
  function option(value,text){const node=document.createElement('option');node.value=value;node.textContent=text;return node;}
  const when=seconds=>new Date(seconds*1000).toLocaleString('ru-RU');
  function speechName(item){const kind={notes:'Снимок для конспекта',translate:'Перевод',diarize:'С говорящими'}[item.task]||({'whisper-local':'Локальное распознавание','whisper-npu':'Локальное распознавание','whisper':'Локальное распознавание','gemini':'Google · распознавание'}[item.engine])||item.engine||'Распознавание';return kind+' · '+when(item.created)+(item.status==='running'?' · Обработка':item.status==='queued'?' · В очереди':item.status==='error'?' · Остановлено':'');}
  function paint(){
    if(!data)return;
    const key=JSON.stringify([data.speech,data.reports]);
    if(key!==libraryKey){libraryKey=key;speechSelect.replaceChildren(...data.speech.map(item=>option(item.folder,speechName(item))),option('__new__','＋ Создать новую расшифровку…'));
      $('recording-notes').replaceChildren(option('','Конспект ещё не создан'),...data.reports.map(item=>option(item.url,(item.model||item.name||'Конспект')+' · '+when(item.created))),option('__new__','＋ Создать новый конспект…'));
    }
    speechSelect.value=snapshot?.folder||data.folder;
    const own=data.reports.find(item=>item.folder===snapshot?.folder&&item.name===window.studioUI.reportVariant());
    $('recording-notes').value=own?.url||'';
    $('recording-notes-origin').textContent=own?'По расшифровке: '+speechName(data.speech.find(item=>item.folder===own.speech_folder)||{created:own.created}):'Создайте конспект по выбранной расшифровке.';
    $('recording-stop').hidden=!window.recordingUI.native||!(data.active_job||['queued','running'].includes(job?.status));
    for(const id of ['recording-diarize','recording-translate'])$(id).disabled=!snapshot?.has_ready_transcript||Boolean(data.active_job)||['queued','running'].includes(job?.status);
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
      if(value.active_job){$('recording-stop').hidden=!window.recordingUI.native;notice.textContent='Новый вариант '+({notes:'конспекта',translate:'перевода',diarize:'с говорящими'}[value.active_job.task]||'расшифровки')+(value.active_job.status==='queued'?' в очереди.':' обрабатывается.')+' Готовые варианты доступны в списках.';}
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
  $('recording-notes').onchange=()=>{
    const value=$('recording-notes').value;
    if(value==='__new__'){paint();showNewNotes();return;}
    const report=data?.reports.find(item=>item.url===value);if(!report)return;
    if($('report-editor').contentWindow?.notesEditorDirty?.()){notice.textContent='Сохраните правки перед выбором другого конспекта.';paint();return;}
    if(report.folder===snapshot?.folder){window.studioUI.chooseReport(report.name);paint();}
    else {pendingReport=report;window.recordingSelection.select({folder:report.speech_folder});}
  };
  document.addEventListener('recording-snapshot',event=>{
    const changed=snapshot?.folder!==event.detail.snapshot.folder;snapshot=event.detail.snapshot;job=event.detail.job;
    if(changed){newNotes.hidden=true;$('speech-settings').open=false;currentTimeKey='';library();}
    $('construction-cloud-label').hidden=$('construction-provider').value!=='gemini';
    if(pendingReport&&pendingReport.folder===snapshot.folder){const report=pendingReport;pendingReport=null;window.studioUI.chooseReport(report.name);}
    const state=JSON.stringify([snapshot.report_variants,job?.status,snapshot.speech_count]);if(state!==statusKey){statusKey=state;library();}
    if(!snapshot.has_ready_transcript&&!snapshot.running&&!['queued','running'].includes(job?.status))$('speech-settings').open=true;
    if(!snapshot.report_variants?.length)$('notes-feed').querySelector('.empty')?.replaceChildren(document.createTextNode('Конспект ещё не создан. Выберите «Создать новый конспект…» в списке выше.'));
    $('recording-stop').hidden=!window.recordingUI.native||!['queued','running'].includes(job?.status);
    for(const id of ['recording-diarize','recording-translate'])$(id).disabled=!snapshot.has_ready_transcript||snapshot.running||['queued','running'].includes(job?.status);
    if(changed)detail.open=job?.status==='error';
    const stateInfo=snapshot.status||{},active=snapshot.running||['queued','running'].includes(job?.status);
    requestStatus.hidden=!active;
    requestStatus.textContent=active?[stateInfo.total>0?'Готово '+(stateInfo.completed||0)+' из '+stateInfo.total:null,stateInfo.request_state,stateInfo.received?'Получено '+stateInfo.received+' символов':null,stateInfo.request_seconds?'Текущий запрос: '+Math.round(stateInfo.request_seconds)+' с':null].filter(Boolean).join(' · '):'';
    paint();sync();
  });
  document.addEventListener('recording-selection',()=>{epoch++;snapshot=null;currentTimeKey='';library();});
  async function postprocess(task,extra={}){
    const response=await fetch('/api/native/postprocess',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':window.recordingUI.instance},body:JSON.stringify({folder:snapshot?.folder,task,...extra})});
    const value=await response.json();if(!response.ok)throw Error(value.error);return value;
  }
  async function action(task){try{const value=await postprocess(task);document.dispatchEvent(new CustomEvent('construction-started',{detail:value}));}catch(error){notice.textContent=error.message;}}
  $('recording-diarize').onclick=()=>action('diarize');$('recording-translate').onclick=()=>action('translate');
  $('recording-stop').onclick=async()=>{try{const response=await fetch('/api/native/cancel?id='+encodeURIComponent(data?.active_job?.id||job.id),{method:'POST',headers:{'X-App-Instance':window.recordingUI.instance}});const value=await response.json();if(!response.ok)throw Error(value.error);notice.textContent='Останавливаем. Готовые результаты сохранятся.';window.recordingSelection.refresh();library();}catch(error){notice.textContent=error.message;}};
  window.recordingUI={seek,sync,linked:()=>link.checked&&!paused,pauseLink,postprocess,native:false,instance:null};
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
