import type { TFile } from '~/types/chat';
import type { ExtendedFile } from '~/common';
import FilePreview from './FilePreview';
import RemoveFile from './RemoveFile';
import { getFileType, cn } from '~/utils';
import { getFileTypebyFileName } from '~/components/ui/icon/File/FileIcon';
import { useLocalize } from '~/hooks';
import { useMemo } from 'react';

const FileContainer = ({
  file,
  onDelete,
}: {
  file: ExtendedFile | TFile;
  onDelete?: () => void;
}) => {

  // 聊天框兼容展示文件名
  const currentFile = useMemo(() => {
    if (!file.filename && file.filepath) {
      const fileName = file.filepath.split('/').pop()?.split('?').shift() || '';
      return {
        ...file,
        filename: decodeURIComponent(fileName),
      };
    }
    return file;
  }, [file]);

  function getFileSuffix(file) {
    if (file.type) {
      return file.type;
    }

    if (!file.filename) return 'artifact';

    // Extract file extension
    const extension = file.filename.split('.').pop().toLowerCase();

    // Match extensions to types
    switch (extension) {
      case 'txt':
      case 'md':
      case 'html':
      case 'htm':
        return 'text';

      case 'csv':
        return 'csv';

      case 'pdf':
        return 'pdf';

      default:
        return 'file';
    }
  }

  const fileType = getFileType(getFileSuffix(file));
  const localize = useLocalize();
  // Task-mode ingestion result: the attachment could not be parsed into the
  // workspace, so the model never saw it (the task still ran without it).
  const parseFailed = file.parsing_status === 'failed' || file.valid === false;

  return (
    <div className="group relative inline-block text-sm text-text-primary">
      <div
        className={cn(
          'relative overflow-hidden rounded-2xl border',
          parseFailed && 'border-red-300',
        )}
      >
        <div className={cn('w-56 bg-white p-2', parseFailed && 'opacity-60')}>
          <div className="flex flex-row items-center gap-2">
            <FilePreview file={currentFile} fileType={fileType} className="relative" />
            <div className="overflow-hidden">
              <div className="truncate font-bold" title={currentFile.filename}>
                {currentFile.filename}
              </div>
              <div
                className={cn('truncate', parseFailed ? 'text-red-500' : 'text-text-secondary')}
                title={parseFailed ? (file.error_message || localize('com_file_parse_failed')) : fileType.title}
              >
                {parseFailed
                  ? localize('com_file_parse_failed')
                  : currentFile.filename && getFileTypebyFileName(currentFile.filename)}
              </div>
            </div>
          </div>
        </div>
      </div>
      {onDelete && <RemoveFile onRemove={onDelete} />}
    </div>
  );
};

export default FileContainer;
