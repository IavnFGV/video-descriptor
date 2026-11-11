(() => {
  const $ = id => document.getElementById(id);
  let wizardLoaded=false, setupPolling=false, ollamaEndpointChanged=false;
  let diarizationConfigured=false, storageLocked=false;
  let componentTimer, componentBusy=false;
  let instance, selected = new URLSearchParams(location.search).get('job'), timer, uploading=false, currentJob, processing=false;
  const statusNames = {queued:'В очереди', running:'Обрабатываем', done:'Готово', error:'Ошибка обработки'};
  const actionNames = {translation_model_configured:'Модель перевода подключена',model_configured:'Модель подключена',settings_changed:'Настройки сохранены',device_selected:'Устройство выбрано',device_loading:'Загрузка модели',device_ready:'Модель готова',device_skipped:'Устройство пропущено',device_attempt_failed:'Ошибка устройства',device_fallback:'Переход на другое устройство',job_added:'Запись добавлена',job_device_snapshot:'Устройство закреплено за записью',job_started:'Обработка начата',job_finished:'Обработка завершена',job_failed:'Ошибка обработки',job_retried:'Повтор обработки',transcript_edited:'Текст исправлен',export:'Экспорт'};
  const stamp = s => {
    if (!Number.isFinite(s) || s < 0) return 'метка не определена';
    const total=Math.floor(s);
    return [Math.floor(total/3600),Math.floor(total/60)%60,total%60].map(n=>String(n).padStart(2,'0')).join(':');
  };
  function showView(focus=false) {
    if(selected&&!['new','settings','diagnostics'].includes(location.hash.slice(1))){
      location.replace('/create?'+new URLSearchParams({job:selected}));return;
    }
    const context=new URLSearchParams(location.search);
    if(context.get('workspace')==='1'){
      context.delete('workspace');$('records-open').href='/create?'+context;
    }

    const view=['new','settings','diagnostics'].includes(location.hash.slice(1))?location.hash.slice(1):'records';
    $('readiness-panel').hidden=view!=='diagnostics';
    $('bootstrap-notice').hidden=view==='settings';
    $('setup-callout').hidden=view==='settings'||$('setup-callout').dataset.complete==='true';
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
    $('view-description').textContent={new:'Добавьте файл и выберите параметры распознавания.',records:selected?'Проверьте расшифровку по записи. Здесь доступны обработка и результаты.':'Откройте запись, чтобы продолжить работу с её текстом и результатами.',settings:'Выберите нужные функции и разрешите автоматическую подготовку.',diagnostics:'Проверьте компоненты, доступность устройств и историю действий.'}[view];
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
  const SIDEBAR_STORAGE_KEY='video-descriptor:ui:sidebar';
  const SIDEBAR_TOGGLE_ICONS={open:'<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m14 9 3 3-3 3"/>',close:'<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/>'};
  function readSidebarState(){try{return localStorage.getItem(SIDEBAR_STORAGE_KEY)==='1';}catch(_e){return false;}}
  function writeSidebarState(collapsed){try{localStorage.setItem(SIDEBAR_STORAGE_KEY,collapsed?'1':'0');}catch(_e){}}
  function setSidebarCollapsed(collapsed) {
    const shell=$('app-shell');
    if(shell){shell.classList.toggle('sidebar-collapsed',collapsed);}
    const toggle=$('sidebar-toggle');
    if(toggle){
      toggle.setAttribute('aria-expanded',String(!collapsed));
      toggle.setAttribute('aria-label',collapsed?'Показать панель навигации':'Свернуть панель навигации');
      toggle.querySelector('svg').innerHTML=collapsed?SIDEBAR_TOGGLE_ICONS.open:SIDEBAR_TOGGLE_ICONS.close;
    }
    writeSidebarState(collapsed);
    document.body.classList.toggle('sidebar-collapsed',collapsed);
  }
  $('sidebar-toggle').onclick=()=>setSidebarCollapsed($('sidebar-toggle').getAttribute('aria-expanded')==='true');
  setSidebarCollapsed(readSidebarState());
  async function api(url, options) {
    let response;
    try{response=await fetch(url,options);}catch(e){throw Error('Нет связи с приложением. Повторите действие.');}
    const data = await response.json();
    if (!response.ok) throw Error(data.error || `Ошибка ${response.status}`);
    return data;
  }
  function message(text, error=false) { $('message').textContent=deviceMessage(text); $('message').dataset.tone=error?'danger':'success'; }
  async function setupStatus() {
    const s=await api('/api/setup');
    if(!wizardLoaded)wizardLoaded=true;
    $('download-info').textContent=`Официальный источник: ${s.download.source} · revision ${s.download.revision} · ${(s.download.download_bytes/1024**2).toFixed(0)} МиБ. После сбоя повторите загрузку: готовые файлы будут проверены и использованы.`;
    const op=s.operation;
    $('setup-progress').hidden=op.status!=='running';
    if(op.total)$('setup-progress').value=100*op.bytes/op.total;else $('setup-progress').removeAttribute('value');
    $('operation-feedback').textContent=(op.status==='error'?'Ошибка: ':op.status==='done'?'Готово: ':'')+deviceMessage(op.result?.message||op.message||'')+(op.result?.device?' · '+deviceName(op.result.device)+' · реплик: '+op.result.segments:'');
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
  // Historical ollama-* DOM ids now belong to the single local-provider form.
  const localConfigs={ollama:{url:'',savedUrl:'',savedModel:'',choices:new Map()},lmstudio:{url:'',savedUrl:'',savedModel:'',choices:new Map(),token:''}};
  let localRequest=0, localBusy=false, localLoaded=false, localWorkerTest=null;
  const localProvider=()=>$('local-provider').value;
  const localCurrent=(request,provider,endpoint,model)=>request===localRequest&&provider===localProvider()&&endpoint===$('ollama-service-url').value&&(model===undefined||model===$('ollama-model').value);
  function localControls() {
    const worker=localProvider()==='ollama'&&componentBusy;
    $('local-provider').disabled=!localLoaded;
    for(const id of ['ollama-use-connection','ollama-refresh'])$(id).disabled=!localLoaded||localBusy||worker;
    for(const id of ['ollama-connect','ollama-test'])$(id).disabled=!localLoaded||localBusy||worker||!$('ollama-model').value;
    $('ollama-test').setAttribute('aria-busy',String(localBusy||!!localWorkerTest&&worker));
    $('ollama-test').textContent=localWorkerTest&&worker?'Проверяем модель…':'Проверить модель';
    $('ollama-service-url').disabled=!!localWorkerTest&&worker;
    $('ollama-model').disabled=!!localWorkerTest&&worker;
  }
  function clearOllamaModels() {
    $('ollama-model').replaceChildren(new Option('Обновите список моделей', ''));
    localControls();
  }
  function localRemember() {
    const config=localConfigs[localProvider()];
    config.url=$('ollama-service-url').value;
    if($('ollama-model').value)config.choices.set(config.url,$('ollama-model').value);
    if(localProvider()==='lmstudio')config.token=$('local-token').value;
  }
  function localRender() {
    ++localRequest;localBusy=false;
    const provider=localProvider(), config=localConfigs[provider], lm=provider==='lmstudio';
    $('ollama-service-url').value=config.url;
    $('local-token').value=lm?config.token:'';
    $('local-provider').dataset.previous=provider;
    $('component-ollama').hidden=lm;
    $('local-token-field').hidden=!lm;
    $('local-guide').textContent=lm?'LM Studio: скачайте и загрузите языковую модель в приложении, откройте Developer / Local Server и запустите сервер. Укажите адрес API с /v1 (обычно http://127.0.0.1:1234/v1). При включённой авторизации введите токен. Устройство и контекст настраиваются в LM Studio. Затем проверьте подключение, выберите модель и выполните проверку генерации.':'Ollama: установите и запустите внешний сервер самостоятельно. Добавьте модель командой ollama pull <model-name>. Укажите HTTP(S)-адрес (обычно http://127.0.0.1:11434), проверьте подключение и выберите модель. Приложение не устанавливает и не останавливает Ollama. Проверка генерации запускается отдельно.';
    $('ollama-connection-current').textContent='Подключение ещё не проверено.';
    $('ollama-feedback').textContent='Обновите список. Отображаются только модели выбранного сервера.';
    ollamaEndpointChanged=localConfigs.ollama.url!==localConfigs.ollama.savedUrl;
    clearOllamaModels();
  }
  async function localDiscover(saveConnection=false) {
    if(!localLoaded)return;
    localRemember();
    const provider=localProvider(),config=localConfigs[provider],endpoint=config.url,request=++localRequest;
    const chosen=config.choices.get(endpoint)||(endpoint===config.savedUrl?config.savedModel:'');
    localBusy=true;clearOllamaModels();
    $('ollama-connection-current').textContent='Проверяем подключение…';
    $('ollama-feedback').textContent='Получаем список моделей…';
    try {
      let rows;
      if(provider==='ollama'){
        if(saveConnection){await setupPost('ollama',{endpoint});if(endpoint!==config.savedUrl)config.savedModel='';config.savedUrl=endpoint;ollamaEndpointChanged=config.url!==config.savedUrl;}
        if(!localCurrent(request,provider,endpoint))return;
        const status=await api('/api/setup/ollama'+'?endpoint='+encodeURIComponent(endpoint));
        if(!status.service_ready)throw Error(status.message||'Сервер недоступен.');
        if(!Array.isArray(status.models)||status.models.some(row=>!row||typeof row.name!=='string'||!row.name.trim()))throw Error('Некорректный список моделей сервера.');
        rows=status.models.map(row=>({id:row.name,title:row.name}));
      }else{
        rows=await localLM('models',endpoint);
        if(!Array.isArray(rows)||rows.some(row=>!row||typeof row.id!=='string'||!row.id.trim()))throw Error('Некорректный список моделей сервера.');
      }
      if(!localCurrent(request,provider,endpoint))return;
      const list=$('ollama-model');list.replaceChildren(new Option('Выберите модель', ''));
      for(const row of rows)list.add(new Option(row.title||row.id,row.id));
      list.value=rows.some(row=>row.id===chosen)?chosen:'';
      if(chosen&&!list.value)config.choices.delete(endpoint);
      ollamaEndpointChanged=localConfigs.ollama.url!==localConfigs.ollama.savedUrl;
      $('ollama-connection-current').textContent='Сервер подключён · '+endpoint;
      $('ollama-feedback').textContent=!rows.length?'Сервер ответил, моделей нет. Добавьте модель на сервере и обновите список.':chosen&&!list.value?'Сохранённая модель отсутствует на сервере. Выбор сброшен. Выберите модель.':'Модели получены. Генерация ещё не проверена.';
    }catch(e){if(localCurrent(request,provider,endpoint)){clearOllamaModels();$('ollama-connection-current').textContent='Подключение не проверено.';$('ollama-feedback').textContent=e.message;}}
    finally{if(localCurrent(request,provider,endpoint)){localBusy=false;localControls();}}
  }
  function localLM(action,endpoint,model) {
    return api('/api/translation-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,lmstudio_url:endpoint,lmstudio_model:model,lmstudio_api_key:$('local-token').value})});
  }
  async function localPreferences() {
    const [prefs,status]=await Promise.all([api('/api/translation-settings'),api('/api/setup/ollama')]);
    Object.assign(localConfigs.ollama,{url:status.url,savedUrl:status.url,savedModel:prefs.ollama_model||status.selected});
    Object.assign(localConfigs.lmstudio,{url:prefs.lmstudio_url,savedUrl:prefs.lmstudio_url,savedModel:prefs.lmstudio_model});
    $('local-token').placeholder=prefs.lmstudio_has_key?'Токен сохранён':'Необязательный токен';
    $('local-provider').value=prefs.provider==='lmstudio'?'lmstudio':'ollama';
    localLoaded=true;localRender();await localDiscover();
  }
  async function ollamaStatus() {
    if(localLoaded&&localProvider()==='ollama'&&!localBusy&&!localWorkerTest)await localDiscover();
  }
  function check(label, ready, suffix) { const row=document.createElement('div');row.className='check';const a=document.createElement('span');a.textContent=label;const b=document.createElement('span');b.className='vd-status';b.dataset.tone=ready?'success':'warning';b.textContent=deviceMessage(suffix||(ready?'Готово':'Не подключено'));row.append(a,b);return row; }
  function systemStatus(ready, preparing=false) {
    $('system-dot').className='dot'+(ready&&!preparing?' good':'');
    $('system-status').textContent=preparing?'Готовим распознавание…':ready?'Распознавание готово':'Нужна настройка распознавания';
  }
  async function readiness() {
    try {
      const d=await api('/api/doctor');$('doctor').textContent=JSON.stringify(d,null,2);
      diarizationConfigured=d.diarization?.state==='configured';$('diarize-run').textContent='Разделить по участникам'+(d.diarization?.device?' · '+deviceName(d.diarization.device):'');$('diarize-run').disabled=processing;$('diarize-run').title='Выбрать способ обработки и разделить по участникам';
      if(d.compute){
        const c=d.compute, chosen=c.selected, ready=chosen&&c.capabilities[chosen].ready;
        const deviceReason=(name)=>{const cap=c.capabilities[name];return c.preparing&&name===chosen?'Запускаем распознавание…':cap.available&&!cap.ready&&cap.model_present&&cap.reason==='Модель не загружена'?'Распознавание не запущено':cap.reason;};
        if(document.activeElement!==$('speech-device'))$('speech-device').value=c.settings.speech_device;
        if(document.activeElement!==$('settings-speech-device'))$('settings-speech-device').value=c.settings.speech_device;
        for(const id of ['speech-device','settings-speech-device'])for(const option of $(id).options){if(option.value==='AUTO')continue;const cap=c.capabilities[option.value];option.disabled=!cap.available;option.textContent=deviceName(option.value)+' · '+deviceReason(option.value);}
        $('device-status').textContent=c.preparing?'Запускаем распознавание с моделью на диске…':c.error||(chosen?`Выбрано: ${deviceName(c.settings.speech_device)} → ${deviceName(chosen)}. Настройка применяется только к новым заданиям.`:'Нет готового поддержанного backend. См. диагностику.');
        $('readiness').replaceChildren(...['NPU','GPU','CPU'].map(name=>check(deviceName(name),c.capabilities[name].ready,deviceReason(name))),check('Ollama · перевод',d.ollama.ready,d.ollama.ready?'Настроено · без проверки генерации':'Нужна настройка'));
        $('ready-dot').className='dot'+(ready&&d.ffmpeg?' good':'');
        systemStatus(ready&&d.ffmpeg,c.preparing);
        $('start').disabled=storageLocked||uploading||!ready||!d.ffmpeg||c.preparing||!!c.operation;
        $('start-npu').hidden=!!ready||!chosen;$('start-npu').disabled=c.preparing||!!c.operation;
        $('npu-notice').textContent=ready?'Распознавание готово. Можно добавить запись.':'Подготавливаем распознавание в фоне. Выбранный файл сохраняется.';
        if(!componentBusy){$('bootstrap-message').textContent=c.preparing?'Подготавливаем распознавание…':ready?'Распознавание готово':c.error?'Не удалось подготовить распознавание. Повторите.':'Нужно подготовить распознавание';$('prepare-speech').hidden=!!ready||c.preparing;}
        $('ai-summary').textContent=(ready?'Распознавание готово. ':'Распознавание требует подготовки. ')+(d.ollama.ready?'Локальный перевод подключён. ':'Локальный перевод не подключён. ')+(diarizationConfigured?'Разделение по участникам доступно.':'Участники подготавливаются при первом использовании.');
        try{const events=await api('/api/native/events');$('events').textContent=events.slice(-20).map(e=>`${new Date(e.time_utc).toLocaleTimeString()} · ${e.label||actionNames[e.action]||e.action}${e.device||e.requested?' · '+(e.device||e.requested):''}${e.previous_device?' ← '+e.previous_device:''}${e.job_id?' · запись '+e.job_id.slice(0,8):''}`).join('\n')||'Событий пока нет';}catch(e){$('events').textContent='Не удалось обновить историю: '+e.message;}
        return;
      }
      $('readiness').replaceChildren(check('Распознавание · Intel NPU',d.npu.ready),check('Видео и аудио',!!d.ffmpeg),check('Ollama · перевод',d.ollama.ready));
      $('ready-dot').className='dot'+(d.npu.ready&&d.ffmpeg?' good':'');
      systemStatus(d.npu.ready&&d.ffmpeg);
      $('start').disabled=storageLocked||uploading||!d.npu.ready||!d.ffmpeg;
      $('start-npu').hidden=d.npu.ready||!d.can_start_npu;
      $('npu-notice').textContent=d.npu.ready?'Модель готова. Можно добавлять запись.':'Нажмите «Подготовить распознавание», если компоненты уже установлены. Модели автоматически не скачиваются.';
      if(!d.npu.ready&&d.npu_startup?.exit_code!==undefined)$('npu-notice').textContent=`Не удалось загрузить модель (код ${d.npu_startup.exit_code}). Подробности в windows-app/runtime/logs/npu.log. Окружение автоматически не переустанавливается.`;
    } catch(e) { $('system-dot').className='dot';$('system-status').textContent='Нет связи с приложением';$('start').disabled=true;$('device-status').textContent='Не удалось проверить готовность. Обновите диагностику перед запуском.';message('Приложение недоступно: '+e.message,true); }
  }
  async function jobs() {
    const all=await api('/api/jobs');
    const seen=new Set();
    const recordings=all.sort((a,b)=>b.created-a.created).filter(job=>{const key=job.video||job.id;if(seen.has(key))return false;seen.add(key);return true;});
    const buttons=recordings.map(job=>{
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
  async function select(id) { if(!await window.mayLeaveQuickReply())return;location.assign('/create?'+new URLSearchParams({job:id})); }
  function render(result,job,progress={}) {
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
    $('progress-text').textContent=(device?`${deviceName(job.device_plan?.requested||device)} → ${deviceName(device)} · `:'')+((job.status==='error'&&result?.status==='error'&&failureMessage?failureMessage:job.error)||result?.message||(job.status==='done'?(result?.no_speech?'Речь не обнаружена':'Расшифровка готова'):job.status==='running'?'Распознаём запись…':'Ожидаем свободный обработчик'));
    $('progress-text').textContent=deviceMessage($('progress-text').textContent);
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
      $('progress-text').textContent=job.task==='diarize'?(job.error||result?.message||'Разделяем реплики по участникам'):(job.error||`${phases[job.stage]||statusNames[job.status]} · ${job.stage==='translation'?job.translation_model:job.construction?.model||job.translation_model||'Ollama'}`);
      if(['queued','running'].includes(job.status)){
        $('progress').removeAttribute('value');
        if(job.status==='running'&&job.task!=='diarize'){
          const phase={notes:'Конспект',consolidation:'Объединение частей',translation:'Перевод реплик'}[progress.phase];
          if(phase&&((job.stage==='translation')===(progress.phase==='translation'))){$('progress-text').textContent+=' · '+phase+': обработано '+(progress.completed||0)+' из '+progress.total+' · '+(progress.chunk?'часть '+progress.chunk+' · ':'')+(progress.request_state||progress.message||'');if(progress.total>0)$('progress').value=100*(progress.completed||0)/progress.total;}
          $('progress-text').textContent+=' · Выполняется '+durationText(Date.now()/1000-(job.started||job.created));
          if(progress.request_started)$('progress-text').textContent+=' · Текущий запрос '+durationText((progress.request_seconds||0)+Math.max(0,Date.now()/1000-(progress.updated||Date.now()/1000)));
          if(progress.received)$('progress-text').textContent+=' · Получено '+progress.received+' символов ответа';
        }
      }
    }
    $('retry').hidden=job.status!=='error';
    $('retry').textContent=job.task==='diarize'?'Повторить разделение по участникам':result?.segments?.length?'Продолжить из кэша':'Повторить распознавание';
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
    $('timing-note').textContent=job.status==='error'?'':result.speaker_notice|| (result.no_speech?'Речь не обнаружена. Это решение VAD, а не ручная проверка записи.':'Таймкоды относятся к целым репликам. Разделение слов и участников в этом режиме не выполняется.');
    const content=JSON.stringify([job.id,result.segments,result.translations,result.speaker_names,result.edit_revision,done,result.no_speech]);
    if($('transcript').dataset.content===content)return;
    $('transcript').dataset.content=content;
    const rows=result.segments.map((segment,index)=>{
      const row=document.createElement('div');row.className='row';const time=document.createElement('button');time.type='button';time.className='vd-button vd-button--quiet vd-button--compact seek';time.textContent=stamp(segment.start)+' — '+stamp(segment.end);time.setAttribute('aria-label','Воспроизвести с '+stamp(segment.start));time.disabled=!Number.isFinite(segment.start)||segment.start<0||!result.video;time.onclick=()=>{$('video').currentTime=segment.start;$('video').play().catch(()=>{});};
      const header=document.createElement('div'),tools=document.createElement('div');header.className='reply-heading';tools.className='reply-tools';header.append(time);row.append(header);
      if(done){const edit=document.createElement('button');edit.type='button';edit.className='vd-button vd-button--compact row-edit';edit.title='Исправить реплику';edit.setAttribute('aria-label','Исправить реплику');const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('width','18');icon.setAttribute('height','18');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-width','2');icon.setAttribute('stroke-linecap','round');icon.setAttribute('stroke-linejoin','round');icon.setAttribute('aria-hidden','true');const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M16 3a2.1 2.1 0 0 1 3 3L7 18l-4 1 1-4L16 3Z M14 5l3 3');icon.append(path);edit.append(icon);edit.onclick=()=>window.editSpeechReply(result,index,$('video'),saved=>render(saved,job));tools.append(edit);}
      const p=document.createElement('p');p.textContent=segment.text;if(done)window.enableQuickReplyEdit(p,result,index,saved=>{if(selected!==job.id)return;render(saved,job);$('transcript').querySelectorAll('.row')[index]?.querySelector('p')?.focus({preventScroll:true});});if(result.diarization_device){if(done){header.append(window.createSpeakerName(result,segment.speaker,saved=>{if(selected!==job.id)return;render(saved,job);$('transcript').querySelectorAll('.speaker-name')[index]?.focus({preventScroll:true});}));tools.prepend(window.createSpeakerSelect(result,index,saved=>{if(selected!==job.id)return;render(saved,job);$('transcript').querySelectorAll('.speaker-select')[index]?.focus({preventScroll:true});}));}else{const speaker=document.createElement('span');speaker.className='vd-status';speaker.textContent=result.speaker_names?.[segment.speaker]||(segment.speaker==='unknown'?'Участник не указан':segment.speaker);header.append(speaker);}}header.append(tools);row.append(p);const translated=result.translations?.[segment.id];if(translated){const ru=document.createElement('p');ru.className='translation';ru.textContent=translated;row.append(ru);}return row;
    });
    if(!rows.length){const p=document.createElement('p');p.className='empty';p.textContent=result.no_speech?'Речевых фрагментов не найдено.':job.status==='error'?'Распознавание остановилось до сохранения текста. Причина указана выше. Повторный запуск может завершиться той же ошибкой.':'Текст появится после первого сохранённого фрагмента.';rows.push(p);}
    $('transcript').replaceChildren(...rows);
  }
  async function poll() {
    if(!selected)return;
    const id=selected;
    try{const {job,result,progress}=await api('/api/speech?job='+id);if(id!==selected)return;render(result,job,progress);if(['queued','running'].includes(job.status)){timer=setTimeout(poll,2000);}else{await jobs();}}catch(e){if(id!==selected)return;message(e.message,true);timer=setTimeout(poll,5000);}
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
  $('settings-speech-device').onchange=async()=>{try{$('speech-device').value=$('settings-speech-device').value;await api('/api/compute-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speech_device:$('settings-speech-device').value})});}catch(e){message(e.message,true);}};
  $('stop').onclick=async()=>{try{await api('/api/native/stop',{method:'POST',headers:{'X-App-Instance':instance}});clearTimeout(timer);clearInterval(checks);message('Приложение завершено. Эту вкладку можно закрыть.');$('start').disabled=true;}catch(e){message(e.message,true);}};
  $('refresh').onclick=()=>jobs().catch(e=>message(e.message,true));
  async function postprocess(task,options={}) {
    if(!currentJob?.folder||processing)return;
    processing=true;$('translate-run').disabled=true;$('notes-run').disabled=true;
    try{const job=await api('/api/native/postprocess',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({folder:currentJob.folder,task,...options})});message('Создана отдельная версия. Исходная расшифровка сохранена.');select(job.id);await jobs();return true;}catch(e){message(e.message,true);return false;}finally{processing=false;$('translate-run').disabled=false;$('notes-run').disabled=false;}
  }
  $('diarize-run').onclick=openSpeakers;
  $('translate-run').onclick=()=>localAI('translate');
  $('notes-run').onclick=openNotes;
  $('setup-toggle').onclick=()=>{$('setup-form').hidden=!$('setup-form').hidden;$('setup-toggle').setAttribute('aria-expanded',String(!$('setup-form').hidden));};
  $('inspect-model').onclick=()=>modelAction(false);
  $('setup-form').onsubmit=e=>{e.preventDefault();modelAction(true);};
  $('pick-model').onclick=async()=>{const b=$('pick-model');b.disabled=true;$('setup-feedback').textContent='Выберите папку в окне Windows…';try{const r=await api('/api/setup/pick-model',{method:'POST',headers:{'X-App-Instance':instance}});if(r.path)$('model-path').value=r.path;$('setup-feedback').textContent=r.path?'Папка выбрана. Теперь проверьте и подключите модель.':'Выбор отменён.';}catch(e){$('setup-feedback').textContent=e.message;}finally{b.disabled=false;}};
  async function setupPost(path, body={}) {return api('/api/setup/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify(body)});}
  async function diagnostics() {
    const d=await api('/api/setup/diagnostics');
    const inv=d.inventory;
    const gpuOption=Array.from($('diarization-device').options).find(o=>o.value==='xpu');
    gpuOption.disabled=!d.hardware.intel_gpu.length;gpuOption.textContent='Видеокарта (GPU)'+(gpuOption.disabled?' · совместимая видеокарта не обнаружена':'');
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
  $('local-provider').onchange=()=>{
    // The selector already has its new value; remember the old provider before rendering.
    const previous=$('local-provider').dataset.previous||'ollama',current=localProvider();
    $('local-provider').value=previous;localRemember();$('local-provider').value=current;
    $('local-provider').dataset.previous=current;
    localRender();localDiscover();
  };
  $('ollama-refresh').onclick=()=>localDiscover();
  $('ollama-use-connection').onclick=()=>localDiscover(true);
  $('ollama-model').onchange=()=>{++localRequest;localBusy=false;localRemember();$('ollama-feedback').textContent='Выбор изменён. Генерация ещё не проверена.';localControls();};
  $('ollama-form').onsubmit=async e=>{
    e.preventDefault();localRemember();
    const provider=localProvider(),config=localConfigs[provider],endpoint=config.url,model=$('ollama-model').value,token=config.token,request=++localRequest;
    localBusy=true;localControls();
    try{
      if(!model)throw Error('Обновите список и выберите модель.');
      if(provider==='ollama'){
        if(ollamaEndpointChanged)throw Error('Сначала проверьте и сохраните подключение.');
        await setupPost('ollama',{model,task:'translation'});
      }else{
        const saved=await api('/api/translation-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider,lmstudio_url:endpoint,lmstudio_model:model,lmstudio_api_key:token})});
        config.savedUrl=endpoint;config.savedModel=saved.lmstudio_model;if(config.token===token)config.token='';
      }
      if(provider==='ollama')config.savedModel=model;
      if(localCurrent(request,provider,endpoint,model)){$('local-token').value='';$('ollama-feedback').textContent='Провайдер и модель по умолчанию сохранены. Генерация проверяется отдельно.';}
    }catch(e){if(localCurrent(request,provider,endpoint))$('ollama-feedback').textContent=e.message;}
    finally{if(localCurrent(request,provider,endpoint)){localBusy=false;localControls();}}
  };
  $('ollama-test').onclick=async()=>{
    const provider=localProvider(),endpoint=$('ollama-service-url').value,model=$('ollama-model').value,request=++localRequest;
    localBusy=true;localControls();$('ollama-feedback').textContent='Проверяем генерацию…';
    try{
      if(!model)throw Error('Выберите модель.');
      if(provider==='ollama'){
        if(ollamaEndpointChanged)throw Error('Сначала проверьте и сохраните подключение.');
        localWorkerTest={request,provider,endpoint,model};
        await componentAction('ollama','check',{model,task:'translation'});
      }else{
        await localLM('verify',endpoint,model);
        if(localCurrent(request,provider,endpoint,model))$('ollama-feedback').textContent='Генерация проверена.';
      }
    }catch(e){if(localCurrent(request,provider,endpoint,model))$('ollama-feedback').textContent=e.message;}
    finally{if(localCurrent(request,provider,endpoint)){localBusy=false;localControls();}}
  };
  localControls();
  localPreferences().catch(e=>{$('ollama-feedback').textContent=e.message;});
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

  const deviceNames={AUTO:'Автоматически',auto:'Автоматически',CPU:'Процессор (CPU)',cpu:'Процессор (CPU)',GPU:'Видеокарта (GPU)',xpu:'Видеокарта (GPU)',NPU:'Нейропроцессор (NPU)',npu:'Нейропроцессор (NPU)'};
  const deviceName=value=>deviceNames[value]||value;
  const durationText=seconds=>{const value=Math.max(0,Math.floor(seconds));return Math.floor(value/60)+' мин '+String(value%60).padStart(2,'0')+' с';};
  const deviceMessage=value=>String(value||'').replace(/PyTorch XPU|Intel GPU|XPU/g,'видеокарта (GPU)');
  const componentNames={not_installed:'Не установлен',installed:'Установлен · нужна проверка',downloading:'Загрузка',installing:'Установка',verifying:'Проверка',ready:'Готово',error:'Ошибка · можно повторить',update_available:'Доступно обновление'};
  async function componentAction(component,action,extra={}) {
    try {
      if(componentBusy&&action!=='cancel')return;
      if(component==='ollama'&&action==='check'&&ollamaEndpointChanged)throw Error('Сначала сохраните подключение Ollama.');
      componentBusy=action!=='cancel';
      await api('/api/components',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({component,action,...extra})});
      await componentStatus();
    }catch(e){message(e.message,true);componentBusy=false;await componentStatus().catch(()=>{});}
  }
  async function componentStatus() {
    const data=await api('/api/components');
    const diarization=data.components.find(item=>item.id==='diarization');
    $('open-hf-settings').hidden=diarization?.requires_download===false;
    $('diarization-hf-fields').hidden=diarization?.requires_download===false;
    $('diarization-prepare-fields').hidden=diarization?.state==='ready';
    $('diarization-setup-help').hidden=diarization?.state==='ready';
    $('diarization-prepare-help').textContent=diarization?.state==='ready'?'Участники готовы. Повторная настройка и доступ Hugging Face не требуются.':diarization?.requires_download===false?'Локальная модель уже установлена. При смене устройства подготовим только необходимое окружение.':'Для первой загрузки модели примите условия и укажите токен в разделе «Участники».';
    $('hf-token').placeholder=data.has_hf_token?'Токен сохранён — повторно вводить не нужно':'Токен чтения Hugging Face для первой загрузки';
    const plan=data.preparation||{},preparing=plan.state==='running';componentBusy=!!data.active||preparing;
    if(!$('prepare-selected').loaded){
      if(plan.features)for(const key of ['whisper','diarization','ollama'])$('prepare-'+key).checked=plan.features.includes(key);
      $('prepare-selected').loaded=true;
    }
    $('prepare-selected').disabled=componentBusy;
    for(const id of ['prepare-consent','prepare-whisper','prepare-diarization','prepare-ollama','settings-speech-device','diarization-device'])$(id).disabled=preparing;
    $('prepare-selected-stop').hidden=!preparing;
    $('preparation-status').textContent=(plan.message||'')+(preparing?' · Готово '+(plan.completed||[]).length+' из '+plan.features.length:'');
    if(preparing&&data.active){const active=data.components.find(c=>c.id===data.active);if(active)$('preparation-status').textContent+=' · '+deviceMessage(active.message);}
    $('preparation-status').dataset.tone=plan.state==='error'?'danger':plan.state==='ready'?'success':'info';
    $('setup-callout').dataset.complete=String(plan.state==='ready');
    $('setup-callout').hidden=location.hash==='#settings'||plan.state==='ready';
    $('setup-callout-message').textContent=plan.message||'Откройте настройки, выберите нужные функции и разрешите загрузки. Приложение само подготовит выбранные компоненты.';
    $('setup-open').classList.toggle('needs-setup',plan.state!=='ready');
    const whisper=data.profiles.whisper_model;
    $('prepare-sources').textContent='Источники: '+(whisper?whisper.source+' (распознавание ≈'+Math.ceil((whisper.recorded_download_bytes||whisper.files.reduce((sum,file)=>sum+file.bytes,0))/1024**2)+' МиБ); ':'')+(diarization?.state==='ready'?'Участники подготовлены, повторная загрузка не нужна; ':'Hugging Face / PyPI / PyTorch (участники: несколько ГиБ, требуется 8 ГиБ свободного места); ')+'Ollama подключается к внешнему серверу. Установку Ollama и моделей выполните самостоятельно по инструкции ниже.';
    $('cancel-preparation').hidden=!data.active;
    if(data.active){const active=data.components.find(c=>c.id===data.active);$('bootstrap-message').textContent=deviceMessage(active.message)+(active.total?' · '+Math.floor(100*(active.bytes||0)/active.total)+'%':'');$('prepare-speech').hidden=true;}
    for(const item of data.components){
      const box=$('component-'+item.id);
      if(item.id==='diarization'&&!box.deviceLoaded){$('diarization-device').value=item.requested_device||plan.device||'auto';box.deviceLoaded=true;}
      if(item.id==='diarization'&&!$('diarization-consent').loaded){$('diarization-consent').checked=item.download_consent===true&&item.consent_revision===data.profiles.diarization_model?.revision;$('diarization-consent').loaded=true;}
      if(!box.componentControls){
        const state=document.createElement('p'),details=document.createElement('p'),progress=document.createElement('progress'),caption=document.createElement('p'),activity=document.createElement('p'),button=document.createElement('button'),remove=document.createElement('button');
        state.className='vd-status';state.setAttribute('role','status');details.className='footnote';progress.className='vd-progress';button.type='button';button.className='vd-button';remove.type='button';remove.className='vd-button vd-button--danger';
        caption.className='footnote';activity.className='footnote';caption.id='progress-caption-'+item.id;progress.setAttribute('aria-describedby',caption.id);
        const actions=document.createElement('div');actions.className='vd-actions';actions.append(button,remove);
        box.replaceChildren(state,details,progress,caption,activity,actions);box.componentControls={state,details,progress,caption,activity,button,remove};
      }
      const {state,details,progress,caption,activity,button,remove}=box.componentControls;
      state.dataset.tone=item.state==='error'?'danger':item.state==='ready'?'success':'info';
      state.textContent=(item.id==='ollama'?'Ollama · ':'')+(item.id==='ollama'?({not_installed:'Подключение не проверено',installed:'Сервер подключён',installing:'Проверка подключения'}[item.state]||componentNames[item.state]):componentNames[item.state]||item.state)+' · '+deviceMessage(item.message)+(item.state==='ready'&&item.fallback_reason?' · '+deviceMessage(item.fallback_reason):'');
      if(data.active===item.id&&item.preparing_device)state.textContent+=' · '+deviceName(item.preparing_device);
      details.textContent=[item.version?'Версия: '+item.version:'',item.device?(item.state==='error'?'Последняя успешная проверка: ':['installing','downloading','verifying'].includes(item.state)?'Ранее подготовлено: ':'Устройство: ')+deviceName(item.device):'',item.model?'Модель: '+item.model:'',item.bytes_on_disk?'На диске: '+(item.bytes_on_disk/1024**3).toFixed(2)+' ГиБ':''].filter(Boolean).join(' · ');
      progress.hidden=data.active!==item.id;progress.setAttribute('aria-label',item.name);
      if(item.total){progress.max=item.total;progress.value=item.bytes||0;if(data.active===item.id)state.textContent+=' · '+Math.floor(100*(item.bytes||0)/item.total)+'%';}else progress.removeAttribute('value');
      caption.hidden=data.active!==item.id;
      caption.textContent=item.total?(item.progress_unit==='steps'?'Прогресс текущего этапа: '+Math.floor(100*(item.bytes||0)/item.total)+'%':(item.progress_scope==='file'?'Текущий файл: ':'Загрузка компонента: ')+((item.bytes||0)/1024**2).toFixed(1)+' из '+(item.total/1024**2).toFixed(1)+' МиБ'):'Этот этап выполняется без оценки процента.';
      activity.hidden=data.active!==item.id||!item.process_running||!item.step_started_at;
      const quiet=Math.max(0,Date.now()/1000-(item.activity_at||item.step_started_at));
      activity.textContent='Выполняется: '+durationText(Date.now()/1000-item.step_started_at)+'. '+(quiet>=60?'Новых сообщений нет уже '+durationText(quiet)+'. Процесс ещё запущен.':'Последняя активность: '+durationText(quiet)+' назад.');
      activity.classList.toggle('warning',quiet>=60);
      button.hidden=item.id==='diarization'&&item.state==='ready'||item.id==='ollama'&&data.active!=='ollama';
      button.textContent=data.active===item.id?'Остановить':item.state==='error'?'Повторить проверку':'Проверить';button.disabled=!!data.active&&data.active!==item.id;
      if(item.id==='ollama'&&data.active===item.id&&item.cancel_requested){button.textContent='Ожидаем завершения запроса…';button.disabled=true;}
      if(item.id==='diarization'&&data.active!==item.id&&$('diarization-device').value==='xpu'&&item.device==='cpu'){button.disabled=true;button.textContent='Для видеокарты нужна подготовка';}
      button.onclick=()=>componentAction(item.id,data.active===item.id?'cancel':'check',item.id==='diarization'?{device:$('diarization-device').value}:item.id==='ollama'?{model:localProvider()==='ollama'?$('ollama-model').value:localConfigs.ollama.savedModel,task:'translation'}:{});
      remove.hidden=!item.path||!!data.active||item.id==='ollama';remove.textContent='Удалить окружение';remove.onclick=()=>{if(window.confirm('Удалить только управляемое приложением окружение? Модели и пользовательские файлы сохранятся.'))componentAction(item.id,'remove',{confirmed:true});};
    }
    $('component-summary').replaceChildren(...data.components.map(item=>check(item.name,item.state==='ready',componentNames[item.state])));
    if(!$('component-root').value)$('component-root').value=data.root;
    $('component-directory').textContent='Модели, окружения и проверенные загрузки: '+data.root+'. При обновлении приложения сохраняются.';
    $('diarization-install').disabled=!!data.active;
    if(localWorkerTest&&data.active!=='ollama'){
      const {request,provider,endpoint,model}=localWorkerTest;
      const result=data.components.find(item=>item.id==='ollama');
      if(localCurrent(request,provider,endpoint,model))$('ollama-feedback').textContent=result?.message||'Проверка завершена.';
      localWorkerTest=null;
    }
    localControls();
    clearTimeout(componentTimer);
    if(data.active||preparing)componentTimer=setTimeout(()=>componentStatus().then(()=>{if(!componentBusy){readiness();setupStatus();}}).catch(e=>message(e.message,true)),1000);
  }
  for(const [button,field] of [['open-hf-settings','hf-token'],['open-local-settings','ollama-service-url']])$(button).onclick=()=>{const target=$(field);target.closest('details').open=true;target.focus();};
  for(const key of ['whisper','diarization','ollama'])$('prepare-'+key).onchange=()=>{$('prepare-consent').checked=false;};
  $('prepare-consent').onchange=()=>{$('preparation-status').textContent=$('prepare-consent').checked?'Разрешение отмечено. Нажмите «Сохранить и подготовить».':'Для автоматической подготовки отметьте разрешение на загрузку.';$('preparation-status').dataset.tone='info';};
  $('prepare-selected').onclick=async()=>{
    const button=$('prepare-selected');button.disabled=true;
    try{
      const features=['whisper','diarization','ollama'].filter(key=>$('prepare-'+key).checked);
      if(!features.length)throw Error('Выберите хотя бы одну функцию.');
      if(!$('prepare-consent').checked){$('prepare-consent').focus();throw Error('Отметьте разрешение на загрузку и установку выбранных компонентов. Для GPU нужно это же разрешение.');}
      if(features.includes('diarization')&&!$('diarization-hf-fields').hidden&&!$('diarization-consent').checked){$('diarization-consent').closest('details').open=true;$('diarization-consent').focus();throw Error('Для участников примите условия community-1 и отметьте согласие в разделе «Участники».');}
      if(features.includes('ollama')&&ollamaEndpointChanged)throw Error('Сначала сохраните подключение Ollama.');
      const model=localProvider()==='ollama'?$('ollama-model').value:localConfigs.ollama.savedModel;
      if(features.includes('ollama')&&!model){$('ollama-service-url').closest('details').open=true;$('ollama-service-url').focus();throw Error('Выберите подключение и языковую модель в разделе «Локальный AI».');}
      await api('/api/components',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({action:'prepare_selected',features,device:$('diarization-device').value,model,token:$('hf-token').value,hf_consent:$('diarization-consent').checked,confirmed:true})});
      $('hf-token').value='';await componentStatus();
    }catch(e){$('preparation-status').textContent=e.message;$('preparation-status').dataset.tone='danger';button.disabled=false;}
  };
  $('prepare-selected-stop').onclick=async()=>{try{await api('/api/components',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({action:'cancel_selected'})});await componentStatus();}catch(e){message(e.message,true);}};
  $('ollama-service-url').oninput=()=>{
    ++localRequest;localBusy=false;localConfigs[localProvider()].url=$('ollama-service-url').value;
    ollamaEndpointChanged=localConfigs.ollama.url!==localConfigs.ollama.savedUrl;
    clearOllamaModels();$('ollama-connection-current').textContent='Адрес изменён. Проверьте подключение.';$('ollama-feedback').textContent='Список моделей сброшен.';
  };
  $('local-token').oninput=()=>{localConfigs.lmstudio.token=$('local-token').value;++localRequest;localBusy=false;clearOllamaModels();$('ollama-connection-current').textContent='Токен изменён. Проверьте подключение.';};
  $('ollama-guide').onclick=()=>{const guide=$('local-guide');guide.hidden=!guide.hidden;$('ollama-guide').setAttribute('aria-expanded',String(!guide.hidden));};
  $('ollama-guide-open').onclick=()=>setupPost('external',{page:localProvider()==='lmstudio'?'lmstudio-guide':'ollama-guide'}).catch(e=>message(e.message,true));
  $('diarization-device').onchange=()=>componentStatus().catch(e=>message(e.message,true));
  $('diarization-install').onclick=()=>{const token=$('hf-token').value;$('hf-token').value='';componentAction('diarization','install',{confirmed:$('diarization-consent').checked,device:$('diarization-device').value,token});};
  for(const [id,page] of [['hf-terms','terms'],['hf-tokens','tokens']])$(id).onclick=()=>setupPost('external',{page}).catch(e=>message(e.message,true));

  let notesFolder=null,notesDefaults={},notesModelsLoading=false,notesRequest=0;
  async function openNotes(){
    if(!currentJob?.folder||processing)return;
    notesFolder=currentJob.folder;$('notes-provider').disabled=true;$('notes-confirm').disabled=true;$('notes-choice-status').textContent='Загружаем настройки подключения…';$('notes-cloud-consent').checked=false;
    $('notes-dialog').showModal();
    try{notesDefaults=await api('/api/translation-settings');$('notes-provider').disabled=false;$('notes-provider').value=notesDefaults.provider==='lmstudio'?'lmstudio':notesDefaults.provider==='gemini'&&notesDefaults.has_key?'gemini':'ollama';await notesModels();}catch(e){$('notes-provider').disabled=false;$('notes-choice-status').textContent=e.message;}
  }
  async function notesModels(){
    const provider=$('notes-provider').value,request=++notesRequest;
    notesModelsLoading=true;$('notes-confirm').disabled=true;$('notes-model-choice').replaceChildren();$('notes-cloud-label').hidden=provider!=='gemini';$('notes-choice-status').textContent='Получаем список моделей…';
    try{
      let models,chosen;
      if(provider==='gemini'){
        if(!notesDefaults.has_key)throw Error('Сначала сохраните API-ключ Google в настройках AI.');
        const r=await setupPost('gemini',{check:true});models=r.models.map(m=>m.id);chosen=notesDefaults.model;
      }else if(provider==='lmstudio'){const r=await api('/api/construction-models?provider=lmstudio');models=r.map(m=>m.id);chosen=notesDefaults.lmstudio_model;}else{const r=await api('/api/setup/ollama');models=r.models.map(m=>m.name);chosen=r.selected;}
      if(request!==notesRequest)return;
      $('notes-model-choice').replaceChildren(new Option('Выберите модель',''),...models.map(name=>{const o=document.createElement('option');o.value=name;o.textContent=name;return o;}));
      if(models.includes(chosen))$('notes-model-choice').value=chosen;
      $('notes-choice-status').textContent=models.length?(provider==='gemini'?'Google получит текст расшифровки и краткую память предыдущих частей.':'Текст останется на вашем компьютере.'):'Нет доступных моделей. Настройте подключение AI.';
    }catch(e){if(request===notesRequest)$('notes-choice-status').textContent=e.message;}
    finally{if(request===notesRequest){notesModelsLoading=false;$('notes-confirm').disabled=!$('notes-model-choice').value;}}
  }
  $('notes-provider').onchange=()=>{$('notes-cloud-consent').checked=false;notesModels();};
  $('notes-model-refresh').onclick=notesModels;
  $('notes-model-choice').onchange=()=>{$('notes-confirm').disabled=notesModelsLoading||!$('notes-model-choice').value;};
  $('notes-auto-context').onchange=()=>{$('notes-context').disabled=$('notes-auto-context').checked;};
  $('notes-cancel').onclick=()=>$('notes-dialog').close();
  $('notes-open-settings').onclick=()=>{const provider=$('notes-provider').value;$('notes-dialog').close();location.hash='settings';if(provider!=='gemini'&&provider!==localProvider()){$('local-provider').value=provider;$('local-provider').onchange();}const target=$(provider==='gemini'?'gemini-key':'ollama-service-url');target.closest('details').open=true;target.focus();};
  $('notes-confirm').onclick=async()=>{
    if(notesModelsLoading||processing)return;
    const provider=$('notes-provider').value;
    if(currentJob?.folder!==notesFolder){$('notes-choice-status').textContent='Выбрана другая запись. Закройте окно и откройте конспект для нужной записи.';return;}
    if(provider==='gemini'&&!$('notes-cloud-consent').checked){$('notes-choice-status').textContent='Подтвердите отправку текста в Google.';return;}
    $('notes-confirm').disabled=true;
    const construction={provider,model:$('notes-model-choice').value,strategy:$('notes-strategy').value,context_tokens:Number($('notes-context').value),auto_context:$('notes-auto-context').checked,output_tokens:2048};
    try{if(await postprocess('notes',{construction,translate_after:$('notes-translate-after').checked,cloud_confirmed:$('notes-cloud-consent').checked}))$('notes-dialog').close();else $('notes-choice-status').textContent=$('message').textContent;}finally{$('notes-confirm').disabled=false;}
  };
  async function localAI(task){
    try{
      const prefs=await api('/api/translation-settings');
      if(prefs.provider==='lmstudio'){await postprocess(task);return;}
      const status=await api('/api/setup/ollama');
      if(status.ready){await postprocess(task);return;}
      location.hash='settings';const target=$('ollama-service-url');target.closest('details').open=true;
      target.focus();$('ollama-feedback').textContent=status.message;
    }catch(e){message(e.message,true);}
  }

  let speakerFolder=null, speakerPending=false, speakerNeedsInstall=false;
  async function openSpeakers(){
    speakerFolder=currentJob?.folder;
    if(!speakerFolder)return;
    $('speaker-dialog').showModal();
    try{await speakerStatus();$('speaker-device').focus();}catch(e){$('speaker-status').textContent='Не удалось проверить готовность. Закройте окно и повторите.';}
  }
  async function speakerStatus(preserveDevice=false){
    const d=await api('/api/components'), item=d.components.find(c=>c.id==='diarization');
    const health=await api('/api/doctor');
    const diagnostics=await api('/api/setup/diagnostics');
    speakerNeedsInstall=health.diarization?.state!=='configured';
    if(!speakerPending&&!preserveDevice)$('speaker-device').value=health.diarization?.requested_device||'auto';
    if($('speaker-device').value==='xpu'&&health.diarization?.device!=='xpu')speakerNeedsInstall=true;
    for(const option of $('speaker-device').options){const unavailable=option.value==='npu'||option.value==='xpu'&&!diagnostics.hardware.intel_gpu.length;option.disabled=unavailable;const ready=!speakerNeedsInstall&&item.state==='ready'&&(option.value==='auto'||option.value===health.diarization?.device);option.textContent=(option.value==='auto'?'Автоматически (рекомендуется)':deviceName(option.value))+' · '+(option.value==='npu'?'не поддерживается для этой задачи':unavailable?'не обнаружена совместимая видеокарта':ready?'готово':'потребуется проверка или подготовка');}
    if(!preserveDevice)$('speaker-consent').checked=item.download_consent===true&&item.consent_revision===d.profiles.diarization_model?.revision;
    $('speaker-hf-fields').hidden=item.requires_download===false;
    $('speaker-token').placeholder=d.has_hf_token?'Токен сохранён; можно оставить пустым':'Введите токен чтения';
    $('speaker-install-fields').open=speakerNeedsInstall;
    $('speaker-install-fields').hidden=!speakerNeedsInstall;
    $('speaker-status').textContent=speakerNeedsInstall?'Потребуется подготовка. Подтвердите загрузку и доступ к модели.':(item.state==='ready'?'Готово для ':'Окружение найдено для ')+deviceName(health.diarization?.device||'cpu')+(item.state==='ready'?'. Можно запускать.':'. Проверим автоматически перед запуском.');
    $('speaker-go').textContent=speakerNeedsInstall?'Скачать, подготовить и запустить':'Разделить по участникам';
  }
  $('speaker-device').onchange=async()=>{$('speaker-go').disabled=true;try{await speakerStatus(true);}catch(e){$('speaker-status').textContent=e.message;}finally{$('speaker-go').disabled=false;}};
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
      const cached=health.diarization?.state==='configured'&&previous.state==='ready'&&(device==='auto'||health.diarization.device===device);
      if(!cached)await api('/api/components',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({component:'diarization',action:speakerNeedsInstall?'install':'check',device,token,resume:{folder,task:'diarize'},confirmed:$('speaker-consent').checked})});
      await componentStatus();
      $('speaker-token').value='';
      $('speaker-status').textContent='Подготавливаем разделение по участникам… Можно закрыть это окно.';
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
  async function storageStatus(){
    const data=await api('/api/storage'),t=data.transfer||{};storageLocked=data.active||data.restart_required;
    $('records-directory').textContent='Сейчас записи хранятся в: '+data.records;
    for(const [id,path] of [['component-root',data.components],['records-root',data.records]]){if(!$(id).dataset.storageLoaded){$(id).value=path;$(id).dataset.storageLoaded='true';}}
    $('storage-feedback').textContent=(t.message||'')+(t.source?' Исходная папка: '+t.source+'. Новая: '+t.target+'.':'')+(data.active&&t.total?' Скопировано и проверяется: '+(t.bytes/1024**3).toFixed(2)+' из '+(t.total/1024**3).toFixed(2)+' ГиБ.':'');
    $('storage-progress').hidden=!data.active;if(t.total){$('storage-progress').max=t.total;$('storage-progress').value=t.bytes||0;}else $('storage-progress').removeAttribute('value');
    $('storage-cleanup').hidden=!t.cleanup_pending||data.restart_required||data.active;
    for(const id of ['save-component-root','save-records-root','pick-component-root','pick-records-root'])$(id).disabled=data.active||data.restart_required||!!t.cleanup_pending;
    if(data.active||data.restart_required){$('start').disabled=true;$('bootstrap-message').textContent=data.restart_required?'Данные перенесены. Полностью завершите приложение через меню трея и откройте снова.':'Переносим данные. Дождитесь завершения.';}
    if(data.active)setTimeout(()=>storageStatus().catch(e=>message(e.message,true)),1000);
  }
  async function storageAction(body){try{await setupPost('storage',body);await storageStatus();}catch(e){$('storage-feedback').textContent=e.message;}}
  for(const [kind,input,pick,save] of [['components','component-root','pick-component-root','save-component-root'],['records','records-root','pick-records-root','save-records-root']]){
    $(pick).onclick=async()=>{try{const result=await setupPost('storage',{action:'pick'});if(result.path)$(input).value=result.path;}catch(e){$('storage-feedback').textContent=e.message;}};
    $(save).onclick=()=>{if(window.confirm('Перенести данные в «'+$(input).value+'»? После проверки потребуется полностью перезапустить приложение. Старые файлы сохранятся до отдельной очистки.'))storageAction({action:'transfer',kind,directory:$(input).value,confirmed:true});};
  }
  $('storage-cleanup').onclick=()=>{if(window.confirm('Удалить проверенные файлы старой копии? Новая папка уже должна использоваться приложением.'))storageAction({action:'cleanup',confirmed:true});};
  $('cancel-preparation').onclick=async()=>{const d=await api('/api/components');if(d.active)await componentAction(d.active,'cancel');};

  for(const section of document.querySelectorAll('.ai-section')){const summary=section.querySelector(':scope > summary');summary.setAttribute('aria-expanded',String(section.open));section.addEventListener('toggle',()=>summary.setAttribute('aria-expanded',String(section.open)));}
  api('/health').then(h=>{instance=h.instance;$('build-label').textContent='Video Descriptor '+h.version+(h.build!=null?' · билд '+h.build:'');return Promise.all([readiness(),jobs(),setupStatus(),componentStatus()]).then(()=>Promise.allSettled([ollamaStatus(),diagnostics(),storageStatus()]));}).then(()=>{if(selected)poll();}).catch(e=>message(e.message,true));
  const checks=setInterval(()=>{readiness();jobs().catch(()=>{});},15000);
})();
