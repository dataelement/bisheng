import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Outlined } from 'bisheng-icons';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuCheckboxItem } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { ComposerMenuContext } from './ComposerSubmenu';
import { KnowledgeSpaceDialog } from './KnowledgeSpaceDialog';
import { useComposerMenuAnchor } from './useComposerMenuAnchor';
import type { KnowledgeItem } from './knowledgeTypes';
import { useAgentToolSelection, iconForGroup, labelForGroup, type AvailableToolGroup } from './AgentToolSelector';

/** Match Harness: one 16px surface fade, only while more rows remain below. */
function ComposerMenuScroll({ children }: { children: ReactNode }) {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [overflowBelow, setOverflowBelow] = useState(false);
  useLayoutEffect(() => {
    const element = viewport.current;
    const body = content.current;
    if (!element || !body) return;
    const update = () => setOverflowBelow(
      element.scrollHeight - element.clientHeight - element.scrollTop > 1,
    );
    const observer = new ResizeObserver(update);
    observer.observe(element);
    observer.observe(body);
    element.addEventListener('scroll', update, { passive: true });
    update();
    return () => {
      observer.disconnect();
      element.removeEventListener('scroll', update);
    };
  }, []);
  return <div className="dsh-command-scroll-frame" data-overflow-below={overflowBelow || undefined}>
    <div ref={viewport} className="dsh-command-scroll">
      <div ref={content}>{children}</div>
    </div>
  </div>;
}

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
  const activeToolGroups = showTools
    ? availableTools.filter((group) => isChecked(group.id))
    : [];
  const trigger = useRef<HTMLButtonElement>(null);
  const pointerOpened = useRef(false);
  const returnFocus = () => {
    const target = pointerOpened.current
      ? trigger.current?.closest('.dsh-chat-composer')?.querySelector<HTMLElement>('[contenteditable="true"]')
      : trigger.current;
    target?.focus({ preventScroll: true });
  };
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);
  const anchor = useComposerMenuAnchor(trigger, open);
  return <>
    <DropdownMenu open={open} onOpenChange={(next) => { setOpen(next); if (!next) setPage(null); }}>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button ref={trigger} type="button" className="dsh-composer-add" disabled={disabled}
          title={localize('dshChat.addContext')} aria-label={localize('dshChat.addContext')}
          onPointerDown={() => { pointerOpened.current = true; }}
          onKeyDown={() => { pointerOpened.current = false; }}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true" strokeWidth="1.3">
            <path d="M8 2V14M2 8H14" stroke="currentColor" />
          </svg>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" sideOffset={anchor.sideOffset} alignOffset={anchor.alignOffset} collisionPadding={12}
        style={{ width: anchor.width }}
        className="dsh-chat-menu dsh-add-menu dsh-command-panel" onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (!selecting) returnFocus();
        }}>
        <ComposerMenuScroll>
        <ComposerMenuContext.Provider value={{ page, setPage }}>
        {!page && <>
        {showFileUpload && <DropdownMenuItem aria-label={localize('com_ui_upload_files')} disabled={fileUploadDisabled} onSelect={onFileUploadClick} className="gap-2">
          <Outlined.Attachment size={16} /><span className="dsh-command-name">{localize('com_ui_upload_files')}</span>
          <span className="dsh-command-description">{localize('dshChat.uploadDescription')}</span>
        </DropdownMenuItem>}
        {showFileUpload && onFolderUploadClick && <DropdownMenuItem disabled={fileUploadDisabled} onSelect={onFolderUploadClick} className="gap-2">
          <Outlined.FolderClose size={16} /><span className="dsh-command-name">{localize('com_ui_upload_folder')}</span>
        </DropdownMenuItem>}
        {showKnowledgeSelection && <DropdownMenuItem aria-label={localize('dshChat.selectKnowledge')} onSelect={() => { setOpen(false); setSelecting(true); }} className="gap-2">
          <Outlined.FolderClose size={16} /><span className="dsh-command-name">{localize('dshChat.selectKnowledge')}</span>
          <span className="dsh-command-description">{localize('dshChat.knowledgeDescription')}</span>
        </DropdownMenuItem>}
        {showTools && availableTools.map((group) => <DropdownMenuCheckboxItem key={group.id}
          aria-label={labelForGroup(group, localize)} indicatorSide="right" checked={isChecked(group.id)} disabled={disabled}
          onCheckedChange={() => toggle(group)} onSelect={(event) => event.preventDefault()} className="gap-2">
          {iconForGroup(group)}<span className="dsh-command-name">{labelForGroup(group, localize)}</span>
          <span className="dsh-command-description">{group.description}</span>
        </DropdownMenuCheckboxItem>)}
        {showWebSearch && <DropdownMenuCheckboxItem aria-label={localize('com_tools_web_search')} indicatorSide="right" checked={webSearchActive}
          disabled={disabled} onCheckedChange={onWebSearchChange} onSelect={(event) => event.preventDefault()} className="gap-2">
          <Outlined.Earth size={16} /><span className="dsh-command-name">{localize('com_tools_web_search')}</span>
          <span className="dsh-command-description">{localize('dshChat.searchDescription')}</span>
        </DropdownMenuCheckboxItem>}
        {showResearch && <DropdownMenuCheckboxItem aria-label={localize('com_linsight_task_mode')} indicatorSide="right" checked={researchActive}
          disabled={disabled} onCheckedChange={onResearchChange} className="gap-2">
          <Outlined.ListSuccess size={16} /><span className="dsh-command-name">{localize('com_linsight_task_mode')}</span>
          <span className="dsh-command-description">{localize('dshChat.taskDescription')}</span>
        </DropdownMenuCheckboxItem>}
        </>}
        {children}
        </ComposerMenuContext.Provider>
        </ComposerMenuScroll>
      </DropdownMenuContent>
    </DropdownMenu>
    <div className="dsh-active-capabilities">
      {activeToolGroups.map((group) => <button key={group.id} type="button"
        className="dsh-composer-control dsh-active-capability" aria-pressed="true" disabled={disabled}
        onClick={() => toggle(group)}>
        {iconForGroup(group)}<span>{labelForGroup(group, localize)}</span><Outlined.Close size={12} />
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
      requestAnimationFrame(returnFocus);
    }} />}
  </>;
}
