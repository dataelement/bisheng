import { Switch } from "@/components/bs-ui/switch";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
  getDepartmentKnowledgeSpaceApprovalSettingsApi,
  updateDepartmentKnowledgeSpaceApprovalSettingsApi,
  type DepartmentKnowledgeSpaceSummary,
  type DepartmentKnowledgeSpaceApprovalSettings,
} from "@/controllers/API/departmentKnowledgeSpace";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  space: DepartmentKnowledgeSpaceSummary | null;
  onSaved?: (spaceId: number, settings: DepartmentKnowledgeSpaceApprovalSettings) => void;
}

const DEFAULT_SETTINGS: DepartmentKnowledgeSpaceApprovalSettings = {
  approval_enabled: true,
  sensitive_check_enabled: false,
};

export function DepartmentKnowledgeSpaceApprovalDialog({ open, onOpenChange, space, onSaved }: Props) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [form, setForm] = useState<DepartmentKnowledgeSpaceApprovalSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !space?.id) return;
    setLoading(true);
    getDepartmentKnowledgeSpaceApprovalSettingsApi(space.id)
      .then((res) => {
        setForm({
          approval_enabled: Boolean(res?.approval_enabled),
          sensitive_check_enabled: Boolean(res?.sensitive_check_enabled),
        });
      })
      .finally(() => setLoading(false));
  }, [open, space?.id]);

  const handleSave = async () => {
    if (!space?.id) return;
    setSaving(true);
    const res = await captureAndAlertRequestErrorHoc(
      updateDepartmentKnowledgeSpaceApprovalSettingsApi(space.id, form),
    );
    setSaving(false);
    if (!res) return;
    toast({
      title: t("prompt"),
      description: t("chatConfig.saveSuccess"),
      variant: "success",
    });
    onSaved?.(space.id, res);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>
            {t("bench.departmentKnowledgeSpaceApprovalSettings", "审批设置")}
            {space?.name ? ` · ${space.name}` : ""}
          </DialogTitle>
          <DialogDescription>
            {t("bench.departmentKnowledgeSpaceApprovalSettingsDesc", "配置部门知识空间上传是否需要审批，以及是否开启内容安全检测。")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-5 py-2">
          <div className="rounded-lg border border-[#ECECEC] bg-white px-4 py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1 space-y-1">
                <Label className="bisheng-label">
                  {t("bench.departmentKnowledgeSpaceApprovalEnabled", "开启部门知识空间上传审批")}
                </Label>
                <p className="text-sm text-[#86909C]">
                  {t("bench.departmentKnowledgeSpaceApprovalEnabledDesc", "开启后，部门知识空间上传文件会先进入审批流程，再正式入库。")}
                </p>
              </div>
              <div className="shrink-0 pt-1">
                <Switch
                  checked={form.approval_enabled}
                  disabled={loading}
                  onCheckedChange={(checked) => setForm((prev) => ({ ...prev, approval_enabled: checked }))}
                />
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-[#ECECEC] bg-white px-4 py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1 space-y-1">
                <Label className="bisheng-label">
                  {t("bench.departmentKnowledgeSpaceSensitiveCheckEnabled", "开启内容安全检测")}
                </Label>
                <p className="text-sm text-[#86909C]">
                  {t("bench.departmentKnowledgeSpaceSensitiveCheckEnabledDesc", "开启后，上传文件会先做内容安全检测，通过后才会进入人工审批。")}
                </p>
              </div>
              <div className="shrink-0 pt-1">
                <Switch
                  checked={form.sensitive_check_enabled}
                  disabled={loading}
                  onCheckedChange={(checked) => setForm((prev) => ({ ...prev, sensitive_check_enabled: checked }))}
                />
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={saving || loading} onClick={handleSave}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
