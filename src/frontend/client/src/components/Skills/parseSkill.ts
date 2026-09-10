import JSZip from 'jszip';
import { load, JSON_SCHEMA } from 'js-yaml';
import { SkillError, type SkillManifest } from './types';

const MAX_UPLOAD = 10 * 1024 * 1024;
const MAX_EXPANDED = 100 * 1024 * 1024;
const MAX_MANIFEST = 1024 * 1024;

function parseManifest(text: string): Pick<SkillManifest, 'name' | 'displayName' | 'description' | 'instructions'> {
  const match = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)([\s\S]*)$/.exec(text);
  if (!match) throw new SkillError('manifest');
  let metadata: unknown;
  try {
    metadata = load(match[1], { schema: JSON_SCHEMA });
  } catch {
    throw new SkillError('manifest');
  }
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
    throw new SkillError('manifest');
  }
  const { name, description, display_name: displayName } = metadata as Record<string, unknown>;
  if (typeof name !== 'string' || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name) || name.length > 64) {
    throw new SkillError('name');
  }
  if (typeof description !== 'string' || !description.trim() || description.length > 1024 || !match[2].trim()) {
    throw new SkillError('manifest');
  }
  return {
    name,
    displayName: typeof displayName === 'string' && displayName.trim() ? displayName.trim().slice(0, 80) : name,
    description: description.trim(),
    instructions: match[2].trim(),
  };
}

function readManifest(entry: JSZip.JSZipObject): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const chunks: Uint8Array[] = [];
    let size = 0;
    // The browser stream exists in pinned JSZip 3.10.1 but is absent from its declarations.
    const stream = (entry as JSZip.JSZipObject & {
      internalStream: (type: 'uint8array') => {
        on: ((event: 'data', listener: (chunk: Uint8Array) => void) => void)
          & ((event: 'error' | 'end', listener: () => void) => void);
        pause: () => void;
        resume: () => void;
      };
    }).internalStream('uint8array');
    stream.on('data', (chunk: Uint8Array) => {
      size += chunk.byteLength;
      if (size > MAX_MANIFEST) {
        stream.pause();
        reject(new SkillError('manifest_size'));
        return;
      }
      chunks.push(chunk);
    });
    stream.on('error', () => reject(new SkillError('archive')));
    stream.on('end', () => {
      const result = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
      resolve(result);
    });
    stream.resume();
  });
}

export async function parseSkillFile(file: File): Promise<SkillManifest> {
  if (!/\.(md|zip|skill)$/i.test(file.name)) throw new SkillError('format');
  if (!file.size || file.size > MAX_UPLOAD) throw new SkillError('size');
  let bytes: Uint8Array;
  let files = ['SKILL.md'];
  if (/\.md$/i.test(file.name)) {
    if (file.size > MAX_MANIFEST) throw new SkillError('manifest_size');
    bytes = new Uint8Array(await file.arrayBuffer());
  } else {
    let zip: JSZip;
    try { zip = await JSZip.loadAsync(await file.arrayBuffer()); }
    catch { throw new SkillError('archive'); }
    const entries = Object.values(zip.files);
    if (entries.length > 1000) throw new SkillError('archive_size');
    let expandedSize = 0;
    for (const entry of entries) {
      const original: unknown = Object.getOwnPropertyDescriptor(entry, 'unsafeOriginalName')?.value ?? entry.name;
      if (typeof original !== 'string' || /(^\/|\\|^[a-z]:|(^|\/)\.\.(\/|$)|\0)/i.test(original)) {
        throw new SkillError('archive_path');
      }
      // JSZip 3.10.1 keeps central-directory sizes here; inspect before inflating.
      // The manifest also has an independent streaming limit on actual output.
      const data = Object.getOwnPropertyDescriptor(entry, '_data')?.value as { uncompressedSize?: unknown } | undefined;
      if (!entry.dir) {
        if (typeof data?.uncompressedSize !== 'number' || !Number.isSafeInteger(data.uncompressedSize) || data.uncompressedSize < 0) {
          throw new SkillError('archive');
        }
        expandedSize += data.uncompressedSize;
      }
    }
    if (expandedSize > MAX_EXPANDED) throw new SkillError('archive_size');
    const content = entries.filter((entry) => !entry.dir && !entry.name.startsWith('__MACOSX/'));
    files = content.map((entry) => entry.name).sort();
    const manifests = content.filter((entry) => /(^|\/)SKILL\.md$/.test(entry.name));
    if (manifests.length !== 1) throw new SkillError('manifest_count');
    bytes = await readManifest(manifests[0]);
  }
  let text: string;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
  catch { throw new SkillError('encoding'); }
  return { ...parseManifest(text), files, fileName: file.name, size: file.size };
}
