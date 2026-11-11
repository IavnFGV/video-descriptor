(() => {
  const stamp=s=>{s=Math.floor(s);return [Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(n=>String(n).padStart(2,'0')).join(':');};
  const speechHistories=new Map(),historyBindings=new Map();
  let lastHistoryRoot=null;
  const historyFor=folder=>{if(!speechHistories.has(folder))speechHistories.set(folder,{undo:[],redo:[],revision:null,busy:false});return speechHistories.get(folder);};
  async function post(url,payload){
    let before=null;
    if(url==='/api/speech-edit'&&['edit','split','resolve'].includes(payload.action)){
      const response=await fetch('/api/speech?'+new URLSearchParams({folder:payload.folder}),{cache:'no-store'}),data=await response.json();
      if(!response.ok)throw Error(data.error||'Не удалось проверить версию расшифровки');before=data.result;
      if(before.edit_revision!==payload.revision)throw Error('Реплики изменились. Обновите страницу перед сохранением');
    }
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const x=await r.json();if(!r.ok)throw Error(x.error||'Не удалось сохранить');
    if(before){const state=historyFor(payload.folder);if(state.revision&&state.revision!==before.edit_revision)state.undo=[];state.undo.push({before,after:x});if(state.undo.length>20)state.undo.shift();state.redo=[];state.revision=x.edit_revision;updateHistoryButtons();}
    return x;
  }
  function updateHistoryButtons(){for(const binding of historyBindings.values()){const state=historyFor(binding.folder);binding.undo.disabled=state.busy||editing||!state.undo.length;binding.redo.disabled=state.busy||editing||!state.redo.length;}}
  async function speechHistoryStep(binding,redo=false){
    const state=historyFor(binding.folder),stack=redo?state.redo:state.undo,item=stack.at(-1);if(!item||state.busy||editing)return;
    state.busy=true;editing=true;updateHistoryButtons();binding.feedback.textContent='Сохраняем '+(redo?'повтор':'отмену')+'…';
    try{const target=redo?item.after:item.before;const saved=await post('/api/speech-edit',{folder:binding.folder,revision:state.revision,action:'restore',segments:target.segments,translations:target.translations||{}});stack.pop();(redo?state.undo:state.redo).push(item);state.revision=saved.edit_revision;editing=false;binding.onSave(saved);binding.feedback.textContent=redo?'Действие повторено и сохранено.':'Действие отменено и сохранено.';}
    catch(error){binding.feedback.textContent=error.message+' Отмена не сохранена.';}finally{editing=false;state.busy=false;updateHistoryButtons();}
  }
  window.bindSpeechHistory=(root,folder,onSave)=>{
    let binding=historyBindings.get(root);
    if(!binding){const toolbar=document.createElement('div'),undo=document.createElement('button'),redo=document.createElement('button'),feedback=document.createElement('span');toolbar.className='subtitle-history vd-actions';undo.type=redo.type='button';undo.textContent='↶ Отменить';redo.textContent='↷ Повторить';undo.title='Ctrl+Z';redo.title='Ctrl+Shift+Z';feedback.setAttribute('role','status');toolbar.append(undo,redo,feedback);(root.querySelector('.subtitle-tools')||root).append(toolbar);binding={undo,redo,feedback};historyBindings.set(root,binding);undo.onclick=()=>speechHistoryStep(binding);redo.onclick=()=>speechHistoryStep(binding,true);}
    binding.folder=folder;binding.onSave=onSave;updateHistoryButtons();
    if(!root.dataset.historyBound){root.dataset.historyBound='true';root.addEventListener('focusin',()=>{lastHistoryRoot=root;});root.addEventListener('pointerdown',()=>{lastHistoryRoot=root;});}
  };
  document.addEventListener('keydown',event=>{
    if(!(event.ctrlKey||event.metaKey)||event.key.toLowerCase()!=='z'||event.target.closest('input,textarea,[contenteditable=true],.CodeMirror'))return;
    for(const [root,binding] of historyBindings){if(root.contains(event.target)||event.target===document.body&&root===lastHistoryRoot){event.preventDefault();speechHistoryStep(binding,event.shiftKey);break;}}
  });
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
  window.speechReplyEditing=()=>editing;
  let hoveredReply=null,quickEdit=null;
  window.mayLeaveQuickReply=async()=>!quickEdit||(!quickEdit.saving()&&(!quickEdit.dirty()||await window.confirmDiscard('Текст реплики ещё не сохранён. Закрыть без сохранения?')));
  window.closeQuickReplyEdit=()=>quickEdit?.close();
  let controlTimer;
  document.addEventListener('keydown',e=>{clearTimeout(controlTimer);if(e.key==='Control'&&!e.repeat)controlTimer=setTimeout(()=>hoveredReply?.(),220);});
  document.addEventListener('keyup',e=>{if(e.key==='Control')clearTimeout(controlTimer);});
  window.enableQuickReplyEdit = function(text, original, index, onSave){
    const row=original.segments[index];
    text.title='Ctrl + наведение — быстро исправить текст';text.tabIndex=0;
    const open=()=>{
      if(editing||!text.isConnected)return;
      window.recordingUI?.pauseLink();
      editing=true;hoveredReply=null;
      const panel=document.createElement('div'),input=document.createElement('textarea'),actions=document.createElement('div');
      const save=document.createElement('button'),cancel=document.createElement('button'),feedback=document.createElement('p');
      panel.className='quick-reply-editor';input.className='vd-textarea';input.value=row.text;
      input.setAttribute('aria-label','Текст реплики '+stamp(row.start));actions.className='vd-actions';
      save.type=cancel.type='button';save.className='vd-button vd-button--primary';cancel.className='vd-button';
      save.textContent='Сохранить';cancel.textContent='Отмена';feedback.setAttribute('role','status');feedback.className='vd-error';
      let saving=false;
      let localTouched=false;input.addEventListener('input',()=>{localTouched=true;});
      const beforeUnload=e=>{if(input.value!==row.text){e.preventDefault();e.returnValue='';}};
      window.addEventListener('beforeunload',beforeUnload);
      const close=()=>{editing=false;quickEdit=null;window.removeEventListener('beforeunload',beforeUnload);panel.replaceWith(text);text.focus({preventScroll:true});};
      quickEdit={close,dirty:()=>input.value!==row.text,saving:()=>saving};
      cancel.onclick=()=>{if(!saving)close();};
      save.onclick=async()=>{
        if(saving)return;if(!input.value.trim()){feedback.textContent='Введите текст реплики.';input.focus();return;}
        saving=true;save.disabled=cancel.disabled=true;input.disabled=true;panel.setAttribute('aria-busy','true');feedback.textContent='Сохраняем…';
        try{
          const saved=await post('/api/speech-edit',{folder:original.folder,revision:original.edit_revision,index,action:'edit',
            text:input.value,speaker:row.speaker,translation:original.translations?.[row.id||`s${index+1}`]||''});
          close();onSave(saved);
        }catch(e){feedback.textContent=e.message;}
        finally{saving=false;save.disabled=cancel.disabled=false;input.disabled=false;panel.removeAttribute('aria-busy');}
      };
      input.onkeydown=e=>{
        if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'&&!localTouched&&!saving){
          const binding=[...historyBindings].find(([root])=>root.contains(panel))?.[1],state=binding&&historyFor(binding.folder);
          if(state&&(e.shiftKey?state.redo:state.undo).length){e.preventDefault();e.stopPropagation();close();speechHistoryStep(binding,e.shiftKey);return;}
        }
        if(e.key==='Escape'){e.preventDefault();cancel.click();}if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();save.click();}
      };
      actions.append(save,cancel);panel.append(input,actions,feedback);text.replaceWith(panel);input.focus({preventScroll:true});
    };
    text.onpointerenter=e=>{hoveredReply=open;if(e.ctrlKey)open();};
    text.onpointerleave=()=>{if(hoveredReply===open)hoveredReply=null;};
    text.onkeydown=e=>{if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();open();}};
  };
  function speakerActionIcon(path){
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('width','16');svg.setAttribute('height','16');
    svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.8');
    svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');
    const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d',path);svg.append(shape);return svg;
  }
  window.createSpeakerName = function(original, speaker, onSave){
    const holder=document.createElement('span'), button=document.createElement('button');
    const input=document.createElement('input'), feedback=document.createElement('span');
    const label=original.speaker_names?.[speaker]||(speaker==='unknown'?'Участник не указан':speaker);
    button.type='button';button.className='vd-button vd-button--quiet vd-button--compact speaker-name';
    button.textContent=label;button.append(speakerActionIcon('M16 3a2.1 2.1 0 0 1 3 3L7 18l-4 1 1-4L16 3Z M14 5l3 3'));button.title='Изменить имя участника во всех его репликах';button.setAttribute('aria-label','Изменить имя участника '+label+' во всех его репликах');
    input.className='vd-input speaker-name-input';input.maxLength=100;input.hidden=true;
    input.setAttribute('aria-label','Имя участника '+label);feedback.className='vd-help';feedback.setAttribute('role','status');
    let active=false,saving=false;
    const close=()=>{active=false;editing=false;input.hidden=true;button.hidden=false;button.focus({preventScroll:true});};
    button.onclick=()=>{if(editing)return;editing=true;active=true;input.value=label;button.hidden=true;input.hidden=false;input.focus();input.select();};
    const save=async()=>{
      if(!active||saving)return;
      const name=input.value.trim();
      if(!name){feedback.textContent='Введите имя участника.';input.focus();return;}
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
  window.createSpeakerSelect = function(original, index, onSave, compact=false){
    const row=original.segments[index], holder=document.createElement('span');holder.className='speaker-controls';
    const select=document.createElement('select'), feedback=document.createElement('span');
    select.className='vd-select speaker-select';
    select.setAttribute('aria-label','Назначить участника только этой реплике '+stamp(row.start));
    select.title='Кто говорит в этой реплике?';
    const speakers=[...new Set([...(original.speaker_options||[]),...original.segments.map(s=>s.speaker),'unknown'])];
    select.replaceChildren(...speakers.map(s=>option(s,original.speaker_names?.[s]||(s==='unknown'?'Участник не указан':s))));
    if(compact)select.append(option('__new_speaker__','＋ Создать и назначить…'));
    select.value=row.speaker;
    feedback.className='vd-help';feedback.setAttribute('role','status');
    select.onchange=async()=>{
      if(editing){select.value=row.speaker;feedback.textContent='Сначала завершите текущую правку.';return;}
      if(compact&&select.value==='__new_speaker__'){select.value=row.speaker;add.click();return;}
      if(select.value===row.speaker)return;
      editing=true;select.disabled=true;select.setAttribute('aria-busy','true');feedback.textContent='Сохраняем…';
      try{
        const saved=await post('/api/speech-edit',{folder:original.folder,revision:original.edit_revision,index,
          action:'edit',text:row.text,speaker:select.value,translation:original.translations?.[row.id||`s${index+1}`]||''});
        feedback.textContent='';onSave(saved);
      }catch(e){select.value=row.speaker;feedback.textContent=e.message;}
      finally{editing=false;select.disabled=false;select.removeAttribute('aria-busy');}
    };
    const add=document.createElement('button'), name=document.createElement('input');
    add.type='button';add.className='vd-button vd-button--compact';add.title='Добавить нового участника в эту запись';
    add.setAttribute('aria-label','Добавить участника');
    add.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M8 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Z M2 10v1a6 6 0 0 0 12 0v-1 M8 17v4 M5 21h6 M19 5v8 M15 9h8"/></svg>';
    name.className='vd-input speaker-name-input';name.maxLength=100;name.hidden=true;name.placeholder=compact?'Имя · Enter — создать и назначить':'Имя нового участника';name.setAttribute('aria-label','Имя нового участника');
    let adding=false,publishing=false;
    const cancel=()=>{adding=false;editing=false;name.hidden=true;add.hidden=compact;feedback.textContent='';(compact?select:add).focus();};
    add.onclick=()=>{if(editing)return;editing=true;adding=true;name.value='';name.hidden=false;add.hidden=true;name.focus();};
    const create=async()=>{
      if(!adding||publishing)return;
      const label=name.value.trim();if(!label){feedback.textContent='Введите имя нового участника.';return;}
      publishing=true;name.disabled=true;feedback.textContent='Добавляем…';
      try{
        const id='speaker_'+crypto.randomUUID().replaceAll('-',''),names={...original.speaker_names,[id]:label};
        await post('/api/speech-names',{folder:original.folder,speaker_names:names});
        if(compact){
          // Registration and assignment are separate existing API operations.
          // Keep the new speaker available if a concurrent edit blocks assignment.
          original={...original,speaker_names:names,speaker_options:[...speakers,id]};
          select.insertBefore(option(id,label),select.lastElementChild);
          const saved=await post('/api/speech-edit',{folder:original.folder,revision:original.edit_revision,index,
            action:'edit',text:row.text,speaker:id,translation:original.translations?.[row.id||`s${index+1}`]||''});
          adding=false;editing=false;onSave(saved);
        }else{adding=false;editing=false;onSave({...original,speaker_names:names,speaker_options:[...speakers,id]});}
      }catch(e){feedback.textContent=e.message;}
      finally{publishing=false;name.disabled=false;}
    };
    name.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();create();}if(e.key==='Escape'&&!publishing){e.preventDefault();cancel();}};
    name.onblur=()=>{if(adding&&!publishing){if(name.value.trim())create();else cancel();}};
    const assignment=document.createElement('label');assignment.className='speaker-assignment';assignment.title='Назначить участника только этой реплике';
    assignment.append(select);
    add.hidden=compact;
    holder.append(assignment,add,name,feedback);return holder;
  };
  window.editSpeechReply = function(original, index, video, onSave){
    openReplyEditor(original, original.segments[index], index, null, video, onSave);
  };
  window.editSpeechGap = function(original, gap, video, onSave){
    openReplyEditor(original, {id:gap.id, start:gap.start, end:gap.end, text:'', speaker:'unknown'},
                    null, gap, video, onSave);
  };
  function openReplyEditor(original, row, index, gap, video, onSave){
    if(editing)return;
    const dialog=document.createElement('dialog');dialog.className='reply-editor vd-dialog';dialog.setAttribute('aria-labelledby','reply-editor-title');
    dialog.innerHTML=`<form><div class="reply-editor-toolbar"><h2 id="reply-editor-title">Правка реплики</h2><div class="actions"><button type="submit">Сохранить</button><button type="button" class="cancel">Отмена</button></div></div><div class="reply-editor-body"><p class="bounds"></p><p>Исправьте текст и участника. Чтобы разделить реплику, поставьте курсор в тексте на границе второй части и нажмите «Разделить по курсору».</p><label>Текст первой части<textarea name="left" required></textarea></label><label>Перевод первой части<textarea name="translation"></textarea></label><label>Участник<select name="speaker"></select></label><button type="button" class="split">Разделить по курсору</button><div class="second" hidden><h3>Вторая часть</h3><label>Текст второй части<textarea name="right"></textarea></label><label>Перевод второй части<textarea name="rightTranslation"></textarea></label><p>При разделении перевод остаётся в первой части. Перенесите нужный текст во вторую вручную.</p><label>Участник второй части<select name="rightSpeaker"></select></label><p>Выберите момент смены участника внутри исходной реплики. Обе части сохранят её общий интервал.</p><label>Граница времени<input class="boundary" type="text" aria-label="Время разделения" placeholder="02:32:40"></label><input class="split-range" type="range" step="0.01" aria-label="Граница разделения внутри реплики"><button type="button" class="from-video">Взять позицию видео</button> <button type="button" class="preview">Послушать перед границей</button><p class="ranges"></p></div><p class="error" role="status"></p></div></form>`;
    const form=dialog.querySelector('form'), left=form.elements.left, right=form.elements.right;
    const firstSpeaker=form.elements.speaker, secondSpeaker=form.elements.rightSpeaker;
    const boundary=dialog.querySelector('.boundary'), range=dialog.querySelector('.split-range');
    const error=dialog.querySelector('.error');let splitting=false, saving=false;
    const times=document.createElement('div');times.innerHTML='<label>Начало, секунды<input name="startTime" type="number" min="0" step="0.001" required></label><label>Конец, секунды<input name="endTime" type="number" min="0" step="0.001" required></label>';
    dialog.querySelector('.bounds').after(times);form.elements.startTime.value=Number(row.start.toFixed(3));form.elements.endTime.value=Number(row.end.toFixed(3));
    const speakers=original.speaker_options||[...new Set(original.segments.map(s=>s.speaker))];
    for(const select of [firstSpeaker,secondSpeaker]){select.replaceChildren(...speakers.map(s=>option(s,original.speaker_names?.[s]||s)));select.value=row.speaker;}
    const addedNames={};
    for(const target of [firstSpeaker,secondSpeaker]){
      const controls=document.createElement('div'),add=document.createElement('button'),input=document.createElement('input');
      controls.className='dialog-speaker-controls';target.after(controls);controls.append(target);
      add.type='button';add.className='vd-button vd-button--compact';add.textContent='+ Участник';add.setAttribute('aria-label','Добавить участника');
      input.className='vd-input';input.name='newSpeaker_'+target.name;input.maxLength=100;input.placeholder='Имя нового участника';input.setAttribute('aria-label','Имя нового участника');input.hidden=true;
      const create=()=>{const name=input.value.trim();if(!name){error.textContent='Введите имя нового участника.';return;}const id='speaker_'+crypto.randomUUID().replaceAll('-','');addedNames[id]=name;for(const select of [firstSpeaker,secondSpeaker])select.append(option(id,name));target.value=id;input.value='';input.hidden=true;add.hidden=false;error.textContent='';target.focus();};
      add.onclick=()=>{if(input.hidden){input.hidden=false;input.focus();add.textContent='Добавить';}else{create();add.textContent='+ Участник';}};
      input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();e.stopPropagation();create();add.textContent='+ Участник';}if(e.key==='Escape'){e.preventDefault();e.stopPropagation();input.value='';input.hidden=true;add.textContent='+ Участник';target.focus();}};
      controls.append(add,input);
    }
    left.value=row.text;
    form.elements.translation.value=original.translations?.[row.id || `s${index+1}`] || '';
    form.elements.translation.parentElement.hidden=!original.has_translation;
    form.elements.rightTranslation.parentElement.hidden=!original.has_translation;
    if(gap){
      // A gap has no recognized text yet: the user supplies it and the interval becomes a real reply.
      dialog.querySelector('#reply-editor-title').textContent='Заполнение участка без таймкодов';
      dialog.querySelector('.reply-editor-body>p:nth-of-type(2)').textContent=
        'Модель не смогла определить время реплик на этом участке. Введите текст вручную — он станет обычной репликой с таймкодами.';
      dialog.querySelector('.bounds').textContent=`Участок без таймкодов: ${stamp(row.start)}–${stamp(row.end)}`;
      dialog.querySelector('.split').hidden=true;
    } else {
      dialog.querySelector('.bounds').textContent=`Исходная реплика: ${stamp(row.start)}–${stamp(row.end)}`;
    }
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
    const dirty=()=>splitting||Object.keys(addedNames).length>0||new URLSearchParams(new FormData(form)).toString()!==initial;
    const mayClose=async()=>!saving&&(!dirty()||await window.confirmDiscard('Правки реплики ещё не сохранены. Их можно сохранить, вернувшись к редактированию.'));
    dialog.querySelector('.cancel').onclick=async()=>{if(await mayClose())dialog.close();};
    dialog.addEventListener('cancel',async e=>{e.preventDefault();if(await mayClose())dialog.close();});
    const beforeUnload=e=>{if(dirty()){e.preventDefault();e.returnValue='';}};
    window.addEventListener('beforeunload',beforeUnload);
    dialog.addEventListener('close',()=>{editing=false;window.removeEventListener('beforeunload',beforeUnload);dialog.remove();opener?.focus();});
    form.onsubmit=async e=>{e.preventDefault();if(saving)return;const payload=gap?{folder:original.folder,revision:original.edit_revision,action:'resolve',unresolved_id:gap.id,text:left.value,speaker:firstSpeaker.value,translation:form.elements.translation.value,start:Number(form.elements.startTime.value),end:Number(form.elements.endTime.value)}:{folder:original.folder,revision:original.edit_revision,index,action:splitting?'split':'edit',text:left.value,speaker:firstSpeaker.value,translation:form.elements.translation.value};if(!splitting&&!gap){payload.start=Number(form.elements.startTime.value);payload.end=Number(form.elements.endTime.value);}if(splitting){boundary.onchange();if(error.textContent)return;payload.at=Number(range.value);payload.right_text=right.value;payload.right_speaker=secondSpeaker.value;payload.right_translation=form.elements.rightTranslation.value;}saving=true;dialog.setAttribute('aria-busy','true');form.querySelector('[type=submit]').disabled=true;error.textContent='Сохраняем…';try{if(Object.keys(addedNames).length)await post('/api/speech-names',{folder:original.folder,speaker_names:{...original.speaker_names,...addedNames}});const saved=await post('/api/speech-edit',payload);onSave(saved);dialog.close();}catch(e){error.textContent=e.message;}finally{saving=false;dialog.setAttribute('aria-busy','false');form.querySelector('[type=submit]').disabled=false;}};
    editing=true;document.body.append(dialog);dialog.showModal();left.focus();
  }
  function option(value,label){const o=document.createElement('option');o.value=value;o.textContent=label;return o;}
})();
