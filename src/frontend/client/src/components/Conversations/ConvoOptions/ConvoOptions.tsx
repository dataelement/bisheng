import { useState, useRef, memo } from "react";
import { Outlined } from "bisheng-icons";

import { useLocalize } from "~/hooks";
import { useChatContext, useToastContext } from "~/Providers";
import { Dropdown, DropdownItem, DropdownSeparator, DropdownSub, Tooltip } from "@bisheng/ui";
import {
  useProjectMemberships,
} from "~/layouts/WorkbenchSidebar/projectsStore";
import { useChatProjectActions, useProjectIdentity } from "~/hooks/useChatProjects";
import { useSidebarProjects } from "~/layouts/WorkbenchSidebar/useSidebarProjects";
import { SIDEBAR_ICON_BUTTON_CLASS_NAME } from "~/layouts/WorkbenchSidebar/sidebarIconButton";
import { ProjectNameDialog } from "~/layouts/WorkbenchSidebar/ProjectNameDialog";
import { useDeleteConversationConfirm } from "./useDeleteConversationConfirm";
import ShareButton from "./ShareButton";
import { cn } from "~/utils";
import { NotificationSeverity } from "~/common";

function ConvoOptions({
  conversationId,
  title,
  retainView,
  renameHandler,
  isPopoverActive,
  setIsPopoverActive,
  onMenuExit,
}: {
  conversationId: string | null;
  title: string | null;
  retainView: () => void;
  renameHandler: () => void;
  isPopoverActive: boolean;
  setIsPopoverActive: (open: boolean) => void;
  onMenuExit?: () => void;
}) {
  const localize = useLocalize();
  const { index } = useChatContext();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [showShareDialog, setShowShareDialog] = useState(false);
  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false);
  const createProjectAfterMenuCloseRef = useRef(false);
  const deleteConversationConfirm = useDeleteConversationConfirm();
  // Membership and project targets share the authenticated server cache.
  const projects = useSidebarProjects();
  const projectChats = useProjectMemberships();
  const actions = useChatProjectActions();
  const identity = useProjectIdentity();
  const [dialogIdentity, setDialogIdentity] = useState(identity);
  const { showToast } = useToastContext();
  const failed = () => showToast?.({ message: localize('project_sync.save_failed'), severity: NotificationSeverity.ERROR });
  const currentProjectId = conversationId ? projectChats[conversationId] : undefined;
  // Projects are accessible from the global workbench sidebar on every width.

  const handleMoveToProject = (projectId: string) => {
    if (!conversationId) {
      return;
    }
    void actions.mutateAsync({ operation: { operation: 'assign', chat_id: conversationId, project_id: projectId } }).catch(failed);
  };

  const handleRemoveFromProject = () => {
    if (!conversationId) {
      return;
    }
    void actions.mutateAsync({ operation: { operation: 'assign', chat_id: conversationId, project_id: null } }).catch(failed);
  };

  const handleNewProject = () => {
    if (!conversationId) return;
    createProjectAfterMenuCloseRef.current = true;
    setIsPopoverActive(false);
  };

  const handleMenuCloseAutoFocus = (event: Event) => {
    onMenuExit?.();
    if (!createProjectAfterMenuCloseRef.current) return;
    createProjectAfterMenuCloseRef.current = false;
    // Open the dialog after the menu releases its focus scope.
    event.preventDefault();
    setDialogIdentity(identity);
    setNewProjectDialogOpen(true);
  };

  const handleProjectCreate = async (name: string, requestId: string) => {
    if (!conversationId) return;
    await actions.mutateAsync({ operation: { operation: 'create', name, chat_id: conversationId }, requestId });
  };

  const handleDelete = () => {
    if (!conversationId) {
      return;
    }
    deleteConversationConfirm({ conversationId, title: title ?? "", retainView });
  };

  return (
    <>
      {/* The menu is portaled, but its clicks still bubble through the React
          tree to the conversation row — stop them here. */}
      <Tooltip content={localize("com_workbench_sidebar.more")}>
      <span className="inline-flex shrink-0" onClick={(e) => e.stopPropagation()}>
        <Dropdown
          align="end"
          open={isPopoverActive}
          onOpenChange={setIsPopoverActive}
          onCloseAutoFocus={handleMenuCloseAutoFocus}
          menu={
            <>
              <DropdownItem icon={<Outlined.Edit />} onSelect={renameHandler}>
                {localize("com_ui_rename")}
              </DropdownItem>
                <DropdownSub label={localize("com_workbench_sidebar.move_to_project")} icon={<Outlined.MoveToFolder />}>
                  <DropdownItem icon={<Outlined.Plus />} disabled={!conversationId} onSelect={handleNewProject}>
                    {localize("com_workbench_sidebar.project_new")}
                  </DropdownItem>
                  {projects.length > 0 && <DropdownSeparator />}
                  {projects.filter(project => !project.readonly).map((project) => (
                    <DropdownItem key={project.id} icon={<Outlined.FolderClose />} onSelect={() => handleMoveToProject(project.id)}>
                      {project.name}
                    </DropdownItem>
                  ))}
                  {currentProjectId != null && (
                    <>
                    <DropdownSeparator />
                    <DropdownItem icon={<Outlined.Return />} onSelect={handleRemoveFromProject}>
                      {localize("com_workbench_sidebar.move_out_of_project")}
                    </DropdownItem>
                    </>
                  )}
                </DropdownSub>
              <DropdownSeparator />
              <DropdownItem danger icon={<Outlined.Delete />} onSelect={handleDelete}>
                {localize("com_ui_delete")}
              </DropdownItem>
            </>
          }
        >
          <button
            ref={triggerRef}
            type="button"
            id={`conversation-menu-${conversationId}`}
            aria-label={localize("com_nav_convo_menu_options")}
            className={cn(
              SIDEBAR_ICON_BUTTON_CLASS_NAME,
              "opacity-0 focus-visible:opacity-100 group-has-[:focus-visible]:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100 coarse-pointer:opacity-100",
            )}
          >
            <Outlined.More className="size-4" aria-hidden />
          </button>
        </Dropdown>
      </span>
      </Tooltip>
      <ProjectNameDialog
        open={newProjectDialogOpen && dialogIdentity === identity}
        onOpenChange={setNewProjectDialogOpen}
        onSubmit={handleProjectCreate}
      />
      {showShareDialog && (
        <ShareButton
          conversationId={conversationId ?? ""}
          open={showShareDialog}
          onOpenChange={setShowShareDialog}
          triggerRef={triggerRef}
        />
      )}
    </>
  );
}

export default memo(ConvoOptions);
