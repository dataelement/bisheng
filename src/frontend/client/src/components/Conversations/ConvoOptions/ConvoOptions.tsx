import { useState, useRef, memo } from 'react';
import { Ellipsis } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import { useDuplicateConversationMutation, useGetStartupConfig } from '~/hooks/queries/data-provider';
import { useLocalize, useArchiveHandler, useNavigateToConvo } from '~/hooks';
import { useToastContext, useChatContext } from '~/Providers';
import { Dropdown, DropdownItem, DropdownSeparator } from '@bisheng/ui';
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
}: {
  conversationId: string | null;
  title: string | null;
  retainView: () => void;
  renameHandler: () => void;
  isPopoverActive: boolean;
  setIsPopoverActive: React.Dispatch<React.SetStateAction<boolean>>;
  isActiveConvo: boolean;
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
        status: 'warning',
      });
    },
  });

  const handleDelete = () => {
    if (!conversationId) {
      return;
    }
    deleteConversationConfirm({ conversationId, title: title ?? '', retainView });
  };

  return (
    <>
      {/* The menu is portaled, but its clicks still bubble through the React
          tree to the conversation row — stop them here. */}
      <span className="contents" onClick={(e) => e.stopPropagation()}>
        <Dropdown
          align="end"
          open={isPopoverActive}
          onOpenChange={setIsPopoverActive}
          menu={
            <>
              <DropdownItem icon={<Outlined.Edit />} onSelect={renameHandler}>
                {localize('com_ui_rename')}
              </DropdownItem>
              <DropdownSeparator />
              <DropdownItem danger icon={<Outlined.Delete />} onSelect={handleDelete}>
                {localize('com_ui_delete')}
              </DropdownItem>
            </>
          }
        >
          <button
            ref={triggerRef}
            type="button"
            id={`conversation-menu-${conversationId}`}
            aria-label={localize('com_nav_convo_menu_options')}
            className={cn(
              'z-30 inline-flex h-4 w-4 items-center justify-center gap-2 rounded-md border-none p-0 text-sm font-medium text-text-3 ring-ring-primary transition-all duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 fine-pointer:hover:text-text-1',
              isActiveConvo
                ? 'opacity-100'
                : 'opacity-0 focus:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100 coarse-pointer:opacity-100',
            )}
          >
            <Ellipsis className="icon-md" aria-hidden />
          </button>
        </Dropdown>
      </span>
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
