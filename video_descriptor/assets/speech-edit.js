(() => {
  const stamp=s=>{s=Math.floor(s);return [Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(n=>String(n).padStart(2,'0')).join(':');};
  async function post(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const x=await r.json();if(!r.ok)throw Error(x.error||'Не удалось сохранить');return x;}
  const styles=document.createElement('style');
  styles.textContent=`.utterance .edit-reply{float:right;padding:4px 8px;border:1px solid #ccd5e0;border-radius:6px;font-size:14px}dialog.reply-editor{width:min(760px,90vw);box-sizing:border-box;border:1px solid #ccd5e0;border-radius:12px;padding:24px;color:#202b3b}dialog.reply-editor::backdrop{background:#0007}.reply-editor textarea{width:100%;min-height:110px;font:inherit;box-sizing:border-box;padding:8px;resize:vertical}.reply-editor label{display:block;margin:12px 0}.reply-editor select{width:100%}.reply-editor .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.reply-editor input[type=range]{width:100%}.reply-editor .error{color:#b42318;white-space:pre-wrap}`;
  document.head.append(styles);
  let editing=false;
  window.editSpeechReply = function(original, index, video, onSave){
    if(editing)return;
    const row=original.segments[index];
    const dialog=document.createElement('dialog');dialog.className='reply-editor';
    dialog.innerHTML=`<form><h2>Правка реплики</h2><p class="bounds"></p><p>Исправьте текст и говорящего. Чтобы разделить реплику, поставьте курсор в тексте на границе второй части и нажмите «Разделить по курсору».</p><label>Текст первой части<textarea name="left" required></textarea></label><label>Перевод первой части<textarea name="translation"></textarea></label><label>Говорящий<select name="speaker"></select></label><button type="button" class="split">Разделить по курсору</button><div class="second" hidden><h3>Вторая часть</h3><label>Текст второй части<textarea name="right"></textarea></label><label>Перевод второй части<textarea name="rightTranslation"></textarea></label><p>При разделении перевод остаётся в первой части. Перенесите нужный текст во вторую вручную.</p><label>Говорящий второй части<select name="rightSpeaker"></select></label><p>Выберите момент смены говорящего внутри исходной реплики. Обе части сохранят её общий интервал.</p><label>Граница времени<input class="boundary" type="text" aria-label="Время разделения" placeholder="02:32:40"></label><input class="split-range" type="range" step="0.01" aria-label="Граница разделения внутри реплики"><button type="button" class="from-video">Взять позицию видео</button> <button type="button" class="preview">Послушать перед границей</button><p class="ranges"></p></div><p class="error" role="status"></p><div class="actions"><button type="submit">Сохранить</button><button type="button" class="cancel">Отмена</button></div></form>`;
    const form=dialog.querySelector('form'), left=form.elements.left, right=form.elements.right;
    const firstSpeaker=form.elements.speaker, secondSpeaker=form.elements.rightSpeaker;
    const boundary=dialog.querySelector('.boundary'), range=dialog.querySelector('.split-range');
    const error=dialog.querySelector('.error');let splitting=false, saving=false;
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
    dialog.querySelector('.cancel').onclick=()=>{if(!saving)dialog.close();};
    dialog.addEventListener('cancel',e=>{if(saving)e.preventDefault();});
    dialog.addEventListener('close',()=>{editing=false;dialog.remove();});
    form.onsubmit=async e=>{e.preventDefault();if(saving)return;const payload={folder:original.folder,revision:original.edit_revision,index,action:splitting?'split':'edit',text:left.value,speaker:firstSpeaker.value,translation:form.elements.translation.value};if(splitting){boundary.onchange();if(error.textContent)return;payload.at=Number(range.value);payload.right_text=right.value;payload.right_speaker=secondSpeaker.value;payload.right_translation=form.elements.rightTranslation.value;}saving=true;form.querySelector('[type=submit]').disabled=true;error.textContent='Сохраняем…';try{const saved=await post('/api/speech-edit',payload);onSave(saved);dialog.close();}catch(e){error.textContent=e.message;}finally{saving=false;form.querySelector('[type=submit]').disabled=false;}};
    editing=true;document.body.append(dialog);dialog.showModal();left.focus();
  }
  function option(value,label){const o=document.createElement('option');o.value=value;o.textContent=label;return o;}
})();
