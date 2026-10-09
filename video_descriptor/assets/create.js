(() => {
  const $ = id => document.getElementById(id);
  const video = $('process-video'), follow = $('follow'), timeline = $('timeline');
  const phases = ['Проверка видео', 'Распознаём речь', 'Читаем слайды', 'Собираем конспект', 'Сохраняем отчёт', 'Переводим субтитры'];
  const params = new URLSearchParams(location.search);
  let selected = params.has('job') ? {job: params.get('job')} : params.has('folder') ? {folder: params.get('folder')} : null;
  let polling = false, lastSnapshot = null, uploadBusy = false, polls = 0;
  const rendered = {};
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
  async function showRequest() {
    if (!$('request-panel').open || !requestUrl || requestLoading || loadedRequest === requestUrl) return;
    const url = requestUrl;
    requestLoading = true;
    try {
      const journal = await json(url);
      if (requestUrl !== url) return;
      const payload = journal.payload, node = $('request-feed'); node.replaceChildren();
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
  function select(value) {
    selected = value; lastSnapshot = null;
    requestUrl = null; loadedRequest = null;
    $('request-feed').replaceChildren(text('p', 'Запрос появится после обращения к модели.', 'empty'));
    video.removeAttribute('src'); video.load(); follow.checked = true;
    Object.keys(rendered).forEach(key => delete rendered[key]);
    $('workspace').hidden = false;
    $('setup').hidden = true; $('toggle-upload').hidden = false;
    $('speech-feed').replaceChildren(text('p', 'Ожидаем распознавание.', 'empty'));
    $('notes-feed').replaceChildren(text('p', 'Ожидаем конспект.', 'empty'));
    $('frame-feed').replaceChildren();
    $('open-report').hidden = true; $('retry-job').hidden = true;
    history.replaceState(null, '', '/create?' + new URLSearchParams(value));
    poll();
  }
  function jump(time) { follow.checked = false; video.currentTime = time; timeline.value = time; }
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
    lastSnapshot = snapshot;
    $('workspace').hidden = false;
    $('run-title').textContent = job?.title ? job.title + ' [' + snapshot.filename + ']' : snapshot.display_title || snapshot.filename;
    const status = snapshot.status || {};
    if (!savingThinking) $('live-thinking').checked = Boolean(snapshot.thinking_next);
    if (requestUrl !== snapshot.request_url) {
      requestUrl = snapshot.request_url || null; loadedRequest = null;
      $('request-feed').replaceChildren(text('p', requestUrl ? 'Загружаем точный запрос…' : 'Для этого этапа ещё нет запроса к модели.', 'empty'));
    }
    showRequest();
    const done = job ? job.status === 'done' : snapshot.done;
    const error = job?.status === 'error';
    const gaps = snapshot.errors.length;
    const label = error ? 'Остановлено' : job?.status === 'queued' ? 'В очереди' : done ? (gaps ? 'Готово с пропусками' : 'Готово') : snapshot.running || job?.status === 'running' ? 'Обрабатывается' : 'Запуск не активен';
    $('run-state').textContent = label;
    $('run-state').className = 'badge ' + (error || gaps ? 'error' : done ? 'done' : '');
    $('stage-label').textContent = done ? 'Обработка завершена' : phases[snapshot.phase - 1] + (status.chunk && status.chunk !== '—' ? ' · блок ' + status.chunk.split(' ')[0] : '');
    $('position-label').textContent = clock(snapshot.position) + ' / ' + clock(snapshot.start + snapshot.duration);
    const fraction = (status.chunk || '').match(/(\d+)\/(\d+)/);
    let progress = fraction ? (Number(fraction[1]) - (done ? 0 : 1)) / Number(fraction[2]) * 100 : 0;
    if (snapshot.phase === 2 || snapshot.phase === 3) progress = Math.max(0, snapshot.position - snapshot.start) / Math.max(1, snapshot.duration) * 100;
    if (done) progress = 100;
    $('stage-progress').value = progress;
    document.querySelectorAll('#steps li').forEach((step, index) => {
      step.className = done || index + 1 < snapshot.phase ? 'done' : index + 1 === snapshot.phase ? 'active' : '';
    });
    $('run-message').textContent = job?.error || status.message || 'Ожидаем следующий результат.';
    if (snapshot.video_url && video.getAttribute('src') !== snapshot.video_url) video.src = snapshot.video_url;
    timeline.max = snapshot.start + snapshot.duration || 1;
    if (follow.checked) {
      timeline.value = snapshot.position;
      if (video.readyState >= 1 && Math.abs(video.currentTime - snapshot.position) > 1) {
        video.pause(); video.currentTime = Math.min(snapshot.position, video.duration || snapshot.position);
      }
      $('video-clock').textContent = clock(snapshot.position);
    }
    $('speech-count').textContent = snapshot.speech.length + ' / ' + snapshot.speech_count + ' реплик';
    changed('speech-feed', snapshot.speech, node => {
      node.replaceChildren();
      if (!snapshot.speech.length) node.append(text('p', 'Whisper ещё не вернул реплики.', 'empty'));
      for (const source of snapshot.speech) {
        const row = text('div', '', 'utterance'); row.append(stamp(source.start), text('p', source.text)); node.append(row);
      }
      node.scrollTop = node.scrollHeight;
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
    $('task-label').textContent = status.task && status.task !== '—' ? status.task : 'Ожидание';
    const stats = $('request-stats'); stats.replaceChildren();
    const span = (status.span || '').match(/([\d.]+)–([\d.]+) сек/);
    const videoSeconds = status.video_seconds ?? (span ? Number(span[2]) - Number(span[1]) : null);
    for (const value of [status.model, videoSeconds != null ? 'Материал: ' + videoSeconds + ' сек видео' : null,
      status.received != null ? 'Ответ: ' + status.received + ' симв.' : null,
      status.images != null ? status.images + ' картинок отправлено' : null,
      status.request_seconds != null ? Math.round(status.request_seconds) + ' сек.' : null]) if (value) stats.append(text('span', value));
    const thinking = $('thinking-feed');
    thinking.textContent = snapshot.thinking || (status.request_thinking ?? status.thinking_enabled ? 'Ждём передаваемые моделью рассуждения.' : 'Текущий запрос работает без рассуждений. Переключатель выше задаёт режим следующих запросов.');
    thinking.scrollTop = thinking.scrollHeight;
    $('response-feed').textContent = snapshot.response || 'Ожидаем ответ.';
    $('errors-card').hidden = !gaps;
    changed('errors-feed', snapshot.errors, node => { node.replaceChildren(); snapshot.errors.forEach(error => node.append(text('p', 'Блок ' + error.block + ': ' + error.error, 'error-item'))); });
    $('log-feed').textContent = snapshot.log.join('\n');
    $('open-report').hidden = !snapshot.report_url;
    if (snapshot.report_url) $('open-report').href = snapshot.report_url;
    $('retry-job').hidden = !job || (!error && !(done && gaps));
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
          $('workspace').hidden = false; $('run-title').textContent = data.job.title || data.job.filename;
          $('run-state').textContent = data.job.status === 'error' ? 'Ошибка' : 'В очереди';
          $('run-message').textContent = data.job.error || 'Видео сохранено. Начнём, когда завершится текущая обработка.';
          $('retry-job').hidden = data.job.status !== 'error';
        }
      } else {
        const data = await json('/api/progress?' + new URLSearchParams(selected));
        if (selection === JSON.stringify(selected)) show(data);
      }
    } catch (error) { $('run-message').textContent = error.message + ' Повторим подключение автоматически.'; }
    finally { polling = false; }
    if (++polls % 5 === 0) listJobs();
  }
  async function listJobs() {
    try {
      const jobs = await json('/api/jobs'); const node = $('job-list'); node.replaceChildren();
      jobs.sort((a, b) => b.created - a.created).forEach(job => {
        const status = {queued: 'В очереди', running: 'В работе', done: 'Готово', error: 'Ошибка'}[job.status];
        const button = text('button', (job.title || job.filename) + ' · ' + status);
        button.type = 'button'; button.addEventListener('click', () => select({job: job.id})); node.append(button);
      });
    } catch (_) {}
  }
  const input = $('video-file');
  $('toggle-upload').addEventListener('click', () => {
    $('setup').hidden = !$('setup').hidden;
    $('toggle-upload').textContent = $('setup').hidden ? '＋ Другое видео / новый конспект' : 'Скрыть загрузку';
  });
  function fileLabel() { $('file-label').textContent = input.files[0]?.name || 'Выберите или перетащите видео'; }
  input.addEventListener('change', fileLabel);
  const drop = $('drop-zone');
  drop.addEventListener('dragover', event => { event.preventDefault(); drop.classList.add('dragging'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragging'));
  drop.addEventListener('drop', event => { event.preventDefault(); drop.classList.remove('dragging'); if (event.dataTransfer.files.length) { input.files = event.dataTransfer.files; fileLabel(); } });
  $('upload-form').addEventListener('submit', event => {
    event.preventDefault(); if (uploadBusy || !input.files[0]) return;
    uploadBusy = true; $('start').disabled = true; $('upload-progress').hidden = false;
    $('upload-status').hidden = false; $('upload-status').textContent = 'Загружаем видео…';
    const file = input.files[0], xhr = new XMLHttpRequest();
    const query = new URLSearchParams({filename: file.name, title: $('lecture-name').value, thinking: String($('thinking-option').checked)});
    xhr.open('POST', '/api/upload?' + query);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.addEventListener('progress', event => { if (event.lengthComputable) { $('upload-progress').value = event.loaded / event.total * 100; $('upload-status').textContent = 'Загрузка: ' + Math.round(event.loaded / event.total * 100) + '%'; } });
    xhr.addEventListener('load', () => {
      try {
        const result = JSON.parse(xhr.responseText);
        if (xhr.status !== 202) throw new Error(result.error || 'Не удалось загрузить видео');
        $('upload-status').textContent = 'Видео добавлено в очередь. Можно закрыть страницу — обработка продолжится.';
        select({job: result.id}); listJobs();
      } catch (error) { $('upload-status').textContent = error.message; }
    });
    xhr.addEventListener('error', () => { $('upload-status').textContent = 'Соединение оборвалось. Попробуйте загрузить видео ещё раз.'; });
    xhr.addEventListener('loadend', () => { uploadBusy = false; $('start').disabled = false; });
    xhr.send(file);
  });
  $('retry-job').addEventListener('click', async () => {
    if (!selected?.job) return;
    try { await json('/api/retry?' + new URLSearchParams({id: selected.job}), {method: 'POST'}); poll(); listJobs(); }
    catch (error) { $('run-message').textContent = error.message; }
  });
  $('existing-runs').addEventListener('change', event => { if (event.target.value) select({folder: event.target.value}); });
  timeline.addEventListener('input', () => jump(Number(timeline.value)));
  video.addEventListener('pointerdown', () => { follow.checked = false; });
  video.addEventListener('timeupdate', () => { if (!follow.checked) { timeline.value = video.currentTime; $('video-clock').textContent = clock(video.currentTime); } });
  follow.addEventListener('change', () => { if (follow.checked && lastSnapshot) show(lastSnapshot); });
  json('/api/runs').then(items => items.forEach(run => { const option = text('option', run.filename + (run.ready ? ' · отчёт готов' : ' · в работе') + ' [' + run.folder.slice(-6) + ']'); option.value = run.folder; $('existing-runs').append(option); })).catch(() => {});
  listJobs(); if (selected) select(selected);
  setInterval(poll, 2000);
})();
