import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

// Actual preview, router, preload and native host; account/data calls use synthetic fixtures.
const project = resolve(import.meta.dirname, '..');
const client = join(project, 'src/frontend/client');
const desktop = process.env.DESKTOP_SOURCE && resolve(process.env.DESKTOP_SOURCE);
assert.ok(desktop, 'Set DESKTOP_SOURCE to a BISHENG Desktop V1.2.0 checkout');
const output = resolve(process.argv[2] || 'tmp/knowledge-square-navigation');
const requireDesktop = createRequire(join(desktop, 'package.json'));
const { build } = requireDesktop('esbuild');
const temporary = await mkdtemp(join(tmpdir(), 'bisheng-square-'));
await mkdir(output, { recursive: true });
const renderer = `
import React, { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, useLocation } from 'react-router-dom';
import { KnowledgeSquarePane } from './src/pages/knowledge/KnowledgeSquarePane';
import { useDesktopNavigation } from './src/components/Chat/useDesktopNavigation';
function Fixture() {
  useDesktopNavigation();
  const location = useLocation();
  useEffect(() => {
    window.dshChatPresentation?.reportNavigation({ entries: [{ id: 'square', path: '/square', label: 'Discover', active: true, primary: true }] });
  }, [location]);
  return <KnowledgeSquarePane />;
}
createRoot(document.getElementById('root')).render(<BrowserRouter basename="/workspace"><Fixture /></BrowserRouter>);
`;
const fixtures = {
  '~/hooks': `import { useRef } from 'react'; export { default as usePrefersMobileLayout } from './src/hooks/usePrefersMobileLayout'; export const useScrollRevealRef=()=>useRef(null); const labels={'com_ui_go_back':'返回','com_knowledge.join':'加入','com_knowledge.joined':'已加入','com_knowledge.pending':'待审核','com_knowledge.all_files':'全部文件','com_knowledge.space_view_requires_approval':'该知识空间内容申请通过后方可查看','com_knowledge.articles_count':'篇内容','com_knowledge.users_count':'用户'}; export const useLocalize=()=>key=>labels[key]||key;`,
  '~/hooks/useEffectiveQuota': 'export const useEffectiveQuota=()=>({isOverQuota:()=>false});',
  '~/components/illustrations': 'import React from "react";import { LockKeyhole } from "lucide-react";export const EmptyStateIllustration=()=>null;export const NoPermissionIllustration=()=> <LockKeyhole size={100} color="#165dff"/>;',
  '~/components/ui/icon/Loading': 'export const LoadingIcon=()=>null;',
  '~/Providers': 'export const useToastContext=()=>({showToast:()=>{}});',
  '~/common': 'export const NotificationSeverity={WARNING:"warning"};',
  '~/utils': 'import clsx from "clsx"; import { twMerge } from "tailwind-merge"; export const cn=(...args)=>twMerge(clsx(args));',
  '~/api/permission': 'export const checkResourceAction=async()=>({allowed:new URLSearchParams(location.search).get("scenario")==="joined"});',
  '~/api/knowledge': `export const SpaceRole={MEMBER:'member',CREATOR:'creator',ADMIN:'admin'};export const VisibilityType={PUBLIC:'public',APPROVAL:'approval',PRIVATE:'private'};export const SPACE_CHILDREN_STATUS_SUCCESS_ONLY=[1];export const getSpaceInfoApi=async()=>{const scenario=new URLSearchParams(location.search).get('scenario');return {id:'77',name:scenario==='pending-long'?'知识空间详情长标题与操作区布局验证'.repeat(4):'授权审核加入',description:scenario==='pending-long'?'空间说明用于验证长标题、摘要和操作按钮的布局。':undefined,creator:'Fixture owner',visibility:'approval',role:'member',fileCount:0,memberCount:1,subscriptionStatus:scenario==='joined'?'subscribed':scenario==='pending-long'?'pending':'not_subscribed'};};export const getJoinedSpacesApi=async()=>[];export const getSpaceChildrenApi=async()=>({data:[],total:0});export const subscribeSpaceApi=async()=>({status:'pending'});export const unsubscribeSpaceApi=async()=>({});`,
  './SpaceDetail/FileCard': 'export const FileCard=()=>null;',
  './KnowledgeSquare': `import React from 'react';export default function Square({onPreviewSpace}){return <div style={{padding:32}}><h1>发现广场 · 知识空间</h1><input aria-label="Search" placeholder="搜索知识空间"/><button id="open-space" onClick={()=>onPreviewSpace({id:'77',name:'授权审核加入',visibility:'approval',role:'member',fileCount:0,memberCount:1})}>授权审核加入</button></div>}`,
};

async function nativeFixture(config, EnterpriseChatView) {
  const { app, BrowserWindow, webContents } = require('electron');
  const { createServer } = require('node:http');
  const { writeFile } = require('node:fs/promises');
  const assert = require('node:assert/strict');
  app.setPath('userData', config.profile);
  let context;
  const until = async check => {
    for (let i=0;i<160;i++) { if (await check()) return; await new Promise(r=>setTimeout(r,40)); }
    throw new Error('Timeout: '+JSON.stringify(context));
  };
  app.on('web-contents-created', (_event, contents) => contents.on('console-message', (_event, level, message) => { if (level >= 2) console.error('[renderer]', message); }));
  await app.whenReady();
  const server = createServer((req,res)=>{
    const data = req.url === '/fixture.js' ? ['application/javascript',config.renderer]
      : req.url === '/style.css' ? ['text/css',config.css] : ['text/html',config.html];
    res.writeHead(200, {'Content-Type':data[0]+'; charset=utf-8'});res.end(data[1]);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const base='http://127.0.0.1:'+server.address().port;
  const win=new BrowserWindow({width:1280,height:900,show:true,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
  await win.loadURL('data:text/html,<body style="margin:0;background:%23f6f7f8"><aside style="padding:50px 20px">BISHENG<br>Discover</aside>');
  const service={snapshot:()=>({connected:true,connectionKey:'fixture'}),subscribe:()=>()=>{},webSession:async()=>({base,cookieName:'fixture',cookie:'fixture',expiresAt:Date.now()+300000})};
  const host=new EnterpriseChatView(service,line=>console.log('[host]',line));
  const results=[];
  try {
    for (const scenario of ['joined','pending-long','join']) for (const width of [900,1280,1600]) for (const zoom of [1,1.25,1.5]) for (const theme of ['light','dark']) {
      context={scenario,width,zoom,theme};
      win.setSize(width,900);win.webContents.setZoomFactor(zoom);
      const [cw,ch]=win.getContentSize();
      host.present(win,{visible:true,theme,bounds:{x:280/zoom,y:40/zoom,width:(cw-280)/zoom,height:(ch-40)/zoom}});
      context.step='host-ready'; await until(()=>host.snapshot().phase==='ready');
      const page=webContents.getAllWebContents().find(w=>w!==win.webContents&&w.getURL().startsWith(base));
      assert.ok(page);page.setZoomFactor(zoom);
      await page.loadURL(base+'/workspace/square?embed=dsh&scenario='+scenario);
      context.step='square-mounted'; await until(()=>page.executeJavaScript('!!document.querySelector("#open-space")'));
      context.step='navigation-reported'; await until(()=>host.snapshot().navigation?.entries.some(e=>e.id==='square'));
      const open=async()=>{
        await page.executeJavaScript('document.querySelector("#open-space").click()');
        await until(()=>page.executeJavaScript('!!document.querySelector("[role=dialog]")'));
        await page.executeJavaScript('Promise.all(document.getAnimations().filter(a=>Number.isFinite(a.effect.getComputedTiming().endTime)).map(a=>a.finished.catch(()=>{})))');
      };
      await open();
      assert.equal(new URL(page.getURL()).searchParams.get('previewSpace'),'77');
      const bounds=await page.executeJavaScript(`(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent==='返回');const d=document.querySelector('[role=dialog]');const r=b?.getBoundingClientRect();const p=d.getBoundingClientRect();return {back:!!b,x:r?.x,y:r?.y,right:r?.right,bottom:r?.bottom,viewport:innerWidth,height:innerHeight,dialogX:p.x,dialogRight:p.right};})()`);
      assert.ok(bounds.back);assert.ok(bounds.x>=0&&bounds.y>=0&&bounds.right<=bounds.viewport&&bounds.bottom<=bounds.height,JSON.stringify(bounds));
      assert.ok(bounds.dialogX>=-1&&bounds.dialogRight<=bounds.viewport+1,JSON.stringify(bounds));
      const layout=await page.executeJavaScript(`(()=>{
        const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
        const d=document.querySelector('[role=dialog]'), header=d.querySelector('[data-slot=sheet-header]');
        const back=[...d.querySelectorAll('button')].find(b=>b.textContent==='返回');
        const title=header.querySelector('[data-slot=sheet-title]'), action=header.querySelector('button');
        const files=[...d.querySelectorAll('button')].find(b=>b.textContent==='全部文件');
        return {icon:rect(back.querySelector('svg')),back:rect(back),title:rect(title),action:rect(action),header:rect(header),files:files?rect(files):null,scrollWidth:d.scrollWidth,clientWidth:d.clientWidth};
      })()`);
      assert.ok(Math.abs(layout.icon.x-layout.title.x)<=1,JSON.stringify(layout));
      assert.ok(Math.abs(layout.title.y-layout.back.bottom-16)<=1,JSON.stringify(layout));
      assert.ok(Math.abs(layout.action.y-layout.title.y)<=1,JSON.stringify(layout));
      assert.ok(layout.title.right+15<=layout.action.x,JSON.stringify(layout));
      assert.ok(layout.scrollWidth<=layout.clientWidth+1,JSON.stringify(layout));
      if (scenario==='joined') {
        assert.ok(layout.files,JSON.stringify(layout));
        assert.ok(Math.abs(layout.files.x-layout.title.x)<=1,JSON.stringify(layout));
        assert.ok(Math.abs(layout.files.y-layout.header.bottom-16)<=1,JSON.stringify(layout));
      }
      if (zoom===1) await writeFile(config.output+'/'+scenario+'-'+width+'-'+theme+'.png',(await page.capturePage()).toPNG());
      // Actual native host openPage, including its same-URL early return.
      await host.openPage('square');
      await until(()=>page.executeJavaScript('document.querySelector("[role=dialog]")===null'));
      assert.equal(new URL(page.getURL()).pathname,'/workspace/square');
      await open();
      await page.executeJavaScript('[...document.querySelectorAll("button")].find(b=>b.textContent==="返回").click()');
      await until(()=>page.executeJavaScript('document.querySelector("[role=dialog]")===null'));
      assert.equal(new URL(page.getURL()).searchParams.has('previewSpace'),false);
      results.push({...context,bounds,layout,hostReturn:true,headerReturn:true});
    }
    const browserResults=[];
    const browser=new BrowserWindow({width:1400,height:900,show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
    try {
      for (const width of [390,900,1400]) {
        browser.setSize(width,900);
        await browser.loadURL(base+'/workspace/square?scenario=joined');
        await until(()=>browser.webContents.executeJavaScript('!!document.querySelector("#open-space")'));
        await browser.webContents.executeJavaScript('document.querySelector("#open-space").click()');
        await until(()=>browser.webContents.executeJavaScript('!!document.querySelector("[data-slot=sheet-header]")'));
        await browser.webContents.executeJavaScript('Promise.all(document.getAnimations().filter(a=>Number.isFinite(a.effect.getComputedTiming().endTime)).map(a=>a.finished.catch(()=>{})))');
        const layout=await browser.webContents.executeJavaScript(`(()=>{
          const d=document.querySelector('[role=dialog]'),h=d.querySelector('[data-slot=sheet-header]');
          const a=h.querySelector('button').getBoundingClientRect(),t=h.querySelector('[data-slot=sheet-title]').getBoundingClientRect();
          const c=d.querySelector('button[aria-label]'),r=c.getBoundingClientRect();
          return {close:c.getAttribute('aria-label'),closeBottom:r.bottom,actionTop:a.y,titleTop:t.y,titleRight:t.right,actionLeft:a.x,scrollWidth:d.scrollWidth,clientWidth:d.clientWidth};
        })()`);
        assert.ok(layout.scrollWidth<=layout.clientWidth+1,JSON.stringify(layout));
        assert.ok(layout.titleRight+15<=layout.actionLeft,JSON.stringify(layout));
        if (width<768) assert.ok(layout.closeBottom<=layout.titleTop,JSON.stringify(layout));
        await writeFile(config.output+'/browser-'+width+'.png',(await browser.webContents.capturePage()).toPNG());
        await browser.webContents.executeJavaScript('document.querySelector("[role=dialog] button[aria-label]").click()');
        await until(()=>browser.webContents.executeJavaScript('document.querySelector("[role=dialog]")===null'));
        browserResults.push({width,layout,close:true});
      }
    } finally {browser.destroy();}
    await writeFile(config.output+'/electron-results.json',JSON.stringify({platform:process.platform,electron:process.versions.electron,results,browserResults},null,2));
    console.log('PASS: '+results.length+' native host/layout/navigation cases and '+browserResults.length+' browser layouts');
  } finally {host.dispose();win.destroy();server.close();}
  app.exit(0);
}
try {
  const assets=join(client,'build/assets');
  const cssFile=(await readdir(assets)).find(f=>/^main[.-].*\.css$/.test(f));
  assert.ok(cssFile,'Build Client first');
  const rendererBuild=await build({stdin:{contents:renderer,resolveDir:client,loader:'jsx'},absWorkingDir:client,jsx:'automatic',bundle:true,format:'iife',write:false,define:{'import.meta.env':'{"DEV":false}','__APP_ENV__':'{"BASE_URL":""}'},tsconfig:join(client,'tsconfig.json'),plugins:[{name:'fixture-services',setup(b){
    b.onResolve({filter:/.*/},args=>Object.hasOwn(fixtures,args.path)?{path:args.path,namespace:'fixture'}:undefined);
    b.onLoad({filter:/.*/,namespace:'fixture'},args=>({contents:fixtures[args.path],resolveDir:client,loader:'jsx'}));
  }}]});
  await build({entryPoints:[join(desktop,'src/preload/enterprise-chat.ts')],outfile:join(temporary,'preload/enterprise-chat.cjs'),bundle:true,platform:'node',format:'cjs',external:['electron']});
  const config={output,profile:join(temporary,'profile'),renderer:rendererBuild.outputFiles[0].text,css:await readFile(join(assets,cssFile),'utf8'),html:'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/style.css"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>'};
  const source='import { EnterpriseChatView } from "./src/main/enterprise/chat-view";('+nativeFixture.toString()+')('+JSON.stringify(config)+',EnterpriseChatView).catch(e=>{console.error(e);require("electron").app.exit(1)});';
  await build({stdin:{contents:source,resolveDir:desktop,loader:'ts'},outfile:join(temporary,'main/index.cjs'),bundle:true,platform:'node',format:'cjs',external:['electron'],define:{'import.meta.dirname':'__dirname'}});
  const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;
  const child=spawn(requireDesktop('electron'),[join(temporary,'main/index.cjs')],{env,stdio:'inherit',signal:AbortSignal.timeout(300000)});
  assert.equal(await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);}),0);
} finally {await rm(temporary,{recursive:true,force:true});}
