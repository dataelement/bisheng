import { useRef, useState, type ReactNode } from 'react';
import { Outlined } from 'bisheng-icons';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuCheckboxItem, DropdownMenuSeparator } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { KnowledgeSpaceDialog } from './KnowledgeSpaceDialog';
import type { KnowledgeItem } from './knowledgeTypes';
import { useAgentToolSelection, iconForGroup, labelForGroup, type AvailableToolGroup } from './AgentToolSelector';

const EMPTY_TOOLS: AvailableToolGroup[] = [];

interface Props {
  disabled?: boolean;
  availableTools?: AvailableToolGroup[];
  showTools?: boolean;
  showWebSearch?: boolean;
  webSearchActive?: boolean;
  onWebSearchChange?: (active: boolean) => void;
  showResearch?: boolean;
  researchActive?: boolean;
  onResearchChange?: () => void;
  children?: ReactNode;
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
  fileUploadDisabled, value, onChange, onFileUploadClick, onFolderUploadClick,
  availableTools = EMPTY_TOOLS, showTools, showWebSearch, webSearchActive, onWebSearchChange,
  showResearch, researchActive, onResearchChange, children }: Props) {
  const localize = useLocalize();
  const { isChecked, toggle } = useAgentToolSelection(availableTools);
  const activeSearchGroups = showTools
    ? availableTools.filter((group) => isChecked(group.id)
      && group.children?.some((child) => child.tool_key === 'web_search'))
    : [];
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [selecting, setSelecting] = useState(false);
  return <>
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button ref={trigger} type="button" className="dsh-composer-add" disabled={disabled}
          title={localize('dshChat.addContext')} aria-label={localize('dshChat.addContext')}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true" strokeWidth="1.3">
            <path d="M8 2V14M2 8H14" stroke="currentColor" />
          </svg>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" sideOffset={8} collisionPadding={12}
        className="dsh-chat-menu dsh-add-menu w-[248px] p-1" onCloseAutoFocus={(event) => { if (selecting) event.preventDefault(); }}>
        {showFileUpload && <DropdownMenuItem disabled={fileUploadDisabled} onSelect={onFileUploadClick} className="gap-2">
          <Outlined.Attachment size={16} />{localize('com_ui_upload_files')}
        </DropdownMenuItem>}
        {showFileUpload && onFolderUploadClick && <DropdownMenuItem disabled={fileUploadDisabled} onSelect={onFolderUploadClick} className="gap-2">
          <Outlined.FolderClose size={16} />{localize('com_ui_upload_folder')}
        </DropdownMenuItem>}
        {showKnowledgeSelection && <DropdownMenuItem onSelect={() => { setOpen(false); setSelecting(true); }} className="gap-2">
          <Outlined.FolderClose size={16} />{localize('dshChat.selectKnowledge')}
        </DropdownMenuItem>}
        {(showTools || showWebSearch || showResearch || children) && <DropdownMenuSeparator />}
        {showTools && availableTools.map((group) => <DropdownMenuCheckboxItem key={group.id}
          checked={isChecked(group.id)} disabled={disabled}
          onCheckedChange={() => toggle(group)} onSelect={(event) => event.preventDefault()} className="gap-2">
          {iconForGroup(group)}<span className="min-w-0 truncate">{labelForGroup(group, localize)}</span>
        </DropdownMenuCheckboxItem>)}
        {showWebSearch && <DropdownMenuCheckboxItem checked={webSearchActive}
          disabled={disabled} onCheckedChange={onWebSearchChange} onSelect={(event) => event.preventDefault()} className="gap-2">
          <Outlined.Earth size={16} />{localize('com_tools_web_search')}
        </DropdownMenuCheckboxItem>}
        {showResearch && <DropdownMenuCheckboxItem checked={researchActive}
          disabled={disabled} onCheckedChange={onResearchChange} className="gap-2">
          <Outlined.ListSuccess size={16} />{localize('com_linsight_task_mode')}
        </DropdownMenuCheckboxItem>}
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
    <div className="dsh-active-capabilities">
      {activeSearchGroups.map((group) => <button key={group.id} type="button"
        className="dsh-composer-control dsh-active-capability" aria-pressed="true" disabled={disabled}
        onClick={() => toggle(group)}>
        <Outlined.Earth size={14} /><span>{labelForGroup(group, localize)}</span><Outlined.Close size={12} />
      </button>)}
      {showWebSearch && webSearchActive && <button type="button"
        className="dsh-composer-control dsh-active-capability" aria-pressed="true" disabled={disabled}
        onClick={() => onWebSearchChange?.(false)}>
        <Outlined.Earth size={14} /><span>{localize('com_tools_web_search')}</span><Outlined.Close size={12} />
      </button>}
      {showResearch && researchActive && <button type="button"
        className="dsh-composer-control dsh-active-capability" aria-pressed="true" disabled={disabled}
        onClick={onResearchChange}>
        <Outlined.ListSuccess size={14} /><span>{localize('com_linsight_task_mode')}</span><Outlined.Close size={12} />
      </button>}
    </div>
    {selecting && <KnowledgeSpaceDialog value={value} onConfirm={onChange} onClose={() => {
      setSelecting(false);
      requestAnimationFrame(() => trigger.current?.focus());
    }} />}
  </>;
}
