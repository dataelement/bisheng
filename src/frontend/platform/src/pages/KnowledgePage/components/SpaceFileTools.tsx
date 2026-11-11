import { Button, Dropdown, DropdownItem } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { checkResourceActionApi } from "@/controllers/API/permission";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { SpaceProcessingDialog } from "./SpaceProcessingDialog";
import { SpaceIndexEditDialog } from "./SpaceIndexEditDialog";

interface SpaceFileToolsProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  fileId: number;
  status?: number | null;
}
export function SpaceFileTools(props: SpaceFileToolsProps) {
  const { t } = useTranslation("knowledge");
  const scopeKey = JSON.stringify([
    ...knowledgeQueryKeys.space(props.scope, props.spaceId),
    props.fileId,
  ]);
  const [opened, setOpened] = useState<{ key: string; mode: "process" | "index" } | null>(null);
  const active = opened?.key === scopeKey ? opened.mode : null;
  const setActive = (mode: "process" | "index" | null) =>
    setOpened(mode ? { key: scopeKey, mode } : null);
  useEffect(() => {
    setOpened(null);
  }, [scopeKey]);
  const permissions = useQuery({
    queryKey: [...knowledgeQueryKeys.space(props.scope, props.spaceId), "container-edit"],
    queryFn: async ({ signal }) => {
      const result = await checkResourceActionApi({
        resource_type: "knowledge_space",
        resource_id: String(props.spaceId),
        action: "edit",
      });
      if (signal?.aborted) throw new DOMException("Retired permission read", "AbortError");
      return result;
    },
    enabled: Boolean(props.scope.identityKey),
    cacheTime: 0,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    if (permissions.error) showApiError(permissions.error);
  }, [permissions.error]);
  if (permissions.isError || !permissions.data?.allowed || (permissions.isFetching && !active))
    return null;
  return (
    <>
      <Dropdown
        menu={
          <>
            <DropdownItem onSelect={() => setActive("process")}>
              {t("f118.processing_title_file")}
            </DropdownItem>
            <DropdownItem onSelect={() => setActive("index")}>
              {t("f118.index_edit_title")}
            </DropdownItem>
          </>
        }
      >
        <Button variant="text" disabled={[1, 4, 5].includes(props.status ?? -1)}>
          {t("f118.processing_title_file")}
        </Button>
      </Dropdown>
      <SpaceProcessingDialog
        scope={props.scope}
        spaceId={props.spaceId}
        fileId={props.fileId}
        mode="file"
        open={active === "process"}
        onOpenChange={(open) => {
          if (!open) setActive(null);
        }}
      />
      <SpaceIndexEditDialog
        {...props}
        open={active === "index"}
        onOpenChange={(open) => {
          if (!open) setActive(null);
        }}
      />
    </>
  );
}
