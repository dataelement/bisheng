import DepartmentUsersSelect, {
  type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect";
import { Button } from "@/components/bs-ui/button";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
  replaceDepartmentSpaceAdminApi,
  type DepartmentKnowledgeSpaceSummary,
} from "@/controllers/API/departmentKnowledgeSpace";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  space: DepartmentKnowledgeSpaceSummary;
  onChanged?: () => void;
}

/**
 * F045: one created department knowledge space in the bench list — shows the
 * single space admin (or the pending-admin badge) and lets the super admin
 * replace the admin atomically.
 */
export function DepartmentSpaceRow({ space, onChanged }: Props) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [replacing, setReplacing] = useState(false);
  const [saving, setSaving] = useState(false);

  const handleReplace = async (users: DepartmentUserOption[]) => {
    const next = users[0];
    if (!next || !space.department_id || saving) return;
    setSaving(true);
    const res = await captureAndAlertRequestErrorHoc(
      replaceDepartmentSpaceAdminApi(space.department_id, Number(next.value)),
    );
    setSaving(false);
    if (!res) return;
    toast({
      title: t("prompt"),
      description: t("bench.departmentKnowledgeSpaceReplaceAdminSuccess"),
      variant: "success",
    });
    setReplacing(false);
    onChanged?.();
  };

  return (
    <div className="rounded-lg border border-[#E5E6EB] bg-white px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-[#1D2129]">{space.name}</p>
            <span className="rounded bg-[#F2F3F5] px-2 py-0.5 text-xs text-[#4E5969]">
              {space.department_name || "--"}
            </span>
            {space.pending_admin && (
              <span className="rounded bg-[#FFF7E8] px-2 py-0.5 text-xs text-[#D25F00]">
                {t("bench.departmentKnowledgeSpacePendingAdmin")}
              </span>
            )}
          </div>
          <p className="mt-2 text-xs text-[#86909C]">
            {t("bench.departmentKnowledgeSpaceDepartmentLabel")}：{space.department_name || "--"}
          </p>
          <div className="mt-1 flex items-center gap-2 text-xs text-[#86909C]">
            <span className="shrink-0">
              {t("bench.departmentKnowledgeSpaceAdminLabel")}：
              {space.admin_user_name || (space.pending_admin ? t("bench.departmentKnowledgeSpacePendingAdmin") : "--")}
            </span>
            {replacing ? (
              <DepartmentUsersSelect
                multiple={false}
                disabled={saving}
                className="max-w-[260px]"
                value={[]}
                onChange={handleReplace}
                placeholder={t("bench.departmentKnowledgeSpaceAdminSearchPlaceholder")}
                searchPlaceholder={t("bench.departmentKnowledgeSpaceAdminSearchPlaceholder")}
              />
            ) : (
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0 text-xs"
                onClick={() => setReplacing(true)}
              >
                {t("bench.departmentKnowledgeSpaceReplaceAdmin")}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
