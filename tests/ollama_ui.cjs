// Exercise production discovery code with controlled HTTP completion order.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('windows-app/ui/app.js', 'utf8');
const functions = source.slice(source.indexOf('  function clearOllamaModels()'), source.indexOf('  function check('));
const endpointHandler = source.slice(source.indexOf("  $('ollama-service-url').oninput="), source.indexOf("  $('ollama-use-connection').onclick="));
function field(value = '') {
  return {value, options: [], disabled: false, textContent: '',
    replaceChildren(...options) {this.options = options; this.value = options[0]?.value || '';},
    add(option) {this.options.push(option);}};
}
const fields = Object.fromEntries(['ollama-service-url', 'ollama-model', 'ollama-connect', 'ollama-test', 'ollama-feedback', 'ollama-connection-current'].map(id => [id, field()]));
fields['ollama-service-url'].value = 'http://server-a:11434';
const pending = [];
const context = vm.createContext({$: id => fields[id], api: url => new Promise((resolve, reject) => pending.push({url, resolve, reject})),
  Option: function(text, value) {this.text = text; this.value = value;}, encodeURIComponent});
vm.runInContext('let ollamaRequest=0,ollamaConnectionLoaded=true,ollamaEndpointChanged=false,componentBusy=false;' + functions + endpointHandler, context);
const run = () => vm.runInContext('ollamaStatus()', context);
const inventory = (url, names, selected='') => ({url, models: names.map(name => ({name})), selected, service_ready: true, version: 'test', message: names.length ? 'connected' : 'No models installed'});
(async () => {
  const old = run();
  fields['ollama-service-url'].value = 'http://server-b:11434';
  fields['ollama-service-url'].oninput();
  assert.equal(fields['ollama-model'].value, '');
  assert.equal(fields['ollama-test'].disabled, true);
  assert(pending[1].url.includes('server-b'));
  pending[1].resolve(inventory('http://server-b:11434', ['b']));
  await new Promise(resolve => setImmediate(resolve));
  pending[0].resolve(inventory('http://server-a:11434', ['stale'], 'stale'));
  await old;
  assert.deepEqual(fields['ollama-model'].options.map(o => o.value), ['', 'b']);
  assert.equal(fields['ollama-model'].value, ''); // Never silently choose b.
  fields['ollama-model'].value = 'b';
  let refresh = run(); pending.at(-1).resolve(inventory('http://server-b:11434', ['b', 'new'])); await refresh;
  assert.equal(fields['ollama-model'].value, 'b');
  refresh = run(); pending.at(-1).resolve(inventory('http://server-b:11434', ['new'])); await refresh;
  assert.equal(fields['ollama-model'].value, '');
  assert(fields['ollama-feedback'].textContent.includes('сброшен'));
  refresh = run(); pending.at(-1).resolve(inventory('http://server-b:11434', [])); await refresh;
  assert.equal(fields['ollama-test'].disabled, true);
  assert.equal(fields['ollama-feedback'].textContent, 'No models installed');
  refresh = run(); pending.at(-1).reject(Error('Connection refused')); await refresh;
  assert.deepEqual(fields['ollama-model'].options.map(o => o.value), ['']);
  assert.equal(fields['ollama-feedback'].textContent, 'Connection refused');
  console.log('PASS: endpoint invalidation, refresh, empty/unavailable, explicit selection, stale responses');
})().catch(error => {console.error(error); process.exitCode=1;});
