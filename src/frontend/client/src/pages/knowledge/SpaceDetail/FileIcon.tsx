import { KnowledgeFileArtwork } from "@bisheng/file-viewers/knowledge-artwork";
import { FileStatus, FileType, type KnowledgeFile } from "~/api/knowledge";

interface FileIconRendererProps {
  file: KnowledgeFile;
  isFolder: boolean;
  iconClassName?: string;
  thumbBordered?: boolean;
  transparentBg?: boolean;
}

export function FileIconRenderer({ file, ...props }: FileIconRendererProps) {
  const kind = file.type === FileType.WEB ? "html"
    : file.type === FileType.AUDIO ? "audio"
    : file.type === FileType.VIDEO ? "video"
    : undefined;
  return (
    <KnowledgeFileArtwork
      {...props}
      name={file.name}
      kind={kind}
      parsed={file.status === FileStatus.SUCCESS}
      thumbnail={file.thumbnail}
    />
  );
}

export { FileIconRenderer as default };
