import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { applyMenuAccessApi } from "@/controllers/API/approval";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useToast } from "@/components/bs-ui/toast/use-toast";

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

/** 需审批模式：无菜单权限时占位页，支持在页内发起申请 */
export default function MenuPermissionPlaceholder() {
  const { t } = useTranslation("bs");
  const location = useLocation();
  const { toast } = useToast();

  const menuKey = new URLSearchParams(location.search).get("menu") ?? "";
  const menuLabelKey = menuKey ? MENU_LABEL_KEYS[menuKey] : "";
  const menuName = menuLabelKey ? t(menuLabelKey, { defaultValue: menuKey }) : "";

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
          {menuName ? `「${menuName}」${t("approvalPage.menuNeedsApproval", { defaultValue: "菜单需审批开通" })}` : t("approvalPage.menuNeedsApproval", { defaultValue: "当前菜单需审批开通" })}
        </h2>
        <p className="mt-3 text-sm leading-6 text-text-secondary">
          {t("approvalPage.menuApprovalDesc", { defaultValue: "你的角色当前未包含该菜单权限。点击下方按钮发起申请，审批通过后即可访问。" })}
        </p>
        {menuKey && (
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
