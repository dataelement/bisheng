import { versionDialogStyles } from "@bisheng/knowledge";
import { Button, Dropdown, DropdownItem, Tooltip } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { checkResourceActionApi } from "@/controllers/API/permission";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { useSearchParams } from "react-router-dom";
import { SpaceIndexEditDialog } from "./SpaceIndexEditDialog";

interface SpaceFileToolsProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  fileId: number;
  status?: number | null;
  enabled?: boolean;
  // The owner keeps dialog state alive when the menu content unmounts.
  children?: (items: ReactNode) => ReactNode;
}
export function SpaceFileTools(props: SpaceFileToolsProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const handleProcess = () => {
    const next = new URLSearchParams(searchParams);
    next.set("process_file_id", String(props.fileId));
    setSearchParams(next);
  };
  const { t } = useTranslation("knowledge");
  const enabled = props.enabled !== false;
  const scopeKey = JSON.stringify([
    ...knowledgeQueryKeys.space(props.scope, props.spaceId),
    props.fileId,
  ]);
  const [opened, setOpened] = useState<{ key: string; mode: "index" } | null>(null);
  const active = opened?.key === scopeKey ? opened.mode : null;
  const setActive = (mode: "index" | null) =>
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
    enabled: enabled && Boolean(props.scope.identityKey),
    cacheTime: 0,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    if (enabled && permissions.error) showApiError(permissions.error);
  }, [enabled, permissions.error]);
  const allowed = enabled && !permissions.isError && permissions.data?.allowed === true && (!permissions.isFetching || active !== null);
  const disabled = [1, 4, 5].includes(props.status ?? -1);
  const processingLabel = t("f118.processing_title_file");
  const items = allowed ? (
    <>
      <DropdownItem disabled={disabled} onSelect={handleProcess}>
        {processingLabel}
      </DropdownItem>
      <DropdownItem disabled={disabled} onSelect={() => setActive("index")}>
        {t("f118.index_edit_title")}
      </DropdownItem>
    </>
  ) : null;
  return (
    <>
      {props.children ? props.children(items) : allowed && (
        <Tooltip content={processingLabel}>
          <span className="inline-flex shrink-0">
            <Dropdown menu={items}>
              <Button
                type="button"
                color="default"
                variant="outlined"
                iconOnly
                className={versionDialogStyles.historyAction}
                aria-label={processingLabel}
                disabled={disabled}
              >
                <Outlined.Setting aria-hidden />
              </Button>
            </Dropdown>
          </span>
        </Tooltip>
      )}
      {allowed && <SpaceIndexEditDialog
        scope={props.scope}
        spaceId={props.spaceId}
        fileId={props.fileId}
        open={active === "index"}
        onOpenChange={(open) => {
          if (!open) setActive(null);
        }}
      />}
    </>
  );
}
