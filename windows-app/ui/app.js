(() => {
  const $ = id => document.getElementById(id);
  let instance, selected = new URLSearchParams(location.search).get('job'), timer, uploading=false, currentJob, processing=false;
  const statusNames = {queued:'В очереди', running:'Обрабатываем', done:'Готово', error:'Нужна проверка'};
  const actionNames = {translation_model_configured:'Модель перевода подключена',model_configured:'Модель подключена',settings_changed:'Настройки сохранены',device_selected:'Устройство выбрано',device_loading:'Загрузка модели',device_ready:'Модель готова',device_skipped:'Устройство пропущено',device_attempt_failed:'Ошибка устройства',device_fallback:'Переход на другое устройство',job_added:'Запись добавлена',job_device_snapshot:'Устройство закреплено за записью',job_started:'Обработка начата',job_finished:'Обработка завершена',job_failed:'Ошибка обработки',job_retried:'Повтор обработки',transcript_edited:'Текст исправлен',export:'Экспорт'};
  const stamp = s => new Date(Math.max(0,s)*1000).toISOString().slice(11,19);
  async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw Error(data.error || `Ошибка ${response.status}`);
    return data;
  }
  function message(text, error=false) { $('message').textContent=text; $('message').style.color=error?'#a04b30':'#5b7760'; }
  async function setupStatus() {
    const s=await api('/api/setup');
    $('setup-summary').textContent=s.verified?'Модель подключена и проверена. Можно подготовить распознавание.':s.model_present?'Найдена существующая модель. Проверьте и подключите её в мастере.':'Для распознавания нужно подключить модель. Начните с выбора папки.';
    if(!$('model-path').value)$('model-path').value=s.model_present?s.model_path:'';
    if(!s.model_present)$('setup-form').hidden=false;
  }
  async function modelAction(save) {
    const buttons=['pick-model','inspect-model','apply-model'].map($);buttons.forEach(b=>b.disabled=true);
    $('setup-feedback').textContent='Проверяем комплект файлов и контрольную сумму модели…';
    try {
      const r=await api(save?'/api/setup/model':'/api/setup/inspect',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({path:$('model-path').value})});
      $('setup-feedback').textContent=`${r.model} · ${(r.bytes/1024/1024).toFixed(0)} МиБ · файлы проверены.`+(save?' Модель подключена. Нажмите «Подготовить распознавание» в панели готовности.':' Можно подключить модель.');
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
  function check(label, ready, suffix) { const row=document.createElement('div');row.className='check';const a=document.createElement('span');a.textContent=label;const b=document.createElement('span');b.className=ready?'good':'warning';b.textContent=suffix||(ready?'Готово':'Не подключено');row.append(a,b);return row; }
  async function readiness() {
    try {
      const d=await api('/api/doctor');$('doctor').textContent=JSON.stringify(d,null,2);
      if(d.compute){
        const c=d.compute, chosen=c.selected, ready=chosen&&c.capabilities[chosen].ready;
        $('speech-device').value=c.settings.speech_device;
        for(const option of $('speech-device').options){if(option.value==='AUTO')continue;const cap=c.capabilities[option.value];option.disabled=!cap.available;option.textContent=option.value+' · '+cap.reason;}
        $('device-status').textContent=c.preparing?'Подготавливаем модель…':c.error||(chosen?`Выбрано: ${c.settings.speech_device} → ${chosen}. Настройка применяется только к новым заданиям.`:'Нет готового поддержанного backend. См. диагностику.');
        $('readiness').replaceChildren(...['NPU','GPU','CPU'].map(name=>check(name,c.capabilities[name].ready,c.capabilities[name].reason)),check('Ollama · перевод',d.ollama.ready,d.ollama.ready?'Модель установлена':'Нужна настройка'));
        $('ready-dot').className='dot'+(ready&&d.ffmpeg?' good':'');
        $('start').disabled=uploading||!ready||!d.ffmpeg||c.preparing;
        $('start-npu').hidden=!!ready||!chosen;$('start-npu').disabled=c.preparing;
        $('npu-notice').textContent=ready?'Модель готова. Можно добавлять запись.':'Подготовка использует установленную модель, без скачивания весов.';
        const events=await api('/api/native/events');$('events').textContent=events.slice(-20).map(e=>`${new Date(e.time_utc).toLocaleTimeString()} · ${actionNames[e.action]||e.action}${e.device||e.requested?' · '+(e.device||e.requested):''}${e.previous_device?' ← '+e.previous_device:''}${e.job_id?' · запись '+e.job_id.slice(0,8):''}`).join('\n')||'Событий пока нет';
        return;
      }
      $('readiness').replaceChildren(check('Распознавание · Intel NPU',d.npu.ready),check('Видео и аудио',!!d.ffmpeg),check('Ollama · перевод',d.ollama.ready));
      $('ready-dot').className='dot'+(d.npu.ready&&d.ffmpeg?' good':'');
      $('start').disabled=uploading||!d.npu.ready||!d.ffmpeg;
      $('start-npu').hidden=d.npu.ready||!d.can_start_npu;
      $('npu-notice').textContent=d.npu.ready?'Модель готова. Можно добавлять запись.':'Нажмите «Подготовить распознавание», если компоненты уже установлены. Модели автоматически не скачиваются.';
      if(!d.npu.ready&&d.npu_startup?.exit_code!==undefined)$('npu-notice').textContent=`Не удалось загрузить модель (код ${d.npu_startup.exit_code}). Подробности в windows-app/runtime/logs/npu.log. Окружение автоматически не переустанавливается.`;
    } catch(e) { message('Приложение недоступно: '+e.message,true); }
  }
  async function jobs() {
    const all=await api('/api/jobs');
    const buttons=all.sort((a,b)=>b.created-a.created).map(job=>{
      const b=document.createElement('button');b.className='job';const title=document.createElement('strong');title.textContent=job.title||job.filename;const state=document.createElement('small');state.textContent=(job.mode==='notes'?'Конспект · ':'')+(statusNames[job.status]||job.status);b.append(title,state);b.onclick=()=>select(job.id);return b;
    });
    if(buttons.length)$('jobs').replaceChildren(...buttons);
  }
  function select(id) { selected=id;history.replaceState(null,'','?job='+id);$('result-panel').hidden=false;clearTimeout(timer);poll(); }
  function render(result,job) {
    currentJob=job;
    $('result-panel').hidden=false;$('result-title').textContent=job.title||job.filename;
    $('status').textContent=statusNames[job.status]||job.status;
    const device=result?.device||job.device_plan?.selected;
    $('progress-text').textContent=(device?`${job.device_plan?.requested||device} → ${device} · `:'')+(job.error||result?.message||'Ожидаем свободный обработчик');
    $('progress').value=result?.duration?Math.min(100,100*result.processed/result.duration):0;
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
    if(!result)return;
    const source='/'+result.video.replaceAll('\\','/');if($('video').dataset.source!==source){$('video').src=source;$('video').dataset.source=source;}
    if(done){
      const q=new URLSearchParams({folder:job.folder,language:'original'});
      $('vtt').href='/api/subtitles?'+q;$('srt').href='/api/subtitles?'+q+'&format=srt';$('txt').href='/api/transcript-text?'+q;
      $('editor').href='/create?folder='+encodeURIComponent(job.folder);
      $('ru-srt').href='/api/subtitles?'+new URLSearchParams({folder:job.folder,language:'ru',format:'srt'});
      $('open-report').href='/output/'+encodeURIComponent(job.folder)+'/report.html';
    }
    $('timing-note').textContent=result.no_speech?'Речь не обнаружена. Это решение VAD, а не ручная проверка записи.':'Таймкоды относятся к целым репликам. Разделение слов и говорящих в этом режиме не выполняется.';
    const rows=result.segments.map((segment,index)=>{
      const row=document.createElement('div');row.className='row';const time=document.createElement('time');time.textContent=stamp(segment.start)+' — '+stamp(segment.end);time.onclick=()=>{$('video').currentTime=segment.start;$('video').play().catch(()=>{});};
      if(done){const edit=document.createElement('button');edit.textContent='Исправить';edit.onclick=()=>window.editSpeechReply(result,index,$('video'),saved=>render(saved,job));row.append(edit);}
      const p=document.createElement('p');p.textContent=segment.text;row.append(time,p);const translated=result.translations?.[segment.id];if(translated){const ru=document.createElement('p');ru.className='translation';ru.textContent=translated;row.append(ru);}return row;
    });
    if(!rows.length){const p=document.createElement('p');p.className='empty';p.textContent=result.no_speech?'Речевых фрагментов не найдено.':'Текст появится после первого сохранённого фрагмента.';rows.push(p);}
    $('transcript').replaceChildren(...rows);
  }
  async function poll() {
    if(!selected)return;
    const id=selected;
    try{const {job,result}=await api('/api/speech?job='+id);if(id!==selected)return;render(result,job);if(['queued','running'].includes(job.status)){timer=setTimeout(poll,2000);}else{await jobs();}}catch(e){message(e.message,true);timer=setTimeout(poll,5000);}
  }
  $('file').onchange=()=>{$('filename').textContent=$('file').files[0]?.name||'Перетащите запись сюда';};
  for(const event of ['dragenter','dragover'])$('drop').addEventListener(event,e=>{e.preventDefault();$('drop').classList.add('over');});
  $('drop').addEventListener('dragleave',()=>{$('drop').classList.remove('over');});
  $('drop').addEventListener('drop',e=>{e.preventDefault();$('drop').classList.remove('over');if(e.dataTransfer.files.length===1){$('file').files=e.dataTransfer.files;$('file').onchange();}else message('Добавьте один файл за раз',true);});
  $('upload').onsubmit=e=>{
    e.preventDefault();const file=$('file').files[0];if(!file||uploading)return;
    if(file.size>4*1024**3){message('Файл больше 4 ГБ',true);return;}
    const query=new URLSearchParams({filename:file.name,title:$('title').value,mode:'audio',engine:'whisper-local',device:$('speech-device').value,speech_only:'true',language:$('language').value});
    const xhr=new XMLHttpRequest();xhr.open('POST','/api/upload?'+query);uploading=true;$('start').disabled=true;$('upload-progress').hidden=false;message('Копируем запись в библиотеку…');
    xhr.upload.onprogress=e=>{if(e.lengthComputable)$('upload-progress').value=100*e.loaded/e.total;};
    xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);if(xhr.status!==202)throw Error(data.error||'Ошибка загрузки');message('Запись добавлена. Можно закрыть вкладку — обработка продолжится.');select(data.id);jobs().catch(e=>message(e.message,true));}catch(e){message(e.message,true);}finally{uploading=false;$('upload-progress').hidden=true;readiness();}};
    xhr.onerror=()=>{uploading=false;message('Соединение прервалось. Откройте приложение повторно.',true);$('start').disabled=false;};xhr.send(file);
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
  $('setup-toggle').onclick=()=>{$('setup-form').hidden=!$('setup-form').hidden;};
  $('ollama-refresh').onclick=ollamaStatus;
  $('ollama-form').onsubmit=async e=>{e.preventDefault();const b=$('ollama-connect');b.disabled=true;try{const s=await api('/api/setup/ollama',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({model:$('ollama-model').value})});$('ollama-feedback').textContent='Подключена '+s.selected+'. Перевод доступен в редакторе записи. Для конспекта модель выбирается отдельно в конструкторе.';await readiness();}catch(error){$('ollama-feedback').textContent=error.message;}finally{b.disabled=false;}};
  $('inspect-model').onclick=()=>modelAction(false);
  $('setup-form').onsubmit=e=>{e.preventDefault();modelAction(true);};
  $('pick-model').onclick=async()=>{const b=$('pick-model');b.disabled=true;$('setup-feedback').textContent='Выберите папку в окне Windows…';try{const r=await api('/api/setup/pick-model',{method:'POST',headers:{'X-App-Instance':instance}});if(r.path)$('model-path').value=r.path;$('setup-feedback').textContent=r.path?'Папка выбрана. Теперь проверьте и подключите модель.':'Выбор отменён.';}catch(e){$('setup-feedback').textContent=e.message;}finally{b.disabled=false;}};
  api('/health').then(h=>{instance=h.instance;return Promise.all([readiness(),jobs(),setupStatus(),ollamaStatus()]);}).then(()=>{if(selected)poll();}).catch(e=>message(e.message,true));
  const checks=setInterval(()=>{readiness();jobs().catch(()=>{});},15000);
})();
