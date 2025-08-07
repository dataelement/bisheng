import type { TFile } from '~/data-provider/data-provider/src';
import type { ExtendedFile } from '~/common';
import FilePreview from './FilePreview';
import RemoveFile from './RemoveFile';
import { getFileType } from '~/utils';

const FileContainer = ({
  file,
  onDelete,
}: {
  file: ExtendedFile | TFile;
  onDelete?: () => void;
}) => {

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
        <div className="w-56 bg-white p-4">
          <div className="flex flex-row items-center gap-2">
            <FilePreview file={file} fileType={fileType} className="relative" />
            <div className="overflow-hidden">
              <div className="truncate" title={file.filename}>
                {file.filename}
              </div>
              {/* <div className="truncate text-text-secondary" title={fileType.title}>
                {fileType.title}
              </div> */}
            </div>
          </div>
        </div>
      </div>
      {onDelete && <RemoveFile onRemove={onDelete} />}
    </div>
  );
};

export default FileContainer;
