(() => {
  const $ = id => document.getElementById('construction-' + id);
  const form = document.getElementById('construction-settings-form');
  const fields = {input:'input',material:'material',provider:'provider',model:'model',strategy:'strategy',grouping:'grouping',
    context_tokens:'context',output_tokens:'output',chunk_seconds:'chunk',max_chunk_seconds:'max-chunk',max_chunk_chars:'max-chars',prompt:'prompt',article_prompt:'article-prompt'};
  const numeric = new Set(['context_tokens','output_tokens','chunk_seconds','max_chunk_seconds','max_chunk_chars']);
  let ready = false, selected = null, prompts = {}, lastMaterial = null, drafts = {}, previewVersion = 0, busy = false;
  let resultKind = 'notes';
  function openSettings(kind='notes') {
    resultKind=kind;const article=kind==='article';
    const panel=document.getElementById('notes-settings');panel.closest('section').hidden=false;panel.open=true;
    $('heading').textContent=article?'Настройки новой статьи':'Настройки нового конспекта';
    $('notes-instruction').hidden=article;$('article-instruction').hidden=!article;
    for(const id of ['input','material','strategy'])$(id).closest('label').hidden=article||(id==='input'&&window.recordingUI?.native);
    for(const id of ['grouping','chunk','max-chunk','max-chars'])$(id).closest('label').hidden=article;
    $('source-help').textContent=article?'В модель отправляется полная выбранная расшифровка.':'В запрос передаётся расшифровка и, при выборе, распознанный текст слайдов.';
    $('plan-help').textContent=article?'Перед запуском проверяем, что полная расшифровка, промпт и ответ помещаются в контекст модели.':'Перед запуском проверяем лимиты модели. При обработке по частям результаты объединяются в общий конспект и оглавление.';
    $('status').textContent=article?'Настройте промпт статьи и нажмите «Создать статью».':'Настройте конспект и запустите создание новой версии.';
    buttons();preview();(article?$('article-prompt'):$('model')).focus();
  }
  const providerValues = {};
  let modelRequest=0, modelLoading=false, pendingModel='';
  const modelLists={};
  const validModel=()=>!modelLoading&&(modelLists[$('provider').value]||[]).some(model=>model.id===$('model').value);
  function setModel(value){
    const select=$('model');
    pendingModel=value||'';
    select.value=[...select.options].some(option=>option.value===value)?value:'';
  }
  let lastProvider = null;
  async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Не удалось получить данные');
    return data;
  }
  const post = (url, data) => api(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  function settings() {
    return {...Object.fromEntries(Object.entries(fields).map(([key,id]) => [key,numeric.has(key) ? Number($(id).value) : $(id).value])),...(window.recordingUI?.native?{input:'speech'}:{}),auto_context:$('auto-context').checked,result_kind:resultKind};
  }
  function fill(config) { for (const [key,id] of Object.entries(fields)) (id==='model'?setModel(config[key]):$(id).value = (config[key] ?? (key==='article_prompt'?prompts.article:''))); $('auto-context').checked=config.auto_context!==false; $('context').disabled=$('auto-context').checked; }
  $('auto-context').onchange=()=>{$('context').disabled=$('auto-context').checked;preview();};
  function buttons() {
    $('save').disabled = !ready || busy || !validModel();
    $('preview').hidden = !selected?.has_ready_transcript;
    $('run').hidden = !selected?.has_ready_transcript;
    $('plan').hidden = !selected?.has_ready_transcript;
    $('run').textContent = resultKind==='article' ? 'Создать статью' : selected?.needs_notes ? 'Построить конспект' : 'Создать новую версию конспекта';
    $('preview').disabled = !ready || busy || !validModel() || !selected?.has_ready_transcript;
    $('run').disabled = !ready || busy || !validModel() || !selected?.has_ready_transcript || selected.running || ['queued','running'].includes(selected.job?.status);
    $('article').disabled = !ready || busy || !selected?.has_ready_transcript || selected.running || ['queued','running'].includes(selected.job?.status);
    const active=selected?.running||['queued','running'].includes(selected?.job?.status);
    const reason=!ready?'Загружаем настройки генерации…':busy?'Добавляем задание в очередь…':
      !selected?.has_ready_transcript?'Сначала дождитесь готовой расшифровки.':
      active?(selected?.job?.status==='queued'?'Для этой записи уже есть задание в очереди. Дождитесь его завершения или отмените обработку.':'Для этой записи уже выполняется задание. Дождитесь завершения или нажмите «Остановить обработку».'):
      modelLoading?'Получаем список доступных моделей…':!validModel()?'Выберите доступную модель из списка выше.':'';
    $('run-reason').textContent=reason;
    $('run').title=$('run').disabled?reason:'';
    $('article').title=$('article').disabled?reason:'Настроить статью по полной расшифровке';
  }
  async function preview() {
    if (!ready || !selected?.has_ready_transcript || !validModel()) return;
    const version = ++previewVersion;
    const folder = selected.folder;
    $('plan').textContent = 'Оцениваем размер материала…';
    try {
      const data = await post('/api/construction-plan', {folder,settings:settings()});
      if (version !== previewVersion || folder !== selected?.folder) return;
      const size = 'Материал: ' + data.characters.toLocaleString('ru-RU') + ' символов, ориентировочно ' + data.estimated_tokens.toLocaleString('ru-RU') + ' токенов. ';
      $('plan').textContent = size + (data.strategy === 'whole' ? (resultKind==='article'?'Вся расшифровка будет отправлена одним запросом. Результат: статья.':'Весь подготовленный текст будет отправлен одним запросом. Результат: конспект и оглавление.') :
        'Обработка по частям: ' + data.blocks + '. Затем объединение в общий конспект и оглавление. Минимум ' + data.generation_requests + ' запросов генерации.');
    } catch (error) { if (version === previewVersion) $('plan').textContent = error.message; }
  }
  async function snapshot() {
    if (!ready) throw Error('Дождитесь загрузки настроек конспекта');
    if(!validModel())throw Error('Выберите доступную модель из списка');
    if (!form.checkValidity()) { window.studioUI?.openStage('notes'); document.getElementById('notes-settings').open = true; }
    if (!form.reportValidity()) throw Error('Проверьте настройки конспекта');
    return post('/api/construction-settings', {...settings(),result_kind:'notes'});
  }
  $('material').onchange = () => {
    drafts[lastMaterial] = $('prompt').value;
    lastMaterial = $('material').value;
    $('prompt').value = drafts[lastMaterial] ?? prompts[lastMaterial];
    preview();
  };
  $('provider').onchange = () => {
    $('cloud').checked=false; $('cloud-label').hidden=$('provider').value!=='gemini';
    providerValues[lastProvider] = {model:$('model').value, context:$('context').value, output:$('output').value};
    lastProvider = $('provider').value;
    const values = providerValues[lastProvider] || (lastProvider === 'gemini' ?
      {model:'',context:1048576,output:16384} : {model:'',context:16384,output:4096});
    for (const [id,value] of Object.entries(values)) {if(id==='model')setModel(value);else $(id).value=value;}
    $('models').replaceChildren(); loadModels();
  };
  $('reset-article-prompt').onclick=()=>{$('article-prompt').value=prompts.article;$('article-prompt').dispatchEvent(new Event('input',{bubbles:true}));preview();};
  $('reset-prompt').onclick = () => { $('prompt').value = prompts[$('material').value]; $('prompt').dispatchEvent(new Event('input',{bubbles:true})); preview(); };
  async function loadModels(){
    const provider=$('provider').value,request=++modelRequest,wanted=$('model').value||pendingModel;
    modelLists[provider]=[];$('model').replaceChildren();$('models').replaceChildren();
    modelLoading=true;++previewVersion;$('plan').textContent='План будет рассчитан после выбора доступной модели.';$('load-models').disabled=true;$('model').disabled=true;
    $('model-status').classList.remove('vd-error');$('model-status').textContent='Получаем список моделей…';buttons();
    try{
      const models=await api('/api/construction-models?'+new URLSearchParams({provider}));
      if(request!==modelRequest||provider!==$('provider').value)return;
      modelLists[provider]=models;
      $('models').replaceChildren(...models.map(model=>{const option=document.createElement('option');option.value=model.id;option.label=model.title;return option;}));
      const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent=models.length?'Выберите модель…':'Доступных моделей нет';
      $('model').replaceChildren(placeholder,...models.map(model=>{const option=document.createElement('option');option.value=model.id;option.textContent=model.title||model.id;return option;}));
      setModel(models.some(model=>model.id===wanted)?wanted:'');
      $('model-status').textContent=!models.length?'Моделей нет. Проверьте подключение в настройках AI.':wanted&&!models.some(model=>model.id===wanted)?'Прежняя модель недоступна. Выберите другую из списка.':'Доступно моделей: '+models.length;
    }catch(error){
      if(request!==modelRequest)return;
      modelLists[provider]=[];$('model-status').classList.add('vd-error');$('model-status').textContent=error.message+' Проверьте подключение и нажмите «Обновить».';
    }finally{
      if(request===modelRequest){modelLoading=false;$('load-models').disabled=false;$('model').disabled=false;buttons();preview();}
    }
  }
  $('load-models').onclick=loadModels;
  $('model').onchange=()=>{pendingModel=$('model').value;if(validModel())$('model-status').textContent='Доступно моделей: '+modelLists[$('provider').value].length;};
  $('preview').onclick = preview;
  form.addEventListener('change', event => { buttons(); if (!['material','provider'].some(id => event.target === $(id))) preview(); });
  form.onsubmit = async event => {
    event.preventDefault(); busy = true; buttons();
    try { await snapshot(); window.studioDraft?.clear(form); $('status').textContent = 'Настройки сохранены для новых запусков. Текущая обработка сохраняет свои настройки.'; }
    catch (error) { $('status').textContent = error.message; }
    finally { busy = false; buttons(); }
  };
  $('run').onclick = async () => {
    if(resultKind==='article'){await runArticle();return;}
    if (!selected?.has_ready_transcript || !validModel() || !form.reportValidity()) return;
    if(window.speechReplyEditing?.()){$('status').textContent='Сначала завершите правку реплики.';return;}
    if(document.getElementById('report-editor').contentWindow?.notesEditorDirty?.()){$('status').textContent='Сохраните правки текущего конспекта перед новым запуском.';return;}
    const folder = selected.folder, config = settings(); busy = true; buttons();
    try {
      if(config.provider==='gemini'&&!$('cloud').checked)throw Error('Подтвердите отправку текста в Google и возможные расходы');
      const job = window.recordingUI?.native ? await window.recordingUI.postprocess('notes', {
        construction:config,translate_after:false,cloud_confirmed:$('cloud').checked
      }) : await post('/api/notes-run', {folder,settings:config});
      $('status').textContent = 'Конспект добавлен в очередь. Повторное распознавание речи не требуется.';
      document.dispatchEvent(new CustomEvent('construction-started', {detail:job}));
    } catch (error) { $('status').textContent = error.message; }
    finally { busy = false; buttons(); }
  };
  $('article').onclick = () => {
    if(window.speechReplyEditing?.()||document.getElementById('report-editor').contentWindow?.notesEditorDirty?.()){document.getElementById('article-status').textContent='Сначала сохраните или отмените текущие правки.';return;}
    openSettings('article');
  };
  async function runArticle() {
    if(busy||!selected?.has_ready_transcript)return;
    const status=document.getElementById('article-status');
    status.classList.remove('vd-error');
    if(window.speechReplyEditing?.()||document.getElementById('report-editor').contentWindow?.notesEditorDirty?.()){
      $('status').textContent=status.textContent='Сначала сохраните или отмените текущие правки.';return;
    }
    const showSettings=()=>{const panel=document.getElementById('notes-settings');panel.closest('section').hidden=false;panel.open=true;$('model').focus();};
    if(!validModel()){$('status').textContent=status.textContent='Выберите доступную модель для статьи в настройках.';showSettings();return;}
    if(!form.reportValidity())return;
    const config={...settings(),result_kind:'article'};
    if(config.provider==='gemini'&&!$('cloud').checked){$('status').textContent=status.textContent='Подтвердите отправку расшифровки в Google в настройках.';showSettings();return;}
    busy=true;buttons();$('article').setAttribute('aria-busy','true');
    $('status').textContent=status.textContent='Добавляем статью в очередь…';
    try{
      const job=window.recordingUI?.native?await window.recordingUI.postprocess('notes',{
        construction:config,translate_after:false,cloud_confirmed:$('cloud').checked
      }):await post('/api/notes-run',{folder:selected.folder,settings:config});
      $('status').textContent=status.textContent='Статья добавлена в очередь. Полная расшифровка будет обработана одним запросом.';
      document.dispatchEvent(new CustomEvent('construction-started',{detail:job}));
    }catch(error){status.classList.add('vd-error');$('status').textContent=status.textContent=error.message;}
    finally{busy=false;$('article').removeAttribute('aria-busy');buttons();}
  }
  window.constructionUI = {
    snapshot, openSettings,
    media(name) {
      const audio = /\.(wav|mp3|m4a|flac|ogg)$/i.test(name);
      $('input').querySelector('option[value=slides]').disabled = audio;
      if (audio && $('input').value !== 'speech') { $('input').value = 'speech'; preview(); }
    },
    select(value) {
      const changed = value?.folder !== selected?.folder;
      selected = value;
      if (changed && ready && value?.construction_settings) {
        const config = value.construction_settings;
        fill({...config, input:config.input || (value.frame_count ? 'slides' : 'speech'),
          ...(config.result_kind==='article'?{prompt:prompts[config.material],strategy:'auto'}:{})});
        lastMaterial = config.material; lastProvider = config.provider;
        window.studioDraft?.restore(form,true);
        lastProvider=$('provider').value;lastMaterial=$('material').value;
        loadModels();
      }
      $('download').hidden = !value?.construction_result_url;
      if (value?.construction_result_url) $('download').href = value.construction_result_url;
      buttons();
      if (changed) { ++previewVersion; $('plan').textContent = 'Выберите готовую запись, чтобы оценить размер и способ обработки.'; preview(); }
    }
  };
  api('/api/construction-settings').then(data => {
    prompts = data.prompts; fill({...data.settings,...(data.settings.result_kind==='article'?{prompt:prompts[data.settings.material]}:{})}); lastMaterial = data.settings.material; lastProvider = data.settings.provider;
    window.studioDraft?.restore(form);lastMaterial=$('material').value;lastProvider=$('provider').value;
    ready = true; document.dispatchEvent(new Event('construction-ready')); buttons(); $('status').textContent = 'Настройки применяются к новым конспектам и статьям.'; loadModels();
  }).catch(error => { $('status').textContent = error.message; });
})();
