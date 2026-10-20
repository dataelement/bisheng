import { Button, Input } from '@bisheng/ui';

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { type ApprovalNodeItem } from "@/controllers/API/approval";
import { Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { APPROVER_SOURCE_OPTIONS } from "./approvalMetadata";
import { ActionBtn } from "./ApprovalPrimitives";
import { ApproverUserPicker } from "./components/ApproverUserPicker";

interface NodeDialogProps {
  open: boolean;
  initial: Partial<ApprovalNodeItem>;
  allowedSourceTypes?: string[];
  onClose: () => void;
  onConfirm: (data: { node_name: string; node_mode: string; approver_config: Record<string, unknown> }) => void;
}

export function NodeDialog({ open, initial, allowedSourceTypes, onClose, onConfirm }: NodeDialogProps) {
  const [name, setName] = useState(initial.node_name ?? "");
  const { t } = useTranslation("bs");
  const [mode, setMode] = useState(initial.node_mode ?? "or");
  type SourceEntry = { type: string; label: string; userIds?: number[]; userNames?: string[] };
  const [sources, setSources] = useState<SourceEntry[]>([]);

  // user picker state for direct_user source
  const [userPickerOpen, setUserPickerOpen] = useState(false);
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [selectedUserNames, setSelectedUserNames] = useState<string[]>([]);

  // Filter global list to only those allowed for the current scenario
  const effectiveSourceOptions = allowedSourceTypes
    ? APPROVER_SOURCE_OPTIONS.filter((o) => allowedSourceTypes.includes(o.value))
    : APPROVER_SOURCE_OPTIONS;

  const getApproverLabel = (type: string) => {
    const opt = APPROVER_SOURCE_OPTIONS.find((o) => o.value === type);
    return opt ? t(opt.labelKey, { defaultValue: type }) : type;
  };

  const dialogSnapshot = useRef({ initial, getApproverLabel });
  dialogSnapshot.current = { initial, getApproverLabel };
  useEffect(() => {
    if (open) {
      const { initial, getApproverLabel } = dialogSnapshot.current;
      setName(initial.node_name ?? "");
      setMode(initial.node_mode ?? "or");
      const cfg = initial.approver_config as Record<string, unknown> | undefined;
      const rawSources =
        (cfg?.sources as { type: string; user_ids?: number[]; user_names?: string[]; label?: string }[] | undefined) ??
        [];
      setSources(
        rawSources.map((s) => ({
          type: s.type,
          label: getApproverLabel(s.type),
          userIds: s.user_ids,
          userNames: s.user_names,
        })),
      );
    }
  }, [open]);

  const openUserPicker = () => {
    const existing = sources.find((s) => s.type === "direct_user");
    setSelectedUserIds(existing?.userIds ?? []);
    setSelectedUserNames(existing?.userNames ?? []);
    setUserPickerOpen(true);
  };

  const confirmUserPicker = () => {
    if (!selectedUserIds.length) return;
    setSources((prev) => {
      const without = prev.filter((s) => s.type !== "direct_user");
      return [
        ...without,
        {
          type: "direct_user",
          label: getApproverLabel("direct_user"),
          userIds: selectedUserIds,
          userNames: selectedUserNames,
        },
      ];
    });
    setUserPickerOpen(false);
  };

  const addSource = (type: string) => {
    if (type === "direct_user") {
      openUserPicker();
      return;
    }
    if (sources.some((s) => s.type === type)) return;
    setSources((prev) => [...prev, { type, label: getApproverLabel(type) }]);
  };

  const removeSource = (type: string) => {
    setSources((prev) => prev.filter((s) => s.type !== type));
  };

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{initial.id ? t("approvalPage.editNode") : t("approvalPage.addNode")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <label className="block text-sm text-muted-foreground">
              {t("approvalPage.nodeNameLabel")}
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("subjectSearch.nodeExample")} className={"mt-1 block w-full"} />
            </label>
            <div className="text-sm text-muted-foreground">
              {t("approvalPage.approverSourceSectionLabel")}
              <div className="mt-1 flex flex-wrap gap-2">
                {sources.map((s) => (
                  <span key={s.type} className="inline-flex items-center gap-1">
                    <Tag
                      size="small"
                      closable
                      closeLabel={t("approvalPage.delete")}
                      onClose={() => removeSource(s.type)}
                      className="whitespace-nowrap"
                    >
                      {s.label}
                      {s.type === "direct_user" && s.userIds?.length ? ` (${s.userIds.length})` : ""}
                    </Tag>
                    {s.type === "direct_user" && (
                      <ActionBtn label={t("approvalPage.edit")} onClick={openUserPicker}>
                        <Outlined.Edit size={14} />
                      </ActionBtn>
                    )}
                  </span>
                ))}
                <select
                  value=""
                  onChange={(e) => e.target.value && addSource(e.target.value)}
                  className="h-7 rounded-full border border-dashed border-border bg-gray-50 dark:bg-gray-50/[0.06] px-2 text-xs text-muted-foreground outline-none"
                >
                  <option value="">＋ {t("approvalPage.addApprover")}</option>
                  {effectiveSourceOptions
                    .filter((o) => !sources.some((s) => s.type === o.value))
                    .map((o) => (
                      <option key={o.value} value={o.value}>
                        {t(o.labelKey, { defaultValue: o.value })}
                      </option>
                    ))}
                </select>
              </div>
            </div>
            <label className="block text-sm text-muted-foreground">
              {t("approvalPage.nodeModeLabel")}
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                className="mt-1 block h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none"
              >
                <option value="or">{t("approvalPage.nodeModeOrFull")}</option>
                <option value="and">{t("approvalPage.nodeModeAndFull")}</option>
              </select>
            </label>
          </div>
          <DialogFooter>
            <Button size="medium" variant="outlined" type="button" onClick={onClose} color="default">
              {t("approvalPage.cancel")}
            </Button>
            <Button size="medium" variant="solid" type="button" disabled={!name.trim()} onClick={() =>
                onConfirm({
                  node_name: name.trim(),
                  node_mode: mode,
                  approver_config: {
                    sources: sources.map((s) =>
                      s.type === "direct_user"
                        ? { type: s.type, user_ids: s.userIds ?? [], user_names: s.userNames ?? [] }
                        : { type: s.type },
                    ),
                  },
                })
              } color="primary">
              {t("approvalPage.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* User picker for direct_user source */}

      <Dialog open={userPickerOpen} onOpenChange={(v) => !v && setUserPickerOpen(false)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("approvalPage.approverSource.direct_user")}</DialogTitle>
          </DialogHeader>
          <ApproverUserPicker
            value={selectedUserIds}
            names={selectedUserNames}
            onChange={(ids, names) => {
              setSelectedUserIds(ids);
              setSelectedUserNames(names);
            }}
          />
          <DialogFooter>
            <Button size="medium" variant="outlined" type="button" onClick={() => setUserPickerOpen(false)} color="default">
              {t("approvalPage.cancel")}
            </Button>
            <Button size="medium" variant="solid" type="button" disabled={!selectedUserIds.length} onClick={confirmUserPicker} color="primary">
              {t("approvalPage.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
