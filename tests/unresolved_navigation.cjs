// Exercise the production transcript counter: unresolved intervals are reachable by click.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('video_descriptor/assets/create.js', 'utf8').replace(/\r\n/g, '\n');

function slice(from, to) {
  const start = source.indexOf(from);
  const end = source.indexOf(to);
  assert(start >= 0 && end > start, `missing source anchor: ${from} -> ${to}`);
  return source.slice(start, end);
}

// The production helpers only; the rest of the workspace module stays untouched.
const code = [
  slice('function clock(', 'function text('),
  slice('function text(', 'async function json('),
  slice('function jump(', 'function stamp('),
  slice('function changed(', 'function savedSpeech('),
].join('\n');

function makeElement(tag = 'div') {
  const classes = new Set();
  const node = {
    tag, dataset: {}, attributes: {}, textContent: '', type: '', title: '', onclick: null,
    scrollTop: 0, rectTop: 0, children: [],
    get className() { return [...classes].join(' '); },
    set className(value) { classes.clear(); String(value || '').split(/\s+/).filter(Boolean).forEach(name => classes.add(name)); },
    classList: {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      contains: name => classes.has(name),
      toggle: (name, force) => {
        const on = force === undefined ? !classes.has(name) : Boolean(force);
        if (on) classes.add(name); else classes.delete(name);
        return on;
      },
    },
    append(...nodes) { node.children.push(...nodes); },
    replaceChildren(...nodes) { node.children = [...nodes]; },
    setAttribute(name, value) { node.attributes[name] = value; },
    getAttribute(name) { return node.attributes[name]; },
    querySelectorAll(selector) {
      const found = [];
      const walk = item => { for (const child of item.children || []) { found.push(child); walk(child); } };
      walk(node);
      if (selector.includes('data-gap-id')) return found.filter(item => item.dataset && item.dataset.gapId);
      return found;
    },
    getBoundingClientRect() { return {top: node.rectTop, bottom: node.rectTop}; },
  };
  return node;
}

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, makeElement());
  return elements.get(id);
}
const context = vm.createContext({
  document: {createElement: tag => makeElement(tag)},
  window: {recordingUI: null},
  $: id => element(id),
  follow: {checked: true},
  video: {currentTime: 0},
  syncPlayback() {},
  JSON,
});
vm.runInContext('let rendered = {};' + code, context);
const run = script => vm.runInContext(script, context);

const GAPS = [{id: 'u-0000025000-0000030000', start: 25, end: 30},
  {id: 'u-0000075000-0000080000', start: 75, end: 80}];
const counter = element('speech-count');
const feed = element('speech-feed');
const first = makeElement('div'); first.dataset.gapId = GAPS[0].id; first.rectTop = 300;
const second = makeElement('div'); second.dataset.gapId = GAPS[1].id; second.rectTop = 900;
feed.append(first, second);
feed.rectTop = 100;

// The counter keeps the reply count and adds one link per unresolved interval.
run(`changed('speech-count', [3, 5, ${JSON.stringify(GAPS)}], node => paintSpeechCount({speech:[{},{},{}], speech_count:5, unresolved:${JSON.stringify(GAPS)}}, node));`);
const links = counter.children.filter(child => child.classList.contains('gap-link'));
assert.equal(counter.children[0].textContent, '3 / 5 реплик');
assert(counter.children[1].textContent.includes('участков без таймкодов: 2'));
assert.equal(links.length, 2);
assert.equal(links[0].textContent, '00:00:25');
assert.equal(links[1].textContent, '00:01:15');
assert.equal(links[0].type, 'button');
assert.equal(links[0].getAttribute('aria-label'), 'Перейти к участку без таймкодов 00:00:25–00:00:30');
assert.equal(links[1].getAttribute('aria-label'), 'Перейти к участку без таймкодов 00:01:15–00:01:20');

// An unchanged snapshot keeps the rendered counter, so polling never steals the focus.
const rendered = counter.children[0];
run(`changed('speech-count', [3, 5, ${JSON.stringify(GAPS)}], node => paintSpeechCount({speech:[{},{},{}], speech_count:5, unresolved:${JSON.stringify(GAPS)}}, node));`);
assert.equal(counter.children[0], rendered);
assert.equal(counter.children.filter(child => child.classList.contains('gap-link')).length, 2);

// A click on the second interval moves to that row and to that moment of the recording.
links[1].onclick();
assert.equal(second.classList.contains('current'), true);
assert.equal(first.classList.contains('current'), false);
assert.equal(feed.scrollTop, 900 - 100 - 24);
assert.equal(context.video.currentTime, 75);
assert.equal(context.follow.checked, false);

// Clicking the first interval moves the highlight again; only one interval stays current.
links[0].onclick();
assert.equal(first.classList.contains('current'), true);
assert.equal(second.classList.contains('current'), false);
assert.equal(feed.scrollTop, 900 - 100 - 24 + 300 - 100 - 24);
assert.equal(context.video.currentTime, 25);

// A recording without unresolved intervals keeps the plain counter.
run(`changed('speech-count', [3, 5, []], node => paintSpeechCount({speech:[{},{},{}], speech_count:5, unresolved:[]}, node));`);
assert.equal(counter.children.length, 1);
assert.equal(counter.children[0].textContent, '3 / 5 реплик');
assert.equal(counter.children.filter(child => child.classList.contains('gap-link')).length, 0);

// An older snapshot without the field behaves like a recording without gaps.
run(`changed('speech-count', [0, 0, undefined], node => paintSpeechCount({speech:[], speech_count:0}, node));`);
assert.equal(counter.children.length, 1);
assert.equal(counter.children[0].textContent, '0 / 0 реплик');

console.log('PASS: unresolved intervals are clickable in the transcript counter; one link per interval, ' +
  'the current interval is marked, playback moves to its time and polling keeps the counter intact');
