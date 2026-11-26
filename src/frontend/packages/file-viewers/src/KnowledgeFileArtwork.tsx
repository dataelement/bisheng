import cn from "@bisheng/ui/cn";
import { Colored, Outlined } from "bisheng-icons";
import { useState } from "react";
import { FolderIcon } from "./FolderIcon";
import { TxtIcon } from "./TxtIcon";
import { getViewerType } from "./formats";

export { FolderIcon, TxtIcon };

const icons = {
  folder: FolderIcon,
  doc: Colored.FileDoc,
  ppt: Colored.FilePptx,
  xls: Colored.FileXls,
  csv: Colored.FileCsv,
  txt: Colored.FileTxt,
  md: Colored.FileMd,
  html: Colored.FileHtml,
  audio: Colored.FileAudio,
  video: Colored.FileVideo,
};

type ArtworkKind = keyof typeof icons;

const backgrounds: Record<ArtworkKind, string> = {
  folder: "bg-[linear-gradient(180deg,rgba(240,246,253,0.05)_0%,rgb(var(--brand-500)/0.05)_100%)]",
  doc: "bg-[linear-gradient(180deg,rgba(223,238,255,0.05)_0%,rgba(0,114,255,0.05)_100%)]",
  ppt: "bg-[linear-gradient(180deg,rgba(255,231,233,0.05)_0%,rgba(255,62,76,0.05)_100%)]",
  xls: "bg-[linear-gradient(180deg,rgba(226,245,234,0.05)_0%,rgba(0,198,80,0.05)_100%)]",
  csv: "bg-[linear-gradient(180deg,rgba(226,245,234,0.05)_0%,rgba(0,198,80,0.05)_100%)]",
  txt: "bg-[linear-gradient(180deg,rgba(225,227,230,0.05)_0%,rgba(52,64,84,0.05)_100%)]",
  md: "bg-[linear-gradient(180deg,rgba(225,227,230,0.05)_0%,rgba(52,64,84,0.05)_100%)]",
  html: "bg-[linear-gradient(180deg,rgba(225,227,230,0.05)_0%,rgba(52,64,84,0.05)_100%)]",
  audio: "bg-[linear-gradient(180deg,rgba(255,243,223,0.05)_0%,rgba(255,153,8,0.05)_100%)]",
  video: "bg-[linear-gradient(180deg,rgba(243,231,255,0.05)_0%,rgba(161,64,255,0.05)_100%)]",
};

const extensionKinds = new Map<string, ArtworkKind>([
  ["doc", "doc"], ["docx", "doc"], ["wps", "doc"],
  ["ppt", "ppt"], ["pptx", "ppt"], ["dps", "ppt"],
  ["xls", "xls"], ["xlsx", "xls"], ["et", "xls"],
  ["csv", "csv"], ["txt", "txt"], ["md", "md"], ["markdown", "md"], ["html", "html"], ["htm", "html"],
  ["mp3", "audio"], ["wav", "audio"], ["m4a", "audio"], ["aac", "audio"], ["flac", "audio"], ["ogg", "audio"],
  ["mp4", "video"], ["mov", "video"], ["avi", "video"], ["mkv", "video"], ["webm", "video"],
]);

const iconOnlyKinds = new Set<ArtworkKind>(["folder", "md", "txt", "csv", "html"]);
const slotClass = "flex size-full items-center justify-center";
const getExtension = (name: string) => name.split(".").pop()?.toLowerCase() ?? "";

interface KnowledgeFileTypeIconProps {
  name: string;
  className?: string;
}

export function KnowledgeFileTypeIcon({ name, className }: KnowledgeFileTypeIconProps) {
  const extension = getExtension(name);
  const kind = extensionKinds.get(extension);
  if (kind) {
    const Icon = icons[kind];
    return <Icon aria-hidden="true" className={className} />;
  }

  const Icon = extension === "pdf" ? Outlined.FilePdf
    : getViewerType(extension) === "image" ? Outlined.FileImage
    : Outlined.File;
  return <Icon aria-hidden="true" className={cn("text-text-3", className)} />;
}

interface KnowledgeFileArtworkProps {
  name: string;
  isFolder?: boolean;
  parsed: boolean;
  kind?: "html" | "audio" | "video";
  thumbnail?: string | null;
  thumbnailAlt?: string;
  iconClassName?: string;
  thumbBordered?: boolean;
  transparentBg?: boolean;
}

export function KnowledgeFileArtwork({
  name,
  isFolder,
  parsed,
  kind,
  thumbnail,
  thumbnailAlt = name,
  iconClassName = "size-16 shrink-0",
  thumbBordered,
  transparentBg,
}: KnowledgeFileArtworkProps) {
  const [failedThumbnail, setFailedThumbnail] = useState<string | null>(null);
  const knownKind = isFolder ? "folder" : kind ?? extensionKinds.get(getExtension(name));

  if (!isFolder && !parsed) {
    return (
      <span className={slotClass}>
        <TxtIcon aria-hidden="true" className={iconClassName} />
      </span>
    );
  }

  if (thumbnail && thumbnail !== failedThumbnail && (!knownKind || !iconOnlyKinds.has(knownKind))) {
    return (
      <img
        src={thumbnail}
        alt={thumbnailAlt}
        loading="lazy"
        decoding="async"
        className={cn("size-full object-cover object-top", thumbBordered && "rounded-md border border-border-base")}
        onError={() => setFailedThumbnail(thumbnail)}
      />
    );
  }

  const resolvedKind = knownKind ?? "txt";
  const Icon = icons[resolvedKind];
  return (
    <span className={cn(slotClass, !transparentBg && backgrounds[resolvedKind])}>
      <Icon aria-hidden="true" className={iconClassName} />
    </span>
  );
}
