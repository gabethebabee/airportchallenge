'use strict';

/* SECTION: Render the real dashboard assets against controlled HTTP fixtures.
 * Python builds the actual monitor/journey state without reaching the broker.
 * Playwright checks small-screen layout, preview freshness, form submission and
 * acknowledgement. This does not test the physical camera or optical decoding.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {execFileSync} = require('node:child_process');
const runtimeRoot = process.env.CODEX_PRIMARY_RUNTIME_ROOT || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime');
const {chromium} = require(path.join(runtimeRoot, 'dependencies/node/node_modules/playwright'));
const python = process.env.CODEX_PRIMARY_RUNTIME_PYTHON || path.join(runtimeRoot, 'dependencies/python/python.exe');
const state = JSON.parse(execFileSync(python, ['-c', `
import json
from team8conveyor4 import Conveyor4Monitor
from team8transit import TransitTracker
from team8vision import VisionInbox
now=[100.0]
m=Conveyor4Monitor(':memory:', {'current_topic':'actual/current'})
t=TransitTracker(':memory:', clock=lambda:now[0])
t.scan('apriltag:tag36h11:0','A','mqtt','fixture')
now[0]+=11
v=VisionInbox(t).snapshot()
v.update(fresh=True, age_seconds=0.1, tags_fresh=True,
         tags=[dict(family='tag36h11',tag_id=0,checkpoint='A')],publisher_status='Test camera')
s=m.snapshot()
s.update(vision=v,publish_error=None)
print(json.dumps(s))
m.close()
t.close()
`], {cwd:__dirname,encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
let jpeg;
const posts = [];

/* SECTION: An ephemeral localhost server serves only known assets and fake API
 * replies. All browser writes remain inside this test; they never reach MQTT or
 * the production dashboard. A canvas supplies a valid JPEG for image decoding.
 */
const server = http.createServer((req,res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  res.setHeader('Cache-Control','no-store');
  if (url.pathname === '/api/conveyor4') {
    res.setHeader('Content-Type','application/json');
    return res.end(JSON.stringify(state));
  }
  if (url.pathname === '/api/conveyor4/camera') {
    res.setHeader('Content-Type','image/jpeg');
    return res.end(jpeg);
  }
  if (url.pathname === '/api/conveyor/session') return res.end(JSON.stringify({token:'fixture'}));
  if (req.method === 'POST') {
    let body = '';
    req.on('data',chunk => {body += chunk;});
    req.on('end',() => {
      assert.equal(req.headers['x-team8-session'],'fixture');
      posts.push({path:url.pathname,body:JSON.parse(body)});
      res.end(JSON.stringify({message:'Fixture update accepted'}));
    });
    return;
  }
  const asset = url.pathname === '/' ? 'team8conveyor4.html' : url.pathname.slice(1);
  if (!['team8conveyor4.html','team8conveyor4.js','team8conveyor4.css','team8dashboard.css'].includes(asset)) {
    res.statusCode = 404; return res.end();
  }
  res.setHeader('Content-Type',asset.endsWith('.html') ? 'text/html; charset=utf-8' : asset.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/css');
  res.end(fs.readFileSync(path.join(__dirname,asset)));
});

/* SECTION: Check visible state and actual image decoding at the Jetson's likely
 * display sizes. The stale transition must remove the image while preserving
 * journey history, and narrow screens must wrap instead of scrolling sideways.
 */
async function main() {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  let browser;
  try {
    browser = await chromium.launch({executablePath:process.env.TEAM8_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror',error => errors.push(error.message));
    jpeg = Buffer.from(await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width=480; canvas.height=270;
      const context=canvas.getContext('2d'); context.fillStyle='#183d49'; context.fillRect(0,0,480,270);
      context.fillStyle='white'; context.font='24px sans-serif'; context.fillText('Test camera preview',30,140);
      return canvas.toDataURL('image/jpeg').split(',')[1];
    }), 'base64');
    for (const [width,height] of [[800,480],[1024,600],[480,800]]) {
      await page.setViewportSize({width,height});
      await page.goto('http://127.0.0.1:'+server.address().port);
      await page.locator('#c4visionPanel summary').first().click();
      await page.waitForFunction(() => document.querySelector('#c4cameraImage').naturalWidth > 0);
      assert.match(await page.locator('#c4tags').innerText(),/ID 0/);
      assert.match(await page.locator('#c4tagTrips').innerText(),/11.00 s/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    }
    await page.locator('[data-c4-tag-ack]').click();
    await page.waitForFunction(() => document.querySelector('#c4tagAction').textContent.includes('Fixture'));
    assert.equal(posts[0].path,'/api/conveyor4/tag-ack');
    await page.locator('#c4visionPanel details summary').click();
    await page.locator('#c4tagMax').fill('12');
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/transit/standard')),
      page.locator('#c4tagLimits button').click()
    ]);
    await page.waitForFunction(() => document.querySelector('#c4tagAction').textContent.includes('Fixture'));
    assert.equal(posts[1].body.maximum,12);
    if (process.argv.includes('--screenshot')) await page.screenshot({path:path.join(__dirname,'team8camera-review.png'),fullPage:true});
    state.vision.fresh=false; state.vision.tags_fresh=false; state.vision.tags=[];
    await page.waitForFunction(() => document.querySelector('#c4cameraImage').classList.contains('hidden'));
    assert.match(await page.locator('#c4cameraState').innerText(),/STALE/);
    assert.match(await page.locator('#c4tagTrips').innerText(),/11.00 s/);
    assert.deepEqual(errors,[]);
    console.log('Camera preview, tag timing/ack/settings, stale clearing and 3 small-screen layouts passed.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => {console.error(error); process.exitCode=1;});
