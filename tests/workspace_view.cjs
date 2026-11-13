const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('video_descriptor/assets/workspace-view.js','utf8');
const key='video-descriptor:ui:workspace';
function boot(value,unavailable=false,search=''){
  const values=new Map(value===undefined?[]:[[key,value]]),attrs=new Map(),events={};
  const root={dataset:{},setAttribute:(k,v)=>attrs.set(k,v)};
  const ctx={document:{documentElement:root,getElementById:()=>null,addEventListener(){}},window:{addEventListener:(k,v)=>events[k]=v},localStorage:{getItem:k=>{if(unavailable)throw Error('denied');return values.get(k)??null},setItem:(k,v)=>{if(unavailable)throw Error('quota');values.set(k,v)}}};
  ctx.URLSearchParams=URLSearchParams;ctx.location={search};
  vm.runInNewContext(source,ctx);
  return {ui:ctx.window.workspaceView,root,attrs,values,events};
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
reload.ui.setLayout('floating');assert.equal(reload.root.dataset.workspaceLayout,'stacked');
reload.ui.setPanel('video','false');assert.equal(reload.attrs.get('data-view-video'),'true');
reload.ui.reset();assert.equal(reload.root.dataset.workspaceLayout,'side');assert.equal(reload.attrs.get('data-view-notes'),'false');
reload.values.set(key,JSON.stringify({version:1,panels:{video:false}}));reload.events.storage({key});assert.equal(reload.attrs.get('data-view-video'),'false');
reload.values.clear();reload.events.storage({key:null});assert.equal(reload.attrs.get('data-view-video'),'true');
const blocked=boot(undefined,true);blocked.ui.setPanel('video',false);assert.equal(blocked.attrs.get('data-view-video'),'false');blocked.ui.reset();
const embedded=boot(undefined,false,'?embedded=1');assert.equal(embedded.ui,undefined);assert.equal(embedded.attrs.size,0);
console.log('PASS: versioned workspace defaults/toggles/layout/persistence/reset/invalid storage/cross-window/blocked storage');
