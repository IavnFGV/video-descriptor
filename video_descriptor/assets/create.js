(() => {
  const $ = id => document.getElementById(id);
  const video = $('process-video'), follow = $('follow');
  const phases = ['Проверка видео', 'Распознаём речь', 'Читаем слайды', 'Собираем конспект', 'Сохраняем отчёт', 'Переводим субтитры'];
  const params = new URLSearchParams(location.search);
  let versionInventory = [];
  let selected = params.has('job') ? {job: params.get('job')} : params.has('folder') ? {folder: params.get('folder')} : null;
  let polling = false, lastSnapshot = null, uploadBusy = false, polls = 0;
  const rendered = {};
  let promptData = null, promptTask = null;
  const promptDrafts = window.studioDraft.prompts();
  function selectPrompt() {
    if (!promptData) return;
    promptTask = $('prompt-task').value;
    $('model-prompt').value = promptDrafts[promptTask] ?? promptData.prompts[promptTask];
    window.studioDraft.savePrompts(promptDrafts,promptTask);
  }
  $('prompt-task').onchange = selectPrompt;
  $('model-prompt').addEventListener('input',()=>{if(promptTask){promptDrafts[promptTask]=$('model-prompt').value;window.studioDraft.savePrompts(promptDrafts,promptTask);}});
  $('open-prompt-settings').onclick = () => { window.studioUI.openStage('notes'); $('prompt-settings-panel').open = true; };
  if (location.hash === '#translation-settings-panel') {
    window.studioUI.openStage('speech'); $('translation-settings-panel').open = true;
  }
  $('reset-prompt').onclick = () => {
    $('model-prompt').value = promptData.defaults[promptTask];
    $('model-prompt').dispatchEvent(new Event('input',{bubbles:true}));
    $('prompt-status').textContent = 'Стандартный промпт восстановлен в редакторе. Нажмите «Сохранить промпт».';
  };
  $('prompt-settings-form').onsubmit = async event => {
    event.preventDefault(); if (!promptTask) return;
    $('save-prompt').disabled = true;
    const task = promptTask, content = $('model-prompt').value;
    try {
      promptData = await json('/api/prompts', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({task, text: content})});
      delete promptDrafts[task];window.studioDraft.savePrompts(promptDrafts,promptTask);
      window.studioDraft.clear($('prompt-settings-form'));
      $('prompt-status').textContent = 'Сохранено. Промпт будет использован в следующих блоках обработки.';
    } catch (error) { $('prompt-status').textContent = error.message; }
    finally { $('save-prompt').disabled = false; }
  };
  json('/api/prompts').then(data => {
    promptData = data;
    $('prompt-task').replaceChildren(...Object.entries(data.titles).map(([task, title]) => { const option = text('option', title); option.value = task; return option; }));
    const rememberedTask=window.studioDraft.promptTask();
    if([...$('prompt-task').options].some(option=>option.value===rememberedTask))$('prompt-task').value=rememberedTask;
    selectPrompt(); $('save-prompt').disabled = false; $('reset-prompt').disabled = false;
    $('prompt-status').textContent = 'Редактируйте инструкцию и сохраните изменения.';
  }).catch(error => { $('prompt-status').textContent = error.message; });
  $('subtitle-mode').onchange = () => { document.body.dataset.subtitles = $('subtitle-mode').value; };
  document.body.dataset.subtitles = $('subtitle-mode').value;
  async function editSubtitle(source, button) {
    const folder = lastSnapshot?.folder;
    if (!folder) return;
    button.disabled = true;
    try {
      const data = await json('/api/speech?' + new URLSearchParams({folder}));
      if (lastSnapshot?.folder !== folder) return;
      const result = data.result;
      if (!result || result.status !== 'done') throw Error('Редактирование доступно после завершения распознавания');
      const index = result.segments.findIndex(row => row.start === source.start && row.end === source.end);
      if (index < 0) throw Error('Реплика изменилась. Обновите страницу');
      follow.checked = false;
      window.editSpeechReply(result, index, video, () => {
        delete rendered['speech-feed']; poll();
      });
    } catch (error) { $('run-message').textContent = error.message; }
    finally { button.disabled = false; }
  }
  let namesFolder = null, namesLoadingFolder = null;
  async function loadSpeakerNames() {
    const folder = lastSnapshot?.folder;
    if ($('speaker-settings').hidden || !folder || namesFolder === folder || namesLoadingFolder === folder) return;
    namesLoadingFolder = folder;
    $('speaker-names-form').querySelector('button').disabled = true;
    $('speaker-names-status').textContent = 'Загружаем голоса…';
    try {
      const data = await json('/api/speech?' + new URLSearchParams({folder}));
      if (lastSnapshot?.folder !== folder) return;
      const result = data.result;
      if (!result || result.status !== 'done') throw Error('Имена доступны после завершения распознавания');
      const names = [...new Set(result.segments.map(row => row.speaker).filter(Boolean))];
      $('speaker-names').replaceChildren(...names.map(speaker => {
        const label = text('label', speaker), input = document.createElement('input');
        input.dataset.speaker = speaker; input.maxLength = 100; input.placeholder = 'Имя говорящего';
        input.value = result.speaker_names?.[speaker] || ''; label.append(input); return label;
      }));
      namesFolder = folder;
      $('speaker-names-status').textContent = names.length ? 'Введите имена вместо обозначений голосов. Они применятся ко всей расшифровке.' : 'В этой записи голоса не выделены.';
    } catch (error) { if (lastSnapshot?.folder === folder) $('speaker-names-status').textContent = error.message; }
    finally {
      if (namesLoadingFolder === folder) namesLoadingFolder = null;
      if (lastSnapshot?.folder === folder) $('speaker-names-form').querySelector('button').disabled = namesFolder !== folder || !$('speaker-names').querySelector('input');
    }
  }
  $('toggle-speaker-names').onclick = () => {
    const expanded = $('speaker-settings').hidden;
    $('speaker-settings').hidden = !expanded;
    $('toggle-speaker-names').setAttribute('aria-expanded', String(expanded));
    if (expanded) loadSpeakerNames();
  };
  $('speaker-names-form').onsubmit = async event => {
    event.preventDefault();
    const folder = namesFolder;
    if (!folder) return;
    const button = event.submitter; button.disabled = true;
    try {
      const names = Object.fromEntries([...$('speaker-names').querySelectorAll('input')].map(input => [input.dataset.speaker, input.value.trim()]));
      await json('/api/speech-names', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({folder, speaker_names: names})});
      $('speaker-names-status').textContent = 'Имена сохранены.';
      delete rendered['speech-feed']; poll();
    } catch (error) { $('speaker-names-status').textContent = error.message; }
    finally { button.disabled = false; }
  };
  const imageViewer = $('image-viewer');
  function zoomable(image) {
    image.tabIndex = 0; image.setAttribute('role', 'button');
    image.title = 'Нажмите, чтобы увеличить';
  }
  function enlargeImage(image) {
    $('large-image').src = image.src; $('large-image').alt = image.alt;
    $('image-caption').textContent = image.closest('figure')?.querySelector('figcaption')?.textContent || image.alt;
    if (!imageViewer.open) imageViewer.showModal();
  }
  document.addEventListener('click', event => {
    if (event.target.matches('#frame-feed img, .request-images img')) enlargeImage(event.target);
  });
  document.addEventListener('keydown', event => {
    if (event.target.matches('#frame-feed img, .request-images img') && ['Enter', ' '].includes(event.key)) {
      event.preventDefault(); enlargeImage(event.target);
    }
  });
  $('close-image').addEventListener('click', () => imageViewer.close());
  imageViewer.addEventListener('click', event => {
    if (event.target === imageViewer) imageViewer.close();
  });
  imageViewer.addEventListener('close', () => $('large-image').removeAttribute('src'));
  let requestUrl = null, loadedRequest = null, requestLoading = false;
  let savingThinking = false;
  $('live-thinking').addEventListener('change', async () => {
    if (!lastSnapshot) return;
    savingThinking = true; $('live-thinking').disabled = true;
    try {
      await json('/api/thinking?' + new URLSearchParams({folder: lastSnapshot.folder}), {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({thinking: $('live-thinking').checked})
      });
      $('thinking-control-status').textContent = 'Сохранено. Следующие запросы — ' + ($('live-thinking').checked ? 'с рассуждениями.' : 'без рассуждений.') + ' Текущий запрос не прерывается.';
    } catch (error) { $('thinking-control-status').textContent = error.message; }
    finally { savingThinking = false; $('live-thinking').disabled = false; poll(); }
  });
  function requestSection(parent, title, value, open = false) {
    const section = document.createElement('details'); section.open = open;
    section.append(text('summary', title), text('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
    parent.append(section);
  }
  async function loadTranslationSettings() {
    try {
      const value = await json('/api/translation-settings');
      $('translation-provider').value = value.provider;
      $('translation-local-model').value = value.ollama_model || 'qwen3.5:9b';
      updateTranslationProvider();
      $('gemini-billing').value = value.billing_mode;
      $('gemini-free-ack').checked = value.free_ack;
      $('gemini-free-label').hidden = value.billing_mode !== 'free';
      $('gemini-key-state').textContent = value.has_key ? 'Ключ сохранён. Чтобы заменить, вставьте новый.' : 'Ключ ещё не сохранён.';
      if (!Array.from($('gemini-model').options).some(option => option.value === value.model)) {
        const option = document.createElement('option'); option.value = value.model; option.textContent = value.model; $('gemini-model').append(option);
      }
      $('gemini-model').value = value.model;
      window.studioDraft.restore($('translation-settings-form'));updateTranslationProvider();
    } catch (error) { $('translation-settings-status').textContent = error.message; }
  }
  $('gemini-billing').addEventListener('change', () => { $('gemini-free-label').hidden = $('gemini-billing').value !== 'free'; });
  function updateTranslationProvider() {
    const local = $('translation-provider').value === 'ollama';
    $('translation-local-label').hidden = !local;
    $('translation-gemini-label').hidden = local;
    $('load-gemini-models').hidden = local;
  }
  $('translation-provider').addEventListener('change', updateTranslationProvider);
  async function saveTranslationSettings(event) {
    event.preventDefault();
    const connection = event.currentTarget.id === 'connections-form';
    const changes = connection ? {
      api_key: $('gemini-key').value, billing_mode: $('gemini-billing').value, free_ack: $('gemini-free-ack').checked
    } : {provider: $('translation-provider').value, model: $('gemini-model').value, ollama_model: $('translation-local-model').value};
    const status = $(connection ? 'connections-status' : 'translation-settings-status');
    try {
      await json('/api/translation-settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(changes)});
      if (connection) $('gemini-key').value = '';
      status.textContent = 'Настройки сохранены.';
      if(!connection)window.studioDraft.clear($('translation-settings-form'));
      if (connection) {await loadTranslationSettings();$('connections-form').dispatchEvent(new Event('connections-saved'));}
    } catch (error) { status.textContent = error.message; }
  }
  $('translation-settings-form').addEventListener('submit', saveTranslationSettings);
  $('connections-form').addEventListener('submit', saveTranslationSettings);
  $('load-gemini-models').addEventListener('click', async () => {
    $('translation-settings-status').textContent = 'Запрашиваем список моделей Google…';
    try {
      const list = await json('/api/gemini-models'), current = $('gemini-model').value;
      $('gemini-model').replaceChildren();
      for (const model of list) {
        const option = document.createElement('option'); option.value = model.id;
        option.textContent = model.id + (model.rates ? ' · $' + model.rates[0] + ' / $' + model.rates[1] + ' за 1 млн вход/выход' : ' · тариф уточнить');
        $('gemini-model').append(option);
      }
      if (list.some(model => model.id === current)) $('gemini-model').value = current;
      $('translation-settings-status').textContent = 'Доступно моделей: ' + list.length + '. Наличие в списке не гарантирует бесплатную квоту.';
    } catch (error) { $('translation-settings-status').textContent = error.message; }
  });
  loadTranslationSettings();
  async function showRequest() {
    if (!$('request-panel').open || !requestUrl || requestLoading || loadedRequest === requestUrl) return;
    const url = requestUrl;
    requestLoading = true;
    try {
      const journal = await json(url);
      if (requestUrl !== url) return;
      const payload = journal.payload, node = $('request-feed'); node.replaceChildren();
      if (payload.systemInstruction) {
        requestSection(node, '1. Промпт Gemini', payload.systemInstruction.parts.map(part => part.text || '').join(''), true);
        requestSection(node, '2. Отправленный текст с метками', payload.contents.flatMap(item => item.parts).map(part => part.text || '').join(''), true);
        requestSection(node, '3. Настройки модели', payload.generationConfig);
        loadedRequest = url; return;
      }
      const meta = journal.context || {};
      node.append(text('p', 'Задача: ' + (meta.task || 'анализ') + ' · блок ' + (meta.chunk || '—') +
        ' · ' + payload.model + ' · рассуждения: ' + (payload.think ? 'включены' : 'выключены'), 'hint'));
      node.append(text('p', 'Порядок отправки: инструкция → контекст и материал → прикреплённые изображения. Формат ответа задаётся отдельно.', 'hint'));
      for (const message of payload.messages || []) {
        if (message.role === 'system') {
          requestSection(node, '1. Наш промпт · инструкция модели', message.content, true); continue;
        }
        let evidence;
        try { evidence = JSON.parse(message.content); } catch { evidence = message.content; }
        if (evidence && typeof evidence === 'object' && 'lecture_context' in evidence) {
          requestSection(node, '2. Контекст лекции · план и предыдущие блоки', evidence.lecture_context);
          evidence = evidence.current_material;
        } else node.append(text('p', 'Контекст предыдущих блоков в этом запросе не передавался.', 'hint'));
        const material = document.createElement('details');
        material.append(text('summary', '3. Материал этой задачи · сообщение ' + message.role));
        const sources = Array.isArray(evidence) ? evidence : evidence?.sources || evidence?.speech;
        if (Array.isArray(sources)) {
          for (const source of sources) {
            const row = text('div', '', 'request-source');
            row.append(text('strong', (String(source.id || '').startsWith('f') ? 'Кадр / OCR' : 'Речь') +
              ' · ' + source.id + ' · ' + clock(source.start) + '–' + clock(source.end)));
            row.append(text('p', source.text || 'Текст не передан: см. прикреплённое изображение.'));
            material.append(row);
          }
        }
        requestSection(material, 'Точный материал в JSON · все поля', evidence);
        node.append(material);
        const images = message.images || [], refs = evidence?.image_sources || [];
        const gallery = text('div', '', 'request-images');
        node.append(text('h4', '4. Изображения, отправленные модели: ' + images.length));
        if (!images.length) node.append(text('p', 'Фотографии не отправлялись. Модель получила текстовый материал выше.', 'hint'));
        images.forEach((encoded, index) => {
          const card = document.createElement('figure'), image = document.createElement('img');
          image.src = 'data:image/jpeg;base64,' + encoded; image.alt = 'Отправленное изображение ' + (index + 1);
          zoomable(image);
          const ref = refs[index];
          card.append(image, text('figcaption', 'Изображение ' + (index + 1) + (ref ? ' · ' + ref.id + ' · ' + clock(ref.start) : '')));
          gallery.append(card);
        });
        node.append(gallery);
      }
      requestSection(node, 'Формат ответа · JSON-схема', payload.format);
      requestSection(node, 'Параметры запроса', {url: journal.url, stream: payload.stream, think: payload.think, ...payload.options});
      const link = text('a', 'Открыть полный запрос JSON, включая изображения'); link.href = url; link.target = '_blank'; link.rel = 'noopener'; node.append(link);
      loadedRequest = url;
    } catch (error) {
      if (requestUrl === url) $('request-feed').replaceChildren(text('p', error.message, 'empty'));
    } finally {
      requestLoading = false;
      if (requestUrl !== url) showRequest();
    }
  }
  $('request-panel').addEventListener('toggle', showRequest);
  function clock(seconds) {
    const value = Math.max(0, Math.floor(seconds || 0));
    return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60].map(n => String(n).padStart(2, '0')).join(':');
  }
  function text(tag, value, className) {
    const node = document.createElement(tag); node.textContent = value;
    if (className) node.className = className; return node;
  }
  async function json(url, options) {
    const response = await fetch(url, {...options, cache: 'no-store'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Не удалось получить данные');
    return result;
  }
  function select(value, updateUrl=true) {
    if ($('report-editor').contentWindow?.notesEditorDirty?.()) { $('run-message').textContent = 'Сохраните правки конспекта перед переключением записи.'; return; }
    selected = value; lastSnapshot = null; namesFolder = null;
    input.value = ''; $('source-file').value = ''; fileLabel();
    window.studioUI.select(value);
    $('notes-action-status').textContent = '';
    renderVersions();
    $('speaker-settings').hidden = true;
    $('toggle-speaker-names').hidden = true; $('toggle-speaker-names').setAttribute('aria-expanded', 'false');
    $('speaker-names').replaceChildren();
    window.constructionUI?.select(null);
    requestUrl = null; loadedRequest = null;
    $('request-feed').replaceChildren(text('p', 'Запрос появится после обращения к модели.', 'empty'));
    video.removeAttribute('src'); video.load(); follow.checked = true;
    Object.keys(rendered).forEach(key => delete rendered[key]);
    $('workspace').hidden = false;
    $('processing-title').textContent = 'Текущий этап';
    $('processing-message').textContent = 'Ожидаем данные обработки.';
    $('task-label').textContent = 'Ожидание';
    $('request-stats').replaceChildren();
    for (const id of ['thinking-controls', 'thinking-panel', 'request-panel', 'response-panel']) $(id).hidden = true;
    $('setup').hidden = true; $('toggle-upload').hidden = false;
    $('speech-feed').replaceChildren(text('p', 'Ожидаем распознавание.', 'empty'));
    $('notes-feed').replaceChildren(text('p', 'Ожидаем конспект.', 'empty'));
    $('frame-feed').replaceChildren();
    $('retry-job').hidden = true;
    const query = new URLSearchParams(location.search);
    for(const key of ['job','folder','report'])query.delete(key);
    for(const [key,item] of Object.entries(value))query.set(key,item);
    query.set('stage', document.querySelector('[role=tab][aria-selected=true]').dataset.stage);
    if (value.folder === params.get('folder') && params.has('report')) query.set('report', params.get('report'));
    if(updateUrl)history.replaceState(null, '', '/create?' + query);
    poll();
  }
  let activeReply = null;
  function syncPlayback() {
    if (!lastSnapshot || follow.checked) return;
    const time = video.currentTime;
    const index = lastSnapshot.speech.findIndex(row => row.start <= time && time < row.end);
    const row = index >= 0 ? $('speech-feed').children[index] : null;
    if (row === activeReply) return;
    activeReply?.classList.remove('active'); activeReply = row;
    if (row) {
      row.classList.add('active');
      const feed = $('speech-feed');
      feed.scrollTop += row.getBoundingClientRect().top - feed.getBoundingClientRect().top;
    }
  }
  function jump(time) { follow.checked = false; video.currentTime = time; syncPlayback(); }
  function stamp(time) {
    const button = text('button', clock(time), 'timestamp');
    button.type = 'button'; button.addEventListener('click', () => jump(time)); return button;
  }
  function changed(id, value, build) {
    const signature = JSON.stringify(value);
    if (rendered[id] === signature) return;
    rendered[id] = signature; build($(id));
  }
  function show(snapshot, job) {
    job = job || snapshot.job;
    if (job?.status === 'queued' || !snapshot.running && (!lastSnapshot || lastSnapshot.running)) follow.checked = false;
    lastSnapshot = snapshot;
    renderVersions();
    window.constructionUI?.select({...snapshot, job});
    window.studioDraft.restore($('construction-settings-form'));
    updateMediaOptions();
    $('workspace').hidden = false;
    $('frames-card').hidden = Boolean(snapshot.skip_images);
    $('follow-control').hidden = !snapshot.running || job?.status === 'queued';
    $('follow-hint').hidden = !snapshot.running || job?.status === 'queued';
    $('source-hint').hidden = !snapshot.running;
    $('speech-heading').textContent = snapshot.running ? 'Речь в текущем фрагменте' : 'Расшифровка записи';
    $('toggle-speaker-names').hidden = !snapshot.has_ready_transcript || !Object.keys(snapshot.speaker_names || {}).length && !snapshot.speech.some(row => row.speaker && row.speaker !== 'unknown');
    loadSpeakerNames();
    $('speaker-notice').hidden = !snapshot.speaker_notice;
    $('speaker-notice').textContent = snapshot.speaker_notice || '';
    $('run-title').textContent = snapshot.title ? snapshot.display_title : job?.title ? job.title + ' [' + snapshot.filename + ']' : snapshot.display_title || snapshot.filename;
    const status = snapshot.status || {};
    if (!savingThinking) $('live-thinking').checked = Boolean(snapshot.thinking_next);
    if (requestUrl !== snapshot.request_url) {
      requestUrl = snapshot.request_url || null; loadedRequest = null;
      $('request-feed').replaceChildren(text('p', requestUrl ? 'Загружаем точный запрос…' : 'Для этого этапа ещё нет запроса к модели.', 'empty'));
    }
    showRequest();
    const done = !snapshot.needs_notes && (job ? job.status === 'done' : snapshot.done);
    const error = job?.status === 'error' && !snapshot.notes_deleted;
    const gaps = snapshot.errors.length;
    const label = error ? 'Остановлено' : job?.status === 'queued' ? 'В очереди' : done ? (gaps ? 'Готово с пропусками' : 'Готово') : snapshot.running || job?.status === 'running' ? 'Обрабатывается' : snapshot.has_ready_transcript && snapshot.needs_notes ? 'Речь готова' : 'Запуск не активен';
    $('run-state').textContent = label;
    $('run-state').className = 'badge ' + (error || gaps ? 'error' : done ? 'done' : '');
    $('stage-label').textContent = job?.status === 'queued' ? 'Ожидает запуска' : done ? 'Обработка завершена' : !snapshot.running && snapshot.needs_notes && snapshot.has_ready_transcript ? 'Распознавание завершено · можно построить конспект' : phases[snapshot.phase - 1] + (status.chunk && status.chunk !== '—' ? ' · блок ' + status.chunk.split(' ')[0] : '');
    $('position-label').textContent = clock(snapshot.position) + ' / ' + clock(snapshot.start + snapshot.duration);
    const fraction = (status.chunk || '').match(/(\d+)\/(\d+)/);
    let progress = fraction ? (Number(fraction[1]) - (done ? 0 : 1)) / Number(fraction[2]) * 100 : 0;
    if (snapshot.phase === 2 || snapshot.phase === 3) progress = Math.max(0, snapshot.position - snapshot.start) / Math.max(1, snapshot.duration) * 100;
    if (done) progress = 100;
    const translation = snapshot.translation_progress;
    $('translation-summary').hidden = !translation;
    $('translation-blocks-panel').hidden = !translation;
    if (translation) {
      progress = translation.total ? translation.completed / translation.total * 100 : 0;
      $('translation-summary').textContent = 'Готово: ' + translation.completed + '/' + translation.total +
        ' блоков (включая кэш). Осталось: ' + translation.remaining +
        (snapshot.running ? '. Сейчас обрабатывается блок ' + translation.current + '.' : '. Обработка остановлена.');
      changed('translation-blocks', translation.blocks, node => {
        node.replaceChildren();
        const labels = {ready: 'Готово', active: 'Обрабатывается', error: 'Ошибка', retry: 'Повтор после сбоя', pending: 'Ожидает обработки'};
        for (const block of translation.blocks) {
          const dot = document.createElement('span');
          dot.className = 'block-dot ' + block.status + (block.status === 'active' && block.retry ? ' retrying' : '');
          dot.title = 'Блок ' + block.block + ': ' + labels[block.status] + (block.status === 'active' && block.retry ? ' повтор после сбоя' : '');
          dot.setAttribute('aria-label', dot.title); dot.tabIndex = 0;
          node.append(dot);
        }
      });
    }
    $('stage-progress').value = progress;
    $('run-message').textContent = (!snapshot.notes_deleted && job?.error) || (job?.status === 'queued' ? 'Задание в очереди. Готовые версии остаются доступны.' : !snapshot.running && snapshot.needs_notes && snapshot.has_ready_transcript ? 'Речь готова к просмотру и правке. Постройте конспект, когда закончите проверку.' : status.message || 'Ожидаем следующий результат.');
    if (snapshot.video_url && video.getAttribute('src') !== snapshot.video_url) video.src = snapshot.video_url;
    if (follow.checked) {
      if (video.readyState >= 1 && Math.abs(video.currentTime - snapshot.position) > 1) {
        video.pause(); video.currentTime = Math.min(snapshot.position, video.duration || snapshot.position);
      }
      $('video-clock').textContent = clock(snapshot.position);
    }
    for (const [id, url] of [['download-transcript', snapshot.subtitle_url ? '/api/transcript-text?' + new URLSearchParams({folder: snapshot.folder}) : null], ['download-subtitles', snapshot.subtitle_url], ['download-translation', snapshot.translation_url]]) { $(id).hidden = !url; if (url) $(id).href = url; }
    for(const [id,language,available] of [['download-srt','original',snapshot.subtitle_url],['download-ru-srt','ru',snapshot.translation_url]]){
      $(id).hidden=!available;
      if(available)$(id).href='/api/subtitles?'+new URLSearchParams({folder:snapshot.folder,language,format:'srt'});
    }
    $('subtitle-mode-label').hidden = !snapshot.translation_url;
    document.body.dataset.subtitles = snapshot.translation_url ? $('subtitle-mode').value : 'original';
    $('speech-count').textContent = snapshot.speech.length + ' / ' + snapshot.speech_count + ' реплик';
    changed('speech-feed', [snapshot.speech, snapshot.speaker_names, Boolean(snapshot.speech_editor_url)], node => {
      node.replaceChildren();
      if (!snapshot.speech.length) node.append(text('p', 'Обработчик речи ещё не вернул реплики.', 'empty'));
      for (const source of snapshot.speech) {
        const row = text('div', '', 'utterance'); row.append(stamp(source.start)); if (source.speaker) row.append(text('strong', ' · ' + (snapshot.speaker_names[source.speaker] || source.speaker))); row.append(text('p', source.text, 'subtitle-original')); if (source.translation != null) row.append(text('p', source.translation, 'subtitle-ru'));
        if (snapshot.speech_editor_url) {
          const edit = text('button', '✎', 'edit-subtitle'); edit.type = 'button';
          edit.title = 'Редактировать реплику'; edit.setAttribute('aria-label', 'Редактировать реплику ' + clock(source.start));
          edit.onclick = () => editSubtitle(source, edit); row.prepend(edit);
        }
        node.append(row);
      }
      activeReply = null; syncPlayback();
      if (snapshot.running && follow.checked) node.scrollTop = node.scrollHeight;
    });
    $('frame-count').textContent = snapshot.frames.length + ' / ' + snapshot.frame_count + ' кадров';
    changed('frame-feed', snapshot.frames, node => {
      node.replaceChildren();
      for (const frame of snapshot.frames) {
        const card = text('div', '', 'frame-card'), image = document.createElement('img');
        image.src = frame.image_url; image.alt = 'Кадр ' + clock(frame.start); image.loading = 'lazy';
        zoomable(image);
        card.append(image, stamp(frame.start), text('p', frame.text || 'Читаем изображение без текста.')); node.append(card);
      }
      node.scrollLeft = node.scrollWidth;
    });
    $('notes-count').textContent = snapshot.notes.length + ' заметок';
    $('notes-caption').textContent = snapshot.provisional ? 'Черновики старого запуска: фильтрация этих заметок ещё не подтверждена.' : 'Заметки из завершённых и проверенных блоков. Их можно будет отредактировать в отчёте.';
    changed('notes-feed', snapshot.notes, node => {
      node.replaceChildren();
      if (!snapshot.notes.length) node.append(text('p', 'Учебные заметки появятся после завершения блока.', 'empty'));
      for (const note of snapshot.notes) {
        const card = text('article', '', 'note'); card.append(text('h4', note.title), text('p', note.explanation));
        for (const [label, values] of [['Шаги', note.steps], ['Ограничения', note.limitations]]) {
          if (values?.length) { const list = document.createElement('ul'); card.append(text('strong', label)); values.forEach(value => list.append(text('li', value))); card.append(list); }
        }
        node.append(card);
      }
      node.scrollTop = node.scrollHeight;
    });
    const processing = snapshot.processing || {title: phases[snapshot.phase - 1], parameters: [], message: 'Параметры этого этапа не опубликованы.'};
    $('model-card').hidden = !snapshot.running && !processing.request_available;
    $('processing-title').textContent = processing.title;
    $('processing-message').textContent = processing.message;
    $('task-label').textContent = processing.task && processing.task !== '—' ? processing.task : 'Ожидание';
    $('thinking-controls').hidden = !processing.supports_thinking;
    $('thinking-panel').hidden = !processing.supports_thinking;
    $('request-panel').hidden = !processing.request_available;
    $('response-panel').hidden = !processing.request_available;
    const stats = $('request-stats'); stats.replaceChildren();
    if (processing.engine) stats.append(text('span', 'Обработчик: ' + processing.engine));
    for (const parameter of processing.parameters) {
      const value = typeof parameter.value === 'boolean' ? (parameter.value ? 'Включено' : 'Выключено') :
        typeof parameter.value === 'object' ? JSON.stringify(parameter.value) : String(parameter.value);
      stats.append(text('span', parameter.name + ': ' + value));
    }
    const span = (status.span || '').match(/([\d.]+)–([\d.]+) сек/);
    const videoSeconds = status.video_seconds ?? (span ? Number(span[2]) - Number(span[1]) : null);
    if (processing.request_available) for (const value of [videoSeconds != null ? 'Материал: ' + videoSeconds + ' сек' : null,
      status.received != null ? 'Ответ: ' + status.received + ' симв.' : null,
      status.images != null ? status.images + ' картинок отправлено' : null,
      status.request_seconds != null ? Math.round(status.request_seconds) + ' сек.' : null,
      status.provider === 'gemini' && status.estimated_usd != null ? 'Запрос ≈ $' + status.estimated_usd.toFixed(6) : null]) if (value) stats.append(text('span', value));
    const thinking = $('thinking-feed');
    thinking.textContent = snapshot.thinking || (status.request_thinking ?? status.thinking_enabled ? 'Ждём передаваемые моделью рассуждения.' : 'Текущий запрос работает без рассуждений. Переключатель выше задаёт режим следующих запросов.');
    thinking.scrollTop = thinking.scrollHeight;
    $('response-feed').textContent = snapshot.response || 'Ожидаем ответ.';
    $('errors-card').hidden = !gaps;
    changed('errors-feed', snapshot.errors, node => { node.replaceChildren(); snapshot.errors.forEach(error => node.append(text('p', 'Блок ' + error.block + ': ' + error.error, 'error-item'))); });
    $('log-feed').textContent = snapshot.log.join('\n');

    $('retry-job').hidden = !job || (!error && !(done && gaps));
    $('retry-job').textContent = 'Продолжить из кэша';
    window.studioUI.show(snapshot, job);
  }
  async function poll() {
    if (!selected || polling) return;
    polling = true; const selection = JSON.stringify(selected);
    try {
      if (selected.job) {
        const data = await json('/api/job?' + new URLSearchParams({id: selected.job}));
        if (selection !== JSON.stringify(selected)) return;
        if (data.progress) show(data.progress, data.job);
        else {
          window.studioUI.queued(data.job);
          $('workspace').hidden = false; $('run-title').textContent = data.job.title || data.job.filename;
          $('run-state').textContent = data.job.status === 'error' ? 'Ошибка' : 'В очереди';
          $('run-message').textContent = data.job.error || 'Запись сохранена. Начнём, когда завершится текущая обработка.';
          $('retry-job').hidden = data.job.status !== 'error';
        }
      } else {
        const data = await json('/api/progress?' + new URLSearchParams(selected));
        if (selection === JSON.stringify(selected)) show(data);
      }
    } catch (error) { $('run-message').textContent = error.message + ' Повторим подключение автоматически.'; }
    finally { polling = false; }
    if (++polls % 5 === 0) { listJobs(); loadInventory(); }
  }
  async function listJobs() {
    try {
      const jobs = await json('/api/jobs'); const node = $('job-list'); node.replaceChildren();
      jobs.sort((a, b) => b.created - a.created).forEach(job => {
        const status = {queued: 'В очереди', running: 'В работе', done: 'Готово', error: 'Ошибка'}[job.status];
        const button = text('button', (job.title || job.filename) + ' · ' + status);
        button.type = 'button'; button.addEventListener('click', () => { select({job: job.id}); }); node.append(button);
      });
    } catch (_) {}
  }
  const input = $('video-file');
  function updateMediaOptions() {
    const name = input.files[0]?.name || $('source-file').value || lastSnapshot?.filename || '';
    window.constructionUI?.media(name);
  }
  $('source-file').addEventListener('change', () => { input.value = ''; fileLabel(); updateMediaOptions(); });
  updateMediaOptions();
  document.addEventListener('construction-ready', updateMediaOptions);
  function renderVersions() {
    const folder = lastSnapshot?.folder;
    const videoUrl = lastSnapshot?.video_url;
    const versions = versionInventory.filter(item => item.folder === folder || videoUrl && item.video_url === videoUrl);
    $('record-versions').hidden = !folder;
    changed('existing-runs', [folder, versions], node => {
      node.replaceChildren(text('option', 'Выберите версию'));
      node.firstChild.value = '';
      for (const item of versions) {
        const option = text('option', item.label); option.value = item.folder; node.append(option);
      }
      node.value = folder || '';
    });
  }
  async function loadInventory() {
    const results = await Promise.allSettled([json('/api/speech-inventory'), json('/api/runs')]);
    const inventory = results[0].status === 'fulfilled' ? results[0].value : {sources: [], results: []};
    const runs = results[1].status === 'fulfilled' ? results[1].value : [];
    const source = $('source-file').value;
    $('source-file').replaceChildren(text('option', 'Выберите запись'));
    $('source-file').firstChild.value = '';
    for (const source of inventory.sources) { const option = text('option', source); option.value = source; $('source-file').append(option); }
    $('source-file').value = source;
    const variants = new Map(runs.map(run => [run.folder, {folder:run.folder, video_url:run.video_url, label:run.filename + ' · ' + run.kind + ' · ' + new Date(run.created * 1000).toLocaleString('ru-RU')} ]));
    for (const result of inventory.results) {
      if (result.folder && !variants.has(result.folder)) variants.set(result.folder, {folder: result.folder, video_url:result.video_url, label: (result.title || result.video) + ' · ' + result.engine});
    }
    window.studioDraft.restore($('upload-form'));
    versionInventory = [...variants.values()];
    renderVersions();
    if (results.every(result => result.status === 'rejected')) {
      $('upload-status').hidden = false;
      $('upload-status').textContent = 'Не удалось загрузить список записей. Обновите страницу.';
    }
  }
  let deletionFolder = null, deletionKind = 'version', deletionReport = '';
  function confirmDeletion(kind) {
    if (!lastSnapshot?.folder) return;
    deletionFolder = lastSnapshot.folder; deletionKind = kind;
    deletionReport = kind === 'notes' ? window.studioUI.reportVariant() : '';
    const option = [...$('existing-runs').options].find(item => item.value === deletionFolder);
    $('delete-version-name').textContent = (option?.textContent || lastSnapshot.display_title || lastSnapshot.filename) + ' · ' + deletionFolder + (deletionReport ? ' · ' + deletionReport : '');
    $('delete-version-heading').textContent = kind === 'notes' ? 'Удалить этот конспект?' : 'Удалить версию целиком?';
    $('delete-version-description').textContent = kind === 'notes'
      ? 'Будут удалены только выбранный конспект и его ручные правки. Расшифровка, перевод, имена голосов и кадры сохранятся. Отменить удаление нельзя.'
      : 'Будут удалены расшифровка, конспект и сохранённые правки этой версии. Исходный видеофайл и другие версии сохранятся. Отменить удаление нельзя.';
    $('confirm-delete-version').textContent = kind === 'notes' ? 'Удалить конспект' : 'Удалить версию целиком';
    $('delete-version-status').textContent = '';
    $('confirm-delete-version').disabled = false;
    $('record-menu').open = false;
    $('delete-version-dialog').showModal();
  }
  $('delete-version').onclick = () => confirmDeletion('version');
  $('delete-notes').onclick = () => confirmDeletion('notes');
  $('cancel-delete-version').onclick = () => $('delete-version-dialog').close();
  $('confirm-delete-version').onclick = async () => {
    if (!deletionFolder) return;
    $('confirm-delete-version').disabled = true;
    try {
      await json(deletionKind === 'notes' ? '/api/delete-notes' : '/api/delete-version', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({folder:deletionFolder, report:deletionReport})
      });
      $('delete-version-dialog').close();
      if (lastSnapshot?.folder === deletionFolder) {
        window.studioUI.resetReport();
        if (deletionKind === 'notes') {
          $('notes-settings').open = true;
          $('notes-action-status').textContent = 'Конспект удалён. Готовая речь и субтитры сохранены — можно создать новый.';
          delete rendered['notes-feed'];
          await poll();
        } else {
          selected = null; lastSnapshot = null; namesFolder = null;
          window.constructionUI.select(null); window.studioUI.select(null); renderVersions();
          video.removeAttribute('src'); video.load();
          $('workspace').hidden = true; $('setup').hidden = false; $('toggle-upload').hidden = true;
          $('existing-runs').value = '';
          window.studioUI.openStage('source'); updateMediaOptions();
          history.replaceState(null, '', '/create?stage=source');
        }
      }
      deletionFolder = null;
      loadInventory(); listJobs();
    } catch (error) { $('delete-version-status').textContent = error.message; }
    finally { $('confirm-delete-version').disabled = false; }
  };
  $('toggle-upload').addEventListener('click', () => {
    if (document.getElementById('report-editor').contentWindow?.notesEditorDirty?.()) {
      $('run-message').textContent = 'Сохраните правки конспекта перед открытием другой записи.'; return;
    }
    selected = null; lastSnapshot = null; namesFolder = null;
    window.constructionUI.select(null); window.studioUI.select(null); renderVersions();
    $('workspace').hidden = true; $('setup').hidden = false; $('toggle-upload').hidden = true;
    window.studioUI.openStage('source'); updateMediaOptions();
    history.replaceState(null, '', '/create?stage=source');
  });
  function fileLabel() { $('file-label').textContent = input.files[0]?.name || 'Выберите или перетащите запись'; }
  input.addEventListener('change', () => { $('source-file').value = ''; fileLabel(); updateMediaOptions(); });
  const drop = $('drop-zone');
  drop.addEventListener('dragover', event => { event.preventDefault(); drop.classList.add('dragging'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragging'));
  drop.addEventListener('drop', event => { event.preventDefault(); drop.classList.remove('dragging'); if (event.dataTransfer.files.length) { input.files = event.dataTransfer.files; $('source-file').value = ''; fileLabel(); updateMediaOptions(); } });
  $('upload-form').addEventListener('submit', async event => {
    event.preventDefault(); if (uploadBusy) return;
    if (!input.files[0]) {
      if (!$('source-file').value) { $('upload-status').hidden = false; $('upload-status').textContent = 'Выберите запись.'; return; }
      uploadBusy = true; $('start').disabled = true; $('upload-status').hidden = false;
      try {
        const job = await json('/api/speech-run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
          video: $('source-file').value, title: $('lecture-name').value, engine: $('speech-engine').value,
          mode: $('construction-input').value === 'slides' ? 'lecture' : 'audio', thinking: false,
          construction: (await window.constructionUI.snapshot()).settings
        })});
        select({job: job.id}); listJobs();
      } catch (error) { $('upload-status').textContent = error.message; }
      finally { uploadBusy = false; $('start').disabled = false; }
      return;
    }
    uploadBusy = true; $('start').disabled = true; $('upload-progress').hidden = false;
    $('upload-status').hidden = false; $('upload-status').textContent = 'Загружаем запись…';
    const file = input.files[0], xhr = new XMLHttpRequest();
    const query = new URLSearchParams({filename: file.name, title: $('lecture-name').value, thinking: 'false', mode: $('construction-input').value === 'slides' ? 'lecture' : 'audio', engine: $('speech-engine').value});
    try { query.set('construction', (await window.constructionUI.snapshot()).settings_id); }
    catch (error) { $('upload-status').textContent = error.message; uploadBusy = false; $('start').disabled = false; $('upload-progress').hidden = true; return; }
    $('start').setAttribute('aria-busy','true');$('upload-progress').removeAttribute('value');
    xhr.open('POST', '/api/upload?' + query);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.addEventListener('progress', event => { if (event.lengthComputable) { $('upload-progress').value = event.loaded / event.total * 100; $('upload-status').textContent = 'Загрузка: ' + Math.round(event.loaded / event.total * 100) + '%'; } });
    xhr.addEventListener('load', () => {
      try {
        const result = JSON.parse(xhr.responseText);
        if (xhr.status !== 202) throw new Error(result.error || 'Не удалось загрузить видео');
        $('upload-status').textContent = 'Запись добавлена в очередь. Можно закрыть страницу — обработка продолжится.';
        select({job: result.id}); listJobs();
      } catch (error) { $('upload-status').textContent = error.message; }
    });
    xhr.addEventListener('error', () => { $('upload-status').textContent = 'Соединение оборвалось. Попробуйте загрузить видео ещё раз.'; });
    xhr.addEventListener('loadend', () => { uploadBusy = false; $('start').disabled = false; $('start').setAttribute('aria-busy','false');$('upload-progress').hidden=true; });
    xhr.send(file);
  });
  $('retry-job').addEventListener('click', async () => {
    const id = selected?.job || lastSnapshot?.job?.id;
    if (!id) return;
    try { await json('/api/retry?' + new URLSearchParams({id}), {method: 'POST'}); poll(); listJobs(); }
    catch (error) { $('run-message').textContent = error.message; }
  });
  $('existing-runs').addEventListener('change', event => { if (event.target.value) select({folder: event.target.value}); });
  document.addEventListener('construction-started', event => { select({job:event.detail.id}); listJobs(); });
  video.addEventListener('pointerdown', () => { follow.checked = false; });
  video.addEventListener('timeupdate', () => { if (!follow.checked) { $('video-clock').textContent = clock(video.currentTime); syncPlayback(); } });
  follow.addEventListener('change', () => { if (follow.checked && lastSnapshot) show(lastSnapshot); });
  window.addEventListener('popstate',()=>{
    const query=new URLSearchParams(location.search);
    const value=query.has('job')?{job:query.get('job')}:query.has('folder')?{folder:query.get('folder')}:null;
    if(value&&JSON.stringify(value)!==JSON.stringify(selected))select(value,false);
  });
  loadInventory();
  listJobs(); if (selected) select(selected);
  setInterval(poll, 2000);
})();
