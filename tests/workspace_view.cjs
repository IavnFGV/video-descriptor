const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('video_descriptor/assets/workspace-view.js','utf8');
const key='video-descriptor:ui:workspace';
const panels=['video','transcript','speakers','translation','notes','article','technical'];
const defaults={video:true,transcript:true,speakers:true,translation:false,notes:false,article:false,technical:false};
function boot(value,failures={},search='',hash=''){
  const values=new Map(value===undefined?[]:[[key,value]]),attrs=new Map(),events={};
  const attempts={get:0,set:0},applies={count:0};
  const root={dataset:{},setAttribute:(k,v)=>attrs.set(k,v)};
  root.setAttribute=(k,v)=>{applies.count++;attrs.set(k,v)};
  const ctx={document:{documentElement:root,getElementById:()=>null,addEventListener(){}},window:{addEventListener:(k,v)=>events[k]=v},localStorage:{getItem:k=>{attempts.get++;if(failures.read)throw Error('denied');return values.get(k)??null},setItem:(k,v)=>{attempts.set++;if(failures.write)throw Error('quota');values.set(k,v)}}};
  ctx.URLSearchParams=URLSearchParams;ctx.location={search,hash};
  vm.runInNewContext(source,ctx);
  return {ui:ctx.window.workspaceView,root,attrs,values,events,attempts,applies};
}
function assertView(app,layout,flags,label){
  assert.equal(app.root.dataset.workspaceLayout,layout,label+' layout');
  for(const name of panels)assert.equal(app.attrs.get('data-view-'+name),String(flags[name]),label+' '+name);
}
for(const layout of ['side','stacked'])for(let mask=0;mask<128;mask++){
  const flags=Object.fromEntries(panels.map((name,index)=>[name,Boolean(mask&(1<<index))]));
  const bytes=' '+JSON.stringify({version:1,layout,panels:flags})+' ';
  const combination=boot(bytes),label=layout+' mask '+mask;
  assertView(combination,layout,flags,label);
  assert.equal(combination.values.get(key),bytes,label+' bytes');
  assert.equal(combination.attempts.get,1,label+' reads');
  assert.equal(combination.attempts.set,0,label+' writes');
  combination.ui.route(new URLSearchParams());
  const expected=flags.transcript?(flags.notes||flags.article?'all':'transcript'):(flags.notes?'notes':flags.article?'article':'all');
  assert.equal(combination.root.dataset.workspaceTab,expected,label+' initial tab');
  assert.equal(combination.values.get(key),bytes,label+' route does not rewrite preferences');
  assert.equal(combination.attempts.set,0,label+' route writes');
}
for(const [search,tab,target] of [
  ['?material=article&stage=speech','article','article'],
  ['?material=notes&stage=speech','notes','notes'],
  ['?stage=speech','transcript',undefined],
  ['?material=invalid&stage=speech','transcript',undefined],
  ['?report=missing&stage=speech','notes','notes'],
]){
  const app=boot();app.ui.route(new URLSearchParams(search));
  assert.equal(app.root.dataset.workspaceTab,tab,search);
  assert.equal(app.root.dataset.workspaceTarget,target,search+' override');
  assert.equal(app.attempts.set,0,search+' route writes');
}
const urlFlags={video:false,transcript:true,speakers:false,translation:true,notes:false,article:false,technical:true};
const urlBytes=JSON.stringify({version:1,layout:'stacked',panels:urlFlags});
for(const search of ['?stage=notes&material=article&job=job-1&folder=folder-1&report=report-1','?stage=report&material=article&job=job-2&folder=folder-2','?stage=unknown&material=unknown']){
  const urlApp=boot(urlBytes,{},search,'#section');
  assertView(urlApp,'stacked',urlFlags,search);
  assert.equal(urlApp.values.get(key),urlBytes,search+' bytes');
  assert.equal(urlApp.attempts.get,1,search+' reads');
  assert.equal(urlApp.attempts.set,0,search+' writes');
}
for(const value of [undefined,'bad','null','[]','{"version":99,"panels":{"video":false}}','{"version":1,"layout":"dock","panels":{"video":"false","transcript":null}}']){
  const app=boot(value);
  assert.equal(app.root.dataset.workspaceLayout,'side');
  for(const name of ['video','transcript','speakers'])assert.equal(app.attrs.get('data-view-'+name),'true');
  for(const name of ['notes','article','translation','technical'])assert.equal(app.attrs.get('data-view-'+name),'false');
}
const saved=' { "version": 1, "layout": "stacked", "extra": 42, "panels": { "video": false, "transcript": "false", "notes": true, "future": true } } ';
const partial=boot(saved);
assert.equal(partial.values.get(key),saved); // Reading does not rewrite stored preferences.
assert.equal(partial.root.dataset.workspaceLayout,'stacked');
assert.equal(partial.attrs.get('data-view-video'),'false');
assert.equal(partial.attrs.get('data-view-transcript'),'true'); // Invalid value defaults.
assert.equal(partial.attrs.get('data-view-speakers'),'true'); // Missing value defaults.
assert.equal(partial.attrs.get('data-view-notes'),'true');
for(const name of ['translation','article','technical'])assert.equal(partial.attrs.get('data-view-'+name),'false');
assert.equal(partial.attrs.has('data-view-future'),false);
partial.ui.setPanel('article',true);
assert.deepEqual(JSON.parse(partial.values.get(key)),{
  version:1,layout:'stacked',panels:{video:false,transcript:true,speakers:true,translation:false,notes:true,article:true,technical:false}
}); // Saving keeps recognized settings and omits unknown fields.
const app=boot();
for(const name of ['video','transcript','speakers','notes','article','translation','technical']){
  app.ui.setPanel(name,false);assert.equal(app.attrs.get('data-view-'+name),'false');
  app.ui.setPanel(name,true);assert.equal(app.attrs.get('data-view-'+name),'true');
}
app.ui.setLayout('stacked');
const reload=boot(app.values.get(key));assert.equal(reload.root.dataset.workspaceLayout,'stacked');
for(const name of ['video','transcript','speakers','notes','article','translation','technical'])assert.equal(reload.attrs.get('data-view-'+name),'true');
const writesBeforeInvalid=reload.attempts.set;
reload.ui.setLayout('floating');assert.equal(reload.root.dataset.workspaceLayout,'stacked');
reload.ui.setPanel('video','false');reload.ui.setPanel('unknown',true);assert.equal(reload.attrs.get('data-view-video'),'true');
assert.equal(reload.attempts.set,writesBeforeInvalid,'invalid controls do not write');
reload.ui.reset();assert.equal(reload.root.dataset.workspaceLayout,'side');assert.equal(reload.attrs.get('data-view-notes'),'false');
reload.values.set(key,JSON.stringify({version:1,panels:{video:false}}));reload.events.storage({key});assert.equal(reload.attrs.get('data-view-video'),'false');
reload.values.clear();reload.events.storage({key:null});assert.equal(reload.attrs.get('data-view-video'),'true');
const blocked=boot(undefined,{read:true,write:true});blocked.ui.setPanel('video',false);assert.equal(blocked.attrs.get('data-view-video'),'false');blocked.ui.reset();
const readBlocked=boot(urlBytes,{read:true});
assertView(readBlocked,'side',defaults,'read failure defaults');
assert.equal(readBlocked.attempts.get,1);assert.equal(readBlocked.attempts.set,0);
readBlocked.ui.setPanel('video',false);readBlocked.ui.setLayout('stacked');
assert.equal(readBlocked.attrs.get('data-view-video'),'false');assert.equal(readBlocked.root.dataset.workspaceLayout,'stacked');
readBlocked.ui.reset();assertView(readBlocked,'side',defaults,'read failure reset');
const writeBlocked=boot(urlBytes,{write:true});
writeBlocked.ui.setPanel('notes',true);assert.equal(writeBlocked.attrs.get('data-view-notes'),'true');
writeBlocked.ui.setLayout('side');assert.equal(writeBlocked.root.dataset.workspaceLayout,'side');
writeBlocked.ui.reset();assertView(writeBlocked,'side',defaults,'write failure reset');
assert.equal(writeBlocked.attempts.set,3,'failed writes attempted');assert.equal(writeBlocked.values.get(key),urlBytes,'failed writes preserve bytes');
assertView(boot(writeBlocked.values.get(key)),'stacked',urlFlags,'reload after failed writes');
const storage=boot(urlBytes);
storage.values.set(key,JSON.stringify({version:1,layout:'side',panels:{video:true,notes:true}}));
storage.events.storage({key:'unrelated'});
assertView(storage,'stacked',urlFlags,'unrelated storage event');
assert.equal(storage.attempts.get,1,'unrelated event does not read');assert.equal(storage.applies.count,panels.length,'unrelated event does not apply');
storage.events.storage({key});
assertView(storage,'side',{...defaults,notes:true},'matching storage event');
assert.equal(storage.attempts.get,2,'matching event reads');
storage.values.set(key,'malformed');storage.events.storage({key:null});
assertView(storage,'side',defaults,'malformed storage event');assert.equal(storage.attempts.get,3,'clear event reads');
storage.values.delete(key);storage.events.storage({key});
assertView(storage,'side',defaults,'removed storage event');assert.equal(storage.attempts.get,4,'removed event reads');
assert.equal(storage.attempts.set,0,'storage events do not write');
const embedded=boot(urlBytes,{},'?embedded=1');assert.equal(embedded.ui,undefined);assert.equal(embedded.attrs.size,0);
assert.equal(embedded.attempts.get,0,'embedded does not read');assert.equal(embedded.attempts.set,0,'embedded does not write');
console.log('PASS: 256 workspace combinations/URL neutrality/defaults/toggles/layout/persistence/reset/invalid storage/cross-window/blocked storage');
