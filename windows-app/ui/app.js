(() => {
  const $ = id => document.getElementById(id);
  let wizardLoaded=false, setupPolling=false, ollamaConnectionLoaded=false;
  let diarizationConfigured=false;
  let instance, selected = new URLSearchParams(location.search).get('job'), timer, uploading=false, currentJob, processing=false;
  const statusNames = {queued:'В очереди', running:'Обрабатываем', done:'Готово', error:'Ошибка обработки'};
  const actionNames = {translation_model_configured:'Модель перевода подключена',model_configured:'Модель подключена',settings_changed:'Настройки сохранены',device_selected:'Устройство выбрано',device_loading:'Загрузка модели',device_ready:'Модель готова',device_skipped:'Устройство пропущено',device_attempt_failed:'Ошибка устройства',device_fallback:'Переход на другое устройство',job_added:'Запись добавлена',job_device_snapshot:'Устройство закреплено за записью',job_started:'Обработка начата',job_finished:'Обработка завершена',job_failed:'Ошибка обработки',job_retried:'Повтор обработки',transcript_edited:'Текст исправлен',export:'Экспорт'};
  const stamp = s => {
    if (!Number.isFinite(s) || s < 0) return 'метка не определена';
    const total=Math.floor(s);
    return [Math.floor(total/3600),Math.floor(total/60)%60,total%60].map(n=>String(n).padStart(2,'0')).join(':');
  };
  function showView(focus=false) {
    const context=new URLSearchParams(location.search);
    if(context.get('workspace')==='1'){
      context.delete('workspace');$('records-open').href='/create?'+context;
    }

    const view=['new','settings','diagnostics'].includes(location.hash.slice(1))?location.hash.slice(1):'records';
    $('readiness-panel').hidden=view!=='diagnostics';
    $('bootstrap-notice').hidden=view==='settings';
    $('page-workspace').classList.toggle('workspace--single',view!=='diagnostics');
    $('new-record-view').hidden=view!=='new';
    $('jobs-panel').hidden=!!selected;
    $('result-panel').hidden=!selected;
    $('records-view').hidden=view!=='records';$('setup-wizard').hidden=view!=='settings';$('diagnostics-view').hidden=view!=='diagnostics';
    for(const [id,name] of [['new-record-open','new'],['records-open','records'],['setup-open','settings'],['diagnostics-open','diagnostics']]){
      if(name===view)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current');
    }
    $('view-label').textContent={new:'Новая запись',records:'Записи',settings:'Настройки AI',diagnostics:'Диагностика'}[view];
    $('main-heading').textContent={new:'Новая запись',records:selected?(currentJob?.title||currentJob?.filename||'Запись'):'Записи',settings:'Настройки AI',diagnostics:'Диагностика'}[view];
    $('view-description').textContent={new:'Добавьте файл и выберите параметры распознавания.',records:selected?'Проверьте расшифровку по записи. Здесь доступны обработка и результаты.':'Откройте запись, чтобы продолжить работу с её текстом и результатами.',settings:'Сначала подготовьте распознавание. Перевод и конспект можно подключить позже.',diagnostics:'Проверьте компоненты, доступность устройств и историю действий.'}[view];
    if(focus)$('main-heading').focus();
  }
  window.addEventListener('hashchange',()=>showView(true));
  window.addEventListener('popstate',()=>{
    const id=new URLSearchParams(location.search).get('job');
    if(id!==selected){resetResult();selected=id;clearTimeout(timer);$('result-panel').hidden=!id;if(id)poll();}
    showView();
  });
  showView();
  $('records-open').onclick=async e=>{if($('records-open').getAttribute('href').startsWith('/create'))return;if(e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();if(!await window.mayLeaveQuickReply())return;const url=new URL(location.href);url.searchParams.delete('job');url.hash='records';history.pushState(null,'',url);clearTimeout(timer);selected=null;resetResult();showView(true);};
  $('skip-link').onclick=e=>{e.preventDefault();$('main').focus();};
  async function api(url, options) {
    let response;
    try{response=await fetch(url,options);}catch(e){throw Error('Нет связи с приложением. Повторите действие.');}
    const data = await response.json();
    if (!response.ok) throw Error(data.error || `Ошибка ${response.status}`);
    return data;
  }
  function message(text, error=false) { $('message').textContent=text; $('message').dataset.tone=error?'danger':'success'; }
  async function setupStatus() {
    const s=await api('/api/setup');
    if(!wizardLoaded)wizardLoaded=true;
    $('download-info').textContent=`Официальный источник: ${s.download.source} · revision ${s.download.revision} · ${(s.download.download_bytes/1024**2).toFixed(0)} МиБ. После сбоя повторите загрузку: готовые файлы будут проверены и использованы.`;
    const op=s.operation;
    $('setup-progress').hidden=op.status!=='running';
    if(op.total)$('setup-progress').value=100*op.bytes/op.total;else $('setup-progress').removeAttribute('value');
    $('operation-feedback').textContent=(op.status==='error'?'Ошибка: ':op.status==='done'?'Готово: ':'')+(op.result?.message||op.message||'')+(op.result?.device?' · '+op.result.device+' · реплик: '+op.result.segments:'');
    $('download-model').disabled=op.status==='running';$('probe-model').disabled=op.status==='running';$('probe-custom').disabled=op.status==='running';
    if(op.status==='running'&&!setupPolling){setupPolling=true;setTimeout(()=>{setupPolling=false;setupStatus().catch(e=>message(e.message,true));readiness();},1000);}
    $('setup-summary').textContent=s.verified?'Модель подключена. Распознавание готовится автоматически.':s.model_present?'Проверяем найденную модель…':'Нужно подготовить распознавание. Можно скачать модель или подключить имеющуюся.';
    if(!$('model-path').value)$('model-path').value=s.model_present?s.model_path:'';

    $('setup-toggle').setAttribute('aria-expanded',String(!$('setup-form').hidden));
  }
  async function modelAction(save) {
    const buttons=['pick-model','inspect-model','apply-model'].map($);buttons.forEach(b=>b.disabled=true);
    $('setup-feedback').textContent='Проверяем комплект файлов и контрольную сумму модели…';
    try {
      const r=await api(save?'/api/setup/model':'/api/setup/inspect',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({path:$('model-path').value})});
      $('setup-feedback').textContent=`${r.model} · ${(r.bytes/1024/1024).toFixed(0)} МиБ · файлы проверены.`+(save?' Модель подключена. Нажмите «Подготовить распознавание» в этом разделе.':' Можно подключить модель.');
      if(save){await api('/api/native/prepare',{method:'POST',headers:{'X-App-Instance':instance}});await setupStatus();await readiness();}
    } catch(e){$('setup-feedback').textContent=e.message;}finally{buttons.forEach(b=>b.disabled=false);}
  }
  async function ollamaStatus() {
    try {
      const s=await api('/api/setup/ollama'), list=$('ollama-model');
      $('ollama-connection-current').textContent='Текущее подключение: '+({existing:'Существующая Ollama',service:'Свой сервис',managed:'Управляемая Ollama'}[s.mode]||s.mode)+' · '+s.url+' · '+(s.ownership==='managed'?'Управляется Video Descriptor':'Внешний')+' · '+(s.version?'версия '+s.version:'Сервер недоступен');
      if(!ollamaConnectionLoaded){$('ollama-mode').value=s.mode;$('ollama-service-url').value=s.mode==='service'?s.url:'http://127.0.0.1:11434';ollamaConnectionLoaded=true;connectionMode();}
      const detected=s.mode==='existing'?s:await api('/api/setup/ollama?discover=1');
      $('ollama-existing-info').textContent=detected.service_ready?'Существующая Ollama: '+detected.url+' · '+detected.version+' · модели: '+(detected.models.map(m=>m.name).join(', ')||'нет моделей'):detected.message;
      $('ollama-start-existing').hidden=$('ollama-mode').value!=='existing'||!detected.detected||detected.service_ready;
      const options=s.models.map(m=>{const o=document.createElement('option');o.value=m.name;o.textContent=`${m.name} · ${(m.bytes/1024**3).toFixed(1)} ГиБ`;return o;});
      if(!options.length){const o=document.createElement('option');o.value='';o.textContent='Нет доступных моделей';options.push(o);}
      list.replaceChildren(...options);if(s.models.some(m=>m.name===s.selected))list.value=s.selected;
      $('ollama-connect').disabled=componentBusy||!s.models.length;$('ollama-feedback').textContent=s.message+(s.ready?' · '+s.selected:'');
    }catch(e){$('ollama-feedback').textContent=e.message;}
  }
  function check(label, ready, suffix) { const row=document.createElement('div');row.className='check';const a=document.createElement('span');a.textContent=label;const b=document.createElement('span');b.className='vd-status';b.dataset.tone=ready?'success':'warning';b.textContent=suffix||(ready?'Готово':'Не подключено');row.append(a,b);return row; }
  function systemStatus(ready, preparing=false) {
    $('system-dot').className='dot'+(ready&&!preparing?' good':'');
    $('system-status').textContent=preparing?'Готовим распознавание…':ready?'Распознавание готово':'Нужна настройка распознавания';
  }
  async function readiness() {
    try {
      const d=await api('/api/doctor');$('doctor').textContent=JSON.stringify(d,null,2);
      diarizationConfigured=d.diarization?.state==='configured';$('diarize-run').textContent='Определить говорящих'+(d.diarization?.device?' · '+d.diarization.device.toUpperCase():'');$('diarize-run').disabled=processing;$('diarize-run').title='Выбрать способ обработки и определить говорящих';
      if(d.compute){
        const c=d.compute, chosen=c.selected, ready=chosen&&c.capabilities[chosen].ready;
        const deviceReason=(name)=>{const cap=c.capabilities[name];return c.preparing&&name===chosen?'Запускаем распознавание…':cap.available&&!cap.ready&&cap.model_present&&cap.reason==='Модель не загружена'?'Распознавание не запущено':cap.reason;};
        if(document.activeElement!==$('speech-device'))$('speech-device').value=c.settings.speech_device;
        if(document.activeElement!==$('settings-speech-device'))$('settings-speech-device').value=c.settings.speech_device;
        for(const option of $('speech-device').options){if(option.value==='AUTO')continue;const cap=c.capabilities[option.value];option.disabled=!cap.available;option.textContent=option.value+' · '+deviceReason(option.value);}
        $('device-status').textContent=c.preparing?'Запускаем распознавание с моделью на диске…':c.error||(chosen?`Выбрано: ${c.settings.speech_device} → ${chosen}. Настройка применяется только к новым заданиям.`:'Нет готового поддержанного backend. См. диагностику.');
        $('readiness').replaceChildren(...['NPU','GPU','CPU'].map(name=>check(name,c.capabilities[name].ready,deviceReason(name))),check('Ollama · перевод',d.ollama.ready,d.ollama.ready?'Настроено · без проверки генерации':'Нужна настройка'));
        $('ready-dot').className='dot'+(ready&&d.ffmpeg?' good':'');
        systemStatus(ready&&d.ffmpeg,c.preparing);
        $('start').disabled=uploading||!ready||!d.ffmpeg||c.preparing||!!c.operation;
        $('start-npu').hidden=!!ready||!chosen;$('start-npu').disabled=c.preparing||!!c.operation;
        $('npu-notice').textContent=ready?'Распознавание готово. Можно добавить запись.':'Подготавливаем распознавание в фоне. Выбранный файл сохраняется.';
        if(!componentBusy){$('bootstrap-message').textContent=c.preparing?'Подготавливаем распознавание…':ready?'Распознавание готово':c.error?'Не удалось подготовить распознавание. Повторите.':'Нужно подготовить распознавание';$('prepare-speech').hidden=!!ready||c.preparing;}
        $('ai-summary').textContent=(ready?'Распознавание готово. ':'Распознавание требует подготовки. ')+(d.ollama.ready?'Локальный перевод подключён. ':'Локальный перевод не подключён. ')+(diarizationConfigured?'Определение говорящих доступно.':'Говорящие подготавливаются при первом использовании.');
        try{const events=await api('/api/native/events');$('events').textContent=events.slice(-20).map(e=>`${new Date(e.time_utc).toLocaleTimeString()} · ${actionNames[e.action]||e.action}${e.device||e.requested?' · '+(e.device||e.requested):''}${e.previous_device?' ← '+e.previous_device:''}${e.job_id?' · запись '+e.job_id.slice(0,8):''}`).join('\n')||'Событий пока нет';}catch(e){$('events').textContent='Не удалось обновить историю: '+e.message;}
        return;
      }
      $('readiness').replaceChildren(check('Распознавание · Intel NPU',d.npu.ready),check('Видео и аудио',!!d.ffmpeg),check('Ollama · перевод',d.ollama.ready));
      $('ready-dot').className='dot'+(d.npu.ready&&d.ffmpeg?' good':'');
      systemStatus(d.npu.ready&&d.ffmpeg);
      $('start').disabled=uploading||!d.npu.ready||!d.ffmpeg;
      $('start-npu').hidden=d.npu.ready||!d.can_start_npu;
      $('npu-notice').textContent=d.npu.ready?'Модель готова. Можно добавлять запись.':'Нажмите «Подготовить распознавание», если компоненты уже установлены. Модели автоматически не скачиваются.';
      if(!d.npu.ready&&d.npu_startup?.exit_code!==undefined)$('npu-notice').textContent=`Не удалось загрузить модель (код ${d.npu_startup.exit_code}). Подробности в windows-app/runtime/logs/npu.log. Окружение автоматически не переустанавливается.`;
    } catch(e) { $('system-dot').className='dot';$('system-status').textContent='Нет связи с приложением';$('start').disabled=true;$('device-status').textContent='Не удалось проверить готовность. Обновите диагностику перед запуском.';message('Приложение недоступно: '+e.message,true); }
  }
  async function jobs() {
    const all=await api('/api/jobs');
    const buttons=all.sort((a,b)=>b.created-a.created).map(job=>{
      const b=document.createElement('a');b.className='job';b.href='?job='+encodeURIComponent(job.id)+'#records';b.dataset.job=job.id;if(job.id===selected)b.setAttribute('aria-current','true');const title=document.createElement('strong');title.textContent=job.title||job.filename;const state=document.createElement('span');state.className='vd-status';state.dataset.tone=job.cancelled?'neutral':{running:'info',done:'success',error:'danger'}[job.status]||'neutral';state.textContent=(job.mode==='notes'?'Конспект · ':'')+(job.cancelled?'Остановлено':statusNames[job.status]||job.status);b.append(title,state);b.onclick=e=>{if(e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();select(job.id);};return b;
    });
    const key=JSON.stringify(all.map(job=>[job.id,job.title,job.filename,job.status,job.mode]));
    if($('jobs').dataset.content!==key){
      $('jobs').dataset.content=key;
      if(buttons.length)$('jobs').replaceChildren(...buttons);
      else{const empty=document.createElement('p');empty.className='empty';empty.textContent='Здесь появятся добавленные записи';$('jobs').replaceChildren(empty);}
    }
    for(const link of $('jobs').querySelectorAll('.job')){if(link.dataset.job===selected)link.setAttribute('aria-current','true');else link.removeAttribute('aria-current');}
  }
  function resetResult() {
    window.closeQuickReplyEdit();
    currentJob=null;$('stop-job').hidden=true;$('exports').hidden=true;$('postprocess-actions').hidden=true;$('retry').hidden=true;
    $('result-title').textContent='Загружаем запись…';$('transcript').replaceChildren();$('transcript').dataset.content='';
    $('video').pause();$('video').hidden=true;$('timing-note').textContent='';
  }
  async function select(id) { if(!await window.mayLeaveQuickReply())return;if(id!==selected)resetResult();selected=id;const url=new URL(location.href);url.searchParams.set('job',id);url.hash='records';history.pushState(null,'',url);showView(true);$('result-panel').hidden=false;clearTimeout(timer);poll(); }
  function render(result,job) {
    currentJob=job;
    if(!['new','settings','diagnostics'].includes(location.hash.slice(1)))$('main-heading').textContent=job.title||job.filename||'Запись';
    $('result-panel').hidden=false;$('result-title').textContent=job.title||job.filename;
    $('status').textContent=job.cancelled?'Остановлено':statusNames[job.status]||job.status;
    $('stop-job').hidden=!['queued','running'].includes(job.status);
    $('stop-job').disabled=false;
    $('stop-job').textContent='Стоп';
    $('status').dataset.tone=job.cancelled?'neutral':{running:'info',done:'success',error:'danger'}[job.status]||'neutral';
    const device=result?.device||job.device_plan?.selected;
    const failureMessage=result?.message==='Не удалось получить достоверные таймкоды; см. диагностику фрагмента'?'Модель вернула некорректные временные метки реплик. Этот фрагмент не удалось сохранить. Это ошибка распознавания; повторный запуск может её повторить.':result?.message;
    $('progress-text').textContent=(device?`${job.device_plan?.requested||device} → ${device} · `:'')+((job.status==='error'&&result?.status==='error'&&failureMessage?failureMessage:job.error)||result?.message||(job.status==='done'?(result?.no_speech?'Речь не обнаружена':'Расшифровка готова'):job.status==='running'?'Распознаём запись…':'Ожидаем свободный обработчик'));
    if(job.status==='running'&&result?.duration>0){
      const clock=(seconds)=>{const value=Math.max(0,Math.floor(seconds));return `${Math.floor(value/3600)}:${String(Math.floor(value/60)%60).padStart(2,'0')}:${String(value%60).padStart(2,'0')}`;};
      $('progress-text').textContent+=` · Сохранено ${clock(result.processed||0)} из ${clock(result.duration)} записи`;
    }
    $('progress').hidden=job.status==='error';
    if(job.status==='done'&&result?.status==='done')$('progress').value=100;
    else if(result?.duration>0&&Number.isFinite(result.processed))$('progress').value=Math.max(0,Math.min(100,100*result.processed/result.duration));
    else $('progress').removeAttribute('value');
    if(['postprocess','notes'].includes(job.mode)){
      const phases={queued:'В очереди',notes:'Создаём конспект',translation:'Переводим реплики',done:'Готово'};
      $('progress-text').textContent=job.task==='diarize'?(job.error||result?.message||'Определяем говорящих'):(job.error||`${phases[job.stage]||statusNames[job.status]} · ${job.translation_model||job.construction?.model||'Ollama'}`);
      if(['queued','running'].includes(job.status))$('progress').removeAttribute('value');
    }
    $('retry').hidden=job.status!=='error';
    $('retry').textContent=job.task==='diarize'?'Повторить определение говорящих':result?.segments?.length?'Продолжить из кэша':'Повторить распознавание';
    const done=job.status==='done'&&result?.status==='done';$('exports').hidden=!done;
    $('postprocess-actions').hidden=!done||!result?.segments?.length;
    $('translate-run').disabled=processing;$('notes-run').disabled=processing;$('diarize-run').disabled=processing;
    $('ru-srt').hidden=!done||!result?.has_translation;
    $('open-report').hidden=!done||(job.mode!=='notes'&&job.task!=='notes');
    if(!result){$('video').pause();$('video').hidden=true;$('transcript').replaceChildren();$('transcript').dataset.content='';$('timing-note').textContent='';return;}
    $('video').hidden=!result.video;
    if(result.video){const source='/'+result.video.replaceAll('\\','/');if($('video').dataset.source!==source){$('video').src=source;$('video').dataset.source=source;}}
    if(done){
      const q=new URLSearchParams({folder:job.folder,language:'original'});
      $('vtt').href='/api/subtitles?'+q;$('srt').href='/api/subtitles?'+q+'&format=srt';$('txt').href='/api/transcript-text?'+q;
      $('editor').href='/create?folder='+encodeURIComponent(job.folder);
      $('ru-srt').href='/api/subtitles?'+new URLSearchParams({folder:job.folder,language:'ru',format:'srt'});
      $('open-report').href='/output/'+encodeURIComponent(job.folder)+'/report.html';
    }
    $('timing-note').textContent=job.status==='error'?'':result.speaker_notice|| (result.no_speech?'Речь не обнаружена. Это решение VAD, а не ручная проверка записи.':'Таймкоды относятся к целым репликам. Разделение слов и говорящих в этом режиме не выполняется.');
    const content=JSON.stringify([job.id,result.segments,result.translations,result.speaker_names,result.edit_revision,done,result.no_speech]);
    if($('transcript').dataset.content===content)return;
    $('transcript').dataset.content=content;
    const rows=result.segments.map((segment,index)=>{
      const row=document.createElement('div');row.className='row';const time=document.createElement('button');time.type='button';time.className='vd-button vd-button--quiet vd-button--compact seek';time.textContent=stamp(segment.start)+' — '+stamp(segment.end);time.setAttribute('aria-label','Воспроизвести с '+stamp(segment.start));time.disabled=!Number.isFinite(segment.start)||segment.start<0||!result.video;time.onclick=()=>{$('video').currentTime=segment.start;$('video').play().catch(()=>{});};
      const header=document.createElement('div'),tools=document.createElement('div');header.className='reply-heading';tools.className='reply-tools';header.append(time);row.append(header);
      if(done){const edit=document.createElement('button');edit.type='button';edit.className='vd-button vd-button--compact row-edit';edit.title='Исправить реплику';edit.setAttribute('aria-label','Исправить реплику');const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('width','18');icon.setAttribute('height','18');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-width','2');icon.setAttribute('stroke-linecap','round');icon.setAttribute('stroke-linejoin','round');icon.setAttribute('aria-hidden','true');const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M16 3a2.1 2.1 0 0 1 3 3L7 18l-4 1 1-4L16 3Z M14 5l3 3');icon.append(path);edit.append(icon);edit.onclick=()=>window.editSpeechReply(result,index,$('video'),saved=>render(saved,job));tools.append(edit);}
      const p=document.createElement('p');p.textContent=segment.text;if(done)window.enableQuickReplyEdit(p,result,index,saved=>{if(selected!==job.id)return;render(saved,job);$('transcript').querySelectorAll('.row')[index]?.querySelector('p')?.focus({preventScroll:true});});if(result.diarization_device){if(done){header.append(window.createSpeakerName(result,segment.speaker,saved=>{if(selected!==job.id)return;render(saved,job);$('transcript').querySelectorAll('.speaker-name')[index]?.focus({preventScroll:true});}));tools.prepend(window.createSpeakerSelect(result,index,saved=>{if(selected!==job.id)return;render(saved,job);$('transcript').querySelectorAll('.speaker-select')[index]?.focus({preventScroll:true});}));}else{const speaker=document.createElement('span');speaker.className='vd-status';speaker.textContent=result.speaker_names?.[segment.speaker]||(segment.speaker==='unknown'?'Говорящий не определён':segment.speaker);header.append(speaker);}}header.append(tools);row.append(p);const translated=result.translations?.[segment.id];if(translated){const ru=document.createElement('p');ru.className='translation';ru.textContent=translated;row.append(ru);}return row;
    });
    if(!rows.length){const p=document.createElement('p');p.className='empty';p.textContent=result.no_speech?'Речевых фрагментов не найдено.':job.status==='error'?'Распознавание остановилось до сохранения текста. Причина указана выше. Повторный запуск может завершиться той же ошибкой.':'Текст появится после первого сохранённого фрагмента.';rows.push(p);}
    $('transcript').replaceChildren(...rows);
  }
  async function poll() {
    if(!selected)return;
    const id=selected;
    try{const {job,result}=await api('/api/speech?job='+id);if(id!==selected)return;render(result,job);if(['queued','running'].includes(job.status)){timer=setTimeout(poll,2000);}else{await jobs();}}catch(e){if(id!==selected)return;message(e.message,true);timer=setTimeout(poll,5000);}
  }
  function fileProblem(files, probe=false) {
    const file=files[0], allowed=['mp4','mkv','mov','webm','wav','mp3','m4a','flac','ogg'];
    if(files.length>1)return 'Добавьте один файл за раз.';
    if(!file)return probe?'Сначала выберите свой WAV или нажмите «Проверить на встроенной записи».':'Выберите видео или аудиофайл.';
    if(probe)return file.size>500000?'Для проверки нужен WAV до 500 КБ и до 15 секунд. Выберите меньший файл или встроенную запись.':!file.name.toLowerCase().endsWith('.wav')?'Для проверки выберите WAV. Формат и длительность проверит обработчик.':'';
    return file.size>4*1024**3?'Файл больше 4 ГБ. Выберите меньший файл.':!allowed.includes(file.name.split('.').pop().toLowerCase())?'Формат не поддерживается. Выберите видео или аудио из списка.':'';
  }
  function validateFile(files, required=false) {
    const error=!files.length&&!required?'':fileProblem(files);
    $('file-error').textContent=error;$('file-error').hidden=!error;$('file').setAttribute('aria-invalid',String(!!error));$('drop').setAttribute('aria-invalid',String(!!error));
    return !!files[0]&&!error;
  }
  $('file').onchange=()=>{if($('file').files.length){$('filename').textContent=$('file').files[0].name;validateFile($('file').files);}};
  for(const event of ['dragenter','dragover'])$('drop').addEventListener(event,e=>{e.preventDefault();$('drop').classList.add('over');});
  $('drop').addEventListener('dragleave',()=>{$('drop').classList.remove('over');});
  $('drop').addEventListener('drop',e=>{e.preventDefault();$('drop').classList.remove('over');if(validateFile(e.dataTransfer.files,true)){$('file').files=e.dataTransfer.files;$('file').onchange();}});
  $('upload').onsubmit=e=>{
    e.preventDefault();if(uploading||$('start').disabled)return;const file=$('file').files[0];if(!validateFile($('file').files,true)){$('file').focus();return;}
    const query=new URLSearchParams({filename:file.name,title:$('title').value,mode:'audio',engine:'whisper-local',device:$('speech-device').value,speech_only:'true',language:$('language').value});
    const xhr=new XMLHttpRequest();xhr.open('POST','/api/upload?'+query);uploading=true;$('start').disabled=true;$('start').setAttribute('aria-busy','true');$('start-label').textContent='Копируем запись…';$('upload-progress').removeAttribute('value');$('upload-progress').hidden=false;message('Копируем запись в библиотеку…');
    xhr.upload.onprogress=e=>{if(e.lengthComputable)$('upload-progress').value=100*e.loaded/e.total;};
    xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);if(xhr.status!==202)throw Error(data.error||'Ошибка загрузки');message('Запись добавлена. Можно закрыть окно — обработка продолжится.');select(data.id);jobs().catch(e=>message(e.message,true));}catch(e){message(e.message,true);}};
    xhr.onerror=()=>message('Соединение прервалось. Проверьте диагностику и повторите загрузку.',true);
    xhr.onloadend=()=>{uploading=false;$('start').setAttribute('aria-busy','false');$('start-label').textContent='Расшифровать запись';$('upload-progress').hidden=true;readiness();};xhr.send(file);
  };
  $('stop-job').onclick=async()=>{const id=selected;clearTimeout(timer);$('stop-job').disabled=true;$('stop-job').textContent='Останавливаем…';try{await api('/api/native/cancel?id='+encodeURIComponent(id),{method:'POST',headers:{'X-App-Instance':instance}});message('Останавливаем обработку. Сохранённый текст останется доступен.');poll();}catch(e){message(e.message,true);$('stop-job').disabled=false;$('stop-job').textContent='Стоп';}};
  $('retry').onclick=async()=>{try{await api('/api/retry?id='+selected,{method:'POST'});poll();}catch(e){message(e.message,true);}};
  $('start-npu').onclick=async()=>{message('Запускаем распознавание: загружаем модель с диска в память устройства. Скачивание не требуется.');try{await api('/api/native/prepare',{method:'POST',headers:{'X-App-Instance':instance}});$('start-npu').disabled=true;}catch(e){message(e.message,true);}finally{readiness();}};
  $('speech-device').onchange=async()=>{try{await api('/api/compute-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speech_device:$('speech-device').value})});await api('/api/native/prepare',{method:'POST',headers:{'X-App-Instance':instance}});await readiness();}catch(e){message(e.message,true);}};
  $('settings-speech-device').onchange=()=>{$('speech-device').value=$('settings-speech-device').value;$('speech-device').onchange();};
  $('stop').onclick=async()=>{try{await api('/api/native/stop',{method:'POST',headers:{'X-App-Instance':instance}});clearTimeout(timer);clearInterval(checks);message('Приложение завершено. Эту вкладку можно закрыть.');$('start').disabled=true;}catch(e){message(e.message,true);}};
  $('refresh').onclick=()=>jobs().catch(e=>message(e.message,true));
  async function postprocess(task) {
    if(!currentJob?.folder||processing)return;
    processing=true;$('translate-run').disabled=true;$('notes-run').disabled=true;
    try{const job=await api('/api/native/postprocess',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({folder:currentJob.folder,task})});message('Создана отдельная версия. Исходная расшифровка сохранена.');select(job.id);await jobs();}catch(e){message(e.message,true);}finally{processing=false;$('translate-run').disabled=false;$('notes-run').disabled=false;}
  }
  $('diarize-run').onclick=openSpeakers;
  $('translate-run').onclick=()=>localAI('translate');
  $('notes-run').onclick=()=>localAI('notes');
  $('setup-toggle').onclick=()=>{$('setup-form').hidden=!$('setup-form').hidden;$('setup-toggle').setAttribute('aria-expanded',String(!$('setup-form').hidden));};
  $('ollama-refresh').onclick=ollamaStatus;
  $('ollama-form').onsubmit=async e=>{e.preventDefault();$('ollama-feedback').textContent='Проверяем генерацию перед сохранением модели…';await componentAction('ollama','check',{model:$('ollama-model').value,task:$('ollama-task').value});};
  $('inspect-model').onclick=()=>modelAction(false);
  $('setup-form').onsubmit=e=>{e.preventDefault();modelAction(true);};
  $('pick-model').onclick=async()=>{const b=$('pick-model');b.disabled=true;$('setup-feedback').textContent='Выберите папку в окне Windows…';try{const r=await api('/api/setup/pick-model',{method:'POST',headers:{'X-App-Instance':instance}});if(r.path)$('model-path').value=r.path;$('setup-feedback').textContent=r.path?'Папка выбрана. Теперь проверьте и подключите модель.':'Выбор отменён.';}catch(e){$('setup-feedback').textContent=e.message;}finally{b.disabled=false;}};
  async function setupPost(path, body={}) {return api('/api/setup/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify(body)});}
  async function diagnostics() {
    const d=await api('/api/setup/diagnostics');
    const inv=d.inventory;
    const devices=inv.devices.map(name=>name.split('.')[0]);
    const deviceStatus=(name,listed)=>{
      const available=devices.includes(name);
      const text=available?'Доступен в OpenVINO; готовность модели — в панели AI':listed.length?'Виден в Windows, но недоступен в OpenVINO':'Не обнаружен Windows и OpenVINO';
      return check('Intel '+name+' · распознавание',available,text+(listed.length?' · '+listed.join(', '):''));
    };
    $('setup-diagnostics').replaceChildren(check('CPU',true,d.hardware.cpu),deviceStatus('GPU',d.hardware.intel_gpu),deviceStatus('NPU',d.hardware.intel_npu),check('OpenVINO / GenAI',!!inv.openvino&&!!inv.genai,inv.openvino?`${inv.openvino} / ${inv.genai}`:'Требуется runtime из установщика'),check('Устройства OpenVINO',!!inv.devices.length,inv.devices.join(', ')||'Недоступно'),check('Перевод',d.translation.state==='configured',d.translation.state==='configured'?'Настроено · генерация не проверена':'Требуется настройка'),check('Конспект',d.notes.state==='configured',d.notes.selected||'Требуется настройка'),check('OCR',false,d.ocr.message),check('Диаризация',d.diarization.state==='configured',d.diarization.message));
    if(!document.activeElement.closest('#gemini-form')){$('gemini-model').value=d.gemini.model;$('gemini-billing').value=d.gemini.billing_mode;$('gemini-ack').checked=d.gemini.free_ack;}
    $('gemini-key').placeholder=d.gemini.has_key?'Ключ сохранён':'Введите API-ключ';
  }
  $('setup-open').onclick=()=>{diagnostics().catch(e=>message(e.message,true));};
  $('setup-finish').onclick=async()=>{const b=$('setup-finish'),route=location.hash;b.disabled=true;try{await setupPost('complete');if(location.hash===route){location.hash='records';showView(true);}}catch(e){message(e.message,true);}finally{b.disabled=false;}};
  $('diagnostics-refresh').onclick=async()=>{try{await setupPost('refresh');await diagnostics();await readiness();}catch(e){message(e.message,true);}};
  $('download-model').onclick=()=>componentAction('whisper','install',{confirmed:$('download-consent').checked});
  $('probe-audio').onchange=()=>{if($('probe-audio').files.length)$('probe-filename').textContent=$('probe-audio').files[0].name;};
  async function runProbe(custom=false) {
    const feedback=$('operation-feedback'), buttons=[$('probe-model'),$('probe-custom')];
    const file=custom?$('probe-audio').files[0]:null;
    feedback.scrollIntoView({block:'center',behavior:'auto'});
    if(custom){const error=fileProblem($('probe-audio').files,true);$('probe-audio').setAttribute('aria-invalid',String(!!error));if(error){feedback.textContent=error;$('probe-audio').focus();return;}}
    buttons.forEach(b=>b.disabled=true);
    feedback.textContent=custom?'Отправляем выбранный WAV на проверку…':'Запускаем распознавание встроенной тестовой записи…';
    try{if(custom){await api('/api/setup/probe',{method:'POST',headers:{'X-App-Instance':instance,'Content-Type':'audio/wav'},body:file});}else{await setupPost('probe');}await setupStatus();}
    catch(e){feedback.textContent='Не удалось выполнить проверку: '+e.message;buttons.forEach(b=>b.disabled=false);}
  }
  $('probe-model').onclick=()=>componentAction('whisper','check');
  $('probe-custom').onclick=()=>runProbe(true);
  $('gemini-form').onsubmit=async e=>{e.preventDefault();try{await setupPost('gemini',{api_key:$('gemini-key').value,model:$('gemini-model').value,billing_mode:$('gemini-billing').value,free_ack:$('gemini-ack').checked});$('gemini-key').value='';$('gemini-feedback').textContent='Настройки сохранены. Перевод через Gemini доступен в расширенном редакторе.';await diagnostics();}catch(error){$('gemini-feedback').textContent=error.message;}};
  $('gemini-check').onclick=async()=>{const b=$('gemini-check');b.disabled=true;try{const r=await setupPost('gemini',{check:true});$('gemini-models').replaceChildren(...r.models.map(m=>{const o=document.createElement('option');o.value=m.id;return o;}));$('gemini-feedback').textContent=r.message+(r.available?' Выбранная модель доступна.':' Выберите доступную модель из списка.');}catch(e){$('gemini-feedback').textContent=e.message;}finally{b.disabled=false;}};

  let componentTimer, componentProfiles={}, componentBusy=false;
  const componentNames={not_installed:'Не установлен',installed:'Установлен · нужна проверка',downloading:'Загрузка',installing:'Установка',verifying:'Проверка',ready:'Готово',error:'Ошибка · можно повторить',update_available:'Доступно обновление'};
  async function componentAction(component,action,extra={}) {
    try {
      if(componentBusy&&action!=='cancel')return;
      componentBusy=action!=='cancel';
      await api('/api/components',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({component,action,...extra})});
      await componentStatus();
    }catch(e){message(e.message,true);componentBusy=false;await componentStatus().catch(()=>{});}
  }
  async function componentStatus() {
    const data=await api('/api/components');componentProfiles=data.profiles;componentBusy=!!data.active;
    $('cancel-preparation').hidden=!data.active;
    if(data.active){const active=data.components.find(c=>c.id===data.active);$('bootstrap-message').textContent=active.message+(active.total?' · '+Math.floor(100*(active.bytes||0)/active.total)+'%':'');$('prepare-speech').hidden=true;}
    for(const item of data.components){
      const box=$('component-'+item.id);
      if(!box.componentControls){
        const state=document.createElement('p'),details=document.createElement('p'),progress=document.createElement('progress'),button=document.createElement('button'),remove=document.createElement('button');
        state.className='vd-status';state.setAttribute('role','status');details.className='footnote';progress.className='vd-progress';button.type='button';button.className='vd-button';remove.type='button';remove.className='vd-button vd-button--danger';
        box.replaceChildren(state,details,progress,button,remove);box.componentControls={state,details,progress,button,remove};
      }
      const {state,details,progress,button,remove}=box.componentControls;
      state.dataset.tone=item.state==='error'?'danger':item.state==='ready'?'success':'info';
      state.textContent=(componentNames[item.state]||item.state)+' · '+item.message+(item.fallback_reason?' · '+item.fallback_reason:'');
      details.textContent=[item.version?'Версия: '+item.version:'',item.device?'Устройство: '+item.device:'',item.model?'Модель: '+item.model:'',item.bytes_on_disk?'На диске: '+(item.bytes_on_disk/1024**3).toFixed(2)+' ГиБ':''].filter(Boolean).join(' · ');
      progress.hidden=data.active!==item.id;progress.setAttribute('aria-label',item.name);
      if(item.total){progress.max=item.total;progress.value=item.bytes||0;if(data.active===item.id)state.textContent+=' · '+Math.floor(100*(item.bytes||0)/item.total)+'%';}else progress.removeAttribute('value');
      button.textContent=data.active===item.id?'Остановить':item.state==='error'?'Повторить проверку':'Проверить';button.disabled=!!data.active&&data.active!==item.id;
      button.onclick=()=>componentAction(item.id,data.active===item.id?'cancel':'check',item.id==='diarization'?{device:$('diarization-device').value}:item.id==='ollama'?{model:$('ollama-model').value,task:$('ollama-task').value}:{});
      remove.hidden=!item.path||!!data.active||(item.id==='ollama'&&data.ollama_connection.mode!=='managed');remove.textContent='Удалить окружение';remove.onclick=()=>{if(window.confirm('Удалить только управляемое приложением окружение? Модели и пользовательские файлы сохранятся.'))componentAction(item.id,'remove',{confirmed:true});};
    }
    $('component-summary').replaceChildren(...data.components.map(item=>check(item.name,item.state==='ready',componentNames[item.state])));
    if(!$('component-root').value)$('component-root').value=data.root;
    $('component-directory').textContent='Модели, окружения и проверенные загрузки: '+data.root+'. При обновлении приложения сохраняются.';
    const profile=data.profiles.ollama;
    if(profile)$('ollama-install-info').textContent='Источник: '+profile.source+' · версия '+profile.version+' · '+(profile.bytes/1024**3).toFixed(2)+' ГиБ. Размер распакованного компонента больше.';
    if(!$('ollama-catalog').options.length)for(const model of data.profiles.ollama_models||[]){const o=document.createElement('option');o.value=model.name;o.textContent=model.name+' · ≈'+(model.bytes/1024**3).toFixed(1)+' ГиБ';$('ollama-catalog').append(o);}
    catalogInfo();
    for(const id of ['ollama-install','ollama-pull','diarization-install','ollama-use-connection','ollama-start-existing','ollama-connect'])$(id).disabled=!!data.active;
    if(!$('ollama-model').value)$('ollama-connect').disabled=true;
    clearTimeout(componentTimer);
    if(data.active)componentTimer=setTimeout(()=>componentStatus().then(()=>{if(!componentBusy){ollamaStatus();readiness();setupStatus();}}).catch(e=>message(e.message,true)),1000);
  }
  function catalogInfo(){const model=componentProfiles.ollama_models?.find(m=>m.name===$('ollama-catalog').value);if(model)$('ollama-catalog-info').textContent=model.purpose+' Около '+model.memory_gib+' ГиБ памяти; нужно ≈'+(model.bytes*1.2/1024**3).toFixed(1)+' ГиБ свободного места. Размер ориентировочный, точный прогресс покажет Ollama.';}
  function connectionMode(){
    const mode=$('ollama-mode').value;
    $('ollama-service-fields').hidden=mode!=='service';$('ollama-managed-install').hidden=mode!=='managed';
    $('ollama-use-connection').textContent={existing:'Использовать существующую Ollama',service:'Проверить и использовать сервис',managed:'Подключить установленную управляемую Ollama'}[mode];
    if(mode!=='existing')$('ollama-start-existing').hidden=true;
  }
  $('ollama-mode').onchange=()=>{connectionMode();ollamaStatus().catch(e=>message(e.message,true));};
  $('ollama-use-connection').onclick=()=>componentAction('ollama','connect',{mode:$('ollama-mode').value,url:$('ollama-service-url').value});
  $('ollama-start-existing').onclick=()=>componentAction('ollama','start_existing',{confirmed:true});
  $('ollama-catalog').onchange=catalogInfo;
  $('ollama-install').onclick=()=>componentAction('ollama','install',{confirmed:$('ollama-install-consent').checked,mode:'managed'});
  $('ollama-pull').onclick=()=>componentAction('ollama','pull',{confirmed:$('ollama-pull-consent').checked,model:$('ollama-catalog').value,task:$('ollama-task').value});
  $('diarization-install').onclick=()=>{const token=$('hf-token').value;$('hf-token').value='';componentAction('diarization','install',{confirmed:$('diarization-consent').checked,device:$('diarization-device').value,token});};
  for(const [id,page] of [['hf-terms','terms'],['hf-tokens','tokens']])$(id).onclick=()=>setupPost('external',{page}).catch(e=>message(e.message,true));

  let localTask=null, localFolder=null;
  async function localAI(task){
    try{
      const status=await api('/api/setup/ollama');
      if(status.ready){await postprocess(task);return;}
      localTask=task;localFolder=currentJob?.folder;
      const d=await api('/api/components'), model=d.profiles.ollama_models?.[0], runtime=d.profiles.ollama;
      $('local-ai-info').textContent=status.service_ready?'Выберите установленную языковую модель в настройках AI.':status.mode!=='existing'||status.detected?'Выбранный сервис недоступен. Запустите его или измените подключение в настройках AI.':'Подготовим локальный AI. Источник: '+runtime.source+' и Ollama Library. Объём около '+((runtime.bytes+(model?.bytes||0))/1024**3).toFixed(1)+' ГиБ; модель '+(model?.name||'не выбрана')+'.';
      $('local-ai-go').hidden=status.service_ready||status.mode!=='existing'||status.detected||!model;
      $('local-ai-consent').parentElement.hidden=$('local-ai-go').hidden;
      $('local-ai-dialog').showModal();
    }catch(e){message(e.message,true);}
  }
  $('local-ai-close').onclick=()=>$('local-ai-dialog').close();
  $('local-ai-go').onclick=async()=>{
    $('local-ai-go').disabled=true;
    try{
      const d=await api('/api/components'), model=d.profiles.ollama_models[0];
      await api('/api/components',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({component:'ollama',action:'prepare',mode:'managed',model:model.name,task:localTask==='notes'?'notes':'translation',resume:{folder:localFolder,task:localTask},confirmed:$('local-ai-consent').checked})});
      await componentStatus();
      const folder=localFolder;
      const wait=async()=>{
        const d=await api('/api/components'),item=d.components.find(c=>c.id==='ollama');
        $('local-ai-info').textContent=item.message;
        if(d.active){setTimeout(()=>wait().catch(fail),1000);return;}
        if(item.state!=='ready')throw Error(item.message);
        $('local-ai-go').disabled=false;
        if($('local-ai-dialog').open)$('local-ai-dialog').close();
        if(currentJob?.folder===folder&&item.resumed_job)await select(item.resumed_job);
        await jobs();
      };
      await wait();
    }catch(e){fail(e);}
    function fail(e){$('local-ai-go').disabled=false;$('local-ai-info').textContent=e.message;message(e.message,true);}
  };

  let speakerFolder=null, speakerPending=false, speakerNeedsInstall=false;
  async function openSpeakers(){
    speakerFolder=currentJob?.folder;
    if(!speakerFolder)return;
    $('speaker-dialog').showModal();
    try{await speakerStatus();$('speaker-device').focus();}catch(e){$('speaker-status').textContent='Не удалось проверить готовность. Закройте окно и повторите.';}
  }
  async function speakerStatus(){
    const d=await api('/api/components'), item=d.components.find(c=>c.id==='diarization');
    const health=await api('/api/doctor');
    const diagnostics=await api('/api/setup/diagnostics');
    speakerNeedsInstall=health.diarization?.state!=='configured';
    if(!speakerPending)$('speaker-device').value=health.diarization?.requested_device||'auto';
    for(const option of $('speaker-device').options){const unavailable=option.value==='xpu'&&!diagnostics.hardware.intel_gpu.length;option.disabled=unavailable;const ready=!speakerNeedsInstall&&!!item.proof?.turns?.length&&(option.value==='auto'||option.value===health.diarization?.device);option.textContent=({auto:'Автоматически (рекомендуется)',xpu:'Intel GPU',cpu:'Процессор CPU'}[option.value])+' · '+(unavailable?'недоступно':ready?'готово':'потребуется проверка или подготовка');}
    $('speaker-consent').checked=item.download_consent===true&&item.consent_revision===d.profiles.diarization_model?.revision;
    $('speaker-token').placeholder=d.has_hf_token?'Токен сохранён; можно оставить пустым':'Введите токен чтения';
    $('speaker-install-fields').open=speakerNeedsInstall;
    $('speaker-install-fields').hidden=!speakerNeedsInstall;
    $('speaker-status').textContent=speakerNeedsInstall?'Потребуется подготовка. Подтвердите загрузку и доступ к модели.':(item.proof?.turns?.length?'Готово для ':'Окружение найдено для ')+(health.diarization?.device==='xpu'?'Intel GPU':'процессора')+'. Способ обработки проверим перед запуском.';
    $('speaker-go').textContent=speakerNeedsInstall?'Скачать, подготовить и запустить':'Определить говорящих';
  }
  $('speaker-cancel').onclick=()=>$('speaker-dialog').close();
  $('speaker-dialog').addEventListener('close',()=>{$('speaker-token').value='';$('diarize-run').focus();});
  $('speaker-terms').onclick=()=>setupPost('external',{page:'terms'}).catch(e=>message(e.message,true));
  $('speaker-tokens').onclick=()=>setupPost('external',{page:'tokens'}).catch(e=>message(e.message,true));
  $('speaker-go').onclick=async()=>{
    if(speakerPending)return;
    speakerPending=true;$('speaker-go').disabled=true;$('speaker-device').disabled=true;
    const folder=speakerFolder, device=$('speaker-device').value;
    try{
      const token=$('speaker-token').value;
      const health=await api('/api/doctor');
      const saved=await api('/api/components');
      const previous=saved.components.find(c=>c.id==='diarization');
      const cached=health.diarization?.state==='configured'&&previous.proof?.turns?.length&&health.diarization.requested_device===device;
      if(!cached)await api('/api/components',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({component:'diarization',action:speakerNeedsInstall?'install':'check',device,token,resume:{folder,task:'diarize'},confirmed:$('speaker-consent').checked})});
      await componentStatus();
      $('speaker-token').value='';
      $('speaker-status').textContent='Подготавливаем определение говорящих… Можно закрыть это окно.';
      const wait=async()=>{
        const d=await api('/api/components'),item=d.components.find(c=>c.id==='diarization');
        $('speaker-status').textContent=item.message;
        if(d.active){setTimeout(()=>wait().catch(fail),1000);return;}
        if(!cached&&item.state!=='ready')throw Error(item.message);
        const job=cached?await api('/api/native/postprocess',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({folder,task:'diarize'})}):{id:item.resumed_job};
        speakerPending=false;$('speaker-go').disabled=false;$('speaker-device').disabled=false;
        if($('speaker-dialog').open)$('speaker-dialog').close();
        if(currentJob?.folder===folder)await select(job.id);
        await jobs();await readiness();
      };
      await wait();
    }catch(e){fail(e);}
    function fail(e){speakerPending=false;$('speaker-device').disabled=false;speakerNeedsInstall=true;$('speaker-install-fields').hidden=false;$('speaker-install-fields').open=true;$('speaker-go').textContent='Подготовить и повторить';$('speaker-go').disabled=false;$('speaker-status').textContent=e.message;message(e.message,true);}
  };
  function speechDownloadConsent(profile){
    const dialog=$('speech-download-dialog');
    if(dialog.open)return Promise.resolve(false);
    $('speech-download-info').textContent='Источник: '+profile.source+' · Объём: '+Math.ceil(profile.download_bytes/1024**2)+' МиБ.';
    dialog.returnValue='';
    const result=new Promise(resolve=>dialog.addEventListener('close',()=>{resolve(dialog.returnValue==='download');$('prepare-speech').focus();},{once:true}));
    dialog.showModal();
    return result;
  }
  $('speech-download-confirm').onclick=()=>$('speech-download-dialog').close('download');
  $('speech-download-cancel').onclick=()=>$('speech-download-dialog').close('cancel');
  $('prepare-speech').onclick=async()=>{
    try{
      const s=await api('/api/setup');
      if(s.model_present){await api('/api/native/prepare',{method:'POST',headers:{'X-App-Instance':instance}});await readiness();return;}
      const data=await api('/api/components'), item=data.components.find(c=>c.id==='whisper');
      const consent=(item.download_consent===true&&item.consent_revision===s.download.revision)||await speechDownloadConsent(s.download);
      if(consent)await componentAction('whisper','install',{confirmed:true});
    }catch(e){message(e.message,true);}
  };
  $('save-component-root').onclick=async()=>{const b=$('save-component-root');b.disabled=true;try{const result=await setupPost('component-directory',{directory:$('component-root').value});$('component-root-feedback').textContent=result.message;}catch(e){$('component-root-feedback').textContent=e.message;}finally{b.disabled=false;}};
  $('cancel-preparation').onclick=async()=>{const d=await api('/api/components');if(d.active)await componentAction(d.active,'cancel');};

  for(const section of document.querySelectorAll('.ai-section')){const summary=section.querySelector(':scope > summary');summary.setAttribute('aria-expanded',String(section.open));section.addEventListener('toggle',()=>summary.setAttribute('aria-expanded',String(section.open)));}
  api('/health').then(h=>{instance=h.instance;return Promise.all([readiness(),jobs(),setupStatus(),componentStatus()]).then(()=>Promise.allSettled([ollamaStatus(),diagnostics()]));}).then(()=>{if(selected)poll();}).catch(e=>message(e.message,true));
  const checks=setInterval(()=>{readiness();jobs().catch(()=>{});},15000);
})();
