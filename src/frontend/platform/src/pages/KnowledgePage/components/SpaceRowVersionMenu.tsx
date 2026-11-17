import { Button, DropdownItem } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";

interface SpaceRowVersionMenuProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  item: KnowledgeSpaceChild;
  enabled: boolean;
  indicator?: boolean;
  onOpen: (panel: "merge" | "similar") => void;
}

export function SpaceRowVersionMenu({ scope, spaceId, item, enabled, indicator = false, onOpen }: SpaceRowVersionMenuProps) {
  const { t } = useTranslation("knowledge");
  const similar = item.has_similar === true && item.is_multi_version !== true;
  const eligible = enabled && item.file_type === 1 && item.status === 2 && (!indicator || similar);
  const permission = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "detail-actions"],
    queryFn: () => getMyResourcePermissionsApi("knowledge_space", String(spaceId)),
    enabled: eligible,
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (eligible && permission.error) showApiError(permission.error);
  }, [eligible, permission.error]);
  if (!eligible || permission.isError || !permission.data?.actions?.includes(indicator ? "manage_permission" : "edit")) return null;
  if (indicator) return (
    <Button size="small" variant="link" onClick={() => onOpen("similar")}>
      {t("versions.similar")}
    </Button>
  );
  return (
    <>
      <DropdownItem icon={<Outlined.History aria-hidden />} onSelect={() => onOpen("merge")}>
        {t("versions.manage")}
      </DropdownItem>
      {similar && <DropdownItem icon={<Outlined.FileSearch aria-hidden />} onSelect={() => onOpen("similar")}>
        {t("versions.similar")}
      </DropdownItem>}
    </>
  );
}
