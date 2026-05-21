import { useContext, useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { applyMenuAccessApi } from "@/controllers/API/approval";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";

/** Menu key → i18n label mapping, aligned with MainLayout sidebar */
const MENU_LABEL_KEYS: Record<string, string> = {
  board:       "menu.board",
  build:       "menu.skills",
  knowledge:   "menu.knowledge",
  model:       "menu.models",
  evaluation:  "menu.evaluation",
  mark_task:   "menu.annotation",
  log:         "menu.log",
};

/** 菜单无权限占位页：approval 模式展示申请按钮，非 approval 模式展示无权限提示 */
export default function MenuPermissionPlaceholder() {
  const { t } = useTranslation("bs");
  const location = useLocation();
  const { toast } = useToast();
  const { user } = useContext(userContext);

  const menuKey = new URLSearchParams(location.search).get("menu") ?? "";
  const menuLabelKey = menuKey ? MENU_LABEL_KEYS[menuKey] : "";
  const menuName = menuLabelKey ? t(menuLabelKey, { defaultValue: menuKey }) : "";
  const approvalEnabled = Boolean(user?.menu_approval_mode);

  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);

  const handleApply = async () => {
    if (!menuKey || applying || applied) return;
    setApplying(true);
    await captureAndAlertRequestErrorHoc(
      applyMenuAccessApi({ menu_key: menuKey, menu_name: menuName })
        .then(() => {
          setApplied(true);
          toast({ variant: "success", description: t("approvalPage.genericOperateSuccess") });
        })
    );
    setApplying(false);
  };

  return (
    <div className="flex h-full w-full items-center justify-center bg-background-main-content px-6">
      <div className="max-w-md rounded-xl border border-border-subtle bg-background-primary p-8 text-center shadow-sm">
        <h2 className="text-lg font-semibold text-text-primary">
          {menuName
            ? `「${menuName}」${t(approvalEnabled ? "approvalPage.menuNeedsApproval" : "approvalPage.menuNoPermission", { defaultValue: approvalEnabled ? "菜单需审批开通" : "暂无该菜单权限" })}`
            : t(approvalEnabled ? "approvalPage.menuNeedsApproval" : "approvalPage.menuNoPermission", { defaultValue: approvalEnabled ? "当前菜单需审批开通" : "暂无该菜单权限" })}
        </h2>
        <p className="mt-3 text-sm leading-6 text-text-secondary">
          {approvalEnabled
            ? t("approvalPage.menuApprovalDesc", { defaultValue: "你的角色当前未包含该菜单权限，点击下方按钮发起申请，审批通过后即可访问。" })
            : t("approvalPage.menuNoPermissionDesc", { defaultValue: "你的角色当前未包含该菜单权限，请联系管理员开通。" })}
        </p>
        {approvalEnabled && menuKey && (
          <button
            type="button"
            disabled={applying || applied}
            onClick={handleApply}
            className="mt-6 inline-flex items-center rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
          >
            {applied
              ? t("approvalPage.menuApplied", { defaultValue: "已提交申请" })
              : applying
                ? t("approvalPage.menuApplying", { defaultValue: "提交中…" })
                : t("approvalPage.menuApply", { defaultValue: "申请菜单权限" })}
          </button>
        )}
      </div>
    </div>
  );
}
