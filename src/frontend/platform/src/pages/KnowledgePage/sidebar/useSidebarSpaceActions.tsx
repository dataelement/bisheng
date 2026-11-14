import { DropdownItem, DropdownSeparator, notification } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { userContext } from "@/contexts/userContext";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { useLazyResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { useKnowledgeDeletion } from "../hooks/useKnowledgeDeletion";
import { KnowledgeDeletionDialog } from "../components/KnowledgeDeletionDialog";
import { SpaceCopyDialog } from "../components/SpaceCopyDialog";

const MENU_ACTIONS = ["delete", "manage_permission", "upload_file"];
type DialogTarget = { row: KnowledgeSpaceInfo; scopeKey: string };
export function useSidebarSpaceActions(
  scope: KnowledgeQueryScope,
  canCreate: boolean,
  onDeleted?: (id: number) => void,
) {
  const { t } = useTranslation("knowledge");
  const { user } = useContext(userContext);
  const client = useQueryClient();
  const menus = useLazyResourceActions("knowledge_space", MENU_ACTIONS);
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
      canCreate &&
      Number.isSafeInteger(user?.user_id) &&
      user.user_id === row.user_id &&
      actions.includes("upload_file");
    return (
      <>
        {menus.loading[String(row.id)] && (
          <DropdownItem disabled>
            {t("knowledgeRowActions.loading", { ns: "permission" })}
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
        {actions.includes("manage_permission") && (
          <DropdownItem
            icon={<Outlined.PeopleSafe />}
            onSelect={() => setPermission({ row, scopeKey })}
          >
            {t("managePermission", { ns: "permission" })}
          </DropdownItem>
        )}
        {actions.includes("delete") && (
          <>
            <DropdownSeparator />
            <DropdownItem
              icon={<Outlined.Delete />}
              danger
              onSelect={() => {
                void deletion
                  .open({ spaceId: row.id, kind: "delete" })
                  .then(async (deleted) => {
                    if (deleted && current.current === scopeKey) {
                      await refresh();
                      if (current.current === scopeKey) onDeleted?.(row.id);
                    }
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
