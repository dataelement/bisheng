import { useState, useRef, memo } from 'react';
import { Ellipsis } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import type { MouseEvent } from 'react';
import { useDuplicateConversationMutation, useGetStartupConfig } from '~/hooks/queries/data-provider';
import { useLocalize, useArchiveHandler, useNavigateToConvo, usePrefersMobileLayout } from '~/hooks';
import { useToastContext, useChatContext } from '~/Providers';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import {
  ActionMenuContent,
  ActionMenuDivider,
  ActionMenuItem,
  ActionMenuSub,
  ActionMenuSubContent,
  ActionMenuSubTrigger,
  actionMenuLabelClassName,
} from '~/components/ActionMenu';
import { moveChatToProject, removeChatFromProject, useMockProjectChats } from '~/layouts/WorkbenchSidebar/projectsStore';
import { useSidebarProjects } from '~/layouts/WorkbenchSidebar/useSidebarProjects';
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
  renameHandler: (e: MouseEvent) => void;
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
  // MOCK: projects live in localStorage until the backend has a model for them
  // (see projectsStore) — moving a conversation only re-files it in the sidebar.
  const projects = useSidebarProjects();
  const projectChats = useMockProjectChats();
  const currentProjectId = conversationId ? projectChats[conversationId] : undefined;
  // 项目 only exists in the desktop workbench sidebar, so mobile hides the row
  // rather than filing a conversation into a folder it cannot show.
  const isSmallScreen = usePrefersMobileLayout();

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

  const handleRename = (e: Event) => {
    renameHandler(e as unknown as MouseEvent);
  };

  const handleMoveToProject = (projectId: string) => {
    if (!conversationId) {
      return;
    }
    moveChatToProject(conversationId, projectId);
  };

  const handleRemoveFromProject = () => {
    if (!conversationId) {
      return;
    }
    removeChatFromProject(conversationId);
  };

  const handleDelete = () => {
    if (!conversationId) {
      return;
    }
    deleteConversationConfirm({ conversationId, title: title ?? '', retainView });
  };

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
              'z-30 inline-flex h-4 w-4 items-center justify-center gap-2 rounded-md border-none p-0 text-sm font-medium text-text-3 ring-ring-primary transition-all duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 fine-pointer:hover:text-text-1',
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
          // Both panels 180px: the 项目 list is the wider of the two, and the menu it
          // hangs off matches it rather than the other way round.
          width={180}
          onClick={(e) => e.stopPropagation()}
        >
          <ActionMenuItem
            icon={<Outlined.Edit />}
            label={localize('com_ui_rename')}
            onSelect={handleRename}
          />
          {!isSmallScreen && (
            <ActionMenuSub>
              <ActionMenuSubTrigger
                icon={<Outlined.MoveToFolder />}
                label={localize('com_workbench_sidebar.move_to_project')}
              />
              <ActionMenuSubContent width={180}>
                {projects.length === 0 ? (
                  <div className="px-2 py-[5px] text-sm leading-[22px] text-text-3">
                    {localize('com_workbench_sidebar.project_none')}
                  </div>
                ) : (
                  projects.map((project) => (
                    <ActionMenuItem
                      key={project.id}
                      icon={<Outlined.FolderClose />}
                      onSelect={() => handleMoveToProject(project.id)}
                    >
                      <span className={cn(actionMenuLabelClassName, 'flex-1')}>{project.name}</span>
                      {project.id === currentProjectId && (
                        <Outlined.Check className="size-4 shrink-0 text-text-2" aria-hidden />
                    )}
                  </ActionMenuItem>
                ))
              )}
              {currentProjectId != null && (
                <>
                  <ActionMenuDivider hairline />
                  <ActionMenuItem
                    icon={<Outlined.Return />}
                    label={localize('com_workbench_sidebar.move_out_of_project')}
                    onSelect={handleRemoveFromProject}
                  />
                </>
              )}
            </ActionMenuSubContent>
          </ActionMenuSub>
          )}
          <ActionMenuItem
            danger
            icon={<Outlined.Delete />}
            label={localize('com_ui_delete')}
            onSelect={handleDelete}
          />
        </ActionMenuContent>
      </DropdownMenu>
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
