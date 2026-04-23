import { useState } from 'react';
import { Globe2 } from 'lucide-react';
import BookOpen from '~/components/ui/icon/BookOpen';
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
    return <Globe2 className={cn('size-4 text-[#7C3AED]', iconClassName)} />;
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

function CitationFileTypeIcon({
  fileType = 'txt',
  className,
}: {
  fileType?: FileType;
  className?: string;
}) {
  const normalizedType = normalizeFileType(fileType);
  const renderSvgContent = () => {
    if (normalizedType === 'pdf' || normalizedType === 'ppt' || normalizedType === 'pptx') {
      return (
        <>
          <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
          <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
          <path d="M3.33268 1.33337H9.99935L13.3327 4.66671V14C13.3327 14.3682 13.0342 14.6667 12.666 14.6667H3.33268C2.96449 14.6667 2.66602 14.3682 2.66602 14V2.00004C2.66602 1.63185 2.96449 1.33337 3.33268 1.33337Z" stroke="#F53F3F" strokeWidth="1.33333" strokeLinejoin="round" />
          <path fillRule="evenodd" clipRule="evenodd" d="M5.99902 6H9.99902V8.6639L6.00179 8.66667L5.99902 6Z" stroke="#F53F3F" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M5.99902 6V11.3333" stroke="#F53F3F" strokeWidth="1.33333" strokeLinecap="round" />
        </>
      );
    }

    if (normalizedType === 'txt') {
      return (
        <>
          <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
          <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
          <path d="M3.33268 1.33337H9.99935L13.3327 4.66671V14C13.3327 14.3682 13.0342 14.6667 12.666 14.6667H3.33268C2.96449 14.6667 2.66602 14.3682 2.66602 14V2.00004C2.66602 1.63185 2.96449 1.33337 3.33268 1.33337Z" stroke="#374151" strokeWidth="1.33333" strokeLinejoin="round" />
          <path d="M5.99902 6.00281H9.99902" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" />
          <path d="M8.00098 6.00281V11.3334" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" />
        </>
      );
    }

    if (normalizedType === 'doc' || normalizedType === 'docx') {
      return (
        <>
          <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
          <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
          <path d="M3.33268 1.33337H9.99935L13.3327 4.66671V14C13.3327 14.3682 13.0342 14.6667 12.666 14.6667H3.33268C2.96449 14.6667 2.66602 14.3682 2.66602 14V2.00004C2.66602 1.63185 2.96449 1.33337 3.33268 1.33337Z" stroke="#024DE3" strokeWidth="1.33333" strokeLinejoin="round" />
          <path d="M5.33594 6.66663L6.33594 11.3333L8.0026 7.99996L9.66927 11.3333L10.6693 6.66663" stroke="#024DE3" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </>
      );
    }

    if (normalizedType === 'md') {
      return (
        <>
          <path d="M3.33366 14.6667H12.667C13.0352 14.6667 13.3337 14.3682 13.3337 14V4.66671L10.3337 1.33337H3.33366C2.96547 1.33337 2.66699 1.63185 2.66699 2.00004V14C2.66699 14.3682 2.96547 14.6667 3.33366 14.6667Z" stroke="#FF7D00" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M7.00098 11.6667L10.3343 8.33333L9.00098 7L5.66764 10.3333V11.6667H7.00098Z" stroke="#FF7D00" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </>
      );
    }

    if (normalizedType === 'html') {
      return (
        <>
          <path d="M3.33366 14.6667H12.667C13.0352 14.6667 13.3337 14.3682 13.3337 14V4.66671L10.3337 1.33337H3.33366C2.96547 1.33337 2.66699 1.63185 2.66699 2.00004V14C2.66699 14.3682 2.96547 14.6667 3.33366 14.6667Z" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </>
      );
    }

    if (normalizedType === 'csv' || normalizedType === 'xls' || normalizedType === 'xlsx') {
      return (
        <>
          <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
          <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
          <path d="M3.33268 1.33337H9.99935L13.3327 4.66671V14C13.3327 14.3682 13.0342 14.6667 12.666 14.6667H3.33268C2.96449 14.6667 2.66602 14.3682 2.66602 14V2.00004C2.66602 1.63185 2.96449 1.33337 3.33268 1.33337Z" stroke="#007D1A" strokeWidth="1.33333" strokeLinejoin="round" />
          <path d="M10.668 5.9729H5.33464V11.3062H10.668" stroke="#007D1A" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M10.668 8.63965H5.33464" stroke="#007D1A" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M8.00391 11.3097L8.00391 5.97632" stroke="#007D1A" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M10.666 11.3097L10.666 5.97632" stroke="#007D1A" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </>
      );
    }

    if (normalizedType === 'png' || normalizedType === 'jpg' || normalizedType === 'jpeg' || normalizedType === 'bmp') {
      return (
        <>
          <path d="M3.33366 14.6667H12.667C13.0352 14.6667 13.3337 14.3682 13.3337 14V4.66671L10.0003 1.33337H3.33366C2.96547 1.33337 2.66699 1.63185 2.66699 2.00004V14C2.66699 14.3682 2.96547 14.6667 3.33366 14.6667Z" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M10.0007 1.33337L13.334 4.66671" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M6 7.00004C6.73638 7.00004 7.33333 6.40309 7.33333 5.66671C7.33333 4.93033 6.73638 4.33337 6 4.33337C5.26362 4.33337 4.66667 4.93033 4.66667 5.66671C4.66667 6.40309 5.26362 7.00004 6 7.00004Z" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M5 9.33333V12.3333H11V7L7.83011 10.5L5 9.33333Z" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </>
      );
    }

    return (
      <>
        <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
        <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
        <path d="M3.33268 1.33337H9.99935L13.3327 4.66671V14C13.3327 14.3682 13.0342 14.6667 12.666 14.6667H3.33268C2.96449 14.6667 2.66602 14.3682 2.66602 14V2.00004C2.66602 1.63185 2.96449 1.33337 3.33268 1.33337Z" stroke="#374151" strokeWidth="1.33333" strokeLinejoin="round" />
        <path d="M5.99902 6.00281H9.99902" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" />
        <path d="M8.00098 6.00281V11.3334" stroke="#374151" strokeWidth="1.33333" strokeLinecap="round" />
      </>
    );
  };

  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn('size-4 shrink-0', className)}
      aria-hidden="true"
    >
      {renderSvgContent()}
    </svg>
  );
}

export function CitationSourceIcon({
  detail,
  preview,
  type,
  className,
  iconClassName,
  fallbackKey,
  ragIconVariant = 'document',
}: {
  detail?: ChatCitation | null;
  preview?: CitationPreview | null;
  type?: string;
  className?: string;
  iconClassName?: string;
  fallbackKey?: string;
  ragIconVariant?: RagIconVariant;
}) {
  const icon = buildCitationSourceIconData({ detail, preview, type, fallbackKey });

  return (
    <span
      className={cn('inline-flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-full', className)}
      title={icon.title}
    >
      {icon.type === 'web' ? (
        <WebSourceIcon icon={icon} iconClassName={iconClassName} />
      ) : ragIconVariant === 'knowledge' ? (
        <BookOpen className={cn('size-4 text-[#86909C]', iconClassName)} />
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
    <span className="inline-flex shrink-0 -space-x-1.5">
      {icons.map((icon) => (
        <span
          key={icon.key}
          className="flex size-5 items-center justify-center overflow-hidden rounded-full border-[4px] border-white bg-white shadow-sm"
          title={icon.title}
        >
          {icon.type === 'web' ? (
            <WebSourceIcon icon={icon} iconClassName="size-full" />
          ) : (
            <CitationFileTypeIcon fileType={icon.fileType || 'txt'} className="size-4" />
          )}
        </span>
      ))}
    </span>
  );
}
