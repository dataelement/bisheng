import { useState, useRef, memo } from 'react';
import { createPortal } from 'react-dom';
import { Ellipsis } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import type { MouseEvent } from 'react';
import { useDuplicateConversationMutation, useGetStartupConfig } from '~/hooks/queries/data-provider';
import { useLocalize, useArchiveHandler, useNavigateToConvo } from '~/hooks';
import { useToastContext, useChatContext } from '~/Providers';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import { ActionMenuContent, ActionMenuItem } from '~/components/ActionMenu';
import { useDeleteConversationConfirm } from './useDeleteConversationConfirm';
import ShareButton from './ShareButton';
import { cn } from '~/utils';

function ConvoOptions({
  conversationId,
  title,
  retainView,
  renameHandler,
  isPopoverActive,
  setIsPopoverActive,
  isActiveConvo,
  contextMenuOpen = false,
  contextMenuPosition,
  onContextMenuOpenChange,
}: {
  conversationId: string | null;
  title: string | null;
  retainView: () => void;
  renameHandler: (e: MouseEvent) => void;
  isPopoverActive: boolean;
  setIsPopoverActive: React.Dispatch<React.SetStateAction<boolean>>;
  isActiveConvo: boolean;
  /** Cursor-anchored right-click menu state, owned by the row (desktop only). */
  contextMenuOpen?: boolean;
  contextMenuPosition?: { x: number; y: number };
  onContextMenuOpenChange?: (open: boolean) => void;
}) {
  const localize = useLocalize();
  const { index } = useChatContext();
  const { data: startupConfig } = useGetStartupConfig();
  const archiveHandler = useArchiveHandler(conversationId, true, retainView);
  const { navigateToConvo } = useNavigateToConvo(index);
  const { showToast } = useToastContext();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [showShareDialog, setShowShareDialog] = useState(false);
  const deleteConversationConfirm = useDeleteConversationConfirm();

  const duplicateConversation = useDuplicateConversationMutation({
    onSuccess: (data) => {
      navigateToConvo(data.conversation);
      showToast({
        message: localize('com_ui_duplication_success'),
        status: 'success',
      });
    },
    onMutate: () => {
      showToast({
        message: localize('com_ui_duplication_processing'),
        status: 'info',
      });
    },
    onError: () => {
      showToast({
        message: localize('com_ui_duplication_error'),
        status: 'error',
      });
    },
  });

  const handleRename = (e: Event) => {
    renameHandler(e as unknown as MouseEvent);
  };

  const handleDelete = () => {
    if (!conversationId) {
      return;
    }
    deleteConversationConfirm({ conversationId, title: title ?? '', retainView });
  };

  // Shared items, reused by the "..." dropdown and the row's right-click menu.
  const menuItems = (
    <>
      <ActionMenuItem
        icon={<Outlined.Edit />}
        label={localize('com_ui_rename')}
        onSelect={handleRename}
      />
      <ActionMenuItem
        danger
        icon={<Outlined.Delete />}
        label={localize('com_ui_delete')}
        onSelect={handleDelete}
      />
    </>
  );

  return (
    <>
      <DropdownMenu open={isPopoverActive} onOpenChange={setIsPopoverActive}>
        <DropdownMenuTrigger asChild>
          <button
            ref={triggerRef}
            type="button"
            id={`conversation-menu-${conversationId}`}
            aria-label={localize('com_nav_convo_menu_options')}
            className={cn(
              'z-30 inline-flex h-4 w-4 items-center justify-center gap-2 rounded-md border-none p-0 text-sm font-medium text-[#86909c] ring-ring-primary transition-all duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 fine-pointer:hover:text-[#1d2129]',
              isActiveConvo
                ? 'opacity-100'
                : 'opacity-0 focus:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100 coarse-pointer:opacity-100',
            )}
            onClick={(e) => e.stopPropagation()}
          >
            <Ellipsis className="icon-md" aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <ActionMenuContent
          width={140}
          onClick={(e) => e.stopPropagation()}
        >
          {menuItems}
        </ActionMenuContent>
      </DropdownMenu>
      {/* Right-click menu: an invisible cursor-anchored trigger drives the same
          items as the "..." menu. Portaled to <body> so `position: fixed` anchors
          to the viewport regardless of ancestor containing blocks (WeCom WebView). */}
      {onContextMenuOpenChange && contextMenuPosition && createPortal(
        <DropdownMenu open={contextMenuOpen} onOpenChange={onContextMenuOpenChange}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-hidden="true"
              tabIndex={-1}
              className="fixed size-0 opacity-0"
              style={{ left: contextMenuPosition.x, top: contextMenuPosition.y }}
              onClick={(e) => e.stopPropagation()}
            />
          </DropdownMenuTrigger>
          <ActionMenuContent
            width={140}
            onClick={(e) => e.stopPropagation()}
          >
            {menuItems}
          </ActionMenuContent>
        </DropdownMenu>,
        document.body,
      )}
      {showShareDialog && (
        <ShareButton
          conversationId={conversationId ?? ''}
          open={showShareDialog}
          onOpenChange={setShowShareDialog}
          triggerRef={triggerRef}
        />
      )}
    </>
  );
}

export default memo(ConvoOptions);
