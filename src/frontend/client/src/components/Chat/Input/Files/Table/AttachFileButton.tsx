// @ts-strict-ignore
import { Tooltip as SharedTooltip } from '@bisheng/ui';
import React, { useRef } from 'react';
import { Button, FileUpload } from '~/components/ui';
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
      <SharedTooltip  content={localize('com_sidepanel_attach_files')}  ><div role="button" id="attach-file" aria-label={localize('com_sidepanel_attach_files')} disabled={isUploadDisabled} className={cn(
          'flex items-center justify-center rounded-full p-1 transition-colors focus-visible:outline-none dark:focus-visible:outline-none ',
        )} onKeyDownCapture={(e) => {
          if (disabled) return
          if (!inputRef.current) {
            return;
          }
          if (e.key === 'Enter' || e.key === ' ') {
            inputRef.current.value = '';
            inputRef.current.click();
          }
        }} onClick={() => {
          if (!inputRef.current) {
            return;
          }
          inputRef.current.value = '';
          inputRef.current.click();
        }} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.currentTarget.click(); } }}><div className="flex w-full items-center justify-center gap-2">
          <Button disabled={isUploadDisabled}>
            {disabled && <Loader2 className='animate-spin' />}
            {localize('com_knowledge_add_file')}</Button>
        </div></div></SharedTooltip>
    </FileUpload>
  );
};

export default React.memo(AttachFileButton);
