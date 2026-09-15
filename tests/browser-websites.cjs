// Optional real Chromium check. Uses an isolated temporary profile and local
// HTTP fixtures only. Native transport / managed settings are adapted because
// their Linux installation is tested separately, not installed on the host.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'school-browser-test-'));
  const extension = path.resolve(__dirname, '../service/browser-extension');
  const server = http.createServer((_request, reply) => {
    reply.setHeader('Content-Type', 'text/html');
    reply.end('<!doctype html><title>Local website fixture</title><h1>Local page</h1>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  let context;
  try {
    context = await chromium.launchPersistentContext(root, {
      executablePath: process.env.CHROMIUM_EXECUTABLE,
      headless: true,
      ignoreDefaultArgs: ['--disable-extensions'],
      args: ['--enable-unsafe-extension-debugging', '--host-resolver-rules=MAP *.school.test 127.0.0.1', '--no-proxy-server', '--disable-background-networking']
    });
    const debug = await context.browser().newBrowserCDPSession();
    await debug.send('Extensions.loadUnpacked', {path: extension});
    const worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
    await worker.evaluate(async () => {
      await startup;
      globalThis.websiteTest = controller({...chrome, storage: {...chrome.storage,
        managed: {get: async () => ({SchoolModeInstalled: true})}}});
    });
    const blockedPage = await context.newPage();
    await blockedPage.goto(`http://blocked.school.test:${port}/watch`);
    const schoolPage = await context.newPage();
    await schoolPage.goto(`http://classroom.school.test:${port}/lesson`);
    assert.equal(await worker.evaluate(() => websiteTest.apply({ok: true, enabled: true,
      domains: ['blocked.school.test'], generation: 'school', version: '1.0.0'})), '');
    await blockedPage.waitForURL('**/blocked.html#**');
    assert.equal(await blockedPage.locator('h1').textContent(), 'Save this for Free Time');
    assert.equal(schoolPage.url(), `http://classroom.school.test:${port}/lesson`);
    // Real DNR intercepts main-frame and embedded requests, including subdomains.
    const denied = await schoolPage.evaluate(async url => {
      try { await fetch(url, {mode: 'no-cors'}); return false; } catch (_) { return true; }
    }, `http://sub.blocked.school.test:${port}/embedded`);
    assert.ok(denied, 'subdomain fetch should be blocked by the real Chromium rules');
    const fresh = await context.newPage();
    await assert.rejects(fresh.goto(`http://blocked.school.test:${port}/new`), /ERR_BLOCKED_BY_CLIENT/);
    const screenshot = process.env.BROWSER_SCREENSHOT;
    if (screenshot) await blockedPage.screenshot({path: screenshot});
    await worker.evaluate(() => websiteTest.apply({ok: true, enabled: true,
      domains: [], generation: 'free', version: '1.0.0'}));
    await blockedPage.getByRole('button', {name: 'Try the website again'}).click();
    await blockedPage.waitForURL(`http://blocked.school.test:${port}/watch`);
    await fresh.goto(`http://sub.blocked.school.test:${port}/new`);
    assert.equal(await fresh.locator('h1').textContent(), 'Local page');
    console.log('PASS: real Chromium request blocking, subdomains, existing-tab notice, unrelated tab preserved, Free Time retry.');
  } finally {
    if (context) await context.close();
    await new Promise(resolve => server.close(resolve));
    await fs.rm(root, {recursive: true, force: true});
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
