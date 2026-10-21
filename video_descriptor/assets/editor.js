/* Local Markdown editing. Generated JSON remains the source evidence. */
(() => {
  const button = document.getElementById('rename-lecture');
  if (!button) return;
  const form = document.getElementById('title-form');
  const input = document.getElementById('title-input');
  const status = document.getElementById('title-status');
  const heading = document.getElementById('lecture-title');
  function display(info) {
    heading.textContent = info.display;
    document.title = info.display;
    input.value = info.title;
  }
  button.disabled = true;
  fetch('title.json', {cache: 'no-store'}).then(async response => {
    if (!response.ok) throw new Error('Для изменения названия нужен обновлённый локальный сервер');
    display(await response.json()); button.disabled = false;
  }).catch(error => { status.hidden = false; status.textContent = error.message; });
  button.addEventListener('click', () => {
    form.hidden = false; button.hidden = true; input.focus(); input.select();
  });
  document.getElementById('cancel-title').addEventListener('click', () => {
    form.hidden = true; button.hidden = false;
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); const submit = form.querySelector('[type="submit"]');
    submit.disabled = true; status.hidden = false; status.textContent = 'Сохраняем название…';
    try {
      const response = await fetch('title.json', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: input.value})});
      const info = await response.json();
      if (!response.ok) throw new Error(info.error || 'Не удалось сохранить название');
      display(info); form.hidden = true; button.hidden = false;
      status.textContent = 'Название сохранено';
    } catch (error) { status.textContent = error.message; }
    finally { submit.disabled = false; }
  });
})();
(() => {
  const panel = document.getElementById('personal-notes');
  if (!panel) return;
  const message = document.getElementById('editor-status');
  const saveButton = document.getElementById('save-notes');
  const preview = document.getElementById('personal-preview');
  const outline = document.getElementById('personal-outline');
  const outlineGroup = document.getElementById('outline-group');
  const sectionsKey = 'video-descriptor-sections-open:' + location.pathname;
  let sectionsOpen = false;
  try { sectionsOpen = localStorage.getItem(sectionsKey) === 'true'; } catch (_) {}
  const draftKey = 'video-descriptor-draft:' + location.pathname;
  let revision = null, savedText = '', dirty = false, loading = true, saving = false;
  let sectionDialog=null, sectionDirty=()=>false;
  window.notesEditorDirty = () => dirty || sectionDirty();
  let editing = false, timer;
  const editor = new EasyMDE({
    element: document.getElementById('notes-editor'),
    autoDownloadFontAwesome: false, spellChecker: false, status: false,
    minHeight: '420px', maxHeight: '65vh',
    toolbar: [
      {name: 'bold', action: EasyMDE.toggleBold, text: 'B', title: 'Жирный'},
      {name: 'italic', action: EasyMDE.toggleItalic, text: 'I', title: 'Курсив'},
      {name: 'heading', action: EasyMDE.toggleHeadingSmaller, text: 'H', title: 'Заголовок'},
      '|',
      {name: 'list', action: EasyMDE.toggleUnorderedList, text: '•', title: 'Список'},
      {name: 'link', action: EasyMDE.drawLink, text: '↗', title: 'Ссылка'},
      '|',
      {name: 'undo', action: EasyMDE.undo, text: '↶', title: 'Отменить'},
      {name: 'redo', action: EasyMDE.redo, text: '↷', title: 'Повторить'},
    ],
  });
  const actions=saveButton.parentElement;
  const undo=document.createElement('button'),redo=document.createElement('button'),reset=document.createElement('button');
  undo.id='undo-notes';redo.id='redo-notes';reset.id='reset-notes';
  for(const button of [undo,redo,reset])button.type='button';
  undo.textContent='↶ Отменить';redo.textContent='↷ Повторить';reset.textContent='Сбросить несохранённые правки';
  undo.title='Ctrl+Z';redo.title='Ctrl+Shift+Z';actions.insertBefore(undo,saveButton);actions.insertBefore(redo,saveButton);actions.insertBefore(reset,document.getElementById('add-section'));
  function historyButtons(){const size=editor.codemirror.historySize();undo.disabled=loading||saving||Boolean(sectionDialog)||!size.undo;redo.disabled=loading||saving||Boolean(sectionDialog)||!size.redo;reset.disabled=loading||saving||!dirty;}
  function undoNotes(){if(saving||sectionDialog)return;editor.codemirror.undo();updatePreview();historyButtons();}
  function redoNotes(){if(saving||sectionDialog)return;editor.codemirror.redo();updatePreview();historyButtons();}
  undo.onclick=undoNotes;redo.onclick=redoNotes;
  reset.onclick=async()=>{if(!dirty||saving)return;if(await window.confirmDiscard('Вернуть конспект к последнему сохранению? Все несохранённые правки будут сброшены.')){editor.codemirror.changeGeneration(true);editor.value(savedText);editor.codemirror.changeGeneration(true);updatePreview();historyButtons();}};
  function openSection(index,creating=false){
    if(sectionDialog||saving||loading)return;
    const cm=editor.codemirror,all=headings(editor.value()),section=all[index];if(!section)return;
    window.recordingUI?.pauseLink();if(parent!==window)parent.recordingUI?.pauseLink();
    const lines=editor.value().split('\n'),next=all.slice(index+1).find(item=>item.depth<=section.depth);
    const stop=next?.line??lines.length,body=lines.slice(section.line+1,stop).join('\n');
    const dialog=document.createElement('dialog');sectionDialog=dialog;dialog.className='vd-dialog notes-section-editor';
    dialog.setAttribute('aria-label',creating?'Новый раздел конспекта':'Правка раздела конспекта');
    dialog.innerHTML='<form><h2>Правка раздела</h2><label>Заголовок с временной меткой<input name="heading" required></label><label>Текст раздела · Markdown<textarea name="body" rows="12"></textarea></label><p role="status">«Применить» меняет черновик. Для записи на диск нажмите «Сохранить».</p><div class="vd-actions"><button type="submit">Применить</button><button type="button" data-cancel>Отмена</button></div></form>';
    const form=dialog.querySelector('form');form.elements.heading.value=section.title;form.elements.body.value=body;
    let localTouched=false;form.addEventListener('input',()=>{localTouched=true;});
    sectionDirty=()=>form.elements.heading.value!==section.title||form.elements.body.value!==body;
    const close=()=>{sectionDialog=null;sectionDirty=()=>false;dialog.close();dialog.remove();updatePreview();historyButtons();};
    const cancel=()=>{if(creating)cm.undo();close();};
    dialog.querySelector('[data-cancel]').onclick=cancel;dialog.addEventListener('cancel',event=>{event.preventDefault();cancel();});
    form.onsubmit=event=>{
      event.preventDefault();if(!form.reportValidity())return;
      const heading=form.elements.heading.value.trim();if(!heading||/[\r\n]/.test(heading))return;
      const replacement='#'.repeat(section.depth)+' '+heading+'\n'+form.elements.body.value.replace(/\s*$/,'')+'\n\n';
      if(creating){cm.undo();cm.changeGeneration(true);const last=cm.lastLine();cm.replaceRange('\n\n'+replacement,{line:last,ch:cm.getLine(last).length});}
      else{cm.changeGeneration(true);cm.replaceRange(replacement,{line:section.line,ch:0},next?{line:stop,ch:0}:{line:lines.length-1,ch:lines.at(-1).length});}
      cm.changeGeneration(true);close();
    };
    dialog.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'&&!sectionDirty()&&(creating||!localTouched)){event.preventDefault();event.stopPropagation();if(creating)cancel();else{close();if(event.shiftKey)redoNotes();else undoNotes();}}if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();form.requestSubmit();}});
    document.body.append(dialog);dialog.showModal();historyButtons();form.elements.heading.focus();
  }
  let hoveredSection=null;
  let controlTimer;
  document.addEventListener('keyup',event=>{if(event.key==='Control')clearTimeout(controlTimer);});
  function notify(text) { message.textContent = text; }
  function download(text, name = 'notes.user.md') {
    const url = URL.createObjectURL(new Blob([text], {type: 'text/markdown;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = name;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function timeOf(title) {
    const match = title.match(/\[(\d{2,}):(\d{2}):(\d{2})/);
    return match ? Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) : null;
  }
  function headings(text) {
    let fence = null;
    const result = [];
    text.split('\n').forEach((line, index) => {
      const code = line.match(/^\s*(`{3,}|~{3,})/);
      if (code) { if (!fence) fence = code[1][0]; else if (fence === code[1][0]) fence = null; return; }
      if (fence) return;
      const match = line.match(/^(#{1,6})\s+(.+)$/);
      if (match) result.push({line: index, depth: match[1].length, title: match[2], time: timeOf(match[2])});
    });
    return result;
  }
  function updatePreview() {
    hoveredSection=null;
    const text = editor.value();
    preview.innerHTML = DOMPurify.sanitize(editor.markdown(text), {
      FORBID_TAGS: ['style', 'iframe', 'form', 'input', 'button', 'img'],
      FORBID_ATTR: ['id', 'name', 'style'],
    });
    const sections = headings(text);
    const rendered = preview.querySelectorAll('h1,h2,h3,h4,h5,h6');
    rendered.forEach((heading, index) => {
      heading.id = 'personal-heading-' + index;
      const bind=node=>{node.title='Ctrl + наведение — правка раздела';node.tabIndex=0;node.onpointerenter=event=>{hoveredSection=index;if(event.ctrlKey)openSection(index);};node.onpointerleave=()=>{if(hoveredSection===index)hoveredSection=null;};node.onkeydown=event=>{if(event.ctrlKey&&event.key==='Enter'){event.preventDefault();openSection(index);}};};
      bind(heading);
      let sibling=heading.nextElementSibling;while(sibling&&!sibling.matches('h1,h2,h3,h4,h5,h6')){bind(sibling);sibling=sibling.nextElementSibling;}
      const time = timeOf(heading.textContent);
      if (time !== null) {
        heading.dataset.noteTime = time;
        const jump = document.createElement('button');
        jump.textContent = '▶'; jump.dataset.time = time;
        jump.title = 'Перейти к этому месту видео'; heading.prepend(jump, ' ');
      }
    });
    outline.replaceChildren();
    sections.forEach((section, index) => {
      if (section.time === null) return;
      const row = document.createElement('div'); row.className = 'outline-row';
      const jump = document.createElement('button'); jump.textContent = section.title;
      jump.addEventListener('click', () => {
        seekTo(section.time);
        if (editing) { editor.codemirror.setCursor(section.line, 0); editor.codemirror.focus(); }
        else {
          const target = document.getElementById('personal-heading-' + index);
          const fold = target?.closest('details');
          if (fold) fold.open = true;
          target?.scrollIntoView({block: 'center'});
        }
      });
      const remove = document.createElement('button'); remove.className = 'outline-delete';
      remove.textContent = 'Удалить'; remove.title = 'Удалить раздел; можно отменить ↶';
      remove.addEventListener('click', () => {
        editor.codemirror.changeGeneration(true);
        const lines = editor.value().split('\n');
        const next = sections.slice(index + 1).find(item => item.depth <= section.depth);
        editor.codemirror.replaceRange('', {line: section.line, ch: 0},
          next ? {line: next.line, ch: 0} : {line: lines.length - 1, ch: lines.at(-1).length});
        updatePreview();
        editor.codemirror.changeGeneration(true);historyButtons();
      });
      row.append(jump, remove); outline.append(row);
    });
    // Fold the generated chapter descriptions, keeping the Markdown itself intact.
    const chapterHeading = Array.from(preview.querySelectorAll('h2')).find(
      heading => heading.textContent.trim() === 'Разделы видео');
    if (chapterHeading) {
      const fold = document.createElement('details'); fold.className = 'notes-fold';
      fold.id = 'preview-sections'; fold.open = sectionsOpen;
      const summary = document.createElement('summary'); summary.textContent = 'Разделы видео';
      fold.append(summary); chapterHeading.before(fold);
      let node = chapterHeading;
      while (node) {
        if (node !== chapterHeading && node.matches?.('h1,h2')) break;
        const next = node.nextSibling; fold.append(node); node = next;
      }
      chapterHeading.hidden = true;
      fold.addEventListener('toggle', () => {
        sectionsOpen = fold.open;
        try { localStorage.setItem(sectionsKey, String(sectionsOpen)); } catch (_) {}
      });
    }
  }
  function rememberDraft() {
    try {
      if (dirty) localStorage.setItem(draftKey, JSON.stringify({text: editor.value(), revision}));
      else localStorage.removeItem(draftKey);
    } catch (_) { /* The visible editor and Markdown download still work. */ }
  }
  editor.codemirror.on('change', () => {
    if (loading) return;
    dirty = editor.value() !== savedText; saveButton.disabled = !dirty || revision === null || saving;
    historyButtons();
    rememberDraft(); notify(dirty ? 'Есть несохранённые правки' : 'Сохранено');
    clearTimeout(timer); timer = setTimeout(updatePreview, 250);
  });
  function view(name) {
    editing = name === 'edit'; panel.dataset.editing = String(editing);
    document.getElementById('editor-pane').hidden = !editing;
    preview.hidden = name !== 'read';
    (outlineGroup || outline).hidden = name === 'model';
    document.getElementById('model-material').hidden = name !== 'model';
    document.querySelectorAll('[data-notes-view]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.notesView === name));
    });
    if (editing) editor.codemirror.refresh();
    if (name === 'read') updatePreview();
  }
  document.querySelectorAll('[data-notes-view]').forEach(button => {
    button.addEventListener('click', () => view(button.dataset.notesView));
  });
  async function save() {
    if(sectionDialog){notify('Сначала примените или отмените правку раздела.');return;}
    if (revision === null || saving || !dirty) return;
    saving = true; saveButton.disabled = true; notify('Сохраняем…');
    const text = editor.value();
    try {
      const response = await fetch('editor.json', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text, revision})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Не удалось сохранить');
      revision = result.revision; savedText = text; dirty = editor.value() !== savedText;
      rememberDraft(); notify(dirty ? 'Сохранено; есть новые правки' : 'Сохранено в notes.user.md');
    } catch (error) { notify(error.message + ' Правки можно скачать кнопкой Markdown.'); }
    finally { saving = false; saveButton.disabled = !dirty || revision === null; historyButtons(); }
  }
  saveButton.addEventListener('click', save);
  document.getElementById('download-notes').addEventListener('click', () => download(editor.value()));
  document.getElementById('download-html')?.addEventListener('click',()=>{
    const exported=document.implementation.createHTMLDocument(document.getElementById('lecture-title')?.textContent||'Конспект');
    exported.documentElement.lang='ru';
    const charset=exported.createElement('meta');charset.setAttribute('charset','utf-8');exported.head.prepend(charset);
    exported.body.innerHTML=DOMPurify.sanitize(editor.markdown(editor.value()));
    const blob=new Blob(['<!doctype html>\n'+exported.documentElement.outerHTML],{type:'text/html;charset=utf-8'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='notes.html';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  document.getElementById('add-section').addEventListener('click', () => {
    const time = Math.floor((window.reportPlayer || document.getElementById('video')).currentTime || 0);
    const stamp = [Math.floor(time / 3600), Math.floor(time / 60) % 60, time % 60]
      .map(part => String(part).padStart(2, '0')).join(':');
    const cm = editor.codemirror, last = cm.lastLine();
    if(sectionDialog||saving)return;
    cm.changeGeneration(true);
    cm.replaceRange('\n\n## [' + stamp + '] Новый раздел\n\n', {line: last, ch: cm.getLine(last).length});
    cm.changeGeneration(true);updatePreview();openSection(headings(editor.value()).length-1,true);
  });
  document.addEventListener('keydown', event => {
    clearTimeout(controlTimer);
    if(event.key==='Control'&&!event.repeat&&hoveredSection!==null&&!sectionDialog)controlTimer=setTimeout(()=>{if(hoveredSection!==null&&!sectionDialog)openSection(hoveredSection);},220);
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'&&!event.target.closest('input,textarea,.CodeMirror')&&!sectionDialog){event.preventDefault();if(event.shiftKey)redoNotes();else undoNotes();}
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault(); save();
    }
  });
  window.addEventListener('beforeunload', event => {
    if (window.notesEditorDirty()) { event.preventDefault(); event.returnValue = ''; }
  });
  async function load() {
    try {
      const response = await fetch('editor.json', {cache: 'no-store'});
      if (!response.ok) throw new Error('Откройте отчёт через обновлённый локальный сервер');
      const result = await response.json(); revision = result.revision; savedText = result.text;
      editor.value(savedText);
      let draft;
      try { draft = JSON.parse(localStorage.getItem(draftKey)); } catch (_) {}
      if (draft && draft.revision === revision && draft.text !== savedText) {
        editor.value(draft.text); dirty = true; notify('Восстановлен несохранённый черновик');
      } else notify(result.personal ? 'Открыт ваш конспект' : 'Черновик модели — можно редактировать');
      if (draft && draft.revision !== revision) {
        const recover = document.getElementById('download-draft'); recover.hidden = false;
        recover.addEventListener('click', () => download(draft.text, 'notes.draft.md'));
        notify('Есть черновик другой версии: его можно скачать отдельно');
      }
    } catch (error) {
      editor.value(document.getElementById('editor-seed').textContent);
      notify(error.message + '. Доступно редактирование и скачивание Markdown.');
    }
    editor.codemirror.clearHistory();loading = false; saveButton.disabled = !dirty || revision === null;historyButtons();
    updatePreview(); view('read');
  }
  load();
})();
