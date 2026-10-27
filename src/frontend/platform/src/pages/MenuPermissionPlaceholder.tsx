import { Button, Textarea, notification } from '@bisheng/ui';

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";


import { userContext } from "@/contexts/userContext";
import { applyMenuAccessApi } from "@/controllers/API/approval";
import { showApiError } from "@/controllers/request";
import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

/** Menu key → i18n label mapping, aligned with MainLayout sidebar */
const MENU_LABEL_KEYS: Record<string, string> = {
    board: "menu.board",
    build: "menu.skills",
    knowledge: "menu.knowledge",
    model: "menu.models",
    evaluation: "menu.evaluation",
    mark_task: "menu.annotation",
    log: "menu.log",
};

export default function MenuPermissionPlaceholder() {
    const { t } = useTranslation("bs");
    const location = useLocation();

    const { user } = useContext(userContext);

    const menuKey = new URLSearchParams(location.search).get("menu") ?? "";
    const menuLabelKey = menuKey ? MENU_LABEL_KEYS[menuKey] : "";
    const menuName = menuLabelKey ? t(menuLabelKey, { defaultValue: menuKey }) : "";
    // Admin-area approval scope (legacy global flag as fallback).
    const approvalEnabled = Boolean(user?.menu_approval_mode_admin ?? user?.menu_approval_mode);

    const [showDialog, setShowDialog] = useState(false);
    const [reason, setReason] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [applied, setApplied] = useState(false);

    const handleSubmit = async () => {
        if (!menuKey || submitting) return;
        setSubmitting(true);
        await applyMenuAccessApi({ menu_key: menuKey, menu_name: menuName, reason: reason.trim() || undefined }).then(
                () => {
                    setApplied(true);
                    setShowDialog(false);
                    setReason("");
                    notification.open({ type: "success", description: String(t("approvalPage.genericOperateSuccess") ?? '') });
                },
            ).catch(showApiError).finally(() => setSubmitting(false));
    };

    return (
        <div className="flex h-full w-full items-center justify-center bg-background-main-content px-6">
            <div className="max-w-md rounded-xl border border-border-subtle bg-background-primary p-8 text-center shadow-sm">
                <h2 className="text-lg font-semibold text-text-primary">
                    {menuName
                        ? `「${menuName}」${t(approvalEnabled ? "approvalPage.menuNeedsApproval" : "approvalPage.menuNoPermission")}`
                        : t(approvalEnabled ? "approvalPage.menuNeedsApproval" : "approvalPage.menuNoPermission")}
                </h2>
                <p className="mt-3 text-sm leading-6 text-text-secondary">
                    {approvalEnabled ? t("approvalPage.menuApprovalDesc") : t("approvalPage.menuNoPermissionDesc")}
                </p>
                {approvalEnabled && menuKey && (
                    <Button type="button" variant="solid" disabled={applied} onClick={() => setShowDialog(true)} className="mt-6 items-center" color="primary">
                        {applied ? t("approvalPage.menuApplied") : t("approvalPage.menuApply")}
                    </Button>
                )}
            </div>

            <Dialog
                open={showDialog}
                onOpenChange={(v) => {
                    if (!v) {
                        setShowDialog(false);
                        setReason("");
                    }
                }}
            >
                <DialogContent className="max-w-sm">
                    <DialogHeader>
                        <DialogTitle>{t("approvalPage.menuApply")}</DialogTitle>
                    </DialogHeader>
                    <div className="py-2">
                        <label className="block text-sm text-text-secondary">
                            {t("approvalPage.menuApplyReasonLabel")}
                            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder={t("approvalPage.menuApplyReasonPlaceholder")} textareaClassName={"mt-1 block w-full resize-none rounded-lg border border-border-subtle bg-background-primary px-3 py-2 text-sm text-text-primary outline-none"} />
                        </label>
                    </div>
                    <DialogFooter>
                        <Button type="button" variant="outlined" onClick={() => {
                                setShowDialog(false);
                                setReason("");
                            }} color="default">
                            {t("approvalPage.cancel")}
                        </Button>
                        <Button type="button" variant="solid" disabled={submitting} onClick={() => void handleSubmit()} color="primary">
                            {submitting ? t("approvalPage.menuApplying") : t("approvalPage.save")}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
