import { DropdownItem } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { FileSearch, GitBranch } from "lucide-react";
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
  onOpen: (dialog: "manage" | "similar") => void;
}

export function SpaceRowVersionMenu({ scope, spaceId, item, enabled, indicator = false, onOpen }: SpaceRowVersionMenuProps) {
  const { t } = useTranslation(["knowledge", "shared"]);
  const similar = item.has_similar === true && item.is_multi_version !== true;
  const eligible = enabled && item.file_type === 1 && item.status === 2 && (!indicator || similar);
  const permission = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "version-file-actions", item.id],
    queryFn: ({ signal }) => getMyResourcePermissionsApi("knowledge_file", String(item.id), { signal }),
    enabled: eligible,
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (eligible && permission.error) showApiError(permission.error);
  }, [eligible, permission.error]);
  if (!eligible || permission.isFetching || permission.isError || !permission.data?.actions?.includes("edit")) return null;
  if (indicator) return (
    <button
      type="button"
      className="flex h-5 shrink-0 items-center gap-1 rounded bg-[#FFF3E8] px-1.5 text-xs text-[#F76F44] hover:bg-[#FFE6D2]"
      onClick={event => { event.stopPropagation(); onOpen("manage"); }}
    >
      <FileSearch className="size-3" />
      {t("knowledge.version.pill_similar", { ns: "shared" })}
    </button>
  );
  return (
    <>
      <DropdownItem icon={<GitBranch aria-hidden />} onSelect={() => onOpen("manage")}>
        {t("knowledge.version.dialog_title", { ns: "shared" })}
      </DropdownItem>
      {similar && <DropdownItem icon={<Outlined.FileSearch aria-hidden />} onSelect={() => onOpen("similar")}>
        {t("versions.similar")}
      </DropdownItem>}
    </>
  );
}
