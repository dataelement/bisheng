import { randomUUID, createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, open, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const PERSONAL_TEMPLATE_CHUNK_BYTES = 8 * 1024 * 1024;
const UPLOAD_ID = /^[a-f0-9-]{36}$/;
const owner = session => createHash('sha256').update(session).digest('hex');

export function personalTemplateFileName(value) {
  if (typeof value !== 'string' || value.length > 240 || !/\.pptx$/i.test(value) || /[\\/\u0000]/u.test(value))
    throw new Error('请选择 PPTX 文件');
  return value;
}

export function decodeTemplateBase64(encoded) {
  if (typeof encoded !== 'string' || encoded.length % 4 !== 0 || /[^A-Za-z0-9+/=]/.test(encoded))
    throw new Error('上传数据应为有效 Base64');
  const bytes = Buffer.from(encoded, 'base64');
  if (bytes.toString('base64') !== encoded) throw new Error('上传数据应为有效 Base64');
  return bytes;
}

/** Host-owned temporary files. The library holds its policy/audit lock for every operation. */
export class PersonalTemplateUploads {
  constructor(files) { this.files = files; }
  async start(session, input) {
    const fileName = personalTemplateFileName(input?.fileName), size = input?.size;
    if (!Number.isSafeInteger(size) || size < 4) throw new Error('上传文件大小无效');
    const uploads = await this.files.directory('uploads');
    for (const item of await readdir(uploads, { withFileTypes: true })) {
      if (item.isDirectory() && UPLOAD_ID.test(item.name) && Date.now() - (await lstat(path.join(uploads, item.name))).mtimeMs > 86400000)
        await rm(path.join(uploads, item.name), { recursive: true });
    }
    if ((await readdir(uploads)).length >= 10) throw new Error('请先完成或取消正在上传的模板');
    const uploadId = randomUUID(), directory = await this.files.directory('uploads', uploadId);
    try {
      await writeFile(path.join(directory, 'owner.json'), JSON.stringify({ session: owner(session), fileName, size }), { flag: 'wx', mode: 0o600 });
      await writeFile(path.join(directory, 'source.pptx'), Buffer.alloc(0), { flag: 'wx', mode: 0o600 });
      return { uploadId, chunkBytes: PERSONAL_TEMPLATE_CHUNK_BYTES };
    } catch (error) { await rm(directory, { recursive: true, force: true }); throw error; }
  }
  async record(session, uploadId) {
    if (!UPLOAD_ID.test(uploadId)) throw new Error('上传标识无效');
    const directory = path.join(this.files.root, 'uploads', uploadId), info = await lstat(directory);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('上传目录应为本地独立目录');
    const record = JSON.parse(await readFile(await this.files.checkedFile(directory, 'owner.json'), 'utf8'));
    if (record.session !== owner(session)) throw new Error('该上传属于其他会话');
    personalTemplateFileName(record.fileName);
    if (!Number.isSafeInteger(record.size) || record.size < 4) throw new Error('上传文件大小无效');
    return { directory, record, file: await this.files.checkedFile(directory, 'source.pptx') };
  }
  async append(session, input) {
    const { record, file } = await this.record(session, input?.uploadId);
    if (!Number.isSafeInteger(input.offset) || input.offset < 0) throw new Error('上传分片位置无效');
    if (typeof input.base64 !== 'string' || input.base64.length > Math.ceil(PERSONAL_TEMPLATE_CHUNK_BYTES / 3) * 4)
      throw new Error('上传分片应在 8 MiB 以内');
    const bytes = decodeTemplateBase64(input.base64);
    if (!bytes.length || bytes.length > PERSONAL_TEMPLATE_CHUNK_BYTES) throw new Error('上传分片应为 1 字节至 8 MiB');
    const handle = await open(file, constants.O_RDWR | (constants.O_NOFOLLOW ?? 0));
    try {
      const info = await handle.stat();
      if (!info.isFile() || info.size !== input.offset || bytes.length > record.size - input.offset)
        throw new Error('上传分片与文件位置或大小不匹配');
      let written = 0;
      while (written < bytes.length) {
        const result = await handle.write(bytes, written, bytes.length - written, input.offset + written);
        if (!result.bytesWritten) throw new Error('上传分片写入失败');
        written += result.bytesWritten;
      }
      return { received: input.offset + bytes.length, size: record.size };
    } finally { await handle.close(); }
  }
  async read(session, uploadId) {
    const upload = await this.record(session, uploadId);
    if ((await lstat(upload.file)).size !== upload.record.size) throw new Error('请完成文件上传后再处理模板');
    const bytes = await readFile(upload.file);
    if (bytes.length !== upload.record.size) throw new Error('上传文件内容已变化，请重新上传');
    return { bytes, fileName: upload.record.fileName, directory: upload.directory };
  }
  async cancel(session, uploadId) {
    let upload;
    try { upload = await this.record(session, uploadId); }
    catch (error) { if (error.code === 'ENOENT') return { uploadId }; throw error; }
    await rm(upload.directory, { recursive: true, force: true });
    return { uploadId };
  }
}
