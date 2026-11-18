import path from 'node:path';
import { createHash } from 'node:crypto';
import { unzipSync, zipSync } from 'fflate';
import sharp from 'sharp';
import { RECOMMENDED_ZIP_LIMITS } from '@aiden0z/pptx-renderer';
import { emfToSvg } from './emf-image.js';
import { isSafeSvg } from './pptx-resources.js';

export const MAX_IMPORT_IMAGE_BYTES = 16 * 1024 * 1024;
export const MAX_IMPORT_IMAGE_PIXELS = 20 * 1024 * 1024;
const mediaPart = name => /^ppt\/(?:[^/]+\/)*media\/.+$/i.test(name);
const playbackPart = name => /\.(?:mp4|m4v|mov|webm|avi|wmv|mpeg|mpg|mp3|wav|m4a|ogg|wma)$/i.test(name);
const decodedPath = name => { try { return decodeURIComponent(name); } catch { return name; } };

/** Inspect ZIP sizes before inflation. Keep package limits on the retained parts;
 * oversized pictures and playback resources keep their OOXML geometry only.
 */
export function boundedPptxMedia(bytes) {
  const omitted = new Map();
  let count = 0, total = 0, media = 0;
  unzipSync(bytes, { filter(entry) {
    if (++count > RECOMMENDED_ZIP_LIMITS.maxEntries) throw new Error('PPTX 包含的资源数量超过解析限制');
    const name = entry.name.replaceAll('\\', '/');
    if (mediaPart(name) && (playbackPart(name) || entry.originalSize > MAX_IMPORT_IMAGE_BYTES)) {
      const reason = playbackPart(name) ? '播放资源已按原位置保留占位。' : '图片资源超过单项处理大小限制。';
      omitted.set(name, reason); omitted.set(decodedPath(name), reason);
      return false;
    }
    total += entry.originalSize;
    if (mediaPart(name)) media += entry.originalSize;
    if (entry.originalSize > RECOMMENDED_ZIP_LIMITS.maxEntryUncompressedBytes || total > RECOMMENDED_ZIP_LIMITS.maxTotalUncompressedBytes || media > RECOMMENDED_ZIP_LIMITS.maxMediaBytes)
      throw new Error('PPTX 资源超过解析大小限制');
    return false;
  } });
  if (!omitted.size) return { bytes, omitted };
  const parts = unzipSync(bytes, { filter: entry => !omitted.has(entry.name.replaceAll('\\', '/')) });
  return { bytes: zipSync(parts, { level: 1 }), omitted };
}

function mediaType(file, bytes) {
  const extension = path.extname(file).toLowerCase();
  if (extension === '.png' && bytes[0] === 137 && bytes[1] === 80) return 'image/png';
  if ((extension === '.jpg' || extension === '.jpeg') && bytes[0] === 255 && bytes[1] === 216) return 'image/jpeg';
  if (extension === '.gif' && Buffer.from(bytes.subarray(0, 3)).toString('ascii') === 'GIF') return 'image/gif';
  if (extension === '.webp' && Buffer.from(bytes.subarray(8, 12)).toString('ascii') === 'WEBP') return 'image/webp';
  if (extension === '.svg' && isSafeSvg(bytes)) return 'image/svg+xml';
}

/** One cache per import: decoding work follows unique resources, not slide count. */
export function createPptxImageReader() {
  const cache = new Map();
  return async (file, source) => {
    if (!source) return { reason: '图片资源或内嵌关系缺失。' };
    if (source.byteLength > MAX_IMPORT_IMAGE_BYTES) return { reason: '图片资源超过单项处理大小限制。' };
    const key = path.extname(file).toLowerCase() + ':' + createHash('sha256').update(source).digest('hex');
    if (!cache.has(key)) cache.set(key, (async () => {
      try {
        const emf = /\.emf$/i.test(file);
        const bytes = emf ? emfToSvg(source) : source;
        const type = mediaType(emf ? 'converted.svg' : file, bytes);
        if (!type) return { reason: '图片格式进入占位显示。' };
        const options = { limitInputPixels: MAX_IMPORT_IMAGE_PIXELS, failOn: 'error' };
        const metadata = await sharp(bytes, options).metadata();
        if (!metadata.width || !metadata.height || metadata.width * metadata.height * (metadata.pages ?? 1) > MAX_IMPORT_IMAGE_PIXELS)
          return { reason: '图片像素尺寸超过处理限制。' };
        // Decode once so a damaged payload becomes a local placeholder before export.
        await sharp(bytes, options).resize({ width: 1, height: 1, fit: 'inside' }).png().toBuffer();
        return { bytes, type };
      } catch (error) { return { reason: `图片解码进入占位显示：${String(error.message).slice(0, 240)}` }; }
    })());
    return cache.get(key);
  };
}

/** A replaceable image slot with a translucent white mask and a quiet visual cue. */
export async function mediaPlaceholder(bounds, kind = 'picture') {
  const ratio = Math.max(1 / 32, Math.min(32, Math.abs(bounds[2] / bounds[3]) || 1));
  const width = Math.round(ratio >= 1 ? 720 : 720 * ratio);
  const height = Math.round(ratio >= 1 ? 720 / ratio : 720);
  const size = Math.min(36, width * .22, height * .22), x = width / 2, y = height / 2;
  const cue = kind === 'video' || kind === 'audio'
    ? '<path d="M-7-10 10 0-7 10z" fill="currentColor" stroke="none"/>'
    : '<rect x="-13" y="-10" width="26" height="20" rx="2"/><circle cx="-6" cy="-3" r="2"/><path d="m-11 8 7-7 5 5 4-4 6 6"/>';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect x=".5" y=".5" width="${width - 1}" height="${height - 1}" fill="#FFFFFF" fill-opacity=".92" stroke="#D4D8DE" stroke-dasharray="4 4"/><g transform="translate(${x} ${y}) scale(${size / 28})" color="#A5ADB7" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linejoin="round">${cue}</g></svg>`;
  return { bytes: await sharp(Buffer.from(svg)).png().toBuffer(), type: 'image/png' };
}
