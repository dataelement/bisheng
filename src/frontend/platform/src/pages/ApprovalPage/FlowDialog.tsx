import { Button, Input } from '@bisheng/ui';

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { type ApprovalFlowItem } from "@/controllers/API/approval";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface FlowDialogProps {
  open: boolean;
  initial: Partial<ApprovalFlowItem>;
  onClose: () => void;
  onConfirm: (data: { flow_name: string }) => void;
}

export function FlowDialog({ open, initial, onClose, onConfirm }: FlowDialogProps) {
  const { t } = useTranslation("bs");
  const [name, setName] = useState(initial.flow_name ?? "");
  useEffect(() => {
    if (open) {
      setName(initial.flow_name ?? "");
    }
  }, [open, initial.flow_name]);

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{initial.id ? t("approvalPage.editFlow") : t("approvalPage.createFlow")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <label className="block text-sm text-muted-foreground">
            {t("approvalPage.flowNameLabel")}
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("subjectSearch.flowExample")} className={"mt-1 block w-full"} />
          </label>
        </div>
        <DialogFooter>
          <Button size="medium" variant="outlined" type="button" onClick={onClose} color="default">
            {t("approvalPage.cancel")}
          </Button>
          <Button size="medium" variant="solid" type="button" disabled={!name.trim()} onClick={() => onConfirm({ flow_name: name.trim() })} color="primary">
            {t("approvalPage.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
