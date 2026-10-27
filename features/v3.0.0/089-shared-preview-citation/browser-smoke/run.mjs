import os from 'node:os';import {fileURLToPath} from 'node:url';
import fs from 'node:fs';import path from 'node:path';import {spawn} from 'node:child_process';import {createHash} from 'node:crypto';import http from 'node:http';
const repo=process.cwd(),frontend=path.join(repo,'src/frontend'),scratch=fs.mkdtempSync(path.join(os.tmpdir(),'f089-browser-'));
const helper=path.dirname(fileURLToPath(import.meta.url));
const dependencyRoot=fs.realpathSync(path.join(frontend,'node_modules/vite')).split('/.pnpm/')[0];
const vite=await import(path.join(frontend,'node_modules/vite/dist/node/index.js'));
const report={fixtures:[],production:[],exceptions:[],screenshots:[]};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label,timeout=30000){const start=Date.now();for(;;){if(await check())return;if(Date.now()-start>timeout)throw new Error('Timeout: '+label);await pause(100);}}
const chromeDir=path.join(scratch,'chrome-profile');fs.mkdirSync(chromeDir,{recursive:true});
const oldPort=path.join(chromeDir,'DevToolsActivePort');if(fs.existsSync(oldPort))fs.unlinkSync(oldPort);
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--autoplay-policy=no-user-gesture-required','--remote-debugging-port=0','--user-data-dir='+chromeDir,'about:blank'],{stdio:['ignore',fs.openSync(path.join(scratch,'chrome.log'),'a'),fs.openSync(path.join(scratch,'chrome.log'),'a')]});
let socket;let server;let production;const harnesses=[];
try{
 await until(()=>fs.existsSync(path.join(chromeDir,'DevToolsActivePort')),'Chrome devtools');
 const [port]=fs.readFileSync(path.join(chromeDir,'DevToolsActivePort'),'utf8').split('\n');
 const targets=await(await fetch('http://127.0.0.1:'+port+'/json')).json();socket=new WebSocket(targets.find(item=>item.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
 let next=0;const pending=new Map();const exceptions=[];
 socket.addEventListener('message',event=>{const message=JSON.parse(event.data);if(message.method==='Runtime.exceptionThrown')console.error('Browser exception',JSON.stringify(message.params.exceptionDetails));if(message.id){const item=pending.get(message.id);pending.delete(message.id);if(message.error)item?.reject(new Error(JSON.stringify(message.error)));else item?.resolve(message.result);}else if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails);});
 const cdp=(method,params={})=>new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
 const evaluate=async expression=>{const response=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(response.exceptionDetails)throw new Error(JSON.stringify(response.exceptionDetails));return response.result.value;};
 await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Network.enable');
 const select=async mode=>{await evaluate(`document.querySelector('[data-case="${mode}"]').click()`);await until(()=>evaluate(`window.__checks.mode===${JSON.stringify(mode)}`),mode);};
 const assert=async(expression,label)=>{const value=await evaluate(expression);if(!value)throw new Error(label+' failed: '+JSON.stringify(value));};
 for(const app of ['platform','client']){
  const base=app==='client'?'/workspace':'';const appRoot=path.join(frontend,app);process.chdir(appRoot);
  let source=fs.readFileSync(path.join(helper,'harness-template.tsx'),'utf8');
  source=source.replace('__HOST_CSS__',app==='client'?"import './src/style.css';import './src/mobile.css';":"import './src/style/index.css';");
  source=source.replace('__PLATFORM_IMPORT__',app==='platform'?"import {PlatformPdfPreview} from './src/components/bs-comp/preview/PlatformPdfPreview';":'');
  source=source.replace('__PLATFORM_EDITOR__',app==='platform'?`<PlatformPdfPreview fileUrl={url('mixed.pdf')} startIndex={0} select labels={labels} onSelectLabel={rows=>{global.__checks.selections.push(rows);setActive(value=>!value);}}/>`:'<span>platform editing only</span>');
  const harness=path.join(appRoot,'.f089-browser-harness.tsx');if(fs.existsSync(harness))throw new Error('Existing fixture entry: '+harness);fs.writeFileSync(harness,source);harnesses.push(harness);
  const loaded=await vite.loadConfigFromFile({command:'serve',mode:'development'},path.join(appRoot,app==='client'?'vite.config.ts':'vite.config.mts'));const configured=(await Promise.all(loaded.config.plugins.flat(Infinity))).filter(plugin=>plugin&&!['vite:html','vite:minify-html'].includes(plugin.name));
  server=await vite.createServer({...loaded.config,configFile:false,root:appRoot,cacheDir:path.join(scratch,'cache-'+app),logLevel:'error',optimizeDeps:{...loaded.config.optimizeDeps,entries:[harness]},server:{host:'127.0.0.1',port:0,strictPort:false,fs:{allow:[repo,dependencyRoot]}},plugins:[...configured,{name:'f089-fixtures',enforce:'pre',configureServer(instance){instance.middlewares.use(async(req,res,next)=>{const name=(req.url||'').split('?')[0];const normalized=base&&name.startsWith(base)?name.slice(base.length):name;
   if(normalized==='/__f089__/'){const html=`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from '${base}/@react-refresh';RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>(type)=>type;window.__vite_plugin_react_preamble_installed__=true;</script><script type="module" src="${base}/@vite/client"></script></head><body><div id="root"></div><script type="module" src="${base}/.f089-browser-harness.tsx"></script></body></html>`;res.setHeader('Content-Type','text/html');res.end(html);return;}
   if(normalized.startsWith('/__f089__/fixtures/')){const file=path.join(helper,'fixtures',path.basename(normalized));if(!fs.existsSync(file)){res.statusCode=404;res.end('missing');return;}const ext=path.extname(file);res.setHeader('Content-Type',ext==='.pdf'?'application/pdf':ext==='.wav'?'audio/wav':ext==='.svg'?'image/svg+xml':ext==='.docx'?'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'text/plain');res.end(fs.readFileSync(file));return;}next();});}}]});
  await server.listen();const address=server.httpServer.address();const origin='http://127.0.0.1:'+address.port;exceptions.length=0;
  for(const relative of ['packages/file-viewers/src/viewers/MarkdownViewer.tsx','packages/file-viewers/src/usePreviewResource.ts']){
   const response=await fetch(origin+base+'/@fs'+path.join(frontend,relative));
   if(!response.ok)throw new Error(app+' shared source transform failed: '+relative+' HTTP '+response.status);
  }
  await cdp('Page.navigate',{url:origin+base+'/__f089__/'});await until(()=>evaluate('!!document.querySelector("[data-ready]")'),app+' fixture boot',30000);
  await until(()=>evaluate('document.querySelectorAll("canvas").length===2&&Array.from(document.querySelectorAll("canvas")).every(item=>item.width>0)'),app+' real PDF canvas');
  await until(()=>evaluate('(()=>{const canvas=document.querySelector("canvas");const data=canvas.getContext("2d").getImageData(0,0,canvas.width,canvas.height).data;for(let i=0;i<data.length;i+=4){if(data[i+3]===255&&data[i]<220&&data[i+1]<220&&data[i+2]<220)return true;}return false;})()'),'real PDF text paint');
  const dimensions=await evaluate('Array.from(document.querySelectorAll("canvas")).map(item=>({width:item.width,height:item.height}))');if(!(dimensions[0].height>dimensions[0].width&&dimensions[1].height<dimensions[1].width))throw new Error('Mixed PDF aspect ratios lost');
  const shot=await cdp('Page.captureScreenshot',{format:'png'});const shotPath=path.join(scratch,app+'-pdf.png');fs.writeFileSync(shotPath,Buffer.from(shot.data,'base64'));report.screenshots.push(shotPath);
  await evaluate('document.querySelector("[data-zoom]").click()');await until(()=>evaluate('document.querySelector("canvas").style.width.includes("1251")||parseFloat(document.querySelector("canvas").style.width)>900'),app+' PDF zoom');
  if(app==='platform'){
   await select('edit');await until(()=>evaluate('!!document.querySelector("[data-pdf-page] rect")'),'PDF edit overlay');
   const box=await evaluate('(()=>{const box=document.querySelector("[data-pdf-page] rect").getBoundingClientRect();return{x:box.x+box.width/2,y:box.y+box.height/2};})()');
   await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,...box});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,...box});await assert('window.__checks.selections.length===1','real label click');
   const bounds=await evaluate('(()=>{const r=document.querySelector("[data-pdf-page]").getBoundingClientRect();return{x:r.x,y:r.y};})()');
   await cdp('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,x:bounds.x+5,y:bounds.y+5});await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',button:'left',buttons:1,x:bounds.x+450,y:bounds.y+250});await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,x:bounds.x+450,y:bounds.y+250});await assert('window.__checks.selections.length===2','real box selection');
  }
  await select('docx');await until(()=>evaluate('document.querySelector("[data-viewer]").textContent.includes("Shared DOCX target")'),'real DOCX conversion');
  await select('markdown');await until(()=>evaluate('!!document.querySelector("pre code")'),'markdown code');await assert('document.querySelector("pre code").textContent==="def sample():\\n    return 42\\n"','exact code newlines');
  await select('csv');await until(()=>evaluate('document.querySelector("[data-viewer]").textContent.includes("Alpha")'),'real CSV parser');
  await select('html');await until(()=>evaluate('window.__checks.sandbox?.isolated===true&&window.__checks.sandbox?.storage==="ok"'),'opaque HTML sandbox');
  await select('image');await until(()=>evaluate('document.querySelector("[data-viewer] img")?.naturalWidth>0'),'real image');
  await select('media');await until(()=>evaluate('document.querySelector("audio")?.readyState>=2'),'audio loaded');await evaluate('document.querySelector("audio").play()');await until(()=>evaluate('document.querySelector("audio").currentTime>0'),'actual audio playback');
  await select('reference');await until(()=>evaluate('document.querySelectorAll("[data-cite-hit]").length>0'),'real DOCX citation locating');
  await select('diagrams');await until(()=>evaluate('!!document.querySelector("[data-chart] canvas")&&!!document.querySelector("[data-mermaid] svg")'),'real charts',30000);await assert('window.__checks.dedup===true','diagram script deduplication');
  await select('failed');await until(()=>evaluate('document.querySelector("[data-viewer]").textContent.includes("Failed to load file")'),'friendly failure');
  for(const language of ['zh-Hans','ja','en']){await evaluate(`document.querySelector('[data-lang="${language}"]').click()`);await pause(80);await assert('!document.querySelector("[data-viewer]").textContent.includes("shared:")','localized failure '+language);}
  await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await assert('document.documentElement.scrollWidth<=window.innerWidth+1','narrow viewport width');await cdp('Emulation.clearDeviceMetricsOverride');
  const visibleErrors=await evaluate('window.__checks.errors');if(visibleErrors.length||exceptions.length)throw new Error(app+' runtime errors: '+JSON.stringify({visibleErrors,exceptions}));
  const manifest=JSON.parse(fs.readFileSync(path.join(frontend,'packages/diagram-runtime/assets/manifest.json'),'utf8'));for(const [name,item]of Object.entries(manifest)){const response=await fetch(origin+base+'/'+name);const hash=createHash('sha256').update(Buffer.from(await response.arrayBuffer())).digest('hex');if(hash!==item.sha256)throw new Error('Dev asset mismatch '+name);}
  report.fixtures.push({app,pdf:dimensions,passed:['canvas','zoom','docx','markdown-newlines','csv','sandbox','image','audio-playback','citation-locate','charts','dedup','3-locales','narrow'],exceptions:exceptions.length});
  await server.close();server=null;
 }
 fs.writeFileSync(path.join(scratch,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({report,outputDirectory:scratch}));
}catch(error){report.error=String(error);fs.writeFileSync(path.join(scratch,'report.json'),JSON.stringify(report,null,2));console.error(error);process.exitCode=1;
}finally{socket?.close();chrome.kill();for(const file of harnesses){if(fs.existsSync(file))fs.unlinkSync(file);}server?.httpServer?.closeAllConnections();await server?.close();production?.close();process.chdir(repo);}
