import { useRef, useState } from 'react';
import { Outlined } from 'bisheng-icons';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { KnowledgeSpaceDialog } from './KnowledgeSpaceDialog';
import type { KnowledgeItem } from './knowledgeTypes';

interface Props {
  disabled?: boolean;
  showKnowledgeSelection?: boolean;
  showFileUpload?: boolean;
  fileUploadDisabled?: boolean;
  value: KnowledgeItem[];
  onChange: (value: KnowledgeItem[]) => void;
  onFileUploadClick?: () => void;
  onFolderUploadClick?: () => void;
}

/** Chat context sources: local files and authorized knowledge spaces. */
export function ChatResourceMenu({ disabled, showKnowledgeSelection, showFileUpload,
  fileUploadDisabled, value, onChange, onFileUploadClick, onFolderUploadClick }: Props) {
  const localize = useLocalize();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [selecting, setSelecting] = useState(false);
  return <>
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button ref={trigger} type="button" className="dsh-composer-add" disabled={disabled}
          title={localize('dshChat.addContext')} aria-label={localize('dshChat.addContext')}>
          <Outlined.Plus size={18} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" sideOffset={8} collisionPadding={12}
        className="dsh-chat-menu w-[224px] p-2" onCloseAutoFocus={(event) => { if (selecting) event.preventDefault(); }}>
        {showFileUpload && <DropdownMenuItem disabled={fileUploadDisabled} onSelect={onFileUploadClick} className="gap-2">
          <Outlined.Attachment size={16} />{localize('com_ui_upload_files')}
        </DropdownMenuItem>}
        {showFileUpload && onFolderUploadClick && <DropdownMenuItem disabled={fileUploadDisabled} onSelect={onFolderUploadClick} className="gap-2">
          <Outlined.FolderClose size={16} />{localize('com_ui_upload_folder')}
        </DropdownMenuItem>}
        {showKnowledgeSelection && <DropdownMenuItem onSelect={() => { setOpen(false); setSelecting(true); }} className="gap-2">
          <Outlined.FolderClose size={16} />{localize('dshChat.selectKnowledge')}
        </DropdownMenuItem>}
      </DropdownMenuContent>
    </DropdownMenu>
    {selecting && <KnowledgeSpaceDialog value={value} onConfirm={onChange} onClose={() => {
      setSelecting(false);
      requestAnimationFrame(() => trigger.current?.focus());
    }} />}
  </>;
}
