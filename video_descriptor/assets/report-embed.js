/* Reuse the saved Markdown editor inside the recording workspace. */
(() => {
  const style = document.createElement('style');
  style.textContent = `body,body:has(>.vd-global-nav){margin:0!important;padding:0!important;background:var(--vd-surface);max-width:none!important;width:100%;box-sizing:border-box}.vd-global-nav,.watch-pane,body>a,body>h1,body>p,#rename-lecture,#title-form,#title-status{display:none!important}.workspace{display:block!important}.read-pane{margin:0!important}#personal-notes{border:0;box-shadow:none;padding:0 var(--vd-space-1)}#personal-preview{max-height:calc(100vh - 220px);min-height:180px;overflow:auto;scrollbar-gutter:stable}#personal-preview>*{max-width:100%}#outline-group{margin-top:0}`;
  document.head.append(style);
  const player = parent.document.getElementById('process-video');
  window.reportPlayer = player;
  const localPlayer = document.getElementById('video');
  localPlayer?.removeAttribute('src'); localPlayer?.querySelectorAll('track').forEach(track => track.remove()); localPlayer?.load();
  window.seekTo = time => {
    if(parent.recordingUI){parent.recordingUI.seek(time);return;}
    parent.document.getElementById('follow').checked = false;
    const seek = () => { player.currentTime = Math.min(time, Number.isFinite(player.duration) ? player.duration : time); };
    if (player.readyState === 0) { player.addEventListener('loadedmetadata', seek, {once:true}); player.preload = 'auto'; player.load(); }
    else seek();
  };
  document.addEventListener('wheel',()=>parent.recordingUI?.pauseLink(),{passive:true});
  document.addEventListener('touchmove',()=>parent.recordingUI?.pauseLink(),{passive:true});
  document.addEventListener('keydown',event=>{if(['PageDown','PageUp','ArrowDown','ArrowUp','Home','End',' '].includes(event.key)&&!event.target.closest('textarea,input,.CodeMirror'))parent.recordingUI?.pauseLink();});
  // Preview headings are rebuilt after Markdown edits; handle their buttons by delegation.
  document.addEventListener('click', event => {
    const button = event.target.closest?.('button[data-time]');
    if (!button) return;
    const time = Number(button.dataset.time);
    if (Number.isFinite(time) && time >= 0) window.seekTo(time);
  });
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape') (parent.document.getElementById('recording-notes') || parent.document.getElementById('tab-notes')).focus();
  });
})();
