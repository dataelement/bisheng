import { KnowledgeFileArtwork } from "@bisheng/file-viewers/knowledge-artwork";
import { Outlined } from "bisheng-icons";
import { FileIcon, type FileType } from "@/components/bs-icons/file";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";

interface SpaceDirectoryIconProps {
  item: KnowledgeSpaceChild;
  layout?: "list" | "card";
}

export function SpaceDirectoryIcon({ item, layout }: SpaceDirectoryIconProps) {
  const isFolder = item.file_type === 0;
  if (!layout) {
    const extension = item.file_name.split(".").pop()?.toLowerCase() ?? "txt";
    return isFolder
      ? <Outlined.FolderClose aria-hidden="true" />
      : <FileIcon type={extension as FileType} />;
  }

  const kind = item.file_source === "web_link" ? "html"
    : item.file_source === "audio_transcript" ? "audio"
    : item.file_source === "video_transcript" ? "video"
    : undefined;
  const list = layout === "list";

  return (
    <KnowledgeFileArtwork
      name={item.file_name}
      isFolder={isFolder}
      parsed={item.status === 2}
      kind={kind}
      thumbnail={item.thumbnails}
      thumbnailAlt=""
      iconClassName={list ? "size-8 shrink-0" : undefined}
      thumbBordered={list}
      transparentBg={list}
    />
  );
}
