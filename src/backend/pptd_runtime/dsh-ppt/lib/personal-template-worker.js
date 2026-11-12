import { mkdir,writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath,pathToFileURL } from 'node:url';

// Native Office tools live beside app.asar. Reuse the Desktop's engine resolver
// in this process before importing the Office preview module.
const core=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const archive=path.dirname(path.dirname(core));
if(path.basename(archive)==='app.asar') {
  const {registerOfficeEngineResolution}=await import(pathToFileURL(path.join(path.dirname(archive),'office-engine-resolution.mjs')));
  registerOfficeEngineResolution(path.join(archive,'node_modules','@deepseek-ai','dsh','lib','bin.js'));
}
const {PersonalTemplateLibrary}=await import('./personal-templates.js');
const {convertPptxToPptd}=await import('./pptx-converter.js');

async function writeSource(directory,source) {
  const put=async (relative,bytes)=>{
    if(!/^[A-Za-z0-9_./-]+$/.test(relative)||relative.split('/').some(part=>!part||part==='.'||part==='..'))throw new Error('模板输出路径无效');
    const target=path.join(directory,relative);await mkdir(path.dirname(target),{recursive:true,mode:0o700});
    await writeFile(target,bytes,{flag:'wx',mode:0o600});
  };
  await put(source.entryName,source.manifest);
  for(const [relative,content] of source.pages)await put(relative,content);
  for(const asset of source.assets.values())await put(asset.path,asset.bytes);
}
const controller=new AbortController();
process.on('message',message=>{if(message?.type==='cancel')controller.abort();});
process.once('message',async job=>{
  if(job?.type==='cancel')return;
  try {
    const library=new PersonalTemplateLibrary({root:job.root},convertPptxToPptd,writeSource,job.maxSlides);
    const report=value=>process.send?.({type:'progress',value});
    const result=await library.prepareSource(job.sessionId,{uploadId:job.uploadId,draftId:job.draftId},report,controller.signal);
    process.send?.({type:'result',value:result},()=>process.disconnect());
  } catch(error) {
    process.send?.({type:'error',message:error.message,conversion:error.conversion},()=>process.disconnect());
  }
});
