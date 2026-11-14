(() => {
  if(window.updatesUI)return;
  const $ = id => document.getElementById(id);
  let instance, busy=false, revision=0, state, polling=null;
  const label = value => value ? value.version+(value.build==null?' (сборка разработки)':' (build '+(value.build>=12?String(value.build).padStart(4,'0'):value.build)+')') : '';
  function render(value) {
    state=value;
    const available=value.update_available===true && value.status!=='unsupported';
    $('updates-badge').hidden=!available;
    $('updates-open').hidden=!available;
    $('updates-open').disabled=!available;
    $('updates-check').disabled=value.status==='checking';
    $('updates-check').setAttribute('aria-busy', String(value.status==='checking'));
    $('updates-heading').textContent=available?'Доступно обновление':'Обновления';
    $('updates-status').textContent=({checking:'Проверяем обновления…',unavailable:'Не удалось проверить обновления: GitHub недоступен. Повторим позже.',unsupported:'Проверка обновлений недоступна для этой сборки разработки.',ok:available?'Обновление доступно.':'Вы используете актуальную версию.'})[value.status]||'Обновления ещё не проверялись.';
    $('updates-installed').textContent='Установлено: '+label(value.installed);
    $('updates-available').textContent=available?'Доступно: '+label(value.latest):'';
    $('updates-title').textContent=available?value.latest.title:'';
    $('updates-notes').textContent=available?value.latest.notes:'';
  }
  async function refresh(manual=false) {
    if (!instance || busy) return;
    const current=++revision;
    busy=true;
    $('updates-check').disabled=true;$('updates-check').setAttribute('aria-busy','true');
    if(manual)$('updates-status').textContent='Проверяем обновления…';
    try {
      const response=await fetch(manual?'/api/updates/check':'/api/updates', manual?{method:'POST',headers:{'X-App-Instance':instance}}:{});
      if (!response.ok) throw new Error('unavailable');
      const value=await response.json();
      if (current===revision) render(value);
    } catch (_) {
      if (current===revision) {
        $('updates-status').textContent='Не удалось проверить обновления: GitHub недоступен.';
        $('updates-check').disabled=false;
        $('updates-check').setAttribute('aria-busy','false');
      }
    } finally {if(current===revision)busy=false;}
  }
  $('updates-check').onclick=()=>{
    if (!$('updates-dialog').open) $('updates-dialog').showModal();
    refresh(true);
  };
  $('updates-badge').onclick=()=>{if (!$('updates-dialog').open) $('updates-dialog').showModal();};
  $('updates-later').onclick=()=>$('updates-dialog').close();
  $('updates-open').onclick=async()=>{
    if (!state?.update_available) return;
    try {
      // No API metadata URL is ever sent back or used for navigation.
      const response=await fetch('/api/setup/external',{method:'POST',headers:{'Content-Type':'application/json','X-App-Instance':instance},body:JSON.stringify({page:'update-release'})});
      if(!response.ok)throw new Error('open');
    } catch (_) {$('updates-status').textContent='Не удалось открыть релиз. Повторите позже.';}
  };
  function suspend(){
    instance=null;revision++;busy=false;state=null;
    if(polling!==null){clearInterval(polling);polling=null;}
    $('updates-check').disabled=true;$('updates-check').setAttribute('aria-busy','false');$('updates-badge').hidden=true;
    $('updates-open').disabled=true;
  }
  window.updatesUI={
    init(value){
      if(instance===value&&polling!==null)return;
      if(instance!==value){revision++;busy=false;state=null;}
      instance=value;
      if(polling===null)polling=setInterval(()=>{if(!document.hidden)refresh();},15000);
      refresh();
    },refresh,suspend
  };
  window.addEventListener('pagehide',suspend);
})();
