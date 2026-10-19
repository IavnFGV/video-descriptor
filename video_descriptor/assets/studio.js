/* One recording workspace, with settings and results scoped to each stage. */
(() => {
  const $ = id => document.getElementById(id);
  let stage = new URLSearchParams(location.search).get('stage') || 'source';
  let snapshot = null, job = null, reportUrl = null, currentFolder = null;
  let variant = new URLSearchParams(location.search).get('report') || '';
  $('notes-variant').onchange = () => {
    if ($('report-editor').contentWindow?.notesEditorDirty?.()) { $('notes-variant').value = variant; $('report-version-notice').hidden = false; $('report-version-notice').textContent = 'Сохраните правки перед выбором другого варианта.'; return; }
    variant = $('notes-variant').value;
    const params = new URLSearchParams(location.search);
    if (variant) params.set('report', variant); else params.delete('report');
    history.pushState(null, '', '/create?' + params);
    loadReport();
  };
  const stages = ['source', 'speech', 'notes'];
  for(const link of document.querySelectorAll('.vd-global-nav a[href^="/#"]')){
    link.addEventListener('click',()=>{
      const target=new URL(link.href),params=new URLSearchParams(location.search);
      params.set('workspace','1');target.search=params.toString();link.href=target.href;
    });
  }
  if (!stages.includes(stage)) stage = 'source';
  function openStage(value, updateUrl = true) {
    stage = value;
    for (const name of stages) {
      const button = $('tab-' + name);
      button.setAttribute('aria-selected', String(name === stage));
      button.tabIndex = name === stage ? 0 : -1;
      $('stage-' + name).hidden = name !== stage;
      $('stage-' + name).tabIndex = -1;
    }
    const skip = document.querySelector('.vd-skip');
    if (skip) {
      skip.href = '#stage-' + stage;
      skip.onclick = event => { event.preventDefault(); $('stage-' + stage).focus(); };
    }
    if (updateUrl) {
      const params = new URLSearchParams(location.search); params.set('stage', stage);
      history.pushState(null, '', '/create?' + params);
    }
    if (stage === 'notes') loadReport();
  }
  stages.forEach(name => {
    $('tab-' + name).onclick = () => openStage(name);
    $('tab-' + name).onkeydown = event => {
      let index = stages.indexOf(name);
      if (event.key === 'ArrowRight') index = (index + 1) % stages.length;
      else if (event.key === 'ArrowLeft') index = (index + stages.length - 1) % stages.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = stages.length - 1;
      else return;
      event.preventDefault(); openStage(stages[index]); $('tab-' + stages[index]).focus();
    };
  });
  function loadReport() {
    const ownReport = snapshot?.report_variants?.find(item => item.name === variant)?.url || snapshot?.report_url || snapshot?.report_variants?.[0]?.url;
    const busy = snapshot?.running || ['queued', 'running'].includes(job?.status);
    const url = ownReport || (busy ? snapshot?.previous_report_url : null);
    $('report-editor-card').hidden = !url;
    const previous = !ownReport && Boolean(url);
    $('report-version-notice').hidden = !previous;
    if (previous) $('report-version-notice').textContent = 'Показана предыдущая версия. Новая ' + (job?.status === 'queued' ? 'ожидает в очереди.' : 'ещё не готова.');
    if (!url) {
      if (reportUrl) { reportUrl = null; $('report-editor').src = 'about:blank'; }
      return;
    }
    if (reportUrl === url || stage !== 'notes') return;
    const frame = $('report-editor');
    if (frame.contentWindow?.notesEditorDirty?.()) {
      $('report-version-notice').hidden = false;
      $('report-version-notice').textContent = 'Есть другая версия конспекта. Сохраните текущие правки перед переключением версии.';
      return;
    }
    reportUrl = url;
    frame.src = url + '?embedded=1';
  }
  $('new-notes').onclick = () => { $('notes-settings').open = true; $('construction-model').focus(); };
  let connectionDraft='';
  const connectionValue=()=>new URLSearchParams(new FormData($('connections-form'))).toString()+JSON.stringify([...$('connections-form').querySelectorAll('input,select')].map(el=>[el.id,el.value,el.checked]));
  $('open-connections').onclick = () => {connectionDraft=connectionValue();$('connections-dialog').showModal();};
  const closeConnections=async()=>connectionValue()===connectionDraft||await window.confirmDiscard('Настройки подключения ещё не сохранены.');
  $('close-connections').onclick = async () => {if(await closeConnections())$('connections-dialog').close();};
  $('connections-form').addEventListener('connections-saved',()=>{connectionDraft=connectionValue();});
  $('connections-dialog').addEventListener('cancel',async event=>{event.preventDefault();if(await closeConnections())$('connections-dialog').close();});
  window.addEventListener('popstate',()=>{
    const params=new URLSearchParams(location.search);
    const next=params.get('stage')||'source';
    if(stages.includes(next))openStage(next,false);
    const nextVariant=params.get('report')||'';
    if(nextVariant!==variant){
      if($('report-editor').contentWindow?.notesEditorDirty?.()){
        const restored=new URLSearchParams(location.search);
        if(variant)restored.set('report',variant);else restored.delete('report');
        history.replaceState(null,'','/create?'+restored);
        $('report-version-notice').hidden=false;
        $('report-version-notice').textContent='Сохраните правки перед выбором другого варианта.';
      }else{variant=nextVariant;$('notes-variant').value=variant;loadReport();}
    }
  });
  async function post(url, value) {
    const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(value)});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Не удалось запустить обработку');
    return data;
  }
  $('source-title-form').onsubmit = async event => {
    event.preventDefault();
    if (!snapshot) return;
    try {
      const info = await post('/output/' + encodeURIComponent(snapshot.folder) + '/title.json', {title:$('source-title').value});
      snapshot.title = info.title; snapshot.display_title = info.display;
      window.studioDraft.clear($('source-title-form'));
      $('run-title').textContent = info.display; $('source-title-status').textContent = 'Название сохранено.';
    } catch (error) { $('source-title-status').textContent = error.message; }
  };
  const rememberedEngine = localStorage.getItem('video-descriptor-speech-engine');
  if ([...$('speech-engine').options].some(option => option.value === rememberedEngine)) $('speech-engine').value = rememberedEngine;
  $('speech-engine').onchange = () => localStorage.setItem('video-descriptor-speech-engine', $('speech-engine').value);
  $('rerun-speech').onclick = async () => {
    if (!snapshot) return;
    const button = $('rerun-speech'); button.disabled = true;
    try {
      const source = snapshot.source_video;
      if (!source) throw Error('Источник записи не найден');
      const next = await post('/api/speech-run', {
        video: source, title: snapshot.title || '', engine: $('speech-engine').value,
        mode:'audio', speech_only:true
      });
      $('speech-settings-status').textContent = 'Новая версия добавлена в очередь. Предыдущая остаётся в списке версий.';
      document.dispatchEvent(new CustomEvent('construction-started', {detail:next}));
    } catch (error) { $('speech-settings-status').textContent = error.message; }
    finally { update(); }
  };
  function state(name, label, status) {
    $('state-' + name).textContent = label;
    $('tab-' + name).dataset.status = status;
  }
  function mediaTime(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    return [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60].map(value => String(value).padStart(2, '0')).join(':');
  }
  function updateSourceInfo() {
    if (!snapshot) return;
    const video = $('process-video');
    const fullDuration = video.getAttribute('src') === snapshot.video_url && video.readyState >= 1 && Number.isFinite(video.duration) ? video.duration : null;
    const start = snapshot.start || 0;
    const partial = fullDuration !== null && (start > 0 || start + snapshot.duration < fullDuration - 2);
    const info = $('source-info'); info.replaceChildren();
    const rows = [['Файл', snapshot.filename], ['Длительность файла', fullDuration === null ? 'Загружается…' : mediaTime(fullDuration)]];
    if (snapshot.has_ready_transcript) rows.push(['Распознано', mediaTime(start) + ' — ' + mediaTime(start + snapshot.duration)]);
    rows.push(['Проверка', 'Источник доступен']);
    for (const [label, value] of rows) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = value; info.append(dt, dd);
    }
    if (partial && snapshot.has_ready_transcript) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = 'Охват'; dd.textContent = 'Только фрагмент. Остальная запись ещё не распознана.'; info.append(dt, dd);
      if (!snapshot.running) state('speech', 'Фрагмент готов', 'done');
    }
  }
  $('process-video').addEventListener('loadedmetadata', updateSourceInfo);
  function update() {
    const busy = snapshot?.running || ['queued', 'running'].includes(job?.status);
    $('rerun-speech').disabled = !snapshot?.source_video || busy;
    $('delete-version').hidden = !snapshot?.folder;
    $('record-menu').hidden = !snapshot?.folder;
    $('new-notes').hidden = !snapshot?.has_ready_transcript;
    $('new-notes').disabled = Boolean(busy);
    $('delete-notes').hidden = !snapshot?.has_notes;
    $('delete-notes').disabled = Boolean(busy);
    $('delete-version').disabled = Boolean(busy);
    $('delete-version').title = busy ? 'Дождитесь завершения обработки' : 'Удалить выбранную версию';
    if (!snapshot) {
      state('source', job ? 'В очереди' : 'Выберите файл', job ? 'active' : 'pending');
      state('speech', 'Настройки и расшифровка', 'pending');
      state('notes', 'Стратегия и редактор', 'pending');
      return;
    }
    if (currentFolder !== snapshot.folder) {
      if (currentFolder !== null) variant = '';
      currentFolder = snapshot.folder;
      $('source-title').value = snapshot.title || '';
      window.studioDraft.restore($('source-title-form'));
      $('source-title-status').textContent = '';
      $('notes-settings').open = !snapshot.report_url;
      $('speech-settings').open = !snapshot.has_ready_transcript;
      if (snapshot.speech_engine && [...$('speech-engine').options].some(option => option.value === snapshot.speech_engine)) $('speech-engine').value = snapshot.speech_engine;
    }
    const reports = snapshot.report_variants || [];
    if (!reports.some(item => item.name === variant)) variant = reports[0]?.name || '';
    const optionsKey = JSON.stringify(reports);
    if ($('notes-variant').dataset.optionsKey !== optionsKey) {
      $('notes-variant').dataset.optionsKey = optionsKey;
      $('notes-variant').replaceChildren(...reports.map(item => {
        const option = document.createElement('option'); option.value = item.name; option.textContent = item.name || 'Основной'; return option;
      }));
    }
    $('notes-variant').value = variant;
    $('notes-variant-label').hidden = reports.length < 2;
    state('source', 'Файл сохранён', 'done');
    state('speech', snapshot.phase === 6 && busy ? 'Перевод' : snapshot.has_ready_transcript ? 'Готово' : snapshot.phase === 2 && busy ? 'Распознавание' : 'Ожидает', snapshot.has_ready_transcript ? 'done' : snapshot.phase === 2 && busy ? 'active' : 'pending');
    const building = busy && [3, 4, 5].includes(snapshot.phase);
    state('notes', building ? snapshot.phase === 3 ? 'Подготовка слайдов' : 'Построение' : reports.length ? 'Готово' : 'Ожидает', building ? 'active' : reports.length ? 'done' : 'pending');
    if (job?.status === 'error' && !snapshot.notes_deleted) state(snapshot.phase === 2 ? 'speech' : 'notes', 'Ошибка', 'error');
    $('shared-player').hidden = false;
    updateSourceInfo();
    $('slide-material').hidden = !snapshot.frame_count;
    $('notes-card').hidden = Boolean(reports.length || (busy && snapshot.previous_report_url));
    $('diagnostics').hidden = false;
    loadReport();
  }
  window.studioUI = {
    openStage,
    select(value) {
      snapshot = null; job = value?.job ? {status:'queued'} : null;
      $('shared-player').hidden = true;
      $('report-editor-card').hidden = true;
      $('diagnostics').hidden = true;
      update();
    },
    show(value, currentJob) { snapshot = value; job = currentJob || value.job; update(); },
    queued(value) { job = value; update(); },
    resetReport() { reportUrl = null; $('report-editor').src = 'about:blank'; },
    reportVariant: () => variant,
    refreshReport: loadReport
  };
  openStage(stage, false); update();
})();
