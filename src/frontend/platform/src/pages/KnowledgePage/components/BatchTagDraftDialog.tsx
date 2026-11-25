import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { getKnowledgeTagsApi } from "@/controllers/API/knowledgeTags";
import { useSpaceTagPermission } from "../hooks/useSpaceTagPermission";
import { SpaceTagPermissionNotice } from "./tags/SpaceTagPermissionNotice";
import { Alert, Button, Checkbox, Input } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/bs-ui/dialog";
interface BatchTagDraftDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  availableTags: { id: number; name: string }[];
  open: boolean;
  onClose: () => void;
  onReview: (ids: number[], names: string[]) => void;
}
export function BatchTagDraftDialog({
  scope,
  spaceId,
  availableTags,
  open,
  onClose,
  onReview,
}: BatchTagDraftDialogProps) {
  const { t } = useTranslation("knowledge");
  const permission = useSpaceTagPermission(scope, spaceId, open);
  const canManageTags = permission.status === "allowed";
  const catalog = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "batch-tag-candidates"],
    queryFn: () => getKnowledgeTagsApi(spaceId, undefined, true),
    enabled: open && permission.canReadTags === true,
    cacheTime: 0,
    staleTime: 0,
    retry: false,
    keepPreviousData: false,
  });
  // File-only grants must remain usable without reading the root tag dictionary.
  const tags = [...new Map([
    ...availableTags,
    ...(permission.canReadTags ? catalog.data?.data ?? [] : []),
  ].map((tag) => [tag.id, tag])).values()];
  const [ids, setIds] = useState<number[]>([]),
    [names, setNames] = useState<string[]>([]),
    [name, setName] = useState("");
  useEffect(() => {
    if (!open) return;
    setIds([]);
    setNames([]);
    setName("");
    // Opening owns the tag draft; rerenders must not discard in-progress input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, spaceId, scope.identityKey, scope.tenantId, scope.managementTenantId, scope.view]);
  const add = () => {
    const value = name.trim();
    if (!value || value.length > 100 || !canManageTags) return;
    const existing = tags.find((tag) => tag.name === value);
    if (existing) setIds((old) => [...new Set([...old, existing.id])]);
    else setNames((old) => [...new Set([...old, value])]);
    setName("");
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("batch.tag_title")}</DialogTitle>
        </DialogHeader>
        {permission.canReadTags && catalog.isError ? <Alert type="info" live
          description={t("batch.tags_load_failed")}
          actions={[{ label: t("retry"), onClick: () => { void catalog.refetch(); } }]} />
          : <SpaceTagPermissionNotice permission={permission} />}
        {canManageTags && <p>{t("batch.draft_notice")}</p>}
        <div className="max-h-60 overflow-y-auto space-y-2">
          {tags.map((tag) => (
            <Checkbox
              key={tag.id}
              label={tag.name}
              checked={ids.includes(tag.id)}
              onCheckedChange={(checked) =>
                setIds((old) =>
                  checked === true ? [...old, tag.id] : old.filter((id) => id !== tag.id),
                )
              }
            />
          ))}
          {names.map((value) => (
            <Checkbox
              key={value}
              label={value}
              checked
              onCheckedChange={() => setNames((old) => old.filter((name) => name !== value))}
            />
          ))}
        </div>
        <Input
          aria-label={t("batch.new_tag")}
          disabled={!canManageTags}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        {name.length > 100 && <p role="alert">{t("batch.invalid_name")}</p>}
        <Button variant="text" disabled={!canManageTags || !name.trim() || name.length > 100} onClick={add}>
          {t("batch.add_tag")}
        </Button>
        <DialogFooter>
          <Button variant="outlined" onClick={onClose}>
            {t("batch.cancel")}
          </Button>
          <Button
            disabled={(!ids.length && !names.length) || !!name.trim() || (names.length > 0 && !canManageTags)}
            onClick={() => { if (!names.length || canManageTags) onReview(ids, names); }}
          >
            {t("batch.review")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
