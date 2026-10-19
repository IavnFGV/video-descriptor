/* Review-only local state. Deliberately no fetch, XHR, AI or production handlers. */
(() => {
  const $ = id => document.getElementById(id);
  let sample = false;
  const allowed = new Set(['mp4','mkv','mov','webm','wav','mp3','m4a','flac','ogg']);
  function validate(files) {
    const file = files[0];
    const error = files.length > 1 ? 'Добавьте один файл за раз.' : !file ? '' : file.size > 4 * 1024 ** 3 ? 'Файл больше 4 ГБ. Выберите меньший файл.' : !allowed.has(file.name.split('.').pop().toLowerCase()) ? 'Формат не поддерживается. Выберите видео или аудио из списка.' : '';
    $('file-error').textContent = error;
    $('demo-file').setAttribute('aria-invalid', String(Boolean(error)));
    $('demo-drop').setAttribute('aria-invalid', String(Boolean(error)));
    if (file && !error) { sample = false; $('demo-filename').textContent = file.name; }
    return Boolean(file) && !error;
  }
  $('demo-file').addEventListener('change', () => { if ($('demo-file').files.length) validate($('demo-file').files); });
  for (const name of ['dragenter','dragover']) $('demo-drop').addEventListener(name, e => { e.preventDefault(); $('demo-drop').dataset.drag = 'true'; });
  $('demo-drop').addEventListener('dragleave', () => { $('demo-drop').dataset.drag = 'false'; });
  $('demo-drop').addEventListener('drop', e => {
    e.preventDefault(); $('demo-drop').dataset.drag = 'false';
    if (validate(e.dataTransfer.files)) $('demo-file').files = e.dataTransfer.files;
  });
  function state(value) {
    const data = {
      queued:['В очереди','neutral','Ожидаем свободный обработчик','Пример: запись сохранена в очереди. Обработка ещё не началась.'],
      running:['Обрабатываем','info','Распознавание · пример 42%','Пример: распознано 04:12 из 10:00.'],
      done:['Готово','success','Расшифровка готова','Пример: теперь можно проверить текст, создать перевод или экспортировать субтитры.'],
      error:['Нужна проверка','danger','Не удалось продолжить распознавание','Пример ошибки: обработчик недоступен. Проверьте компоненты в диагностике и продолжите из кэша.'],
      'no-speech':['Готово','success','Речь не обнаружена','Пример пустого результата: речевых фрагментов не найдено. Это решение VAD, запись можно проверить вручную.']
    }[value];
    $('demo-result').hidden = !data;
    $('demo-state').value = value;
    if (!data) return;
    $('demo-job-status').textContent = data[0]; $('demo-job-status').dataset.tone = data[1];
    $('demo-stage').textContent = data[2]; $('demo-feedback').textContent = data[3];
    $('demo-progress').hidden = ['error','no-speech'].includes(value);
    if (value === 'queued') $('demo-progress').removeAttribute('value'); else $('demo-progress').value = value === 'running' ? 42 : 100;
    $('demo-result-actions').hidden = !['done','error','no-speech'].includes(value);
    $('demo-retry').hidden = value !== 'error'; $('demo-export').hidden = !['done','no-speech'].includes(value);
  }
  $('demo-upload').addEventListener('submit', e => {
    e.preventDefault();
    if (!sample && !validate($('demo-file').files)) {
      if (!$('file-error').textContent) $('file-error').textContent = 'Сначала выберите файл или добавьте пример в панели согласования.';
      $('demo-file').setAttribute('aria-invalid','true'); $('demo-drop').setAttribute('aria-invalid','true'); $('demo-file').focus(); return;
    }
    state('queued');
    $('demo-announcement').textContent = 'Открыт пример очереди. Файл не отправлялся, задание не создано.';
  });
  $('demo-state').addEventListener('change', e => state(e.target.value));
  $('demo-sample').addEventListener('click', () => {
    sample = true; $('demo-file').value = ''; $('demo-filename').textContent = 'interview-project.mp4 · демонстрационный файл';
    $('demo-title').value = 'Интервью о новом проекте'; $('file-error').textContent = '';
    $('demo-file').setAttribute('aria-invalid','false'); $('demo-drop').setAttribute('aria-invalid','false');
    $('demo-announcement').textContent = 'Добавлен пример файла. Можно посмотреть состояние очереди.';
  });
  $('demo-refresh').addEventListener('click', () => { $('demo-announcement').textContent = 'Пример списка обновлён. Запросы к рабочим сервисам не выполнялись.'; });
  document.querySelector('.record-open').addEventListener('click', () => { state('done'); $('demo-result').scrollIntoView({block:'nearest'}); });
  $('demo-retry').addEventListener('click', () => state('queued'));
  for (const [button, dialog] of [['demo-export','export-dialog'],['demo-components','components-dialog']]) $(button).addEventListener('click', () => $(dialog).showModal());
  function route() {
    const key = ['settings','diagnostics'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'records';
    for (const name of ['records','settings','diagnostics']) $(name + '-view').hidden = key !== name;
    document.querySelectorAll('.nav-item').forEach(link => { if (link.hash === '#' + key) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current'); });
    $('breadcrumb').textContent = {records:'Новая запись',settings:'Настройки AI',diagnostics:'Диагностика'}[key];
  }
  window.addEventListener('hashchange', () => { route(); $('main').focus(); }); route();
})();
