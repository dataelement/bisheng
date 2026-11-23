import { createHash, randomUUID } from 'node:crypto';
import { cp, lstat, mkdir, readFile, readdir, realpath, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';
import { runPersonalTemplateImport } from './personal-template-import.js';
import { loadPptdProject, checkPptdProject, parsePptdProject } from './pptd.js';
import { renderOfficeTemplatePreview } from './office-template-preview.js';
import { prepareOfficeFontAccess } from './office-font-access.js';
import { extractPersonalTemplateProfile, personalTemplateSourceTheme, validPersonalTemplateProfile, PERSONAL_TEMPLATE_PROFILE_VERSION } from './personal-template-profile.js';
import { createPersonalTemplateSamples, validPersonalTemplateSamples } from './personal-template-samples.js';
import { PersonalTemplateUploads, personalTemplateFileName, decodeTemplateBase64 } from './personal-template-upload.js';

export const PERSONAL_TEMPLATE_CONVERSION_VERSION = 10;
export const PERSONAL_TEMPLATE_PREVIEW_VERSION = 11;
const MAX_TEMPLATES = 100;
// Template input pages have their own processing budget; generation remains capped separately.
export const MAX_PERSONAL_TEMPLATE_SLIDES = 200;
const PREVIEW_LONG_EDGE = 1920;
const THUMBNAIL_LONG_EDGE = 720;
// Bounds each JSON RPC request. Browser uploads transfer independent 8 MiB chunks.
export const MAX_PERSONAL_TEMPLATE_HTTP_BODY_BYTES = 86 * 1024 * 1024;
const ID = /^personal-[a-f0-9]{64}$/;
const DRAFT = /^[a-f0-9-]{36}$/;
const hash = value => createHash('sha256').update(value).digest('hex');
const profileMetadata = templateProfile => ({templateProfile,palette:templateProfile.palette,
  titleFontFace:templateProfile.typography.title.fontFace,bodyFontFace:templateProfile.typography.body.fontFace,
  aspectRatio:templateProfile.canvas.width/templateProfile.canvas.height>=1.5?'wide':'standard'});
const nameOf = value => {
  if (typeof value !== 'string' || !value.trim() || value.trim().length > 80 || /[\u0000-\u001f\u007f]/u.test(value))
    throw new Error('模板名称应为 1–80 个字符');
  return value.trim();
};
const descriptionOf = value => {
  if (typeof value !== 'string' || value.length > 1000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(value))
    throw new Error('模板描述应为 1000 个字符以内的文字');
  return value.trim();
};
const exists = async target => {
  try { await lstat(target); return true; }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
};

function conversionError(check, fileName, sha256) {
  const issues = check.issues.filter(issue => issue.severity === 'error');
  const details = issues.map(issue => [
    issue.page === undefined ? '文稿' : `第 ${issue.page} 页`,
    issue.elementId ? `对象 ${issue.elementId}` : '',
    issue.message
  ].filter(Boolean).join(' · '));
  const error = new Error([
    `模板导入遇到 ${check.errorCount} 项转换问题：`,
    ...details,
    '请保留原 PPT 文件，提供这些详情以排查转换兼容性。'
  ].join('\n'));
  error.conversion = { fileName, sha256, check };
  return error;
}

/** One library per host-owned Desktop profile; caller-supplied paths never select a library. */
export class PersonalTemplateLibrary {
  tail = Promise.resolve();
  imports = new Map();
  fontAccess;
  constructor(store, convert, writeSource, maxSlides = MAX_PERSONAL_TEMPLATE_SLIDES) {
    this.store = store;
    this.root = path.join(store.root, 'personal-templates');
    this.convert = convert;
    this.writeSource = writeSource;
    this.maxSlides = maxSlides;
    this.uploads = new PersonalTemplateUploads(this);
  }
  async locked(work) {
    const pending = this.tail.catch(() => {}).then(work);
    this.tail = pending;
    return pending;
  }
  async directory(...parts) {
    await mkdir(this.store.root, { recursive: true, mode: 0o700 });
    const target = path.join(this.root, ...parts);
    const relative = path.relative(this.store.root, target);
    let current = this.store.root;
    for (const part of relative.split(path.sep)) {
      current = path.join(current, part);
      await mkdir(current, { mode: 0o700 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
      const info = await lstat(current);
      if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('模板目录应为本地独立目录');
    }
    return target;
  }
  async checkedFile(directory, file) {
    const target = path.join(directory, file);
    const info = await lstat(target);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error('模板文件应为普通本地文件');
    const actual = await realpath(target);
    if (!actual.startsWith((await realpath(this.root)) + path.sep)) throw new Error('模板文件超出个人库范围');
    return target;
  }
  async readRecord(id) {
    if (!ID.test(id)) throw new Error('个人模板标识无效');
    const directory = path.join(this.root, 'saved', id);
    const info = await lstat(directory);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('模板目录无效');
    const record = JSON.parse(await readFile(await this.checkedFile(directory, 'template.json'), 'utf8'));
    if (record.id !== id || record.origin !== 'personal') throw new Error('模板记录无效');
    if (!Array.isArray(record.previewImages) || record.previewImages.length !== 3 || record.previewImages.some(image =>
      typeof image !== 'string' || !image.startsWith('data:image/png;base64,') || image.length > 4 * 1024 * 1024)) throw new Error('模板预览资源无效');
    nameOf(record.name);
    if (!Array.isArray(record.pageIndex) || record.pageIndex.length !== record.slideCount || record.pageIndex.some((page, i) =>
      page.slideNumber !== i + 1 || typeof page.file !== 'string' || !/^pages\/[A-Za-z0-9_.-]+\.page$/.test(page.file))) throw new Error('模板页面索引无效');
    if(record.templateProfile!==undefined && !validPersonalTemplateProfile(record.templateProfile,record.pageIndex)) throw new Error('模板结构索引无效，请重新上传 PPT');
    if(record.templateSamples!==undefined && !validPersonalTemplateSamples(record.templateSamples,record.slideCount)) throw new Error('模板示例索引无效，请重新上传 PPT');
    return record;
  }
  async list() {
    const directory = path.join(this.root, 'saved');
    if (!await exists(directory)) return [];
    if ((await lstat(directory)).isSymbolicLink()) throw new Error('个人模板库目录无效');
    const items = await readdir(directory, { withFileTypes: true });
    const records = [];
    for (const item of items) {
      if (!ID.test(item.name)) continue;
      records.push(await this.readRecord(item.name));
    }
    return records.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }
  async audit(sessionId, operation, work) {
    const startedAt = new Date().toISOString();
    try {
      const result = await work();
      await this.store.appendAudit(sessionId, {
        id: randomUUID(), operation, actor: 'user', status: 'completed', startedAt,
        completedAt: new Date().toISOString(), summary: operation
      }, { templateId: result?.id, draftId: result?.draftId });
      return result;
    } catch (error) {
      await this.store.appendAudit(sessionId, {
        id: randomUUID(), operation, actor: 'user', status: 'failed', startedAt,
        completedAt: new Date().toISOString(), error: error.message
      }, error.conversion ? { conversion: error.conversion } : {});
      throw error;
    }
  }
  async uploadStart(sessionId, input) {
    return this.locked(() => this.audit(sessionId, 'upload-personal-template', async () => {
      const upload=await this.uploads.start(sessionId,input);
      try {await this.ensureFontAccess();return upload;}
      catch(error) {await this.uploads.cancel(sessionId,upload.uploadId);throw error;}
    }));
  }
  async ensureFontAccess() {
    // One check per host library. Optional denial retains the SDK's font fallbacks.
    const pending=this.fontAccess ??= prepareOfficeFontAccess();
    try {return await pending;}
    catch(error) {if(this.fontAccess===pending)this.fontAccess=undefined;throw error;}
  }
  async uploadChunk(sessionId, input) {
    return this.locked(() => this.audit(sessionId, 'upload-personal-template-chunk', () => this.uploads.append(sessionId, input)));
  }
  async cancelUpload(sessionId, uploadId) {
    if (!DRAFT.test(uploadId)) throw new Error('上传标识无效');
    const jobs = [...this.imports.values()].filter(job => job.uploadId === uploadId);
    const owned = jobs.filter(job => job.session === hash(sessionId));
    if (jobs.length && !owned.length) throw new Error('该处理任务属于其他会话');
    // Interrupt owned workers before joining the library queue that they hold.
    for (const job of owned) job.controller.abort();
    return this.locked(() => this.audit(sessionId, 'cancel-personal-template-upload', async () => {
      await this.uploads.cancel(sessionId, uploadId);
      for (const job of owned) {
        let directory;
        try { directory = await this.draft(sessionId, job.draftId); }
        catch (error) { if (error.code !== 'ENOENT') throw error; }
        if (directory) await rm(directory, { recursive: true, force: true });
      }
      return { uploadId };
    }));
  }
  async prepare(sessionId, input) {
    const requestId=input?.requestId ?? randomUUID();
    if(!DRAFT.test(requestId)) throw new Error('处理标识无效');
    for(const [id,job] of this.imports) if(job.status!=='processing' && Date.now()-job.startedAt>3600000) this.imports.delete(id);
    if(this.imports.has(requestId)||this.imports.size>=32) throw new Error('请稍后重新处理模板');
    const progress={session:hash(sessionId),startedAt:Date.now(),total:0,pages:[],status:'processing',
      uploadId:input?.uploadId,draftId:randomUUID(),controller:new AbortController()};
    this.imports.set(requestId,progress);
    try { return await this.locked(() => this.audit(sessionId, 'prepare-personal-template', async () => {
      progress.controller.signal.throwIfAborted();
      let uploadId=input?.uploadId;
      if(uploadId===undefined) {
        const fileName=personalTemplateFileName(input?.fileName),bytes=decodeTemplateBase64(input?.base64);
        const started=await this.uploads.start(sessionId,{fileName,size:bytes.length});uploadId=started.uploadId;
        try {
          for(let offset=0;offset<bytes.length;offset+=started.chunkBytes)
            await this.uploads.append(sessionId,{uploadId,offset,base64:bytes.subarray(offset,offset+started.chunkBytes).toString('base64')});
        } catch(error) {await this.uploads.cancel(sessionId,uploadId);throw error;}
      }
      const upload=await this.uploads.record(sessionId,uploadId);
      progress.uploadId=uploadId;
      const draftId=progress.draftId;
      if((await lstat(upload.file)).size!==upload.record.size)throw new Error('请完成文件上传后再处理模板');
      try {
        await this.ensureFontAccess();
        progress.controller.signal.throwIfAborted();
        const result=await runPersonalTemplateImport({root:this.store.root,sessionId,uploadId,draftId,maxSlides:this.maxSlides}, update=>{
          progress.total=update.total;
          if(update.page)progress.pages.push(update.page);
        }, {signal:progress.controller.signal});
        progress.controller.signal.throwIfAborted();
        return result;
      } catch(error) {await rm(path.join(this.root,'drafts',draftId),{recursive:true,force:true});throw error;} finally {await rm(upload.directory,{recursive:true,force:true});}
    })); } finally { progress.status=progress.controller.signal.aborted?'cancelled':'finished';progress.startedAt=Date.now(); }
  }
  /** Runs inside the host-owned import process, under the parent's policy/audit lock. */
  async prepareSource(sessionId,input,progress,signal) {
      signal?.throwIfAborted();
      const started=Date.now();
      let upload;
      try {
        if (input?.uploadId !== undefined) upload = await this.uploads.read(sessionId, input.uploadId);
        const fileName = upload?.fileName ?? personalTemplateFileName(input?.fileName);
        const bytes = upload?.bytes ?? decodeTemplateBase64(input?.base64);
        if (bytes.length < 4 || !bytes.subarray(0, 4).equals(Buffer.from([80, 75, 3, 4])))
          throw new Error('请选择有效的 PPTX 文件');
        const id = `personal-${hash(bytes)}`;
        const templates=await this.list();
        const saved = templates.find(item => item.id === id);
        if (saved?.conversionVersion === PERSONAL_TEMPLATE_CONVERSION_VERSION && saved?.previewVersion === PERSONAL_TEMPLATE_PREVIEW_VERSION) {
          if(saved.templateProfile?.version===PERSONAL_TEMPLATE_PROFILE_VERSION)return {duplicate:true,template:saved};
          // Enrich a current cached conversion without repeating Office rendering.
          const project=await loadPptdProject(await this.projectSource(id));
          const template={...saved,...profileMetadata(extractPersonalTemplateProfile(project))};
          const directory=path.join(this.root,'saved',id),temporary=path.join(directory,`profile-${randomUUID()}.json`);
          try {await writeFile(temporary,JSON.stringify(template),{flag:'wx',mode:0o600});await rename(temporary,await this.checkedFile(directory,'template.json'));}
          finally {await rm(temporary,{force:true});}
          return {duplicate:true,template};
        }
        if (!saved && templates.length >= MAX_TEMPLATES) throw new Error('个人模板库最多保存 100 套模板');
        const drafts = await this.directory('drafts');
        // Expired previews are temporary resources, independent of registered templates.
        for (const item of await readdir(drafts, { withFileTypes: true })) {
          if (item.isDirectory() && DRAFT.test(item.name) && Date.now() - (await lstat(path.join(drafts, item.name))).mtimeMs > 86400000)
            await rm(path.join(drafts, item.name), { recursive: true });
        }
        if ((await readdir(drafts)).length >= 10) throw new Error('待保存模板达到 10 套，请先保存或取消已有预览');
        const conversionStarted=Date.now();
        const converted = await this.convert(bytes, fileName, {signal});
        signal?.throwIfAborted();
        const convertedAt=Date.now();
        if (!converted.slideCount || converted.slideCount > this.maxSlides) throw new Error(`模板应包含 1–${this.maxSlides} 页`);
        const missing = converted.diagnostics.filter(item => item.level === 'unsupported');
        if (missing.length) throw conversionError({ errorCount: missing.length, issues: missing.map(item => ({
          severity: 'error', code: 'conversion-unsupported', page: item.slide, elementId: item.nodeId,
          message: `${item.feature}：${item.message}`
        })) }, fileName, hash(bytes));
        progress?.({total:converted.slideCount});
        const original = parsePptdProject(converted.source);
        const checked = checkPptdProject(original);
        if (checked.status === 'fail') throw conversionError(checked, fileName, hash(bytes));
        const templateProfile=extractPersonalTemplateProfile(original);
        const {source:sampleSource,samples:templateSamples}=createPersonalTemplateSamples(original,templateProfile);
        const source=personalTemplateSourceTheme(sampleSource,templateProfile);
        const parsed = parsePptdProject(source);
        const sampleCheck=checkPptdProject(parsed);
        if(sampleCheck.status==='fail')throw conversionError(sampleCheck,fileName,hash(bytes));
        const draftId = input.draftId ?? randomUUID();
        const directory = await this.directory('drafts', draftId);
        try {
          const project = await this.directory('drafts', draftId, 'project');
          await this.writeSource(project, source);
          await writeFile(path.join(directory, 'source.pptx'), bytes, { mode: 0o600 });
          const previewDirectory = path.join(directory, 'preview');
          signal?.throwIfAborted();
          const previewMetadata = await renderOfficeTemplatePreview(parsed,directory,PREVIEW_LONG_EDGE,this.maxSlides,progress ? async ({page,path:imagePath}) => {
            const thumbnail=await sharp(imagePath).resize({width:240,height:240,fit:'inside',withoutEnlargement:true}).png().toBuffer();
            progress({total:converted.slideCount,page:{page,preview:`data:image/png;base64,${thumbnail.toString('base64')}`}});
          } : undefined, signal);
          signal?.throwIfAborted();
          const previewPage = async page => readFile(path.join(previewDirectory, 'pages', `page-${page}.png`));
          const uniquePages=templateSamples.representativePages;
          const representativePages=[uniquePages[0],uniquePages[Math.floor(uniquePages.length/2)],uniquePages.at(-1)];
          const thumbnails=new Map();
          for(const page of new Set(representativePages)) thumbnails.set(page,(async()=>{
            const thumbnail = await sharp(path.join(previewDirectory,'pages',`page-${page}.png`)).resize({
              width: THUMBNAIL_LONG_EDGE, height: THUMBNAIL_LONG_EDGE, fit: 'inside', withoutEnlargement: true
            }).png().toBuffer();
            return `data:image/png;base64,${thumbnail.toString('base64')}`;
          })());
          const previewImages=await Promise.all(representativePages.map(page=>thumbnails.get(page)));
          const preview = `data:image/png;base64,${(await previewPage(1)).toString('base64')}`;
          const name = nameOf(fileName.replace(/\.pptx$/i, '').slice(0, 80));
          const record = {
            id, conversionVersion: PERSONAL_TEMPLATE_CONVERSION_VERSION, previewVersion: PERSONAL_TEMPLATE_PREVIEW_VERSION, origin: 'personal', name: saved?.name ?? name, category: 'personal', supportedModes: ['ppt'], aspectRatio: 'wide',
            description: `${converted.slideCount} 页个人 PPT 模板`, previewTitle: name, previewSubtitle: '我的模板',
            ...profileMetadata(templateProfile),
            templateSamples,
            createdAt: saved?.createdAt ?? new Date().toISOString(), ...(saved ? {description:saved.description,updatedAt:new Date().toISOString()} : {}), fileName, sha256: hash(bytes), slideCount: converted.slideCount,
            previewImages, previewMetadata,
            preparationTimings:{conversionMs:convertedAt-conversionStarted,totalMs:Date.now()-started},
            diagnostics: converted.diagnostics, checkWarnings: checked.warningCount,
            resourcePlaceholders: converted.diagnostics.filter(item => item.level === 'placeholder'),
            reviewIssues: checked.issues.filter(issue => issue.severity === 'warning').map(issue => ({
              ...issue, message: issue.code === 'out-of-bounds' ? '源文件对象位于页面边缘或画布外，预览按页面范围显示。'
                : issue.code === 'text-overflow' ? '源文件文字可能超出文本框，请在预览中核对。' : issue.message
            })),
            pageIndex: [...converted.source.pages.keys()].map((file, i) => ({ slideNumber: i + 1, file }))
          };
          await writeFile(path.join(directory, 'template.json'), JSON.stringify(record), { mode: 0o600 });
          await writeFile(path.join(directory, 'owner.json'), JSON.stringify({ session: hash(sessionId) }), { mode: 0o600 });
          signal?.throwIfAborted();
          return { draftId, template: record, preview };
        } catch (error) { await rm(directory, { recursive: true, force: true }); throw error; }
      } finally { if (upload) await rm(upload.directory, { recursive: true, force: true }); }
  }

  async importProgress(sessionId,requestId,after=0) {
    if(!DRAFT.test(requestId)||!Number.isInteger(after)||after<0||after>this.maxSlides) throw new Error('处理进度参数无效');
    const job=this.imports.get(requestId);
    if(!job) return {total:0,completed:0,pages:[],status:'waiting'};
    if(job.session!==hash(sessionId)) throw new Error('该处理任务属于其他会话');
    return {total:job.total,completed:job.pages.length,pages:job.pages.slice(after),status:job.status};
  }
  async draft(sessionId, draftId) {
    if (!DRAFT.test(draftId)) throw new Error('预览标识无效');
    const directory = path.join(this.root, 'drafts', draftId);
    const info = await lstat(directory);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('预览目录无效');
    const owner = JSON.parse(await readFile(await this.checkedFile(directory, 'owner.json'), 'utf8'));
    if (owner.session !== hash(sessionId)) throw new Error('该预览属于其他会话');
    return directory;
  }
  async readPreview(directory,record,page) {
    if(!Number.isInteger(page)||page<1||page>record.slideCount)throw new Error('预览页码无效');
    const image=await this.checkedFile(path.join(directory,'preview','pages'),`page-${page}.png`);
    return { page, preview: `data:image/png;base64,${(await readFile(image)).toString('base64')}` };
  }
  async previewPage(sessionId,draftId,page) {
    return this.locked(()=>this.audit(sessionId,'preview-personal-template',async()=>{
      const directory=await this.draft(sessionId,draftId);
      const record=JSON.parse(await readFile(await this.checkedFile(directory,'template.json'),'utf8'));
      return this.readPreview(directory,record,page);
    }));
  }
  async previewSavedPage(sessionId, templateId, page) {
    return this.locked(() => this.audit(sessionId, 'preview-personal-template', async () => {
      const record = await this.readRecord(templateId);
      return this.readPreview(path.join(this.root,'saved',templateId),record,page);
    }));
  }
  async save(sessionId, draftId, name) {
    name = nameOf(name);
    return this.locked(() => this.audit(sessionId, 'save-personal-template', async () => {
      const directory = await this.draft(sessionId, draftId);
      const record = JSON.parse(await readFile(await this.checkedFile(directory, 'template.json'), 'utf8'));
      if (!ID.test(record.id)) throw new Error('模板标识无效');
      const templates=await this.list();
      const duplicate = templates.find(item => item.id === record.id);
      if (duplicate?.conversionVersion === record.conversionVersion && duplicate?.previewVersion === record.previewVersion) { await rm(directory, { recursive: true }); return duplicate; }
      if (!duplicate && templates.length >= MAX_TEMPLATES) throw new Error('个人模板库最多保存 100 套模板');
      const project = await loadPptdProject(path.join(directory, 'project'));
      if (checkPptdProject(project).status === 'fail') throw new Error('请重新上传完整的模板文件');
      const next = { ...record, ...(duplicate ? {createdAt:duplicate.createdAt,description:duplicate.description} : {}), name, previewTitle: name };
      await writeFile(path.join(directory, 'template.json'), JSON.stringify(next), { mode: 0o600 });
      const destination = path.join(await this.directory('saved'), record.id);
      if (duplicate) {
        // Publish only after preview acceptance; retain the old source/project for recovery.
        const backup = path.join(await this.directory('backups', record.id), randomUUID());
        await rename(destination, backup);
        try { await rename(directory, destination); }
        catch (error) { await rename(backup, destination); throw error; }
      } else await rename(directory, destination);
      return next;
    }));
  }
  async cancel(sessionId, draftId) {
    return this.locked(() => this.audit(sessionId, 'cancel-personal-template', async () => {
      await rm(await this.draft(sessionId, draftId), { recursive: true });
      return { draftId };
    }));
  }
  async rename(sessionId, id, name) {
    return this.update(sessionId, id, { name }, 'rename-personal-template');
  }
  async update(sessionId, id, changes, operation = 'update-personal-template') {
    return this.locked(() => this.audit(sessionId, operation, async () => {
      const name = nameOf(changes.name);
      const description = changes.description === undefined ? undefined : descriptionOf(changes.description);
      const record = await this.readRecord(id);
      const next = { ...record, name, previewTitle: name, ...(description === undefined ? {} : { description }), updatedAt: new Date().toISOString() };
      const file = path.join(this.root, 'saved', id, 'template.json');
      const temporary = `${file}.${randomUUID()}.tmp`;
      try {
        await writeFile(temporary, JSON.stringify(next), { mode: 0o600 });
        await rename(temporary, file);
      } finally { await rm(temporary, { force: true }); }
      return next;
    }));
  }
  async remove(sessionId, id) {
    return this.locked(() => this.audit(sessionId, 'delete-personal-template', async () => {
      await this.readRecord(id);
      const directory = path.join(this.root, 'saved', id);
      const trash = path.join(await this.directory('trash'), `${id}-${randomUUID()}`);
      await rename(directory, trash);
      return { id };
    }));
  }
  async projectSource(id) {
    await this.readRecord(id);
    const directory = path.join(this.root, 'saved', id, 'project');
    // Walk before reading or copying; saved image paths remain confined to this project.
    const inspect = async current => {
      for (const item of await readdir(current, { withFileTypes: true })) {
        if (item.isSymbolicLink()) throw new Error('模板工程应使用本地文件');
        if (item.isDirectory()) await inspect(path.join(current, item.name));
        else if (!item.isFile()) throw new Error('模板工程包含无效文件');
      }
    };
    if ((await lstat(directory)).isSymbolicLink()) throw new Error('模板工程目录无效');
    await inspect(directory);
    await loadPptdProject(directory);
    return directory;
  }
  async copyProject(id, output) {
    return this.locked(async () => {
      const source = await this.projectSource(id);
      for (const item of await readdir(source))
        await cp(path.join(source, item), path.join(output, item), { recursive: true, errorOnExist: true, force: false });
    });
  }
}
