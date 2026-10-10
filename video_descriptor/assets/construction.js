(() => {
  const $ = id => document.getElementById('construction-' + id);
  const form = document.getElementById('construction-settings-form');
  const fields = {input:'input',material:'material',provider:'provider',model:'model',strategy:'strategy',grouping:'grouping',
    context_tokens:'context',output_tokens:'output',chunk_seconds:'chunk',max_chunk_seconds:'max-chunk',max_chunk_chars:'max-chars',prompt:'prompt'};
  const numeric = new Set(['context_tokens','output_tokens','chunk_seconds','max_chunk_seconds','max_chunk_chars']);
  let ready = false, selected = null, prompts = {}, lastMaterial = null, drafts = {}, previewVersion = 0, busy = false;
  const providerValues = {};
  let lastProvider = null;
  async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Не удалось получить данные');
    return data;
  }
  const post = (url, data) => api(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  function settings() {
    return Object.fromEntries(Object.entries(fields).map(([key,id]) => [key,numeric.has(key) ? Number($(id).value) : $(id).value]));
  }
  function fill(config) { for (const [key,id] of Object.entries(fields)) $(id).value = config[key]; }
  function buttons() {
    $('save').disabled = !ready || busy;
    $('preview').hidden = !selected?.has_ready_transcript;
    $('run').hidden = !selected?.has_ready_transcript;
    $('plan').hidden = !selected?.has_ready_transcript;
    $('run').textContent = selected?.needs_notes ? 'Построить конспект' : 'Создать новую версию конспекта';
    $('preview').disabled = !ready || busy || !selected?.has_ready_transcript;
    $('run').disabled = !ready || busy || !selected?.has_ready_transcript || selected.running || ['queued','running'].includes(selected.job?.status);
  }
  async function preview() {
    if (!ready || !selected?.has_ready_transcript) return;
    const version = ++previewVersion;
    const folder = selected.folder;
    $('plan').textContent = 'Оцениваем размер материала…';
    try {
      const data = await post('/api/construction-plan', {folder,settings:settings()});
      if (version !== previewVersion || folder !== selected?.folder) return;
      const size = 'Материал: ' + data.characters.toLocaleString('ru-RU') + ' символов, ориентировочно ' + data.estimated_tokens.toLocaleString('ru-RU') + ' токенов. ';
      $('plan').textContent = size + (data.strategy === 'whole' ? 'Весь подготовленный текст будет отправлен одним запросом. Результат: конспект и оглавление.' :
        'Обработка по частям: ' + data.blocks + '. Затем объединение в общий конспект и оглавление. Минимум ' + data.generation_requests + ' запросов генерации.');
    } catch (error) { if (version === previewVersion) $('plan').textContent = error.message; }
  }
  async function snapshot() {
    if (!ready) throw Error('Дождитесь загрузки настроек конспекта');
    if (!form.checkValidity()) { window.studioUI?.openStage('notes'); document.getElementById('notes-settings').open = true; }
    if (!form.reportValidity()) throw Error('Проверьте настройки конспекта');
    return post('/api/construction-settings', settings());
  }
  $('material').onchange = () => {
    drafts[lastMaterial] = $('prompt').value;
    lastMaterial = $('material').value;
    $('prompt').value = drafts[lastMaterial] ?? prompts[lastMaterial];
    preview();
  };
  $('provider').onchange = () => {
    providerValues[lastProvider] = {model:$('model').value, context:$('context').value, output:$('output').value};
    lastProvider = $('provider').value;
    const values = providerValues[lastProvider] || (lastProvider === 'gemini' ?
      {model:'gemini-3.8-flash',context:1048576,output:16384} : {model:'qwen3.5:9b',context:16384,output:4096});
    for (const [id,value] of Object.entries(values)) $(id).value = value;
    $('models').replaceChildren(); preview();
  };
  $('reset-prompt').onclick = () => { $('prompt').value = prompts[$('material').value]; preview(); };
  $('load-models').onclick = async () => {
    const provider = $('provider').value; $('load-models').disabled = true;
    try {
      const models = await api('/api/construction-models?' + new URLSearchParams({provider}));
      if (provider !== $('provider').value) return;
      $('models').replaceChildren(...models.map(model => { const option = document.createElement('option'); option.value = model.id; option.label = model.title; return option; }));
      $('status').textContent = 'Доступно моделей: ' + models.length;
    } catch (error) { $('status').textContent = error.message; }
    finally { $('load-models').disabled = false; }
  };
  $('preview').onclick = preview;
  form.addEventListener('change', event => { if (!['material','provider'].some(id => event.target === $(id))) preview(); });
  form.onsubmit = async event => {
    event.preventDefault(); busy = true; buttons();
    try { await snapshot(); $('status').textContent = 'Настройки сохранены для новых запусков. Текущая обработка сохраняет свои настройки.'; }
    catch (error) { $('status').textContent = error.message; }
    finally { busy = false; buttons(); }
  };
  $('run').onclick = async () => {
    if (!selected?.has_ready_transcript || !form.reportValidity()) return;
    const folder = selected.folder, config = settings(); busy = true; buttons();
    try {
      const job = await post('/api/notes-run', {folder,settings:config});
      $('status').textContent = 'Конспект добавлен в очередь. Повторное распознавание речи не требуется.';
      document.dispatchEvent(new CustomEvent('construction-started', {detail:job}));
    } catch (error) { $('status').textContent = error.message; }
    finally { busy = false; buttons(); }
  };
  window.constructionUI = {
    snapshot,
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
        fill({...config, input:config.input || (value.frame_count ? 'slides' : 'speech')});
        lastMaterial = config.material; lastProvider = config.provider;
      }
      $('download').hidden = !value?.construction_result_url;
      if (value?.construction_result_url) $('download').href = value.construction_result_url;
      buttons();
      if (changed) { ++previewVersion; $('plan').textContent = 'Выберите готовую запись, чтобы оценить размер и способ обработки.'; preview(); }
    }
  };
  api('/api/construction-settings').then(data => {
    prompts = data.prompts; fill(data.settings); lastMaterial = data.settings.material; lastProvider = data.settings.provider;
    ready = true; document.dispatchEvent(new Event('construction-ready')); buttons(); $('status').textContent = 'Эти настройки применяются к новым запускам конспекта.'; preview();
  }).catch(error => { $('status').textContent = error.message; });
})();
