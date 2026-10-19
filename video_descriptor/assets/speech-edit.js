(() => {
  const stamp=s=>{s=Math.floor(s);return [Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(n=>String(n).padStart(2,'0')).join(':');};
  async function post(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const x=await r.json();if(!r.ok)throw Error(x.error||'Не удалось сохранить');return x;}
  let discardDialog=null;
  window.confirmDiscard = message => {
    if(discardDialog)return Promise.resolve(false);
    return new Promise(resolve=>{
      const opener=document.activeElement,dialog=document.createElement('dialog');discardDialog=dialog;
      dialog.className='vd-dialog';dialog.setAttribute('aria-labelledby','discard-heading');
      dialog.innerHTML='<h2 id="discard-heading">Есть несохранённые изменения</h2><p></p><div class="vd-actions"><button type="button" class="vd-button" data-keep-editing>Продолжить редактирование</button><button type="button" class="vd-button vd-button--danger" data-discard>Закрыть без сохранения</button></div>';
      dialog.querySelector('p').textContent=message;
      let discard=false;
      dialog.querySelector('[data-keep-editing]').onclick=()=>dialog.close();
      dialog.querySelector('[data-discard]').onclick=()=>{discard=true;dialog.close();};
      dialog.onclose=()=>{discardDialog=null;dialog.remove();opener?.focus();resolve(discard);};
      document.body.append(dialog);dialog.showModal();dialog.querySelector('[data-keep-editing]').focus();
    });
  };
  let editing=false;
  window.createSpeakerName = function(original, speaker, onSave){
    const holder=document.createElement('span'), button=document.createElement('button');
    const input=document.createElement('input'), feedback=document.createElement('span');
    const label=original.speaker_names?.[speaker]||(speaker==='unknown'?'Не определён':speaker);
    button.type='button';button.className='vd-button vd-button--quiet vd-button--compact speaker-name';
    button.textContent=label;button.title='Переименовать во всех репликах этого говорящего';
    input.className='vd-input speaker-name-input';input.maxLength=100;input.hidden=true;
    input.setAttribute('aria-label','Имя говорящего '+label);feedback.className='vd-help';feedback.setAttribute('role','status');
    let active=false,saving=false;
    const close=()=>{active=false;editing=false;input.hidden=true;button.hidden=false;button.focus({preventScroll:true});};
    button.onclick=()=>{if(editing)return;editing=true;active=true;input.value=label;button.hidden=true;input.hidden=false;input.focus();input.select();};
    const save=async()=>{
      if(!active||saving)return;
      const name=input.value.trim();
      if(!name){feedback.textContent='Введите имя говорящего.';input.focus();return;}
      if(name===label){close();return;}
      saving=true;input.disabled=true;feedback.textContent='Сохраняем имя…';
      try{
        const names={...original.speaker_names,[speaker]:name};
        await post('/api/speech-names',{folder:original.folder,speaker_names:names});
        active=false;editing=false;onSave({...original,speaker_names:names});
      }catch(e){feedback.textContent=e.message;}
      finally{saving=false;input.disabled=false;}
    };
    input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();save();}if(e.key==='Escape'&&!saving){e.preventDefault();feedback.textContent='';close();}};
    input.onblur=()=>{if(active&&!saving)save();};
    holder.append(button,input,feedback);return holder;
  };
  window.createSpeakerSelect = function(original, index, onSave){
    const row=original.segments[index], holder=document.createElement('span');
    const select=document.createElement('select'), feedback=document.createElement('span');
    select.className='vd-select speaker-select';
    select.setAttribute('aria-label','Говорящий реплики '+stamp(row.start));
    select.title='Изменить говорящего';
    const speakers=[...new Set([...(original.speaker_options||[]),...original.segments.map(s=>s.speaker),'unknown'])];
    select.replaceChildren(...speakers.map(s=>option(s,original.speaker_names?.[s]||(s==='unknown'?'Не определён':s))));
    select.value=row.speaker;
    feedback.className='vd-help';feedback.setAttribute('role','status');
    select.onchange=async()=>{
      if(editing){select.value=row.speaker;feedback.textContent='Сначала завершите текущую правку.';return;}
      if(select.value===row.speaker)return;
      editing=true;select.disabled=true;select.setAttribute('aria-busy','true');feedback.textContent='Сохраняем…';
      try{
        const saved=await post('/api/speech-edit',{folder:original.folder,revision:original.edit_revision,index,
          action:'edit',text:row.text,speaker:select.value,translation:original.translations?.[row.id||`s${index+1}`]||''});
        feedback.textContent='';onSave(saved);
      }catch(e){select.value=row.speaker;feedback.textContent=e.message;}
      finally{editing=false;select.disabled=false;select.removeAttribute('aria-busy');}
    };
    holder.append(select,feedback);return holder;
  };
  window.editSpeechReply = function(original, index, video, onSave){
    if(editing)return;
    const row=original.segments[index];
    const dialog=document.createElement('dialog');dialog.className='reply-editor vd-dialog';dialog.setAttribute('aria-labelledby','reply-editor-title');
    dialog.innerHTML=`<form><h2 id="reply-editor-title">Правка реплики</h2><p class="bounds"></p><p>Исправьте текст и говорящего. Чтобы разделить реплику, поставьте курсор в тексте на границе второй части и нажмите «Разделить по курсору».</p><label>Текст первой части<textarea name="left" required></textarea></label><label>Перевод первой части<textarea name="translation"></textarea></label><label>Говорящий<select name="speaker"></select></label><button type="button" class="split">Разделить по курсору</button><div class="second" hidden><h3>Вторая часть</h3><label>Текст второй части<textarea name="right"></textarea></label><label>Перевод второй части<textarea name="rightTranslation"></textarea></label><p>При разделении перевод остаётся в первой части. Перенесите нужный текст во вторую вручную.</p><label>Говорящий второй части<select name="rightSpeaker"></select></label><p>Выберите момент смены говорящего внутри исходной реплики. Обе части сохранят её общий интервал.</p><label>Граница времени<input class="boundary" type="text" aria-label="Время разделения" placeholder="02:32:40"></label><input class="split-range" type="range" step="0.01" aria-label="Граница разделения внутри реплики"><button type="button" class="from-video">Взять позицию видео</button> <button type="button" class="preview">Послушать перед границей</button><p class="ranges"></p></div><p class="error" role="status"></p><div class="actions"><button type="submit">Сохранить</button><button type="button" class="cancel">Отмена</button></div></form>`;
    const form=dialog.querySelector('form'), left=form.elements.left, right=form.elements.right;
    const firstSpeaker=form.elements.speaker, secondSpeaker=form.elements.rightSpeaker;
    const boundary=dialog.querySelector('.boundary'), range=dialog.querySelector('.split-range');
    const error=dialog.querySelector('.error');let splitting=false, saving=false;
    const times=document.createElement('div');times.innerHTML='<label>Начало, секунды<input name="startTime" type="number" min="0" step="0.001" required></label><label>Конец, секунды<input name="endTime" type="number" min="0" step="0.001" required></label>';
    dialog.querySelector('.bounds').after(times);form.elements.startTime.value=Number(row.start.toFixed(3));form.elements.endTime.value=Number(row.end.toFixed(3));
    const speakers=original.speaker_options||[...new Set(original.segments.map(s=>s.speaker))];
    for(const select of [firstSpeaker,secondSpeaker]){select.replaceChildren(...speakers.map(s=>option(s,original.speaker_names?.[s]||s)));select.value=row.speaker;}
    left.value=row.text;
    form.elements.translation.value=original.translations?.[row.id || `s${index+1}`] || '';
    form.elements.translation.parentElement.hidden=!original.has_translation;
    form.elements.rightTranslation.parentElement.hidden=!original.has_translation;
    dialog.querySelector('.bounds').textContent=`Исходная реплика: ${stamp(row.start)}–${stamp(row.end)}`;
    range.min=row.start;range.max=row.end;
    const current=video.currentTime;
    range.value=current>row.start&&current<row.end?current:(row.start+row.end)/2;
    const exactStamp=s=>{const seconds=Math.floor(s);return stamp(seconds)+(s-seconds>0.0001?(s-seconds).toFixed(2).slice(1):'');};
    function updateBoundary(){boundary.value=exactStamp(Number(range.value));dialog.querySelector('.ranges').textContent=`Первая: ${exactStamp(row.start)}–${boundary.value} · Вторая: ${boundary.value}–${exactStamp(row.end)}`;}
    updateBoundary();range.oninput=updateBoundary;
    boundary.onchange=()=>{const value=boundary.value.trim();const parts=value.split(':').map(Number);const at=/^\d{2,}:[0-5]\d:[0-5]\d(?:\.\d+)?$/.test(value)?parts[0]*3600+parts[1]*60+parts[2]:NaN;if(!Number.isFinite(at)||at<=row.start||at>=row.end){error.textContent='Укажите время ЧЧ:ММ:СС внутри исходной реплики';return;}range.value=at;error.textContent='';updateBoundary();};
    dialog.querySelector('.split').onclick=()=>{const pos=left.selectionStart;if(pos<=0||pos>=left.value.length){error.textContent='Поставьте курсор между текстами двух частей';left.focus();return;}right.value=left.value.slice(pos).trim();left.value=left.value.slice(0,pos).trim();splitting=true;right.required=true;dialog.querySelector('.second').hidden=false;dialog.querySelector('.split').hidden=true;error.textContent='';right.focus();};
    dialog.querySelector('.from-video').onclick=()=>{const at=video.currentTime;if(at<=row.start||at>=row.end){error.textContent='Позиция видео должна быть внутри исходной реплики';return;}range.value=at;updateBoundary();error.textContent='';};
    dialog.querySelector('.preview').onclick=()=>{video.currentTime=Math.max(row.start,Number(range.value)-2);video.play().catch(e=>error.textContent=e.message);};
    const initial=new URLSearchParams(new FormData(form)).toString();
    const opener=document.activeElement;
    const dirty=()=>splitting||new URLSearchParams(new FormData(form)).toString()!==initial;
    const mayClose=async()=>!saving&&(!dirty()||await window.confirmDiscard('Правки реплики ещё не сохранены. Их можно сохранить, вернувшись к редактированию.'));
    dialog.querySelector('.cancel').onclick=async()=>{if(await mayClose())dialog.close();};
    dialog.addEventListener('cancel',async e=>{e.preventDefault();if(await mayClose())dialog.close();});
    const beforeUnload=e=>{if(dirty()){e.preventDefault();e.returnValue='';}};
    window.addEventListener('beforeunload',beforeUnload);
    dialog.addEventListener('close',()=>{editing=false;window.removeEventListener('beforeunload',beforeUnload);dialog.remove();opener?.focus();});
    form.onsubmit=async e=>{e.preventDefault();if(saving)return;const payload={folder:original.folder,revision:original.edit_revision,index,action:splitting?'split':'edit',text:left.value,speaker:firstSpeaker.value,translation:form.elements.translation.value};if(!splitting){payload.start=Number(form.elements.startTime.value);payload.end=Number(form.elements.endTime.value);}if(splitting){boundary.onchange();if(error.textContent)return;payload.at=Number(range.value);payload.right_text=right.value;payload.right_speaker=secondSpeaker.value;payload.right_translation=form.elements.rightTranslation.value;}saving=true;dialog.setAttribute('aria-busy','true');form.querySelector('[type=submit]').disabled=true;error.textContent='Сохраняем…';try{const saved=await post('/api/speech-edit',payload);onSave(saved);dialog.close();}catch(e){error.textContent=e.message;}finally{saving=false;dialog.setAttribute('aria-busy','false');form.querySelector('[type=submit]').disabled=false;}};
    editing=true;document.body.append(dialog);dialog.showModal();left.focus();
  }
  function option(value,label){const o=document.createElement('option');o.value=value;o.textContent=label;return o;}
})();
