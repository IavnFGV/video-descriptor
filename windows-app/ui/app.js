(() => {
  const $ = id => document.getElementById(id);
  let wizardLoaded=false, setupPolling=false;
  let instance, selected = new URLSearchParams(location.search).get('job'), timer, uploading=false, currentJob, processing=false;
  const statusNames = {queued:'В очереди', running:'Обрабатываем', done:'Готово', error:'Нужна проверка'};
  const actionNames = {translation_model_configured:'Модель перевода подключена',model_configured:'Модель подключена',settings_changed:'Настройки сохранены',device_selected:'Устройство выбрано',device_loading:'Загрузка модели',device_ready:'Модель готова',device_skipped:'Устройство пропущено',device_attempt_failed:'Ошибка устройства',device_fallback:'Переход на другое устройство',job_added:'Запись добавлена',job_device_snapshot:'Устройство закреплено за записью',job_started:'Обработка начата',job_finished:'Обработка завершена',job_failed:'Ошибка обработки',job_retried:'Повтор обработки',transcript_edited:'Текст исправлен',export:'Экспорт'};
  const stamp = s => {
    if (!Number.isFinite(s) || s < 0) return 'метка не определена';
    const total=Math.floor(s);
    return [Math.floor(total/3600),Math.floor(total/60)%60,total%60].map(n=>String(n).padStart(2,'0')).join(':');
  };
  function showView(focus=false) {
    const view=['settings','diagnostics'].includes(location.hash.slice(1))?location.hash.slice(1):'records';
    $('records-view').hidden=view!=='records';$('setup-wizard').hidden=view!=='settings';$('diagnostics-view').hidden=view!=='diagnostics';
    for(const [id,name] of [['records-open','records'],['setup-open','settings'],['diagnostics-open','diagnostics']]){
      if(name===view)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current');
    }
    $('view-label').textContent={records:'Записи',settings:'Настройки AI',diagnostics:'Диагностика'}[view];
    $('main-heading').textContent={records:'Новая запись',settings:'Настройки AI',diagnostics:'Диагностика'}[view];
    $('view-description').textContent={records:'Добавьте файл, получите расшифровку и проверьте её по записи.',settings:'Сначала подготовьте распознавание. Перевод и конспект можно подключить позже.',diagnostics:'Проверьте компоненты, доступность устройств и историю действий.'}[view];
    if(focus)$('main-heading').focus();
  }
  window.addEventListener('hashchange',()=>showView(true));
  window.addEventListener('popstate',()=>{
    const id=new URLSearchParams(location.search).get('job');
    if(id!==selected){resetResult();selected=id;clearTimeout(timer);$('result-panel').hidden=!id;if(id)poll();}
    showView();
  });
  showView();
  $('skip-link').onclick=e=>{e.preventDefault();$('main').focus();};
  async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw Error(data.error || `Ошибка ${response.status}`);
    return data;
  }
  function message(text, error=false) { $('message').textContent=text; $('message').dataset.tone=error?'danger':'success'; }
  async function setupStatus() {
    const s=await api('/api/setup');
    if(!wizardLoaded){if(!s.completed&&!selected&&!location.hash){history.replaceState(null,'',location.search+'#settings');showView();}wizardLoaded=true;}
    $('download-info').textContent=`Официальный источник: ${s.download.source} · revision ${s.download.revision} · ${(s.download.download_bytes/1024**2).toFixed(0)} МиБ. После сбоя повторите загрузку: готовые файлы будут проверены и использованы.`;
    const op=s.operation;
    $('setup-progress').hidden=op.status!=='running';
    if(op.total)$('setup-progress').value=100*op.bytes/op.total;else $('setup-progress').removeAttribute('value');
    $('operation-feedback').textContent=(op.status==='error'?'Ошибка: ':op.status==='done'?'Готово: ':'')+(op.result?.message||op.message||'')+(op.result?.device?' · '+op.result.device+' · реплик: '+op.result.segments:'');
    $('download-model').disabled=op.status==='running';$('probe-model').disabled=op.status==='running';$('probe-custom').disabled=op.status==='running';
    if(op.status==='running'&&!setupPolling){setupPolling=true;setTimeout(()=>{setupPolling=false;setupStatus().catch(e=>message(e.message,true));readiness();},1000);}
    $('setup-summary').textContent=s.verified?'Модель подключена и проверена. Можно подготовить распознавание.':s.model_present?'Найдена существующая модель. Проверьте и подключите её в мастере.':'Для распознавания нужно подключить модель. Начните с выбора папки.';
    if(!$('model-path').value)$('model-path').value=s.model_present?s.model_path:'';
    if(!s.model_present)$('setup-form').hidden=false;
    $('setup-toggle').setAttribute('aria-expanded',String(!$('setup-form').hidden));
  }
  async function modelAction(save) {
    const buttons=['pick-model','inspect-model','apply-model'].map($);buttons.forEach(b=>b.disabled=true);
    $('setup-feedback').textContent='Проверяем комплект файлов и контрольную сумму модели…';
    try {
      const r=await api(save?'/api/setup/model':'/api/setup/inspect',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({path:$('model-path').value})});
      $('setup-feedback').textContent=`${r.model} · ${(r.bytes/1024/1024).toFixed(0)} МиБ · файлы проверены.`+(save?' Модель подключена. Нажмите «Подготовить распознавание» в этом разделе.':' Можно подключить модель.');
      if(save){await setupStatus();await readiness();}
    } catch(e){$('setup-feedback').textContent=e.message;}finally{buttons.forEach(b=>b.disabled=false);}
  }
  async function ollamaStatus() {
    try {
      const s=await api('/api/setup/ollama'), list=$('ollama-model');
      const options=s.models.map(m=>{const o=document.createElement('option');o.value=m.name;o.textContent=`${m.name} · ${(m.bytes/1024**3).toFixed(1)} ГиБ`;return o;});
      if(!options.length){const o=document.createElement('option');o.value='';o.textContent='Нет доступных моделей';options.push(o);}
      list.replaceChildren(...options);if(s.models.some(m=>m.name===s.selected))list.value=s.selected;
      $('ollama-connect').disabled=!s.models.length;$('ollama-feedback').textContent=s.message+(s.ready?' · '+s.selected:'');
    }catch(e){$('ollama-feedback').textContent=e.message;}
  }
  function check(label, ready, suffix) { const row=document.createElement('div');row.className='check';const a=document.createElement('span');a.textContent=label;const b=document.createElement('span');b.className='vd-status';b.dataset.tone=ready?'success':'warning';b.textContent=suffix||(ready?'Готово':'Не подключено');row.append(a,b);return row; }
  async function readiness() {
    try {
      const d=await api('/api/doctor');$('doctor').textContent=JSON.stringify(d,null,2);
      if(d.compute){
        const c=d.compute, chosen=c.selected, ready=chosen&&c.capabilities[chosen].ready;
        $('speech-device').value=c.settings.speech_device;
        for(const option of $('speech-device').options){if(option.value==='AUTO')continue;const cap=c.capabilities[option.value];option.disabled=!cap.available;option.textContent=option.value+' · '+cap.reason;}
        $('device-status').textContent=c.preparing?'Подготавливаем модель…':c.error||(chosen?`Выбрано: ${c.settings.speech_device} → ${chosen}. Настройка применяется только к новым заданиям.`:'Нет готового поддержанного backend. См. диагностику.');
        $('readiness').replaceChildren(...['NPU','GPU','CPU'].map(name=>check(name,c.capabilities[name].ready,c.capabilities[name].reason)),check('Ollama · перевод',d.ollama.ready,d.ollama.ready?'Настроено · без проверки генерации':'Нужна настройка'));
        $('ready-dot').className='dot'+(ready&&d.ffmpeg?' good':'');
        $('start').disabled=uploading||!ready||!d.ffmpeg||c.preparing||!!c.operation;
        $('start-npu').hidden=!!ready||!chosen;$('start-npu').disabled=c.preparing||!!c.operation;
        $('npu-notice').textContent=ready?'Модель готова. Можно добавлять запись.':'Подготовка использует установленную модель, без скачивания весов.';
        try{const events=await api('/api/native/events');$('events').textContent=events.slice(-20).map(e=>`${new Date(e.time_utc).toLocaleTimeString()} · ${actionNames[e.action]||e.action}${e.device||e.requested?' · '+(e.device||e.requested):''}${e.previous_device?' ← '+e.previous_device:''}${e.job_id?' · запись '+e.job_id.slice(0,8):''}`).join('\n')||'Событий пока нет';}catch(e){$('events').textContent='Не удалось обновить историю: '+e.message;}
        return;
      }
      $('readiness').replaceChildren(check('Распознавание · Intel NPU',d.npu.ready),check('Видео и аудио',!!d.ffmpeg),check('Ollama · перевод',d.ollama.ready));
      $('ready-dot').className='dot'+(d.npu.ready&&d.ffmpeg?' good':'');
      $('start').disabled=uploading||!d.npu.ready||!d.ffmpeg;
      $('start-npu').hidden=d.npu.ready||!d.can_start_npu;
      $('npu-notice').textContent=d.npu.ready?'Модель готова. Можно добавлять запись.':'Нажмите «Подготовить распознавание», если компоненты уже установлены. Модели автоматически не скачиваются.';
      if(!d.npu.ready&&d.npu_startup?.exit_code!==undefined)$('npu-notice').textContent=`Не удалось загрузить модель (код ${d.npu_startup.exit_code}). Подробности в windows-app/runtime/logs/npu.log. Окружение автоматически не переустанавливается.`;
    } catch(e) { $('start').disabled=true;$('device-status').textContent='Не удалось проверить готовность. Обновите диагностику перед запуском.';message('Приложение недоступно: '+e.message,true); }
  }
  async function jobs() {
    const all=await api('/api/jobs');
    const buttons=all.sort((a,b)=>b.created-a.created).map(job=>{
      const b=document.createElement('a');b.className='job';b.href='?job='+encodeURIComponent(job.id)+'#records';b.dataset.job=job.id;if(job.id===selected)b.setAttribute('aria-current','true');const title=document.createElement('strong');title.textContent=job.title||job.filename;const state=document.createElement('span');state.className='vd-status';state.dataset.tone={running:'info',done:'success',error:'danger'}[job.status]||'neutral';state.textContent=(job.mode==='notes'?'Конспект · ':'')+(statusNames[job.status]||job.status);b.append(title,state);b.onclick=e=>{if(e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();select(job.id);};return b;
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
    currentJob=null;$('exports').hidden=true;$('postprocess-actions').hidden=true;$('retry').hidden=true;
    $('result-title').textContent='Загружаем запись…';$('transcript').replaceChildren();$('transcript').dataset.content='';
    $('video').pause();$('video').hidden=true;$('timing-note').textContent='';
  }
  function select(id) { if(id!==selected)resetResult();selected=id;const url=new URL(location.href);url.searchParams.set('job',id);url.hash='records';history.replaceState(null,'',url);showView();$('result-panel').hidden=false;clearTimeout(timer);poll(); }
  function render(result,job) {
    currentJob=job;
    $('result-panel').hidden=false;$('result-title').textContent=job.title||job.filename;
    $('status').textContent=statusNames[job.status]||job.status;
    $('status').dataset.tone={running:'info',done:'success',error:'danger'}[job.status]||'neutral';
    const device=result?.device||job.device_plan?.selected;
    $('progress-text').textContent=(device?`${job.device_plan?.requested||device} → ${device} · `:'')+(job.error||result?.message||(job.status==='done'?(result?.no_speech?'Речь не обнаружена':'Расшифровка готова'):job.status==='running'?'Распознаём запись…':'Ожидаем свободный обработчик'));
    if(job.status==='done'&&result?.status==='done')$('progress').value=100;
    else if(result?.duration>0&&Number.isFinite(result.processed))$('progress').value=Math.max(0,Math.min(100,100*result.processed/result.duration));
    else $('progress').removeAttribute('value');
    if(['postprocess','notes'].includes(job.mode)){
      const phases={queued:'В очереди',notes:'Создаём конспект',translation:'Переводим реплики',done:'Готово'};
      $('progress-text').textContent=job.error||`${phases[job.stage]||statusNames[job.status]} · ${job.translation_model||job.construction?.model||'Ollama'}`;
      if(['queued','running'].includes(job.status))$('progress').removeAttribute('value');
    }
    $('retry').hidden=job.status!=='error';
    const done=job.status==='done'&&result?.status==='done';$('exports').hidden=!done;
    $('postprocess-actions').hidden=!done||!result?.segments?.length;
    $('translate-run').disabled=processing;$('notes-run').disabled=processing;
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
    $('timing-note').textContent=result.no_speech?'Речь не обнаружена. Это решение VAD, а не ручная проверка записи.':'Таймкоды относятся к целым репликам. Разделение слов и говорящих в этом режиме не выполняется.';
    const content=JSON.stringify([job.id,result.segments,result.translations,result.edit_revision,done,result.no_speech]);
    if($('transcript').dataset.content===content)return;
    $('transcript').dataset.content=content;
    const rows=result.segments.map((segment,index)=>{
      const row=document.createElement('div');row.className='row';const time=document.createElement('button');time.type='button';time.className='vd-button vd-button--quiet vd-button--compact seek';time.textContent=stamp(segment.start)+' — '+stamp(segment.end);time.setAttribute('aria-label','Воспроизвести с '+stamp(segment.start));time.disabled=!Number.isFinite(segment.start)||segment.start<0||!result.video;time.onclick=()=>{$('video').currentTime=segment.start;$('video').play().catch(()=>{});};
      if(done){const edit=document.createElement('button');edit.type='button';edit.className='vd-button vd-button--compact row-edit';edit.textContent='Исправить';edit.onclick=()=>window.editSpeechReply(result,index,$('video'),saved=>render(saved,job));row.append(edit);}
      const p=document.createElement('p');p.textContent=segment.text;row.append(time,p);const translated=result.translations?.[segment.id];if(translated){const ru=document.createElement('p');ru.className='translation';ru.textContent=translated;row.append(ru);}return row;
    });
    if(!rows.length){const p=document.createElement('p');p.className='empty';p.textContent=result.no_speech?'Речевых фрагментов не найдено.':'Текст появится после первого сохранённого фрагмента.';rows.push(p);}
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
  $('retry').onclick=async()=>{try{await api('/api/retry?id='+selected,{method:'POST'});poll();}catch(e){message(e.message,true);}};
  $('start-npu').onclick=async()=>{message('Загружаем выбранную модель. Ничего не скачиваем.');try{await api('/api/native/prepare',{method:'POST',headers:{'X-App-Instance':instance}});$('start-npu').disabled=true;}catch(e){message(e.message,true);}finally{readiness();}};
  $('speech-device').onchange=async()=>{try{await api('/api/compute-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speech_device:$('speech-device').value})});await readiness();}catch(e){message(e.message,true);}};
  $('stop').onclick=async()=>{try{await api('/api/native/stop',{method:'POST',headers:{'X-App-Instance':instance}});clearTimeout(timer);clearInterval(checks);message('Приложение завершено. Эту вкладку можно закрыть.');$('start').disabled=true;}catch(e){message(e.message,true);}};
  $('refresh').onclick=()=>jobs().catch(e=>message(e.message,true));
  async function postprocess(task) {
    if(!currentJob?.folder||processing)return;
    processing=true;$('translate-run').disabled=true;$('notes-run').disabled=true;
    try{const job=await api('/api/native/postprocess',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({folder:currentJob.folder,task})});message('Создана отдельная версия. Исходная расшифровка сохранена.');select(job.id);await jobs();}catch(e){message(e.message,true);}finally{processing=false;$('translate-run').disabled=false;$('notes-run').disabled=false;}
  }
  $('translate-run').onclick=()=>postprocess('translate');
  $('notes-run').onclick=()=>postprocess('notes');
  $('setup-toggle').onclick=()=>{$('setup-form').hidden=!$('setup-form').hidden;$('setup-toggle').setAttribute('aria-expanded',String(!$('setup-form').hidden));};
  $('ollama-refresh').onclick=ollamaStatus;
  $('ollama-form').onsubmit=async e=>{e.preventDefault();const b=$('ollama-connect');b.disabled=true;try{const s=await api('/api/setup/ollama',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({model:$('ollama-model').value,task:$('ollama-task').value})});$('ollama-feedback').textContent='Подключена '+s.selected+'. Назначение: '+$('ollama-task').selectedOptions[0].textContent+'.';await readiness();}catch(error){$('ollama-feedback').textContent=error.message;}finally{b.disabled=false;}};
  $('inspect-model').onclick=()=>modelAction(false);
  $('setup-form').onsubmit=e=>{e.preventDefault();modelAction(true);};
  $('pick-model').onclick=async()=>{const b=$('pick-model');b.disabled=true;$('setup-feedback').textContent='Выберите папку в окне Windows…';try{const r=await api('/api/setup/pick-model',{method:'POST',headers:{'X-App-Instance':instance}});if(r.path)$('model-path').value=r.path;$('setup-feedback').textContent=r.path?'Папка выбрана. Теперь проверьте и подключите модель.':'Выбор отменён.';}catch(e){$('setup-feedback').textContent=e.message;}finally{b.disabled=false;}};
  async function setupPost(path, body={}) {return api('/api/setup/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify(body)});}
  async function diagnostics() {
    const d=await api('/api/setup/diagnostics');
    const inv=d.inventory;
    $('setup-diagnostics').replaceChildren(check('CPU',true,d.hardware.cpu),check('Intel GPU · обнаружение',!!d.hardware.intel_gpu.length,d.hardware.intel_gpu.join(', ')||'Не обнаружен'),check('Intel NPU · обнаружение',!!d.hardware.intel_npu.length,d.hardware.intel_npu.join(', ')||'Не обнаружен'),check('OpenVINO / GenAI',!!inv.openvino&&!!inv.genai,inv.openvino?`${inv.openvino} / ${inv.genai}`:'Требуется runtime из установщика'),check('Устройства OpenVINO',!!inv.devices.length,inv.devices.join(', ')||'Недоступно'),check('Перевод',d.translation.state==='configured',d.translation.state==='configured'?'Настроено · генерация не проверена':'Требуется настройка'),check('Конспект',d.notes.state==='configured',d.notes.selected||'Требуется настройка'),check('OCR',false,d.ocr.message),check('Диаризация',false,d.diarization.message));
    if(!document.activeElement.closest('#gemini-form')){$('gemini-model').value=d.gemini.model;$('gemini-billing').value=d.gemini.billing_mode;$('gemini-ack').checked=d.gemini.free_ack;}
    $('gemini-key').placeholder=d.gemini.has_key?'Ключ сохранён':'Введите API-ключ';
  }
  $('setup-open').onclick=()=>{diagnostics().catch(e=>message(e.message,true));};
  $('setup-finish').onclick=async()=>{try{await setupPost('complete');location.hash='records';showView(true);}catch(e){message(e.message,true);}};
  $('diagnostics-refresh').onclick=async()=>{try{await setupPost('refresh');await diagnostics();await readiness();}catch(e){message(e.message,true);}};
  $('download-model').onclick=async()=>{try{await setupPost('download',{confirmed:$('download-consent').checked});await setupStatus();}catch(e){$('operation-feedback').textContent=e.message;}};
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
  $('probe-model').onclick=()=>runProbe();
  $('probe-custom').onclick=()=>runProbe(true);
  $('gemini-form').onsubmit=async e=>{e.preventDefault();try{await setupPost('gemini',{api_key:$('gemini-key').value,model:$('gemini-model').value,billing_mode:$('gemini-billing').value,free_ack:$('gemini-ack').checked});$('gemini-key').value='';$('gemini-feedback').textContent='Настройки сохранены. Перевод через Gemini доступен в расширенном редакторе.';await diagnostics();}catch(error){$('gemini-feedback').textContent=error.message;}};
  $('gemini-check').onclick=async()=>{const b=$('gemini-check');b.disabled=true;try{const r=await setupPost('gemini',{check:true});$('gemini-models').replaceChildren(...r.models.map(m=>{const o=document.createElement('option');o.value=m.id;return o;}));$('gemini-feedback').textContent=r.message+(r.available?' Выбранная модель доступна.':' Выберите доступную модель из списка.');}catch(e){$('gemini-feedback').textContent=e.message;}finally{b.disabled=false;}};
  api('/health').then(h=>{instance=h.instance;return Promise.all([readiness(),jobs(),setupStatus(),ollamaStatus(),diagnostics()]);}).then(()=>{if(selected)poll();}).catch(e=>message(e.message,true));
  const checks=setInterval(()=>{readiness();jobs().catch(()=>{});},15000);
})();
