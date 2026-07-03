import { useState } from 'react';
import { Outlined } from 'bisheng-icons';
import type { FileType } from '~/components/ui/icon/File/FileIcon';
import { cn } from '~/utils';
import type { ChatCitation } from '~/api/chatApi';
import {
  buildCitationDocumentPreview,
  getCitationDocumentFileType,
  getCitationDocumentName,
  normalizeCitationType,
  type CitationPreview,
  type CitationReferenceItem,
} from './citationUtils';

export type CitationSourceIconData = {
  key: string;
  type: 'web' | 'rag';
  title: string;
  faviconUrl?: string;
  fileType?: FileType;
};

type RagIconVariant = 'document' | 'knowledge';

const supportedFileTypes = new Set<FileType>([
  'pdf',
  'doc',
  'docx',
  'ppt',
  'pptx',
  'md',
  'html',
  'txt',
  'jpg',
  'jpeg',
  'png',
  'bmp',
  'csv',
  'xls',
  'xlsx',
]);

function normalizeFileType(type?: string): FileType {
  const normalizedType = String(type || '').toLowerCase().replace(/^\./, '') as FileType;
  return supportedFileTypes.has(normalizedType) ? normalizedType : 'txt';
}

function getFaviconUrl(url?: string) {
  if (!url) {
    return '';
  }

  try {
    const parsedUrl = new URL(url, window.location.origin);
    return `${parsedUrl.origin}/favicon.ico`;
  } catch {
    return '';
  }
}

function resolvePreviewUrl(detail?: ChatCitation | null, preview?: CitationPreview | null) {
  return preview?.link || detail?.sourcePayload?.url || detail?.sourcePayload?.sourceUrl || '';
}

function getReferenceIconKey({
  detail,
  preview,
  item,
  type,
}: {
  detail: ChatCitation | null;
  preview: CitationPreview | null;
  item: CitationReferenceItem;
  type: 'web' | 'rag';
}) {
  if (type === 'web') {
    return resolvePreviewUrl(detail, preview) || item.data.citationId;
  }

  return (detail ? getCitationDocumentName(detail) : '') || preview?.title || item.data.groupKey || item.data.citationId;
}

export function buildCitationSourceIconData({
  detail,
  preview,
  type,
  fallbackKey = 'source',
}: {
  detail?: ChatCitation | null;
  preview?: CitationPreview | null;
  type?: string;
  fallbackKey?: string;
}): CitationSourceIconData {
  const normalizedType = normalizeCitationType(preview?.type || detail?.type || type);

  if (normalizedType === 'web') {
    return {
      key: `web:${resolvePreviewUrl(detail, preview) || fallbackKey}`,
      type: 'web',
      title: preview?.title || detail?.sourcePayload?.title || '网页',
      faviconUrl: getFaviconUrl(resolvePreviewUrl(detail, preview)),
    };
  }

  return {
    key: `rag:${(detail ? getCitationDocumentName(detail) : '') || preview?.title || fallbackKey}`,
    type: 'rag',
    title: preview?.title || (detail ? getCitationDocumentName(detail) : '文档'),
    fileType: normalizeFileType(getCitationDocumentFileType(detail) || preview?.sourceMeta),
  };
}

export function buildCitationSourceIconStackData(
  references: CitationReferenceItem[],
  detailMap: Record<string, ChatCitation>,
) {
  const icons: CitationSourceIconData[] = [];
  const seen = new Set<string>();

  for (const item of references) {
    const detail = detailMap[item.data.citationId] ?? item.detail ?? null;
    const preview = item.legacyPreview ?? buildCitationDocumentPreview(detail, item.data);
    const type = normalizeCitationType(preview?.type || detail?.type || item.data.type);
    const iconKey = `${type}:${getReferenceIconKey({ detail, preview, item, type })}`;

    if (seen.has(iconKey)) {
      continue;
    }

    seen.add(iconKey);
    icons.push(buildCitationSourceIconData({
      detail,
      preview,
      type,
      fallbackKey: item.data.citationId,
    }));

    if (icons.length >= 3) {
      break;
    }
  }

  return icons;
}

function WebSourceIcon({
  icon,
  iconClassName,
}: {
  icon: CitationSourceIconData;
  iconClassName?: string;
}) {
  const [imageFailed, setImageFailed] = useState(false);

  if (!icon.faviconUrl || imageFailed) {
    return <Outlined.Earth className={cn('size-4 text-[#7C3AED]', iconClassName)} />;
  }

  return (
    <img
      src={icon.faviconUrl}
      alt=""
      className={cn('size-full rounded-full object-cover', iconClassName)}
      onError={() => setImageFailed(true)}
    />
  );
}

type FileTypeIconConfig = {
  Icon: typeof Outlined.File;
  colorClassName: string;
};

// bisheng-icons Outlined file icons stroke with currentColor; each type pins its
// legacy palette here. These are file-format colors (Word blue / PDF red / Excel
// green), not brand colors — they must NOT follow the blue⇄green theme.
const fileTypeIconConfigs: Partial<Record<FileType, FileTypeIconConfig>> = {
  pdf: { Icon: Outlined.FilePdf, colorClassName: 'text-[#F53F3F]' },
  ppt: { Icon: Outlined.FilePdf, colorClassName: 'text-[#F53F3F]' },
  pptx: { Icon: Outlined.FilePdf, colorClassName: 'text-[#F53F3F]' },
  doc: { Icon: Outlined.FileWord, colorClassName: 'text-[#024DE3]' },
  docx: { Icon: Outlined.FileWord, colorClassName: 'text-[#024DE3]' },
  md: { Icon: Outlined.FileEditing, colorClassName: 'text-[#FF7D00]' },
  html: { Icon: Outlined.File, colorClassName: 'text-[#374151]' },
  csv: { Icon: Outlined.FileExcel, colorClassName: 'text-[#007D1A]' },
  xls: { Icon: Outlined.FileExcel, colorClassName: 'text-[#007D1A]' },
  xlsx: { Icon: Outlined.FileExcel, colorClassName: 'text-[#007D1A]' },
  jpg: { Icon: Outlined.FileImage, colorClassName: 'text-[#374151]' },
  jpeg: { Icon: Outlined.FileImage, colorClassName: 'text-[#374151]' },
  png: { Icon: Outlined.FileImage, colorClassName: 'text-[#374151]' },
  bmp: { Icon: Outlined.FileImage, colorClassName: 'text-[#374151]' },
  txt: { Icon: Outlined.FileTxt, colorClassName: 'text-[#374151]' },
};

const defaultFileTypeIconConfig: FileTypeIconConfig = {
  Icon: Outlined.FileTxt,
  colorClassName: 'text-[#374151]',
};

export function CitationFileTypeIcon({
  fileType = 'txt',
  className,
}: {
  fileType?: FileType;
  className?: string;
}) {
  const normalizedType = normalizeFileType(fileType);
  const { Icon, colorClassName } = fileTypeIconConfigs[normalizedType] ?? defaultFileTypeIconConfig;

  return <Icon className={cn('size-4 shrink-0', colorClassName, className)} aria-hidden="true" />;
}

export function CitationSourceIcon({
  detail,
  preview,
  type,
  className,
  iconClassName,
  fallbackKey,
  ragIconVariant = 'document',
  clipAsCircle,
}: {
  detail?: ChatCitation | null;
  preview?: CitationPreview | null;
  type?: string;
  className?: string;
  iconClassName?: string;
  fallbackKey?: string;
  ragIconVariant?: RagIconVariant;
  /** Override the default circular clip (web favicons / knowledge books). */
  clipAsCircle?: boolean;
}) {
  const icon = buildCitationSourceIconData({ detail, preview, type, fallbackKey });

  const shouldClipAsCircle = clipAsCircle ?? (icon.type === 'web' || ragIconVariant === 'knowledge');

  return (
    <span
      className={cn(
        'inline-flex size-4 shrink-0 items-center justify-center',
        shouldClipAsCircle && 'overflow-hidden rounded-full',
        className,
      )}
      title={icon.title}
    >
      {icon.type === 'web' ? (
        <WebSourceIcon icon={icon} iconClassName={iconClassName} />
      ) : ragIconVariant === 'knowledge' ? (
        <Outlined.BookOpenText className={cn('size-4 text-[#86909C]', iconClassName)} />
      ) : (
        <CitationFileTypeIcon fileType={icon.fileType || 'txt'} className={iconClassName} />
      )}
    </span>
  );
}

export function CitationSourceIconStack({ icons }: { icons: CitationSourceIconData[] }) {
  if (!icons.length) {
    return null;
  }

  return (
    <span className="inline-flex shrink-0 items-center">
      {icons.map((icon, index) => (
        <span
          key={icon.key}
          className={cn(
            'flex size-5 items-center justify-center overflow-hidden rounded-full border-[0.5px] border-[#E0E0E0] bg-[#F4F5F8]',
            index < icons.length - 1 && '-mr-3',
          )}
          title={icon.title}
        >
          {icon.type === 'web' ? (
            <WebSourceIcon icon={icon} iconClassName="size-full" />
          ) : (
            <CitationFileTypeIcon fileType={icon.fileType || 'txt'} className="size-3.5" />
          )}
        </span>
      ))}
    </span>
  );
}
