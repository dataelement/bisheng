import os from 'node:os';
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import {spawn} from 'node:child_process';import {createHash} from 'node:crypto';
const repo=process.cwd(),root=path.join(repo,'src/frontend'),scratch=fs.mkdtempSync(path.join(os.tmpdir(),'f089-browser-'));
const report=[];const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label,timeout=30000){const start=Date.now();for(;;){if(await check())return;if(Date.now()-start>timeout)throw new Error('Timeout: '+label);await pause(100);}}
const profile=path.join(scratch,'chrome-production');fs.mkdirSync(profile,{recursive:true});const portFile=path.join(profile,'DevToolsActivePort');if(fs.existsSync(portFile))fs.unlinkSync(portFile);
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore',fs.openSync(path.join(scratch,'chrome-production.log'),'a'),fs.openSync(path.join(scratch,'chrome-production.log'),'a')]});
let server,socket;
try{
 await until(()=>fs.existsSync(portFile),'production Chrome');const port=fs.readFileSync(portFile,'utf8').split('\n')[0];const pages=await(await fetch('http://127.0.0.1:'+port+'/json')).json();socket=new WebSocket(pages.find(page=>page.type==='page').webSocketDebuggerUrl);await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));
 let next=0;const pending=new Map();const exceptions=[];
 socket.addEventListener('message',event=>{const message=JSON.parse(event.data);if(message.id){const item=pending.get(message.id);pending.delete(message.id);message.error?item.reject(new Error(JSON.stringify(message.error))):item.resolve(message.result);}else if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails);});
 const cdp=(method,params={})=>new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
 const evaluate=async expression=>{const result=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
 await cdp('Runtime.enable');await cdp('Page.enable');
 for(const app of ['platform','client']){
  const base=app==='client'?'/workspace':'';const build=path.join(root,app,'build');
  server=http.createServer((req,res)=>{let name=decodeURIComponent((req.url||'/').split('?')[0]);if(base&&name.startsWith(base))name=name.slice(base.length)||'/';if(/^\/api\//.test(name)){res.statusCode=404;res.setHeader('Content-Type','application/json');res.end('{"status_code":404,"status_message":"offline fixture"}');return;}let file=path.join(build,name);if(!file.startsWith(build)){res.statusCode=400;res.end();return;}if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(build,'index.html');const type={'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.svg':'image/svg+xml','.wasm':'application/wasm','.png':'image/png','.woff2':'font/woff2','.webmanifest':'application/manifest+json'}[path.extname(file)]||'application/octet-stream';res.setHeader('Content-Type',type);res.end(fs.readFileSync(file));});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;exceptions.length=0;
  await cdp('Page.navigate',{url:origin+base+'/'});await until(()=>evaluate('document.readyState==="complete"&&document.querySelector("#root")?.children.length>0'),app+' production bootstrap',60000);await pause(1200);
  const js=[];function scan(folder){for(const entry of fs.readdirSync(folder,{withFileTypes:true})){const file=path.join(folder,entry.name);if(entry.isDirectory())scan(file);else if(file.endsWith('.js'))js.push(file);}}scan(build);
  const editor=js.find(file=>/vendor-editor-.*\.js$/.test(file));const highlights=app==='platform'&&editor?[editor]:js.filter(file=>/markdown_highlight[.-].*\.js$/.test(file));
  for(const file of highlights){const relative=path.relative(build,file).split(path.sep).join('/');const result=await evaluate(`import(${JSON.stringify(origin+base+'/'+relative)}).then(()=>({ok:true})).catch(error=>({ok:false,name:error.name,message:error.message}))`);if(!result.ok)throw new Error(app+' production highlight import: '+JSON.stringify(result));}
  const referenceErrors=exceptions.filter(item=>JSON.stringify(item).includes('ReferenceError')||JSON.stringify(item).includes('HighlightJS'));if(referenceErrors.length)throw new Error(app+' initialization: '+JSON.stringify(referenceErrors));
  const assets={};const manifest=JSON.parse(fs.readFileSync(path.join(root,'packages/diagram-runtime/assets/manifest.json'),'utf8'));
  for(const [name,item] of Object.entries(manifest)){const response=await fetch(origin+base+'/'+name);const hash=createHash('sha256').update(Buffer.from(await response.arrayBuffer())).digest('hex');if(hash!==item.sha256)throw new Error(app+' production resource mismatch: '+name);assets[name]=hash;}
  const html=fs.readFileSync(path.join(build,'index.html'),'utf8');const roots=[...html.matchAll(/<script\b([^>]*)>/g)].filter(match=>/type=["']module["']/.test(match[1])).map(match=>match[1].match(/src=["']([^"']+)["']/)?.[1]).filter(Boolean).map(file=>path.join(build,file.replace(base,'').replace(/^\//,'')));
  const reachable=new Set();function follow(file){if(reachable.has(file)||!fs.existsSync(file))return;reachable.add(file);const text=fs.readFileSync(file,'utf8');for(const match of text.matchAll(/(?:^|[;\n])\s*(?:import|export)\s*(?:[^;()]*?\bfrom\s*)?["']([^"']+\.js)["']/g)){if(match[1].startsWith('.'))follow(path.resolve(path.dirname(file),match[1]));}}roots.forEach(follow);
  const firstScreenHeavy=[...reachable].filter(file=>/vendor-pdf|mammoth|DocxViewer|pdfjs/i.test(path.basename(file))).map(file=>path.basename(file));
  report.push({app,productionBootstrap:true,highlightModules:highlights.map(file=>path.basename(file)),referenceErrors:0,exceptions:structuredClone(exceptions),assets,firstScreenHeavy,firstScreenModules:reachable.size});
  await new Promise(resolve=>server.close(resolve));server=null;
 }
 fs.writeFileSync(path.join(scratch,'production-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({report,outputDirectory:scratch}));
}catch(error){fs.writeFileSync(path.join(scratch,'production-report.json'),JSON.stringify({report,error:String(error)},null,2));console.error(error);process.exitCode=1;}
finally{server?.close();socket?.close();chrome.kill();}
