const {test} = require('node:test');
const assert = require('node:assert/strict');
const {blocked, rules, controller} = require('../service/browser-extension/background.js');

function browser() {
  const updates = [];
  const store = {};
  const state = {installed: true, dynamic: [], tabs: [
    {id: 1, url: 'https://youtube.com/watch?v=local'},
    {id: 2, url: 'https://classroom.example/lesson'}
  ]};
  return {state, updates, api: {
    runtime: {getURL: path => 'chrome-extension://fixture/' + path, getManifest: () => ({version: '1.0.0'})},
    storage: {
      managed: {get: async () => ({SchoolModeInstalled: state.installed})},
      local: {get: async () => ({...store}), set: async value => Object.assign(store, value), remove: async keys => keys.forEach(k => delete store[k])}
    },
    declarativeNetRequest: {getDynamicRules: async () => state.dynamic,
      updateDynamicRules: async value => { state.dynamic = value.addRules; }},
    tabs: {query: async () => state.tabs, get: async id => state.tabs.find(t => t.id === id),
      update: async (id, value) => { updates.push([id, value]); Object.assign(state.tabs.find(t => t.id === id), value); }}
  }};
}

test('domain matching includes subdomains but not lookalike names or URL paths', () => {
  for (const url of ['https://youtube.com/a', 'https://m.youtube.com/a', 'https://YOUTUBE.com./']) assert.ok(blocked(url, ['youtube.com']));
  for (const url of ['https://notyoutube.com/', 'https://youtube.com.evil.example/', 'https://school.example/youtube.com', 'file:///youtube.com', 'broken']) assert.ok(!blocked(url, ['youtube.com']));
  assert.deepEqual(rules([]), []);
  assert.ok(rules(['youtube.com'])[0].condition.resourceTypes.includes('main_frame'));
});

test('School transition blocks requests and moves an existing tab; Free Time clears only these extension rules', async () => {
  const {api, updates, state} = browser(); const control = controller(api);
  assert.equal(await control.apply({ok: true, enabled: true, domains: ['youtube.com'], generation: 'school', version: '1.0.0'}), '');
  assert.equal(updates.length, 1);
  assert.equal(updates[0][0], 1);
  assert.ok(updates[0][1].url.startsWith('chrome-extension://fixture/blocked.html#'));
  assert.equal(state.tabs[1].url, 'https://classroom.example/lesson');
  assert.equal(state.dynamic[0].action.type, 'block');
  await control.apply({ok: true, enabled: true, domains: [], generation: 'free', version: '1.0.0'});
  assert.deepEqual(state.dynamic, []);
  assert.equal(updates.length, 1); // No surprise reopening / autoplay during Free Time.
});

test('concurrent updates settle in order and restart reapplies actual DNR state', async () => {
  const {api, state} = browser(); const control = controller(api);
  await Promise.all([
    control.apply({ok: true, enabled: true, domains: ['youtube.com'], generation: 'school', version: '1.0.0'}),
    control.apply({ok: true, enabled: true, domains: [], generation: 'free', version: '1.0.0'})
  ]);
  assert.deepEqual(state.dynamic, []);
  const fresh = controller(api);
  await fresh.restore();
  await fresh.apply({ok: true, enabled: true, domains: ['youtube.com'], generation: 'school', version: '1.0.0'});
  assert.equal(state.dynamic[0].condition.requestDomains[0], 'youtube.com');
});

test('missing installation and outdated companion are reported; explicit policy removal clears persistent blocks', async () => {
  const {api, state} = browser(); const control = controller(api);
  const packet = {ok: true, enabled: true, domains: ['youtube.com'], generation: 'school', version: '1.0.0'};
  assert.equal(await control.apply({...packet, version: '2.0.0'}), 'outdated_companion');
  await control.apply(packet);
  state.installed = false;
  assert.equal(await control.apply(packet), 'managed_policy_missing');
  await control.clear();
  assert.deepEqual(state.dynamic, []);
});

test('a pending companion upgrade still releases domains for Free Time', async () => {
  const {api, state} = browser(); const control = controller(api);
  await control.apply({ok: true, enabled: true, domains: ['youtube.com'], generation: 'school', version: '1.0.0'});
  assert.equal(await control.apply({ok: true, enabled: true, domains: [], generation: 'free', version: '2.0.0'}), 'outdated_companion');
  assert.deepEqual(state.dynamic, []);
});

test('a stale tab query cannot redirect a tab that has moved to school work', async () => {
  const {api, state, updates} = browser(); const control = controller(api);
  api.tabs.get = async id => ({id, url: 'https://classroom.example/new'});
  await control.apply({ok: true, enabled: true, domains: ['youtube.com'], generation: 'school', version: '1.0.0'});
  assert.deepEqual(updates, []);
});
