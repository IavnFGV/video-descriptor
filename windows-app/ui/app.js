(() => {
  const $ = id => document.getElementById(id);
  let instance, selected = new URLSearchParams(location.search).get('job'), timer, uploading=false;
  const statusNames = {queued:'В очереди', running:'Обрабатываем', done:'Готово', error:'Нужна проверка'};
  const stamp = s => new Date(Math.max(0,s)*1000).toISOString().slice(11,19);
  async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw Error(data.error || `Ошибка ${response.status}`);
    return data;
  }
  function message(text, error=false) { $('message').textContent=text; $('message').style.color=error?'#a04b30':'#5b7760'; }
  function check(label, ready, suffix) { const row=document.createElement('div');row.className='check';const a=document.createElement('span');a.textContent=label;const b=document.createElement('span');b.className=ready?'good':'warning';b.textContent=suffix||(ready?'Готово':'Не подключено');row.append(a,b);return row; }
  async function readiness() {
    try {
      const d=await api('/api/doctor');$('doctor').textContent=JSON.stringify(d,null,2);
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
      const b=document.createElement('button');b.className='job';const title=document.createElement('strong');title.textContent=job.title||job.filename;const state=document.createElement('small');state.textContent=statusNames[job.status]||job.status;b.append(title,state);b.onclick=()=>select(job.id);return b;
    });
    if(buttons.length)$('jobs').replaceChildren(...buttons);
  }
  function select(id) { selected=id;history.replaceState(null,'','?job='+id);$('result-panel').hidden=false;clearTimeout(timer);poll(); }
  function render(result,job) {
    $('result-panel').hidden=false;$('result-title').textContent=job.title||job.filename;
    $('status').textContent=statusNames[job.status]||job.status;
    $('progress-text').textContent=job.error||result?.message||'Ожидаем свободный обработчик';
    $('progress').value=result?.duration?Math.min(100,100*result.processed/result.duration):0;
    $('retry').hidden=job.status!=='error';
    const done=job.status==='done'&&result?.status==='done';$('exports').hidden=!done;
    if(!result)return;
    const source='/'+result.video.replaceAll('\\','/');if($('video').dataset.source!==source){$('video').src=source;$('video').dataset.source=source;}
    if(done){
      const q=new URLSearchParams({folder:job.folder,language:'original'});
      $('vtt').href='/api/subtitles?'+q;$('srt').href='/api/subtitles?'+q+'&format=srt';$('txt').href='/api/transcript-text?'+q;
      $('editor').href='/create?folder='+encodeURIComponent(job.folder);
    }
    $('timing-note').textContent=result.no_speech?'Речь не обнаружена. Это решение VAD, а не ручная проверка записи.':'Таймкоды относятся к целым репликам. Разделение слов и говорящих в этом режиме не выполняется.';
    const rows=result.segments.map((segment,index)=>{
      const row=document.createElement('div');row.className='row';const time=document.createElement('time');time.textContent=stamp(segment.start)+' — '+stamp(segment.end);time.onclick=()=>{$('video').currentTime=segment.start;$('video').play().catch(()=>{});};
      if(done){const edit=document.createElement('button');edit.textContent='Исправить';edit.onclick=()=>window.editSpeechReply(result,index,$('video'),saved=>render(saved,job));row.append(edit);}
      const p=document.createElement('p');p.textContent=segment.text;row.append(time,p);return row;
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
    const query=new URLSearchParams({filename:file.name,title:$('title').value,mode:'audio',engine:'whisper-npu',speech_only:'true',language:$('language').value});
    const xhr=new XMLHttpRequest();xhr.open('POST','/api/upload?'+query);uploading=true;$('start').disabled=true;$('upload-progress').hidden=false;message('Копируем запись в библиотеку…');
    xhr.upload.onprogress=e=>{if(e.lengthComputable)$('upload-progress').value=100*e.loaded/e.total;};
    xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);if(xhr.status!==202)throw Error(data.error||'Ошибка загрузки');message('Запись добавлена. Можно закрыть вкладку — обработка продолжится.');select(data.id);jobs().catch(e=>message(e.message,true));}catch(e){message(e.message,true);}finally{uploading=false;$('upload-progress').hidden=true;readiness();}};
    xhr.onerror=()=>{uploading=false;message('Соединение прервалось. Откройте приложение повторно.',true);$('start').disabled=false;};xhr.send(file);
  };
  $('retry').onclick=async()=>{try{await api('/api/retry?id='+selected,{method:'POST'});poll();}catch(e){message(e.message,true);}};
  $('start-npu').onclick=async()=>{try{await api('/api/native/start-npu',{method:'POST',headers:{'X-App-Instance':instance}});message('Загружаем существующую модель. Ничего не скачиваем.');$('start-npu').disabled=true;}catch(e){message(e.message,true);}finally{setTimeout(()=>{$('start-npu').disabled=false;readiness();},4000);}};
  $('stop').onclick=async()=>{try{await api('/api/native/stop',{method:'POST',headers:{'X-App-Instance':instance}});clearTimeout(timer);clearInterval(checks);message('Приложение завершено. Эту вкладку можно закрыть.');$('start').disabled=true;}catch(e){message(e.message,true);}};
  $('refresh').onclick=()=>jobs().catch(e=>message(e.message,true));
  api('/health').then(h=>{instance=h.instance;return Promise.all([readiness(),jobs()]);}).then(()=>{if(selected)poll();}).catch(e=>message(e.message,true));
  const checks=setInterval(()=>{readiness();jobs().catch(()=>{});},15000);
})();
