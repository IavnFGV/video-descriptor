// Exercise the production shared settings controller with deliberately reordered HTTP replies.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('windows-app/ui/app.js', 'utf8').replace(/\r\n/g,'\n');
const html = fs.readFileSync('windows-app/ui/index.html', 'utf8');
const controller = source.slice(source.indexOf('  // Historical ollama-*'), source.indexOf('  function check('));
const handlers = source.slice(source.indexOf("  $('local-provider').onchange="), source.indexOf("  $('setup-open').onclick="))
  .replace(/  localControls\(\);\n  localPreferences\(\)\.catch[^\n]+\n/, '');
const endpointHandlers = source.slice(source.indexOf("  $('ollama-service-url').oninput="), source.indexOf("  $('diarization-device').onchange="));
function field(value = '') {
  return {value, options: [], disabled: false, hidden: false, textContent: '', dataset: {}, attributes: {},
    setAttribute(name, value) {this.attributes[name] = value;},
    replaceChildren(...options) {this.options = options; this.value = options[0]?.value || '';},
    add(option) {this.options.push(option);}};
}
const fields = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], field()]));
fields['local-guide'].hidden=true;
fields['local-provider'].value = 'ollama';
const pending = [], checks = [];
const context = vm.createContext({$: id => {assert(fields[id], id);return fields[id];},
  api: (url, options) => new Promise((resolve, reject) => pending.push({url, options, resolve, reject})),
  setupPost: (action, body) => new Promise((resolve, reject) => pending.push({action, body, resolve, reject})),
  componentAction: async (...args) => {checks.push(args);vm.runInContext('componentBusy=true', context);},
  Option: function(text, value) {this.text = text; this.value = value;}, encodeURIComponent});
vm.runInContext('let componentBusy=false,ollamaEndpointChanged=false;' + controller + handlers + endpointHandlers, context);
const run = code => vm.runInContext(code, context);
const inventory = (names, selected='') => ({models: names.map(name => ({name})), selected, service_ready: true, message: 'connected'});
const lmInventory = names => names.map(id => ({id, title:id}));
const tick = () => new Promise(resolve => setImmediate(resolve));
const models = () => fields['ollama-model'].options.map(o => o.value);
const switchTo = provider => {fields['local-provider'].value=provider;fields['local-provider'].onchange();};
const select = model => {fields['ollama-model'].value=model;fields['ollama-model'].onchange();};
const endpoint = url => {fields['ollama-service-url'].value=url;fields['ollama-service-url'].oninput();};
const refresh = () => fields['ollama-refresh'].onclick();
const watchdog=setTimeout(()=>{console.error('Unresolved UI request',pending.map(p=>p.url||p.action));process.exit(1);},5000);
(async () => {
  // One form, endpoint, model dropdown and action group; no hidden duplicate forms.
  for (const old of ['lmstudio-form','lmstudio-url','lmstudio-model','lmstudio-test','local-ollama-panel','local-lmstudio-panel','ollama-task','local-task-field']) {
    assert(!html.includes(`id="${old}"`));assert(!source.includes(`$('${old}')`));
  }
  for (const id of ['local-provider','ollama-service-url','ollama-use-connection','ollama-connection-current','ollama-model','ollama-refresh','ollama-test','ollama-guide']) {
    assert.equal([...html.matchAll(new RegExp(`id="${id}"`, 'g'))].length,1);
  }
  const init=run('localPreferences()');
  pending[0].resolve({provider:'ollama',ollama_model:'a',lmstudio_url:'http://127.0.0.1:1234/v1',lmstudio_model:'lm'});
  pending[1].resolve({...inventory(['a'],'a'),url:'http://server-a:11434'});
  await tick();pending.at(-1).resolve(inventory(['a'],'a'));await init;
  assert.equal(fields['ollama-model'].value,'a');assert.equal(fields['ollama-test'].disabled,false);
  switchTo('lmstudio');const oldLM=pending.at(-1);
  assert.equal(fields['ollama-service-url'].value,'http://127.0.0.1:1234/v1');assert.equal(fields['local-token-field'].hidden,false);
  switchTo('ollama');pending.at(-1).resolve(inventory(['a']));await tick();
  oldLM.resolve(lmInventory(['stale']));await tick();assert.deepEqual(models(),['','a']);
  switchTo('lmstudio');pending.at(-1).resolve(lmInventory(['lm','other']));await tick();
  assert.equal(fields['ollama-model'].value,'lm');assert(fields['local-guide'].textContent.includes('LM Studio'));
  assert.equal(checks.length,0); // Switching/discovery never generates.
  let request=refresh();pending.at(-1).resolve(lmInventory(['other']));await request;
  assert.equal(fields['ollama-model'].value,'');assert(fields['ollama-feedback'].textContent.includes('сброшен'));
  select('other');endpoint('http://127.0.0.1:4321/v1');
  assert.deepEqual(models(),['']);assert.equal(fields['ollama-test'].disabled,true);
  request=refresh();const oldEndpoint=pending.at(-1);
  endpoint('http://127.0.0.1:4322/v1');let latest=refresh();pending.at(-1).resolve(lmInventory(['new']));await latest;
  oldEndpoint.reject(Error('Old endpoint failed'));await request;assert.deepEqual(models(),['','new']);
  assert(!fields['ollama-feedback'].textContent.includes('failed'));assert.equal(fields['ollama-model'].value,'');
  request=refresh();pending.at(-1).resolve([]);await request;assert.equal(fields['ollama-test'].disabled,true);assert(fields['ollama-feedback'].textContent.includes('моделей нет'));
  request=refresh();pending.at(-1).resolve({data:{}});await request;assert.deepEqual(models(),['']);assert(fields['ollama-feedback'].textContent.includes('Некорректный'));
  request=refresh();pending.at(-1).reject(Error('Connection refused'));await request;assert.deepEqual(models(),['']);assert.equal(fields['ollama-feedback'].textContent,'Connection refused');
  request=refresh();pending.at(-1).resolve(lmInventory(['new','second']));await request;select('new');
  request=fields['ollama-test'].onclick();assert.equal(JSON.parse(pending.at(-1).options.body).action,'verify');const oldTest=pending.at(-1);
  select('second');oldTest.resolve([]);await request;assert(!fields['ollama-feedback'].textContent.includes('Генерация проверена'));
  request=fields['ollama-test'].onclick();const oldTestError=pending.at(-1);switchTo('ollama');pending.at(-1).resolve(inventory(['a']));await tick();oldTestError.reject(Error('Old verification failed'));await request;
  assert.equal(fields['ollama-model'].value,'a');assert(!fields['ollama-feedback'].textContent.includes('failed'));
  switchTo('lmstudio');pending.at(-1).resolve(lmInventory(['new','second']));await tick();assert.equal(fields['ollama-model'].value,'second');
  request=fields['ollama-test'].onclick();pending.at(-1).resolve([]);await request;assert.equal(fields['ollama-feedback'].textContent,'Генерация проверена.');
  request=fields['ollama-form'].onsubmit({preventDefault(){}});
  const saved=JSON.parse(pending.at(-1).options.body);assert.equal(saved.provider,'lmstudio');assert.equal(saved.lmstudio_model,'second');assert(!('ollama_model' in saved));
  pending.at(-1).resolve({lmstudio_url:saved.lmstudio_url,lmstudio_model:saved.lmstudio_model});await request;
  switchTo('ollama');pending.at(-1).resolve(inventory(['a']));await tick();assert.equal(fields['ollama-model'].value,'a');assert.equal(fields['ollama-service-url'].value,'http://server-a:11434');
  endpoint('http://server-b:11434');request=refresh();pending.at(-1).resolve(inventory(['b'],'a'));await request;assert.equal(fields['ollama-model'].value,'');
  request=fields['ollama-use-connection'].onclick();assert.equal(pending.at(-1).body.endpoint,'http://server-b:11434');pending.at(-1).resolve({});await tick();pending.at(-1).resolve(inventory(['b']));await request;
  select('b');assert.equal(checks.length,0);
  request=fields['ollama-form'].onsubmit({preventDefault(){}});assert.equal(pending.at(-1).body.model,'b');assert.equal(pending.at(-1).body.task,'translation');pending.at(-1).resolve({});await request;
  await fields['ollama-test'].onclick();assert.equal(checks.length,1);assert.equal(checks[0][1],'check');assert.equal(checks[0][2].task,'translation');assert.equal(fields['ollama-model'].disabled,true);assert.equal(fields['ollama-test'].attributes['aria-busy'],'true');
  switchTo('lmstudio');pending.at(-1).resolve(lmInventory(['second']));await tick();assert.equal(fields['ollama-service-url'].value,'http://127.0.0.1:4322/v1');assert.equal(fields['ollama-model'].value,'second');
  assert.equal(fields['ollama-model'].disabled,false);assert.equal(fields['component-ollama'].hidden,true);
  fields['ollama-guide'].onclick();assert.equal(fields['local-guide'].hidden,false);assert.equal(fields['ollama-guide'].attributes['aria-expanded'],'true');
  fields['ollama-guide-open'].onclick();const p=pending.at(-1);assert.equal(p.action,'external');assert.equal(p.body.page,'lmstudio-guide');assert.equal(Object.keys(p.body).length,1);p.resolve({});
  switchTo('ollama');pending.at(-1).resolve(inventory(['a']));await tick();
  fields['ollama-guide-open'].onclick();const q=pending.at(-1);assert.equal(q.action,'external');assert.equal(q.body.page,'ollama-guide');assert.equal(Object.keys(q.body).length,1);q.resolve({});
  console.log('PASS: one shared form, saved provider/endpoint/model isolation, missing/empty/invalid/unavailable inventory, stale discovery/verification, explicit tests, busy states and guide');
})().catch(error => {console.error(error);process.exitCode=1;}).finally(()=>clearTimeout(watchdog));
