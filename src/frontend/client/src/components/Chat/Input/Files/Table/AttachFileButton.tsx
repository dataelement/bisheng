import React, { useRef } from 'react';
import { Button, FileUpload, TooltipAnchor } from '~/components/ui';
import { AttachmentIcon } from '~/components/svg';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { Loader2 } from 'lucide-react';

const AttachFileButton = ({
  disabled,
  handleFileChange,
}: {
  disabled?: boolean | null;
  handleFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
}) => {
  const localize = useLocalize();
  const inputRef = useRef<HTMLInputElement>(null);
  const isUploadDisabled = disabled ?? false;

  return (
    <FileUpload ref={inputRef} handleFileChange={handleFileChange}>
      <TooltipAnchor
        role="button"
        id="attach-file"
        aria-label={localize('com_sidepanel_attach_files')}
        disabled={isUploadDisabled}
        className={cn(
          'flex items-center justify-center rounded-full p-1 transition-colors focus-visible:outline-none dark:focus-visible:outline-none ',
        )}
        description={localize('com_sidepanel_attach_files')}
        onKeyDownCapture={(e) => {
          if (disabled) return
          if (!inputRef.current) {
            return;
          }
          if (e.key === 'Enter' || e.key === ' ') {
            inputRef.current.value = '';
            inputRef.current.click();
          }
        }}
        onClick={() => {
          if (!inputRef.current) {
            return;
          }
          inputRef.current.value = '';
          inputRef.current.click();
        }}
      >
        <div className="flex w-full items-center justify-center gap-2">
          <Button disabled={isUploadDisabled}>
            {disabled && <Loader2 className='animate-spin' />}
            添加文件</Button>
        </div>
      </TooltipAnchor>
    </FileUpload>
  );
};

export default React.memo(AttachFileButton);
