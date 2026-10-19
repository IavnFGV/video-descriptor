/* Per-record tab-session drafts. Never persist credentials or media files. */
(() => {
  const restored = new Set();
  const identity = () => {
    const query = new URLSearchParams(location.search);
    return query.get('folder') || query.get('job') || 'new';
  };
  const key = () => 'vd-studio-draft:' + identity();
  function read() { try { return JSON.parse(sessionStorage.getItem(key()) || '{}'); } catch (_) { return {}; } }
  function write(value) { try { sessionStorage.setItem(key(), JSON.stringify(value)); } catch (_) { /* Visible inputs remain usable. */ } }
  const allowed = element => element.matches('input,textarea,select') && element.id &&
    !['password','file','hidden'].includes(element.type) && !element.closest('#connections-form') &&
    !['existing-runs','notes-variant'].includes(element.id);
  document.addEventListener('input', event => {
    const element = event.target;
    if (!allowed(element)) return;
    const draft = read(); draft[element.id] = element.type === 'checkbox' ? element.checked : element.value;
    write(draft);
  });
  window.studioDraft = {
    restore(root, force=false) {
      if (!root) return;
      const draft = read();
      for (const element of root.querySelectorAll('input,textarea,select')) {
        const fieldKey = key() + ':' + element.id;
        if (!allowed(element) || (!force && restored.has(fieldKey)) || !(element.id in draft)) continue;
        if (element.type === 'checkbox') element.checked = draft[element.id]; else element.value = draft[element.id];
        restored.add(fieldKey);
      }
    },
    clear(root) {
      const draft = read();
      for (const element of root.querySelectorAll('input,textarea,select')) delete draft[element.id];
      write(draft);
    }
  };
})();
