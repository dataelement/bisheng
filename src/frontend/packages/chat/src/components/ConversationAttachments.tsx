import * as Dialog from '@radix-ui/react-dialog';
import { Colored, Outlined } from 'bisheng-icons';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { ChatAttachment } from '../core/types';
export interface AttachmentServices {
  resolveUrl: (url: string) => string;
  getImageUrl?: (file: ChatAttachment) => Promise<string | null>;
  onDownload: (file: ChatAttachment) => void | Promise<unknown>;
  renderMedia?: (file: ChatAttachment) => ReactNode;
  labels: { download: string; unavailable: string; close: string; preview: string };
}
function AttachmentFileIcon({ name }: { name: string }) {
  const extension = name.split(/[?#]/)[0].split('.').pop()?.toLowerCase();
  const Icon = extension === 'doc' || extension === 'docx' || extension === 'wps' ? Colored.FileDoc
    : extension === 'xls' || extension === 'xlsx' || extension === 'et' ? Colored.FileXls
    : extension === 'csv' ? Colored.FileCsv
    : extension === 'ppt' || extension === 'pptx' || extension === 'dps' ? Colored.FilePptx
    : extension === 'md' ? Colored.FileMd
    : extension === 'html' || extension === 'htm' ? Colored.FileHtml
    : extension === 'txt' ? Colored.FileTxt
    : extension === 'pdf' ? Outlined.FilePdf : Outlined.File;
  const outlined = Icon === Outlined.FilePdf || Icon === Outlined.File;
  return <span className="flex size-10 shrink-0 items-center justify-center text-text-2" aria-hidden="true"><Icon size={outlined ? 24 : 40} /></span>;
}
function isImage(file: ChatAttachment): boolean { return /\.(?:png|jpe?g|gif|bmp|webp)(?:[?#].*)?$/i.test(file.name || file.url); }
function isMedia(file: ChatAttachment): boolean { return /\.(?:mp[34]|wav|m4a|aac|ogg|flac|mov|avi|mkv|webm)(?:[?#].*)?$/i.test(file.name || file.url); }
function AttachmentImage({ file, services }: { file: ChatAttachment; services: AttachmentServices }) {
  const { id, name, url: sourceUrl, raw } = file;
  const requestFile = useMemo(() => ({ id, name, url: sourceUrl, raw }), [id, name, sourceUrl, raw]);
  const initial = file.url ? services.resolveUrl(file.url) : null;
  const [url, setUrl] = useState<string | null>(initial);
  const [failed, setFailed] = useState(false);
  const { getImageUrl, resolveUrl } = services;
  useEffect(() => {
    let active = true;
    setFailed(false); setUrl(initial);
    if (!getImageUrl) { if (!initial) setFailed(true); return; }
    void getImageUrl(requestFile).then(fresh => {
      if (!active) return;
      if (fresh) { setUrl(resolveUrl(fresh)); setFailed(false); }
      else if (!initial) setFailed(true);
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [requestFile, getImageUrl, initial, resolveUrl]);
  if (failed) return <div role="status" className="flex size-[100px] items-center justify-center rounded-lg bg-fill-1 p-2 text-caption text-text-3">{services.labels.unavailable}</div>;
  if (!url) return <div className="size-[100px] animate-pulse rounded-lg bg-fill-1" />;
  return <Dialog.Root><Dialog.Trigger asChild><button type="button" title={file.name} className="size-[100px] shrink-0 overflow-hidden rounded-lg bg-[#F8F8F8] cursor-pointer">
    <img src={url} alt={file.name} onError={() => setFailed(true)} className="size-full object-cover" />
  </button></Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden bg-black/90 dark:bg-black/80">
      <Dialog.Close asChild><button type="button" aria-label={services.labels.close} className="absolute right-4 top-4 text-gray-50"><Outlined.Close size={20} /></button></Dialog.Close>
      <Dialog.Content aria-describedby={undefined} className="relative flex items-center justify-center focus:outline-none">
        <Dialog.Title className="sr-only">{services.labels.preview}</Dialog.Title>
        <img src={url} alt={file.name} className="max-h-[60vh] max-w-[min(60vw,640px)] object-contain shadow-xl" />
      </Dialog.Content>
    </Dialog.Overlay></Dialog.Portal>
  </Dialog.Root>;
}
export function ConversationAttachments({ files, services }: { files: readonly ChatAttachment[]; services: AttachmentServices }) {
  if (!files.length) return null;
  const images = files.filter(isImage);
  const others = files.filter(file => !isImage(file));
  return <div className="mt-2">
    {images.length > 0 && <div className="flex flex-wrap gap-2">{images.map((file, index) => <AttachmentImage key={file.id || file.url || index} file={file} services={services} />)}</div>}
    {others.length > 0 && <div className="mt-2 flex max-w-sm flex-wrap gap-2 first:mt-0">{others.map((file, index) => <div key={file.id || file.url || index}>
      {isMedia(file) && services.renderMedia ? services.renderMedia(file)
        : <button type="button" disabled={!file.url} onClick={() => { if (file.url) void services.onDownload(file); }}
          className="group relative flex w-52 max-w-full items-center gap-2 rounded-xl border border-border-base bg-bg-page p-2 text-left cursor-pointer">
          <AttachmentFileIcon name={file.name} />
          <span className="min-w-0 flex-1"><span title={file.name} className="block truncate text-body text-text-1">{file.name}</span>
            <span className="mt-1 block text-caption text-text-3">{file.url ? services.labels.download : services.labels.unavailable}</span>
          </span>
        </button>}
    </div>)}</div>}
  </div>;
}
