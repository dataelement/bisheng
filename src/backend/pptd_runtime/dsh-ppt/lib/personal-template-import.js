import { fork } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

/** Execute one authorized template import in its own bounded V8 process. The
 * upload and draft paths are selected by the library, and the parent owns audit.
 * Only progress and the resulting preview metadata cross IPC; source assets
 * stay in the host-owned library on disk.
 */
export function runPersonalTemplateImport(job,onProgress,{timeoutMs=600000,maxHeapMiB=1536,signal}={}) {
  if(!job||!path.isAbsolute(job.root)||typeof job.sessionId!=='string'||!job.sessionId||![job.uploadId,job.draftId].every(id=>/^[a-f0-9-]{36}$/.test(id))||!Number.isSafeInteger(job.maxSlides)||job.maxSlides<1||job.maxSlides>200)throw new Error('模板处理任务无效');
  if(!Number.isSafeInteger(timeoutMs)||timeoutMs<1||!Number.isSafeInteger(maxHeapMiB)||maxHeapMiB<32||maxHeapMiB>1536)throw new Error('模板处理预算无效');
  signal?.throwIfAborted();
  return new Promise((resolve,reject)=>{
    const child=fork(fileURLToPath(new URL('./personal-template-worker.js',import.meta.url)),[],{
      execArgv:[`--max-old-space-size=${maxHeapMiB}`],
      env:{...process.env,ELECTRON_RUN_AS_NODE:'1'},
      stdio:['ignore','ignore','pipe','ipc']
    });
    let outcome,error,stderr='',stopTimer,memoryExceeded=false;
    const stop=()=>{
      if(stopTimer)return;
      // The worker propagates cancellation through Office before disconnecting.
      if(child.connected)child.send({type:'cancel'},()=>{});
      stopTimer=setTimeout(()=>child.kill('SIGKILL'),5000);
    };
    const abort=()=>{error=signal.reason;stop();};
    signal?.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(()=>{error=new Error('模板处理超时，请减少复杂图形或分拆页面后重试。');stop();},timeoutMs);
    child.stderr.on('data',chunk=>{const text=stderr+chunk.toString();memoryExceeded ||= /heap out of memory|allocation failed/i.test(text);stderr=text.slice(-8192);});
    child.on('message',message=>{
      if(error)return;
      if(message?.type==='progress')onProgress?.(message.value);
      else if(message?.type==='result')outcome=message.value;
      else if(message?.type==='error') {error=new Error(message.message);if(message.conversion)error.conversion=message.conversion;}
    });
    child.once('error',cause=>{error=cause;});
    child.once('close',code=>{
      clearTimeout(timer);clearTimeout(stopTimer);
      signal?.removeEventListener('abort',abort);
      if(error)reject(error);
      else if(code===0&&outcome)resolve(outcome);
      else reject(new Error(memoryExceeded
        ? '模板复杂图形超出处理内存预算，请减少复杂矢量图或分拆页面后重试。'
        : '模板处理进程已结束，请重新上传后重试。'));
    });
    child.send(job,cause=>{if(cause){error=cause;stop();}});
  });
}
