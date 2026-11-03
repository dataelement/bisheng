import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { copyFile, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

// Uses the real Client dialogs and Desktop native-view/preload contract with fixture services.
const project = resolve(import.meta.dirname, '..');
const desktop = process.env.DESKTOP_SOURCE && resolve(process.env.DESKTOP_SOURCE);
assert.ok(desktop, 'Set DESKTOP_SOURCE to a built BISHENG Desktop V1.2.0 checkout');
const client = join(project, 'src/frontend/client');
const output = resolve(process.argv[2] || 'outputs/desktop-dialog-overlay');
const desktopRequire = createRequire(join(desktop, 'package.json'));
const { build } = desktopRequire('esbuild');
const temporary = await mkdtemp(join(tmpdir(), 'bisheng-dialog-overlay-'));
await mkdir(output, { recursive: true });

const renderer = [
  "import React, { useState } from 'react';",
  "import { createRoot } from 'react-dom/client';",
  "import { Dialog, DialogContent, DialogTitle, DialogDescription } from './src/components/ui/Dialog';",
  "import { OGDialog, OGDialogContent, OGDialogTitle, OGDialogDescription } from './src/components/ui/OriginalDialog';",
  "import { AlertDialog, AlertDialogContent, AlertDialogTitle, AlertDialogDescription, AlertDialogCancel } from './src/components/ui/AlertDialog';",
  'window.dismissals = 0;',
  'function Fixture() {',
  '  const [kind, setKind] = useState(null); const [nested, setNested] = useState(false);',
  '  window.fixture = { open(next) { setKind(next); setNested(false); }, closeNested() { setNested(false); } };',
  '  const close = open => { if (!open) { window.dismissals++; setKind(null); } };',
  '  const actions = <><button onClick={() => close(false)}>Cancel</button><button onClick={() => setNested(true)}>Confirm</button></>;',
  '  return <><main><h2>Tools and skills</h2><button onClick={() => setKind("dialog")}>Upload skill</button></main><div aria-live="polite" />',
  '    {kind === "dialog" && <Dialog open onOpenChange={close}><DialogContent><DialogTitle>Upload skill</DialogTitle><DialogDescription>Actual Client dialog components</DialogDescription><input aria-label="Skill file" />{actions}</DialogContent></Dialog>}',
  '    {kind === "original" && <OGDialog open onOpenChange={close}><OGDialogContent><OGDialogTitle>Preview</OGDialogTitle><OGDialogDescription>Actual Client original dialog</OGDialogDescription>{actions}</OGDialogContent></OGDialog>}',
  '    {kind === "alert" && <AlertDialog open onOpenChange={close}><AlertDialogContent><AlertDialogTitle>Confirm</AlertDialogTitle><AlertDialogDescription>Actual Client confirmation</AlertDialogDescription><AlertDialogCancel>Cancel</AlertDialogCancel></AlertDialogContent></AlertDialog>}',
  '    {nested && <AlertDialog open onOpenChange={setNested}><AlertDialogContent><AlertDialogTitle>Nested confirmation</AlertDialogTitle><AlertDialogDescription>Parent dialog remains covered</AlertDialogDescription><AlertDialogCancel>Cancel</AlertDialogCancel></AlertDialogContent></AlertDialog>}',
  '  </>;',
  '}',
  'createRoot(document.getElementById("root")).render(<Fixture />);',
].join('\n');

async function nativeFixture(config, EnterpriseChatView) {
  const assert = require('node:assert/strict');
  const { createServer } = require('node:http');
  const { writeFile } = require('node:fs/promises');
  const { app, BrowserWindow, webContents } = require('electron');
  app.setPath('userData', config.profile);
  const pause = () => new Promise(resolve => setTimeout(resolve, 30));
  let context = 'startup';
  let inspect = async () => ({});
  async function until(check, step = 'presentation') {
    for (let index = 0; index < 200; index++) { if (await check()) return; await pause(); }
    await writeFile(config.output + '/failure.json', JSON.stringify({ context, step, ...await inspect() }, null, 2));
    throw new Error('Native presentation timed out: ' + context + ' / ' + step);
  }
  await app.whenReady();
  const server = createServer((request, response) => {
    const resource = request.url === '/fixture.js' ? ['application/javascript', config.renderer]
      : request.url === '/style.css' ? ['text/css', config.css] : ['text/html', config.html];
    response.writeHead(200, { 'Content-Type': resource[0] }); response.end(resource[1]);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  const window = new BrowserWindow({ width: 1084, height: 998, show: true,
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  await window.loadURL('data:text/html,' + encodeURIComponent('<body style="margin:0;background:#f6f7f8"><aside style="width:280px;padding:40px 20px">Conversation list<button onclick="window.sidebarClicks++">New conversation</button></aside><script>window.sidebarClicks=0</script>'));
  const service = { snapshot: () => ({ connected: true, connectionKey: 'fixture' }), subscribe: () => () => {},
    webSession: async () => ({ base, cookieName: 'fixture', cookie: 'fixture', expiresAt: Date.now() + 300000 }) };
  const host = new EnterpriseChatView(service, line => { if (line.includes('failed')) console.error(line); });
  const results = [];
  try {
    for (const width of [900, 1084]) for (const zoom of [0.8, 1, 1.25]) for (const theme of ['light', 'dark']) {
      context = JSON.stringify({ width, zoom, theme });
      window.setSize(width, 998); window.webContents.setZoomFactor(zoom);
      const [contentWidth, contentHeight] = window.getContentSize();
      const presentation = { visible: true, theme,
        bounds: { x: 280 / zoom, y: 40 / zoom, width: (contentWidth - 280) / zoom, height: (contentHeight - 40) / zoom } };
      host.present(window, presentation); await until(() => host.snapshot().phase === 'ready');
      const page = webContents.getAllWebContents().find(contents => contents !== window.webContents && contents.getURL().startsWith(base));
      assert.ok(page); page.setZoomFactor(zoom);
      await page.loadURL(base + '/workspace/capabilities?embed=dsh');
      await until(() => host.snapshot().phase === 'ready'); host.present(window, presentation);
      await until(() => page.executeJavaScript('!!window.fixture'));
      const view = window.contentView.children[0];
      inspect = async () => ({ bounds: view.getBounds(), snapshot: host.snapshot(), document: await page.executeJavaScript('({hidden:document.hidden,rootHidden:document.getElementById("root").getAttribute("aria-hidden"),dialogs:Array.from(document.querySelectorAll("[role=dialog],[role=alertdialog]")).map(e=>({role:e.getAttribute("role"),modal:e.getAttribute("aria-modal"),state:e.getAttribute("data-state"),visible:e.checkVisibility({checkVisibilityCSS:true})}))})') });
      const region = { x: 280, y: 40, width: contentWidth - 280, height: contentHeight - 40 };
      const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1, actual + ' != ' + expected);
      for (const kind of ['dialog', 'original', 'alert']) {
        context = JSON.stringify({ width, zoom, theme, kind });
        assert.deepEqual(view.getBounds(), region);
        await page.executeJavaScript('window.fixture.open(' + JSON.stringify(kind) + ')');
        await until(() => page.executeJavaScript('document.querySelectorAll("[role=dialog],[role=alertdialog]").length === 1'));
        assert.equal(await page.executeJavaScript('document.getElementById("root").getAttribute("aria-hidden")'), null, 'Live regions keep the root exposed');
        await until(() => view.getBounds().x === 0, 'window expansion');
        await page.executeJavaScript('Promise.all(document.getAnimations().filter(a => Number.isFinite(a.effect.getComputedTiming().endTime)).map(a => a.finished.catch(() => {})))');
        const state = await page.executeJavaScript('(() => { const rect = e => { const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}; };const mask=document.querySelector("[data-state=open][style*=background]");const dialog=document.querySelector("[role=dialog],[role=alertdialog]");return {root:rect(document.getElementById("root")),mask:rect(mask),background:getComputedStyle(mask).backgroundColor,opacity:getComputedStyle(mask).opacity,dialog:rect(dialog),dialogOpacity:getComputedStyle(dialog).opacity,dialogBackground:getComputedStyle(dialog).backgroundColor}; })()');
        assert.deepEqual(view.getBounds(), { x: 0, y: 0, width: contentWidth, height: contentHeight });
        close(state.root.x * zoom, 280); close(state.root.y * zoom, 40);
        close(state.mask.x, 0); close(state.mask.y, 0);
        close(state.mask.width * zoom, contentWidth); close(state.mask.height * zoom, contentHeight);
        assert.equal(state.background, 'rgba(0, 0, 0, 0.4)'); assert.equal(state.opacity, '1');
        assert.equal(state.dialogOpacity, '1'); assert.notEqual(state.dialogBackground, 'rgba(0, 0, 0, 0)');
        const capture = await page.capturePage(); const size = capture.getSize(); const pixels = capture.toBitmap();
        const pixel = (x, y) => {
          const offset = 4 * (Math.round(y * size.height / contentHeight) * size.width + Math.round(x * size.width / contentWidth));
          return [...pixels.subarray(offset, offset + 4)];
        };
        const sidebarPixel = pixel(20, 100);
        assert.ok(Math.abs(sidebarPixel[3] - 102) <= 1, 'Sidebar coordinates carry the 40% black overlay');
        assert.deepEqual(sidebarPixel.slice(0, 3), [0, 0, 0]);
        if (width === 1084 && zoom === 1) await writeFile(config.output + '/' + kind + '-' + theme + '.png', capture.toPNG());
        if (kind === 'dialog') {
          await page.executeJavaScript('Array.from(document.querySelectorAll("button")).find(button=>button.textContent==="Confirm").click()');
          await until(() => page.executeJavaScript('document.querySelectorAll("[role=dialog],[role=alertdialog]").length === 2'), 'nested confirmation open');
          await page.executeJavaScript('window.fixture.closeNested()');
          await until(() => page.executeJavaScript('document.querySelectorAll("[role=dialog],[role=alertdialog]").length === 1'), 'nested confirmation close');
          assert.equal(view.getBounds().x, 0);
        }
        // Native bounds/pixels and hit-testing prove window coverage. Component
        // tests cover Tab/Esc; OS input delivery requires an installed-app run.
        assert.equal(await page.executeJavaScript('document.elementFromPoint(30,100) === document.querySelector("[data-state=open][style*=background]")'), true);
        await page.executeJavaScript('Array.from(document.querySelectorAll("[role=dialog] button,[role=alertdialog] button")).find(button=>button.textContent==="Cancel").click()');
        await until(() => view.getBounds().x === 280, 'cancel restoration'); assert.deepEqual(view.getBounds(), region);
        results.push({ width, zoom, theme, kind, state, sidebarPixel });
        console.log('PASS', JSON.stringify({ width, zoom, theme, kind }));
      }
    }
    await writeFile(config.output + '/native-results.json', JSON.stringify({ platform: process.platform, electron: process.versions.electron,
      fixture: 'actual Client Dialog/OriginalDialog/AlertDialog with Desktop native view and production preload; fixture enterprise service; renderer DOM interaction events', results }, null, 2));
  } finally { host.dispose(); window.destroy(); server.close(); }
  app.exit(0);
}

try {
  const assets = join(client, 'build/assets');
  const cssFile = (await readdir(assets)).find(file => /^main[.-].*\.css$/.test(file));
  assert.ok(cssFile, 'Build the Client before running the native check');
  const bundled = await build({ stdin: { contents: renderer, resolveDir: client, loader: 'jsx' }, absWorkingDir: client,
    bundle: true, format: 'iife', write: false, tsconfig: join(client, 'tsconfig.json'),
    plugins: [{ name: 'fixture-utils', setup(builder) {
      builder.onResolve({ filter: /^(~\/utils|\.\.\/\.\.\/utils)$/ }, () => ({ path: 'utils', namespace: 'fixture' }));
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ contents: 'export const cn=(...values)=>values.filter(Boolean).join(" ");' }));
    } }] });
  await build({ entryPoints: [join(desktop, 'src/preload/enterprise-chat.ts')], outfile: join(temporary, 'preload/enterprise-chat.cjs'),
    bundle: true, platform: 'node', format: 'cjs', external: ['electron'] });
  if (process.env.DESKTOP_PRELOAD) await copyFile(resolve(process.env.DESKTOP_PRELOAD), join(temporary, 'preload/enterprise-chat.cjs'));
  const config = { output, profile: join(temporary, 'profile'), renderer: bundled.outputFiles[0].text,
    css: await readFile(join(assets, cssFile), 'utf8'),
    html: '<!doctype html><html><head><link rel="stylesheet" href="/style.css"><style>html,body{margin:0}#root{height:100vh;padding:30px;background:#fff;color:#222}.dark #root{background:#202124;color:#fff}</style></head><body><main id="root"></main><script src="/fixture.js"></script></body></html>' };
  const source = 'import { EnterpriseChatView } from "./src/main/enterprise/chat-view";(' + nativeFixture.toString() + ')(' + JSON.stringify(config) + ', EnterpriseChatView).catch(error=>{console.error(error);require("electron").app.exit(1)});';
  await build({ stdin: { contents: source, resolveDir: desktop, loader: 'ts' }, outfile: join(temporary, 'main/index.cjs'),
    bundle: true, platform: 'node', format: 'cjs', external: ['electron'], define: { 'import.meta.dirname': '__dirname' } });
  const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
  const child = spawn(desktopRequire('electron'), [join(temporary, 'main/index.cjs')], { env, stdio: 'inherit', signal: AbortSignal.timeout(180000) });
  const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('close', resolve); });
  assert.equal(code, 0, 'Native desktop dialog verification');
} finally { await rm(temporary, { recursive: true, force: true }); }
