/* Reuse the saved Markdown editor inside the recording workspace. */
(() => {
  const style = document.createElement('style');
  style.textContent = `body{margin:0!important;padding:0!important;background:white;max-width:none}.watch-pane,body>a,body>h1,body>p,#rename-lecture,#title-form,#title-status{display:none!important}.workspace{display:block!important}.read-pane{margin:0!important}#personal-notes{border:0;box-shadow:none;padding:0 4px}`;
  document.head.append(style);
  const player = parent.document.getElementById('process-video');
  window.reportPlayer = player;
  const localPlayer = document.getElementById('video');
  localPlayer?.removeAttribute('src'); localPlayer?.querySelectorAll('track').forEach(track => track.remove()); localPlayer?.load();
  window.seekTo = time => {
    parent.document.getElementById('follow').checked = false;
    const seek = () => { player.currentTime = Math.min(time, Number.isFinite(player.duration) ? player.duration : time); };
    if (player.readyState === 0) { player.addEventListener('loadedmetadata', seek, {once:true}); player.preload = 'auto'; player.load(); }
    else seek();
  };
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape') parent.document.getElementById('tab-notes').focus();
  });
})();
