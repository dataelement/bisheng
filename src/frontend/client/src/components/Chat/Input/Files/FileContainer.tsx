import type { TFile } from '~/data-provider/data-provider/src';
import type { ExtendedFile } from '~/common';
import FilePreview from './FilePreview';
import RemoveFile from './RemoveFile';
import { getFileType } from '~/utils';
import { getFileTypebyFileName } from '~/components/ui/icon/File/FileIcon';
import { useMemo } from 'react';

const FileContainer = ({
  file,
  onDelete,
}: {
  file: ExtendedFile | TFile;
  onDelete?: () => void;
}) => {

  const currentFile = useMemo(() => {
    if (!file.filename) {
      const fileName = file.filepath.split('/').pop();
      return {
        ...file,
        filename: fileName,
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

  return (
    <div className="group relative inline-block text-sm text-text-primary">
      <div className="relative overflow-hidden rounded-2xl border">
        <div className="w-56 bg-white p-2">
          <div className="flex flex-row items-center gap-2">
            <FilePreview file={currentFile} fileType={fileType} className="relative" />
            <div className="overflow-hidden">
              <div className="truncate font-bold" title={currentFile.filename}>
                {currentFile.filename}
              </div>
              <div className="truncate text-text-secondary" title={fileType.title}>
                {currentFile.filename && getFileTypebyFileName(currentFile.filename)}
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
