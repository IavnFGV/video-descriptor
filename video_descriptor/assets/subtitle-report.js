(() => {
  const section = document.querySelector('[data-subtitle-folder]');
  if (!section || !/^https?:$/.test(location.protocol)) return;
  const folder = section.dataset.subtitleFolder;
  section.addEventListener('click', async event => {
    const button = event.target.closest('[data-edit-subtitle]');
    if (!button) return;
    button.disabled = true;
    try {
      const response = await fetch('/api/speech?' + new URLSearchParams({folder}));
      const data = await response.json();
      if (!response.ok) throw Error(data.error);
      const result = data.result;
      const index = result.segments.findIndex((row, i) => (row.id || `s${i+1}`) === button.dataset.editSubtitle);
      if (index < 0) throw Error('Реплика изменилась. Обновите страницу');
      window.editSpeechReply(result, index, document.querySelector('video'), () => location.reload());
    } catch (error) {
      let status = section.querySelector('.subtitle-error');
      if (!status) { status = document.createElement('p'); status.className = 'subtitle-error'; status.setAttribute('role', 'status'); section.prepend(status); }
      status.textContent = error.message;
    } finally { button.disabled = false; }
  });
})();
