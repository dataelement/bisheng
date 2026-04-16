import { useState } from "react";
import { Globe2 } from "lucide-react";
import { BookOpenIcon } from "@/components/bs-icons/bookOpen";
import { FileIcon, type FileType } from "@/components/bs-icons/file";
import { cname } from "@/components/bs-ui/utils";
import type { ChatCitation } from "@/controllers/API";
import {
  buildCitationDocumentPreview,
  getCitationDocumentFileType,
  getCitationDocumentName,
  normalizeCitationType,
  type CitationPreview,
  type CitationReferenceItem,
} from "./citationUtils";

export type CitationSourceIconData = {
  key: string;
  type: "web" | "rag";
  title: string;
  faviconUrl?: string;
  fileType?: FileType;
};

type RagIconVariant = "document" | "knowledge";

const supportedFileTypes = new Set<FileType>([
  "pdf",
  "doc",
  "docx",
  "ppt",
  "pptx",
  "md",
  "html",
  "txt",
  "jpg",
  "jpeg",
  "png",
  "bmp",
  "csv",
  "xls",
  "xlsx",
]);

function normalizeFileType(type?: string): FileType {
  const normalizedType = String(type || "").toLowerCase().replace(/^\./, "") as FileType;
  return supportedFileTypes.has(normalizedType) ? normalizedType : "txt";
}

function getFaviconUrl(url?: string) {
  if (!url) {
    return "";
  }

  try {
    const parsedUrl = new URL(url, window.location.origin);
    return `${parsedUrl.origin}/favicon.ico`;
  } catch {
    return "";
  }
}

function resolvePreviewUrl(detail?: ChatCitation | null, preview?: CitationPreview | null) {
  return preview?.link || detail?.sourcePayload?.url || detail?.sourcePayload?.sourceUrl || "";
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
  type: "web" | "rag";
}) {
  if (type === "web") {
    return resolvePreviewUrl(detail, preview) || item.data.citationId;
  }

  return (detail ? getCitationDocumentName(detail) : "") || preview?.title || item.data.groupKey || item.data.citationId;
}

export function buildCitationSourceIconData({
  detail,
  preview,
  type,
  fallbackKey = "source",
}: {
  detail?: ChatCitation | null;
  preview?: CitationPreview | null;
  type?: string;
  fallbackKey?: string;
}): CitationSourceIconData {
  const normalizedType = normalizeCitationType(preview?.type || detail?.type || type);

  if (normalizedType === "web") {
    return {
      key: `web:${resolvePreviewUrl(detail, preview) || fallbackKey}`,
      type: "web",
      title: preview?.title || detail?.sourcePayload?.title || "网页",
      faviconUrl: getFaviconUrl(resolvePreviewUrl(detail, preview)),
    };
  }

  return {
    key: `rag:${(detail ? getCitationDocumentName(detail) : "") || preview?.title || fallbackKey}`,
    type: "rag",
    title: preview?.title || (detail ? getCitationDocumentName(detail) : "文档"),
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
    return <Globe2 className={cname("size-4 text-[#7C3AED]", iconClassName)} />;
  }

  return (
    <img
      src={icon.faviconUrl}
      alt=""
      className={cname("size-full rounded-full object-cover", iconClassName)}
      onError={() => setImageFailed(true)}
    />
  );
}

export function CitationSourceIcon({
  detail,
  preview,
  type,
  className,
  iconClassName,
  fallbackKey,
  ragIconVariant = "document",
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
      className={cname("inline-flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-full", className)}
      title={icon.title}
    >
      {icon.type === "web" ? (
        <WebSourceIcon icon={icon} iconClassName={iconClassName} />
      ) : ragIconVariant === "knowledge" ? (
        <BookOpenIcon className={cname("size-4 text-[#86909C]", iconClassName)} />
      ) : (
        <FileIcon
          type={icon.fileType || "txt"}
          className={cname("!size-4 !min-w-4 !rounded-[4px] !p-0.5", iconClassName)}
        />
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
          {icon.type === "web" ? (
            <WebSourceIcon icon={icon} iconClassName="size-full" />
          ) : (
            <FileIcon
              type={icon.fileType || "txt"}
              className="!size-5 !min-w-5 !rounded-[4px] !p-1"
            />
          )}
        </span>
      ))}
    </span>
  );
}
