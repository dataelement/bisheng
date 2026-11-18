import { DropdownItem, DropdownSeparator, notification } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { userContext } from "@/contexts/userContext";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { useLazyResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { useKnowledgeDeletion } from "./useKnowledgeDeletion";
import { KnowledgeDeletionDialog } from "../components/KnowledgeDeletionDialog";
import { SpaceCopyDialog } from "../components/SpaceCopyDialog";

const MENU_ACTIONS = ["delete", "manage_permission", "upload_file"];
const ADMIN_MENU_ACTIONS = ["delete", "manage_permission", "edit"];
type DialogTarget = { row: KnowledgeSpaceInfo; scopeKey: string };
interface SpaceActionsOptions {
  canCopy?: boolean;
  onDeleted?: (id: number) => void;
  onEdit?: (id: number) => void;
  onMetadata?: (id: number) => void;
}

export function useSpaceActions(
  scope: KnowledgeQueryScope,
  { canCopy: allowCopy, onDeleted, onEdit, onMetadata }: SpaceActionsOptions,
) {
  const { t } = useTranslation("knowledge");
  const { user } = useContext(userContext);
  const client = useQueryClient();
  const menus = useLazyResourceActions(
    "knowledge_space",
    onEdit ? ADMIN_MENU_ACTIONS : MENU_ACTIONS,
  );
  const [permission, setPermission] = useState<DialogTarget | null>(null);
  const [copy, setCopy] = useState<DialogTarget | null>(null);
  const scopeKey = JSON.stringify([scope, user?.user_id]);
  const current = useRef<string | null>(scopeKey);
  current.current = scopeKey;
  useEffect(() => {
    current.current = scopeKey;
    return () => {
      current.current = null;
    };
  }, [scopeKey]);
  const deletion = useKnowledgeDeletion(scopeKey);
  const refresh = () =>
    client.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
  const load = (row: KnowledgeSpaceInfo, open: boolean) => {
    if (open)
      void menus.load(String(row.id)).then((result) => {
        if (current.current === scopeKey && result.hasError)
          notification.open({
            type: "error",
            description: t("error.checkFailed", { ns: "permission" }),
          });
      });
  };
  const render = (row: KnowledgeSpaceInfo) => {
    const actions = menus.actions[String(row.id)] ?? [];
    const canCopy =
      allowCopy &&
      Number.isSafeInteger(user?.user_id) &&
      user.user_id === row.user_id &&
      actions.includes("upload_file");
    const canEdit = onEdit && actions.includes("edit");
    const canManage = actions.includes("manage_permission");
    const canDelete = actions.includes("delete");
    const loading = menus.loading[String(row.id)];
    return (
      <>
        {loading && (
          <DropdownItem disabled>
            <LoadingState size="inline" label={t("knowledgeRowActions.loading", { ns: "permission" })} />
          </DropdownItem>
        )}
        {onEdit && !loading && !canEdit && !canManage && !canDelete && (
          <DropdownItem disabled>
            {t("knowledgeRowActions.empty", { ns: "permission" })}
          </DropdownItem>
        )}
        {canEdit && onMetadata && (
          <DropdownItem icon={<Outlined.File aria-hidden />} onSelect={() => onMetadata(row.id)}>
            {t("detail.metadata")}
          </DropdownItem>
        )}
        {canEdit && (
          <DropdownItem icon={<Outlined.Edit aria-hidden />} onSelect={() => onEdit(row.id)}>
            {t("detail.settings")}
          </DropdownItem>
        )}
        {canCopy && (
          <DropdownItem
            icon={<Outlined.Copy />}
            onSelect={() => setCopy({ row, scopeKey })}
          >
            {t("f118.processing_title_copy")}
          </DropdownItem>
        )}
        {canManage && (
          <DropdownItem
            icon={<Outlined.PeopleSafe />}
            onSelect={() => setPermission({ row, scopeKey })}
          >
            {t("managePermission", { ns: "permission" })}
          </DropdownItem>
        )}
        {canDelete && (
          <>
            {(!onEdit || canEdit || canManage) && <DropdownSeparator />}
            <DropdownItem
              icon={<Outlined.Delete />}
              danger
              onSelect={() => {
                void deletion
                  .open({ spaceId: row.id, kind: "delete" })
                  .then(async (deleted) => {
                    if (!deleted || current.current !== scopeKey) return;
                    // Leave before the catalog refresh. Refreshing first refetches
                    // the page that is still open on the deleted space.
                    onDeleted?.(row.id);
                    if (current.current !== scopeKey) return;
                    const viewKey = knowledgeQueryKeys.scope(scope);
                    await client.invalidateQueries({
                      queryKey: viewKey,
                      predicate: ({ queryKey }) => {
                        const [kind, id] = queryKey.slice(viewKey.length);
                        return kind !== "space" || id !== row.id;
                      },
                    });
                  });
              }}
            >
              {t("deletion.delete_space")}
            </DropdownItem>
          </>
        )}
      </>
    );
  };
  const dialogs = (
    <>
      <KnowledgeDeletionDialog operation={deletion} />
      {permission?.scopeKey === scopeKey && (
        <PermissionDialog
          key={JSON.stringify([scopeKey, permission.row.id])}
          open
          onOpenChange={(open) => {
            if (!open) setPermission(null);
          }}
          resourceType="knowledge_space"
          resourceId={String(permission.row.id)}
          resourceName={permission.row.name}
        />
      )}
      {copy?.scopeKey === scopeKey && (
        <SpaceCopyDialog
          key={JSON.stringify([scopeKey, copy.row.id])}
          scope={scope}
          source={copy.row}
          onClose={() => setCopy(null)}
          onCreated={refresh}
        />
      )}
    </>
  );
  return { load, render, dialogs };
}
