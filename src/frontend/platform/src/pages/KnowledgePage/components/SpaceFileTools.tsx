import { Button, Dropdown, DropdownItem } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
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
  const [active, setActive] = useState<"process" | "index" | null>(null);
  const permissions = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(props.scope, props.spaceId),
      "container-edit",
    ],
    queryFn: () =>
      getMyResourcePermissionsApi("knowledge_space", String(props.spaceId)),
    enabled: Boolean(props.scope.identityKey),
    cacheTime: 0,
  });
  useEffect(() => {
    if (permissions.error) showApiError(permissions.error);
  }, [permissions.error]);
  if (!permissions.data?.actions.includes("edit")) return null;
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
        <Button
          variant="text"
          disabled={[1, 4, 5].includes(props.status ?? -1)}
        >
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
